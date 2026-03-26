"""Neo4j driver singleton — follows the same pattern as shared/redis.py."""

import os
import logging

logger = logging.getLogger(__name__)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

_driver = None

if NEO4J_PASSWORD:
    try:
        from neo4j import GraphDatabase

        _driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
            max_connection_pool_size=25,
            connection_acquisition_timeout=5,
        )
        logger.info(f"[neo4j] Driver initialised → {NEO4J_URI}")
    except Exception as e:
        logger.warning(f"[neo4j] Driver init failed (Neo4j may not be running): {e}")
        _driver = None
else:
    logger.info("[neo4j] NEO4J_PASSWORD not set — driver disabled")


class Neo4jService:
    def __init__(self):
        self.driver = _driver

    def get_session(self):
        if self.driver is None:
            return None
        return self.driver.session()

    def is_available(self) -> bool:
        return self.driver is not None

    def close(self):
        if self.driver is not None:
            self.driver.close()
            logger.info("[neo4j] Driver closed")


def close_driver():
    """Shutdown hook — call from app lifespan."""
    if _driver is not None:
        _driver.close()
        logger.info("[neo4j] Driver closed")
