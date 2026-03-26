"""Recommendation service — Redis-cached graph queries with circuit breaker."""

import time
import logging
from typing import Optional

from shared.redis import RedisService
from shared.neo4j import Neo4jService
from graph.data.graph_repository import GraphRepository

logger = logging.getLogger(__name__)

RECS_CACHE_TTL = 60 * 60          # 1 hour
INFLUENCE_CACHE_TTL = 60 * 60     # 1 hour

# Circuit breaker: after N consecutive failures, skip Neo4j for a cooldown period
CB_FAILURE_THRESHOLD = 5
CB_COOLDOWN_SECONDS = 30


class RecommendationService:
    def __init__(self):
        self.graph_repo = GraphRepository()
        self.redis = RedisService()
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    def _is_circuit_open(self) -> bool:
        if self._consecutive_failures < CB_FAILURE_THRESHOLD:
            return False
        if time.time() >= self._circuit_open_until:
            # Half-open: allow one attempt
            self._consecutive_failures = 0
            return False
        return True

    def _record_success(self):
        self._consecutive_failures = 0

    def _record_failure(self):
        self._consecutive_failures += 1
        if self._consecutive_failures >= CB_FAILURE_THRESHOLD:
            self._circuit_open_until = time.time() + CB_COOLDOWN_SECONDS
            logger.warning(
                f"[graph] Circuit breaker OPEN — skipping Neo4j for {CB_COOLDOWN_SECONDS}s"
            )

    def _neo4j_available(self) -> bool:
        neo4j = Neo4jService()
        return neo4j.is_available() and not self._is_circuit_open()

    # ── Recommendations ─────────────────────────────────────────────────────

    def get_people_you_may_know(self, user_id: str, limit: int = 20) -> list[dict]:
        cache_key = f"graph:recs:{user_id}"
        cached = self.redis.get_value(cache_key)
        if cached is not None:
            return cached

        if not self._neo4j_available():
            return []

        try:
            results = self.graph_repo.get_friend_of_friend_recommendations(user_id, limit)
            self._record_success()
            self.redis.set_value(cache_key, results, ttl=RECS_CACHE_TTL)
            return results
        except Exception as e:
            self._record_failure()
            logger.error(f"[graph] Recommendations failed: {e}")
            return []

    # ── Mutual followers ────────────────────────────────────────────────────

    def get_mutual_followers(
        self, user_a: str, user_b: str, limit: int = 50
    ) -> Optional[list[dict]]:
        """Try Neo4j first; return None if unavailable (caller can fallback to PG)."""
        if not self._neo4j_available():
            return None

        try:
            results = self.graph_repo.get_mutual_followers(user_a, user_b, limit)
            self._record_success()
            return results
        except Exception as e:
            self._record_failure()
            logger.error(f"[graph] Mutual followers failed: {e}")
            return None

    # ── Shortest path ───────────────────────────────────────────────────────

    def get_shortest_path(self, user_a: str, user_b: str) -> Optional[dict]:
        """Returns {user_ids, distance} or None if unavailable."""
        if not self._neo4j_available():
            return None

        try:
            result = self.graph_repo.get_shortest_path(user_a, user_b)
            self._record_success()
            return result
        except Exception as e:
            self._record_failure()
            logger.error(f"[graph] Shortest path failed: {e}")
            return None

    # ── Influence score ─────────────────────────────────────────────────────

    def get_influence_score(self, user_id: str) -> Optional[dict]:
        cache_key = f"graph:influence:{user_id}"
        cached = self.redis.get_value(cache_key)
        if cached is not None:
            return cached

        if not self._neo4j_available():
            return None

        try:
            result = self.graph_repo.get_influence_score(user_id)
            self._record_success()
            if result:
                self.redis.set_value(cache_key, result, ttl=INFLUENCE_CACHE_TTL)
            return result
        except Exception as e:
            self._record_failure()
            logger.error(f"[graph] Influence score failed: {e}")
            return None

    # ── User search ────────────────────────────────────────────────────────

    def search_users(
        self, query: str, current_user_id: str, limit: int = 20
    ) -> Optional[list[dict]]:
        """Graph-ranked user search. Returns None if Neo4j unavailable (caller falls back to PG)."""
        if not self._neo4j_available():
            return None

        try:
            results = self.graph_repo.search_users(query, current_user_id, limit)
            self._record_success()
            return results
        except Exception as e:
            self._record_failure()
            logger.error(f"[graph] User search failed: {e}")
            return None

    # ── Health ──────────────────────────────────────────────────────────────

    def health_check(self) -> Optional[dict]:
        if not self._neo4j_available():
            return None
        try:
            counts = self.graph_repo.get_node_and_edge_counts()
            self._record_success()
            return counts
        except Exception as e:
            self._record_failure()
            logger.error(f"[graph] Health check failed: {e}")
            return None
