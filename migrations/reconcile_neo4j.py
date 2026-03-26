"""
Nightly reconciliation: compare PG and Neo4j follow state, fix drift.

1. Fix follower_count drift on User nodes
2. Remove orphaned Neo4j edges (no matching PG follow)
3. Create missing Neo4j edges (PG follow exists but edge missing)

Usage:
    python -m migrations.reconcile_neo4j
"""

import os
import sys
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.getenv("ENV_FILE", ".env.dev"))

from core.db_client import SessionLocal
from users.data.model import User
from follows.data.model import Follow
from shared.neo4j import Neo4jService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def reconcile():
    neo4j = Neo4jService()
    if not neo4j.is_available():
        logger.error("Neo4j driver not available. Check NEO4J_* env vars.")
        sys.exit(1)

    start = time.time()
    fixed_counts = 0
    removed_edges = 0
    added_edges = 0

    db = SessionLocal()
    try:
        # ── 1. Fix follower_count drift ─────────────────────────────────────
        logger.info("Phase 1: Checking follower_count drift...")
        users = db.query(User).filter(User.is_deleted == False).all()
        user_ids = {u.user_id for u in users}

        # Get PG follower counts
        from sqlalchemy import func
        pg_counts = dict(
            db.query(Follow.following_id, func.count(Follow.id))
            .group_by(Follow.following_id)
            .all()
        )

        with neo4j.get_session() as session:
            for user_id in user_ids:
                pg_count = pg_counts.get(user_id, 0)
                result = session.run(
                    "MATCH (u:User {user_id: $uid}) RETURN u.follower_count AS cnt",
                    uid=user_id,
                )
                record = result.single()
                if record is None:
                    continue
                neo4j_count = record["cnt"] or 0
                if neo4j_count != pg_count:
                    session.run(
                        "MATCH (u:User {user_id: $uid}) SET u.follower_count = $cnt",
                        uid=user_id,
                        cnt=pg_count,
                    )
                    fixed_counts += 1
                    logger.info(
                        f"  Fixed count: {user_id} neo4j={neo4j_count} -> pg={pg_count}"
                    )

        # ── 2. Remove orphaned Neo4j edges ──────────────────────────────────
        logger.info("Phase 2: Checking for orphaned Neo4j edges...")
        pg_edges = set(
            db.query(Follow.follower_id, Follow.following_id).all()
        )

        with neo4j.get_session() as session:
            result = session.run(
                "MATCH (a:User)-[r:FOLLOWS]->(b:User) "
                "RETURN a.user_id AS follower, b.user_id AS following"
            )
            neo4j_edges = {(r["follower"], r["following"]) for r in result}

        orphaned = neo4j_edges - pg_edges
        if orphaned:
            with neo4j.get_session() as session:
                for follower_id, following_id in orphaned:
                    session.run(
                        "MATCH (a:User {user_id: $a})-[r:FOLLOWS]->(b:User {user_id: $b}) DELETE r",
                        a=follower_id,
                        b=following_id,
                    )
                    removed_edges += 1
            logger.info(f"  Removed {removed_edges} orphaned edges")

        # ── 3. Create missing Neo4j edges ────────────────────────────────────
        logger.info("Phase 3: Checking for missing Neo4j edges...")
        missing = pg_edges - neo4j_edges
        if missing:
            # Get follow records for missing edges
            follows_by_pair = {}
            all_follows = db.query(Follow).all()
            for f in all_follows:
                follows_by_pair[(f.follower_id, f.following_id)] = f

            with neo4j.get_session() as session:
                for follower_id, following_id in missing:
                    follow = follows_by_pair.get((follower_id, following_id))
                    if not follow:
                        continue
                    session.run(
                        """
                        MATCH (a:User {user_id: $a})
                        MATCH (b:User {user_id: $b})
                        MERGE (a)-[r:FOLLOWS]->(b)
                        SET r.id = $fid, r.created_at = $cat
                        """,
                        a=follower_id,
                        b=following_id,
                        fid=follow.id,
                        cat=follow.created_at.isoformat() if follow.created_at else "",
                    )
                    added_edges += 1
            logger.info(f"  Added {added_edges} missing edges")

    finally:
        db.close()

    elapsed = time.time() - start
    logger.info(
        f"Reconciliation complete in {elapsed:.1f}s: "
        f"counts_fixed={fixed_counts}, edges_removed={removed_edges}, edges_added={added_edges}"
    )


if __name__ == "__main__":
    reconcile()
