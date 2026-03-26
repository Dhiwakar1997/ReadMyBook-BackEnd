"""Cypher query layer for the Neo4j social graph."""

import logging
from datetime import datetime, timezone

from shared.neo4j import Neo4jService

logger = logging.getLogger(__name__)


class GraphRepository:
    def __init__(self):
        self.neo4j = Neo4jService()

    # ── Schema setup ────────────────────────────────────────────────────────

    def ensure_constraints(self) -> None:
        """Create indexes and constraints (idempotent)."""
        with self.neo4j.get_session() as session:
            session.run(
                "CREATE CONSTRAINT user_id_unique IF NOT EXISTS "
                "FOR (u:User) REQUIRE u.user_id IS UNIQUE"
            )
            session.run(
                "CREATE INDEX user_follower_count IF NOT EXISTS "
                "FOR (u:User) ON (u.follower_count)"
            )
            session.run(
                "CREATE FULLTEXT INDEX user_name_email_search IF NOT EXISTS "
                "FOR (u:User) ON EACH [u.first_name, u.last_name, u.email_id]"
            )
        logger.info("[graph] Constraints and indexes ensured")

    # ── Write operations ────────────────────────────────────────────────────

    def merge_user_node(
        self,
        user_id: str,
        first_name: str = "",
        last_name: str = "",
        email_id: str = "",
        follower_count: int = 0,
        is_verified: bool = False,
        is_private: bool = False,
    ) -> None:
        """Create or update a User node (idempotent via MERGE)."""
        query = """
        MERGE (u:User {user_id: $user_id})
        SET u.first_name  = $first_name,
            u.last_name   = $last_name,
            u.email_id    = $email_id,
            u.is_verified = $is_verified,
            u.is_private  = $is_private,
            u.follower_count = CASE
                WHEN u.follower_count IS NULL THEN $follower_count
                ELSE u.follower_count
            END
        """
        with self.neo4j.get_session() as session:
            session.run(
                query,
                user_id=user_id,
                first_name=first_name,
                last_name=last_name or "",
                email_id=email_id or "",
                follower_count=follower_count,
                is_verified=is_verified,
                is_private=is_private,
            )

    def create_follow_edge(
        self,
        follower_id: str,
        following_id: str,
        follow_id: str,
        created_at: str | None = None,
    ) -> None:
        """Create a FOLLOWS edge and increment the target's follower_count."""
        query = """
        MATCH (a:User {user_id: $follower_id})
        MATCH (b:User {user_id: $following_id})
        MERGE (a)-[r:FOLLOWS]->(b)
        SET r.id = $follow_id,
            r.created_at = $created_at,
            b.follower_count = coalesce(b.follower_count, 0) + 1
        """
        with self.neo4j.get_session() as session:
            session.run(
                query,
                follower_id=follower_id,
                following_id=following_id,
                follow_id=follow_id,
                created_at=created_at or datetime.now(timezone.utc).isoformat(),
            )

    def delete_follow_edge(self, follower_id: str, following_id: str) -> None:
        """Remove a FOLLOWS edge and decrement the target's follower_count."""
        query = """
        MATCH (a:User {user_id: $follower_id})-[r:FOLLOWS]->(b:User {user_id: $following_id})
        DELETE r
        SET b.follower_count = CASE
            WHEN coalesce(b.follower_count, 0) > 0
            THEN b.follower_count - 1
            ELSE 0
        END
        """
        with self.neo4j.get_session() as session:
            session.run(
                query,
                follower_id=follower_id,
                following_id=following_id,
            )

    # ── Read operations ─────────────────────────────────────────────────────

    def get_mutual_followers(
        self, user_a: str, user_b: str, limit: int = 50
    ) -> list[dict]:
        """Users who follow both user_a and user_b."""
        query = """
        MATCH (a:User {user_id: $user_a})<-[:FOLLOWS]-(mutual)-[:FOLLOWS]->(b:User {user_id: $user_b})
        RETURN mutual.user_id   AS user_id,
               mutual.first_name AS first_name,
               mutual.last_name  AS last_name
        LIMIT $limit
        """
        with self.neo4j.get_session() as session:
            result = session.run(query, user_a=user_a, user_b=user_b, limit=limit)
            return [dict(record) for record in result]

    def get_friend_of_friend_recommendations(
        self, user_id: str, limit: int = 20
    ) -> list[dict]:
        """2-hop traversal: friends of my friends that I don't already follow."""
        query = """
        MATCH (me:User {user_id: $user_id})-[:FOLLOWS]->(friend)-[:FOLLOWS]->(rec:User)
        WHERE NOT (me)-[:FOLLOWS]->(rec)
          AND rec.user_id <> $user_id
          AND rec.is_private = false
        RETURN rec.user_id        AS user_id,
               rec.first_name     AS first_name,
               rec.last_name      AS last_name,
               rec.follower_count AS follower_count,
               COUNT(DISTINCT friend) AS mutual_count
        ORDER BY mutual_count DESC, rec.follower_count DESC
        LIMIT $limit
        """
        with self.neo4j.get_session() as session:
            result = session.run(query, user_id=user_id, limit=limit)
            return [dict(record) for record in result]

    def get_shortest_path(
        self, user_a: str, user_b: str, max_depth: int = 6
    ) -> dict | None:
        """Shortest undirected path between two users (max depth 6)."""
        query = """
        MATCH path = shortestPath(
            (a:User {user_id: $user_a})-[:FOLLOWS*..6]-(b:User {user_id: $user_b})
        )
        RETURN [n IN nodes(path) | n.user_id] AS user_ids,
               length(path)                    AS distance
        """
        with self.neo4j.get_session() as session:
            result = session.run(query, user_a=user_a, user_b=user_b)
            record = result.single()
            if record is None:
                return None
            return dict(record)

    def get_influence_score(self, user_id: str) -> dict | None:
        """Direct followers + second-degree reach."""
        query = """
        MATCH (u:User {user_id: $user_id})
        OPTIONAL MATCH (u)<-[:FOLLOWS]-(follower)
        OPTIONAL MATCH (follower)<-[:FOLLOWS]-(second_degree)
        WHERE second_degree.user_id <> $user_id
        RETURN u.follower_count                  AS direct_followers,
               COUNT(DISTINCT second_degree)     AS second_degree_reach
        """
        with self.neo4j.get_session() as session:
            result = session.run(query, user_id=user_id)
            record = result.single()
            if record is None:
                return None
            return dict(record)

    def search_users(
        self, query: str, current_user_id: str, limit: int = 20
    ) -> list[dict]:
        """Full-text search on user names, ranked by relationship closeness.

        Scoring: text relevance + mutual_followers*3 + mutual_following*2
                 + 5 if already following.
        """
        # Escape Lucene special characters, then append * for prefix matching
        import re
        safe_query = re.sub(r'([+\-&|!(){}[\]^"~*?:\\/@ ])', r'\\\1', query)
        lucene_query = f"{safe_query}*"

        cypher = """
        // Fulltext search + direct email prefix match (UNION deduplicates)
        CALL () {
            CALL db.index.fulltext.queryNodes('user_name_email_search', $lucene_query)
            YIELD node, score
            RETURN node, score
            UNION
            MATCH (node:User)
            WHERE node.email_id STARTS WITH $raw_query
            RETURN node, 1.0 AS score
        }
        WITH node, max(score) AS score
        WHERE node.user_id <> $current_user_id

        // Am I following this person?
        OPTIONAL MATCH (me:User {user_id: $current_user_id})-[f:FOLLOWS]->(node)

        // Mutual followers: people who follow both me and this person
        OPTIONAL MATCH (me)<-[:FOLLOWS]-(mf)-[:FOLLOWS]->(node)
        WITH node, score,
             f IS NOT NULL AS is_following,
             count(DISTINCT mf) AS mutual_followers

        // Mutual following: people we both follow
        OPTIONAL MATCH (me:User {user_id: $current_user_id})-[:FOLLOWS]->(mfg)<-[:FOLLOWS]-(node)
        WITH node, score, is_following, mutual_followers,
             count(DISTINCT mfg) AS mutual_following

        RETURN node.user_id    AS user_id,
               node.first_name AS first_name,
               node.last_name  AS last_name,
               mutual_followers,
               mutual_following,
               is_following,
               score + (mutual_followers * 3) + (mutual_following * 2)
                    + CASE WHEN is_following THEN 5 ELSE 0 END AS rank_score
        ORDER BY rank_score DESC
        LIMIT $limit
        """
        with self.neo4j.get_session() as session:
            result = session.run(
                cypher,
                lucene_query=lucene_query,
                raw_query=query.lower(),
                current_user_id=current_user_id,
                limit=limit,
            )
            return [dict(record) for record in result]

    def get_node_and_edge_counts(self) -> dict:
        """Health check: total users and follow edges."""
        with self.neo4j.get_session() as session:
            nodes = session.run("MATCH (u:User) RETURN count(u) AS cnt").single()
            edges = session.run("MATCH ()-[r:FOLLOWS]->() RETURN count(r) AS cnt").single()
            return {
                "node_count": nodes["cnt"] if nodes else 0,
                "edge_count": edges["cnt"] if edges else 0,
            }
