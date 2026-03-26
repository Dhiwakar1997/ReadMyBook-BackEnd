"""
One-time migration: seed Neo4j from PostgreSQL.

Reads all users and follows from PG, batch-MERGEs them into Neo4j,
and computes follower_count per user.

Usage:
    python -m migrations.populate_neo4j

Idempotent — safe to re-run (uses MERGE).
"""

import os
import sys
import time
import logging

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.getenv("ENV_FILE", ".env.dev"))

from core.db_client import SessionLocal
from users.data.model import User
from follows.data.model import Follow
from shared.neo4j import Neo4jService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def populate():
    neo4j = Neo4jService()
    if not neo4j.is_available():
        logger.error("Neo4j driver not available. Check NEO4J_* env vars.")
        sys.exit(1)

    start = time.time()

    # ── 1. Ensure constraints ───────────────────────────────────────────────
    from graph.data.graph_repository import GraphRepository
    graph_repo = GraphRepository()
    graph_repo.ensure_constraints()

    # ── 2. Load users from PG ───────────────────────────────────────────────
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.is_deleted == False).all()
        logger.info(f"Found {len(users)} active users in PG")
    finally:
        db.close()

    # Batch MERGE user nodes via UNWIND
    user_dicts = [
        {
            "user_id": u.user_id,
            "first_name": u.first_name or "",
            "last_name": u.last_name or "",
            "email_id": u.email_id or "",
            "is_verified": u.is_verified,
            "is_private": u.is_private,
        }
        for u in users
    ]

    user_query = """
    UNWIND $batch AS row
    MERGE (u:User {user_id: row.user_id})
    SET u.first_name  = row.first_name,
        u.last_name   = row.last_name,
        u.email_id    = row.email_id,
        u.is_verified = row.is_verified,
        u.is_private  = row.is_private
    ON CREATE SET u.follower_count = 0
    """

    with neo4j.get_session() as session:
        for i in range(0, len(user_dicts), BATCH_SIZE):
            batch = user_dicts[i : i + BATCH_SIZE]
            session.run(user_query, batch=batch)
            logger.info(f"  Users merged: {min(i + BATCH_SIZE, len(user_dicts))}/{len(user_dicts)}")

    # ── 3. Load follows from PG ─────────────────────────────────────────────
    db = SessionLocal()
    try:
        follows = db.query(Follow).all()
        logger.info(f"Found {len(follows)} follow edges in PG")
    finally:
        db.close()

    follow_dicts = [
        {
            "follower_id": f.follower_id,
            "following_id": f.following_id,
            "follow_id": f.id,
            "created_at": f.created_at.isoformat() if f.created_at else "",
        }
        for f in follows
    ]

    follow_query = """
    UNWIND $batch AS row
    MATCH (a:User {user_id: row.follower_id})
    MATCH (b:User {user_id: row.following_id})
    MERGE (a)-[r:FOLLOWS]->(b)
    SET r.id         = row.follow_id,
        r.created_at = row.created_at
    """

    with neo4j.get_session() as session:
        for i in range(0, len(follow_dicts), BATCH_SIZE):
            batch = follow_dicts[i : i + BATCH_SIZE]
            session.run(follow_query, batch=batch)
            logger.info(f"  Edges merged: {min(i + BATCH_SIZE, len(follow_dicts))}/{len(follow_dicts)}")

    # ── 4. Compute follower_count ───────────────────────────────────────────
    count_query = """
    MATCH (u:User)
    OPTIONAL MATCH (u)<-[f:FOLLOWS]-()
    WITH u, count(f) AS cnt
    SET u.follower_count = cnt
    """
    with neo4j.get_session() as session:
        session.run(count_query)

    elapsed = time.time() - start
    logger.info(
        f"Migration complete: {len(user_dicts)} users, "
        f"{len(follow_dicts)} edges in {elapsed:.1f}s"
    )


if __name__ == "__main__":
    populate()
