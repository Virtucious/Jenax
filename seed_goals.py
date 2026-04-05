"""
Optional script to pre-populate Jenax with example goals.
Run: python seed_goals.py
"""
import database as db

db.init_db()

# Yearly goal
y = db.create_goal(
    title="Launch a side project",
    description="Build and ship a product that generates at least $1 of revenue",
    level="yearly",
    deadline="2026-12-31",
)

# Monthly goals under yearly
m1 = db.create_goal(
    title="Build MVP",
    description="Core features only, deployable version",
    level="monthly",
    parent_id=y["id"],
    deadline="2026-04-30",
)
m2 = db.create_goal(
    title="Get first 10 users",
    description="Share on relevant communities, collect feedback",
    level="monthly",
    parent_id=y["id"],
    deadline="2026-05-31",
)

# Weekly goals under monthly
db.create_goal(
    title="Set up project repo and CI",
    level="weekly",
    parent_id=m1["id"],
)
db.create_goal(
    title="Write landing page copy",
    level="weekly",
    parent_id=m1["id"],
)
db.create_goal(
    title="Post in 3 online communities",
    level="weekly",
    parent_id=m2["id"],
)

print("Seed goals created successfully.")
