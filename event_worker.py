"""
Unified event worker — runs all Kafka consumers in a single process.

Each consumer runs in its own thread with its own consumer group,
so Kafka treats them as independent consumers. The main thread
handles SIGINT/SIGTERM and propagates shutdown to all consumers.

Usage:
    python event_worker.py
"""

import os
from dotenv import load_dotenv

env_file = os.getenv("ENV_FILE", ".env.dev")
load_dotenv(env_file)

import signal
import logging
import threading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("event_worker")

# Register all SQLAlchemy models so FK references resolve
from users.data.model import User
from documents.data.model import Document, DocumentAccessModel, DocumentBatch, OriginalDocument
from bookmarks.data.model import Bookmark
from dashboard.data.model import EvalRecord
from billing.data.model import UserBalance, UsageTransaction, RazorpayTopUp
from follows.data.model import Follow
from connections.data.model import Connection
from word_explanations.data.model import WordExplanation
from highlights.data.model import Highlight
from posts.data.model import Post, Like, Comment, Reshare
from notifications.data.model import Notification


def main():
    # ── Import all consumers ──────────────────────────────────────────────
    from workers.notification_worker import NotificationWorker
    from workers.eval_worker import EvalWorker
    from workers.billing_worker import BillingWorker
    from workers.email_worker import EmailWorker
    from workers.word_exp_worker import WordExplanationWorker
    from workers.cache_worker import CacheWorker
    from workers.display_name_worker import DisplayNameWorker
    from fanout_worker.consumer import FanoutConsumer
    from graph_sync_worker.consumer import GraphSyncConsumer

    consumers = [
        NotificationWorker(),
        EvalWorker(),
        BillingWorker(),
        EmailWorker(),
        WordExplanationWorker(),
        CacheWorker(),
        DisplayNameWorker(),
        FanoutConsumer(),
        GraphSyncConsumer(),
    ]

    # ── Launch each consumer in a daemon thread ───────────────────────────
    threads: list[threading.Thread] = []
    for consumer in consumers:
        t = threading.Thread(
            target=consumer.start,
            kwargs={"register_signals": False},
            name=consumer.group_id,
            daemon=True,
        )
        t.start()
        threads.append(t)
        logger.info(f"Started consumer thread: {consumer.group_id}")

    logger.info(f"All {len(consumers)} consumers running. Press Ctrl+C to stop.")

    # ── Main thread: wait for shutdown signal ─────────────────────────────
    shutdown_event = threading.Event()

    def _handle_signal(signum, frame):
        logger.info(f"Received signal {signum}, shutting down all consumers...")
        for c in consumers:
            c.stop()
        shutdown_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Block until shutdown signal received
    shutdown_event.wait()

    # Give consumers time to finish current message and close
    for t in threads:
        t.join(timeout=10.0)

    logger.info("All consumers stopped. Exiting.")


if __name__ == "__main__":
    main()
