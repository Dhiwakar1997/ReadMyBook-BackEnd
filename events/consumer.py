"""Base Kafka consumer with DLQ, retry, and offset management."""

import json
import time
import signal
import logging

from events.config import _base_consumer_config, _base_producer_config

logger = logging.getLogger(__name__)


class BaseConsumer:
    """
    Base consumer loop with:
    - Manual offset commit (at-least-once delivery)
    - Retry with exponential backoff
    - DLQ publishing on exhausted retries
    - Graceful shutdown on SIGINT/SIGTERM
    """

    def __init__(self, group_id: str, topics: list[str], dlq_topic: str,
                 max_retries: int = 3):
        self.group_id = group_id
        self.topics = topics
        self.dlq_topic = dlq_topic
        self.max_retries = max_retries
        self._running = True
        self._consumer = None
        self._dlq_producer = None

    def handle(self, event_type: str, payload: dict) -> None:
        """Override in subclass to process an event."""
        raise NotImplementedError

    def stop(self) -> None:
        """Gracefully stop the consumer loop (thread-safe)."""
        self._running = False

    def start(self, register_signals: bool = True) -> None:
        from confluent_kafka import Consumer, Producer, KafkaError

        if register_signals:
            signal.signal(signal.SIGINT, self._shutdown)
            signal.signal(signal.SIGTERM, self._shutdown)

        consumer_config = _base_consumer_config(self.group_id)
        logger.info(f"[{self.group_id}] Connecting to broker: {consumer_config['bootstrap.servers']}")
        self._consumer = Consumer(consumer_config)
        self._dlq_producer = Producer(_base_producer_config())
        self._consumer.subscribe(self.topics)

        logger.info(f"[{self.group_id}] Subscribed to {self.topics}")

        while self._running:
            msg = self._consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error(f"[{self.group_id}] Consumer error: {msg.error()}")
                continue

            try:
                payload = json.loads(msg.value().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.error(f"[{self.group_id}] Failed to decode message: {e}")
                self._consumer.commit(msg)
                continue

            event_type = payload.get("event_type", "unknown")
            logger.info(
                f"[{self.group_id}] Received {event_type} from "
                f"{msg.topic()}[{msg.partition()}] @offset {msg.offset()}"
            )
            retry_count = 0
            success = False

            while retry_count <= self.max_retries and not success:
                try:
                    self.handle(event_type, payload)
                    success = True
                    logger.info(f"[{self.group_id}] Processed {event_type} successfully")
                except Exception as e:
                    retry_count += 1
                    if retry_count <= self.max_retries:
                        backoff = min(1 * (3 ** (retry_count - 1)), 30)
                        logger.warning(
                            f"[{self.group_id}] Retry {retry_count}/{self.max_retries} "
                            f"for {event_type}: {e}. Backoff {backoff}s"
                        )
                        time.sleep(backoff)
                    else:
                        self._send_to_dlq(msg, payload, str(e), retry_count)

            self._consumer.commit(msg)

        self._consumer.close()
        self._dlq_producer.flush(5.0)
        logger.info(f"[{self.group_id}] Consumer shut down.")

    def _send_to_dlq(self, msg, payload: dict, error: str, retry_count: int) -> None:
        dlq_payload = {
            "original_topic": msg.topic(),
            "original_partition": msg.partition(),
            "original_offset": msg.offset(),
            "original_key": msg.key().decode("utf-8") if msg.key() else None,
            "original_event": payload,
            "error": error,
            "retry_count": retry_count,
            "first_failure_at": time.time(),
            "last_failure_at": time.time(),
            "consumer_group": self.group_id,
        }
        try:
            self._dlq_producer.produce(
                topic=self.dlq_topic,
                value=json.dumps(dlq_payload).encode("utf-8"),
            )
            self._dlq_producer.poll(0)
            logger.error(
                f"[{self.group_id}] Sent to DLQ {self.dlq_topic}: "
                f"{payload.get('event_type', 'unknown')}"
            )
        except Exception as e:
            logger.error(f"[{self.group_id}] CRITICAL: Failed to send to DLQ: {e}")

    def _shutdown(self, signum, frame):
        logger.info(f"[{self.group_id}] Received signal {signum}, shutting down...")
        self._running = False
