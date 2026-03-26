import os


# ── Kafka broker connection ──────────────────────────────────────────────────

KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "localhost:9092")
KAFKA_SECURITY_PROTOCOL = os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
KAFKA_SASL_MECHANISM = os.getenv("KAFKA_SASL_MECHANISM", "PLAIN")
KAFKA_SASL_USERNAME = os.getenv("KAFKA_SASL_USERNAME", "")
KAFKA_SASL_PASSWORD = os.getenv("KAFKA_SASL_PASSWORD", "")

# Consumer group IDs
CONSUMER_GROUP_FEED_FANOUT = "feed-fanout-workers"
CONSUMER_GROUP_NOTIFICATION = "notification-workers"
CONSUMER_GROUP_EVAL_RECORDING = "eval-recording-workers"
CONSUMER_GROUP_BILLING_DEDUCTION = "billing-deduction-workers"
CONSUMER_GROUP_WORD_EXPLANATION = "word-explanation-persistence"
CONSUMER_GROUP_EMAIL_SENDER = "email-sender-workers"
CONSUMER_GROUP_CACHE_INVALIDATION = "cache-invalidation-workers"
CONSUMER_GROUP_DISPLAY_NAME = "display-name-propagation"
CONSUMER_GROUP_POPULAR_USER = "popular-user-tracker"
CONSUMER_GROUP_GRAPH_SYNC = "graph-sync-workers"

# Popular user threshold
POPULAR_USER_THRESHOLD = int(os.getenv("POPULAR_USER_THRESHOLD", "100000"))


def _base_producer_config() -> dict:
    """Base confluent-kafka producer configuration."""
    conf = {
        "bootstrap.servers": KAFKA_BROKERS,
        "security.protocol": KAFKA_SECURITY_PROTOCOL,
        "message.timeout.ms": 10000,
        "queue.buffering.max.messages": 100000,
        "queue.buffering.max.ms": 5,
    }
    if KAFKA_SECURITY_PROTOCOL in ("SASL_SSL", "SASL_PLAINTEXT"):
        conf["sasl.mechanism"] = KAFKA_SASL_MECHANISM
        conf["sasl.username"] = KAFKA_SASL_USERNAME
        conf["sasl.password"] = KAFKA_SASL_PASSWORD
    return conf


def _base_consumer_config(group_id: str) -> dict:
    """Base confluent-kafka consumer configuration."""
    conf = {
        "bootstrap.servers": KAFKA_BROKERS,
        "security.protocol": KAFKA_SECURITY_PROTOCOL,
        "group.id": group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    }
    if KAFKA_SECURITY_PROTOCOL in ("SASL_SSL", "SASL_PLAINTEXT"):
        conf["sasl.mechanism"] = KAFKA_SASL_MECHANISM
        conf["sasl.username"] = KAFKA_SASL_USERNAME
        conf["sasl.password"] = KAFKA_SASL_PASSWORD
    return conf
