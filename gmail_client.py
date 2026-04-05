"""Gmail OAuth flow and email fetching. Read-only access only."""

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import database as db
from config import GOOGLE_CREDENTIALS_PATH

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
REDIRECT_URI = "http://localhost:5000/auth/gmail/callback"

# Sender patterns to filter out automated/marketing emails
_SPAM_SENDER_PATTERNS = [
    "noreply@", "no-reply@", "notifications@", "mailer-daemon@",
    "donotreply@", "do-not-reply@", "newsletter@", "marketing@",
    "automated@", "robot@", "digest@", "bounce@", "support@",
    "info@", "news@", "updates@", "alert@", "alerts@",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self):
        return " ".join(self._parts)


def _strip_html(html):
    s = _HTMLStripper()
    s.feed(html)
    return s.get_text()


def _is_spam_sender(sender):
    sender_lower = sender.lower()
    return any(p in sender_lower for p in _SPAM_SENDER_PATTERNS)


def _decode_body(data):
    """Decode base64url-encoded email body."""
    try:
        decoded = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        return decoded
    except Exception:
        return ""


def _extract_body(payload):
    """Extract plain text body from a message payload, preferring text/plain."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if mime_type == "text/plain" and body_data:
        return _decode_body(body_data)

    if mime_type == "text/html" and body_data:
        return _strip_html(_decode_body(body_data))

    # Multipart: recurse
    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text

    return ""


def _build_flow():
    return Flow.from_client_secrets_file(
        GOOGLE_CREDENTIALS_PATH,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )


# ---------------------------------------------------------------------------
# OAuth Flow
# ---------------------------------------------------------------------------

def get_auth_url():
    """Build and return the Google OAuth authorization URL."""
    if not GOOGLE_CREDENTIALS_PATH:
        return None, None
    try:
        flow = _build_flow()
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        # Persist code_verifier in DB so it survives server restarts between connect and callback
        code_verifier = getattr(flow, "code_verifier", None)
        if code_verifier:
            db.save_oauth_token("gmail_pkce", code_verifier)
        return auth_url, state, code_verifier
    except Exception:
        return None, None, None


def handle_callback(auth_code, code_verifier=None):
    """Exchange auth code for tokens, store in DB, return user's email."""
    flow = _build_flow()
    # Retrieve code_verifier from DB if not passed (survives server restarts)
    if not code_verifier:
        row = db.get_oauth_token("gmail_pkce")
        if row:
            code_verifier = row["token_json"]
    if code_verifier:
        flow.code_verifier = code_verifier
    flow.fetch_token(code=auth_code)
    # Clean up the temporary PKCE entry
    db.delete_oauth_token("gmail_pkce")
    creds = flow.credentials

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
    }

    # Fetch user's email address
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    email = profile.get("emailAddress")

    db.save_oauth_token("gmail", json.dumps(token_data), email)
    return email


def get_gmail_service():
    """Load token from DB, refresh if needed, return gmail API service or None."""
    token_row = db.get_oauth_token("gmail")
    if not token_row:
        return None

    try:
        token_data = json.loads(token_row["token_json"])
        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes", SCOPES),
        )

        # Refresh if expired
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            token_data["token"] = creds.token
            db.save_oauth_token("gmail", json.dumps(token_data))

        return build("gmail", "v1", credentials=creds)
    except Exception:
        db.delete_oauth_token("gmail")
        return None


def is_connected():
    """Check if a valid Gmail token exists."""
    token_row = db.get_oauth_token("gmail")
    if not token_row:
        return {"connected": False, "email": None}
    return {"connected": True, "email": token_row.get("email")}


def disconnect():
    """Delete token from DB and attempt to revoke with Google."""
    token_row = db.get_oauth_token("gmail")
    if token_row:
        try:
            token_data = json.loads(token_row["token_json"])
            token = token_data.get("token") or token_data.get("refresh_token")
            if token:
                import urllib.request
                urllib.request.urlopen(
                    f"https://oauth2.googleapis.com/revoke?token={token}"
                )
        except Exception:
            pass
        db.delete_oauth_token("gmail")


# ---------------------------------------------------------------------------
# Email Fetching
# ---------------------------------------------------------------------------

def fetch_recent_emails(hours=24, max_results=50):
    """Fetch emails from the last N hours, filter spam, return structured list."""
    service = get_gmail_service()
    if not service:
        return None  # Not connected

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    after_epoch = int(cutoff.timestamp())
    query = f"after:{after_epoch}"

    try:
        result = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()
    except HttpError as e:
        raise e

    messages = result.get("messages", [])
    emails = []

    for msg_ref in messages:
        try:
            msg = service.users().messages().get(
                userId="me",
                id=msg_ref["id"],
                format="full",
            ).execute()
        except HttpError:
            continue

        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        sender = headers.get("from", "")
        subject = headers.get("subject", "(no subject)")
        date_str = headers.get("date", "")

        # Filter automated/spam senders
        if _is_spam_sender(sender):
            continue

        # Parse date
        try:
            from email.utils import parsedate_to_datetime
            parsed_date = parsedate_to_datetime(date_str)
            iso_date = parsed_date.isoformat()
        except Exception:
            iso_date = date_str

        body = _extract_body(msg.get("payload", {}))
        snippet = msg.get("snippet", "")[:200]

        emails.append({
            "id": msg_ref["id"],
            "subject": subject,
            "sender": sender,
            "date": iso_date,
            "snippet": snippet,
            "body": body[:1000],
            "labels": msg.get("labelIds", []),
        })

    return emails
