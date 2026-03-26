#!/usr/bin/env bash
# Creates all Kafka topics required by the event worker.
# Usage: ./scripts/create-kafka-topics.sh [container_name]

set -euo pipefail

CONTAINER="${1:-kafka}"
BOOTSTRAP="localhost:9092"
KAFKA_TOPICS="/opt/kafka/bin/kafka-topics.sh"

MAIN_TOPICS=(social-events ai-operations document-events billing-events email-events)

for topic in "${MAIN_TOPICS[@]}"; do
  docker exec "$CONTAINER" "$KAFKA_TOPICS" --bootstrap-server "$BOOTSTRAP" \
    --create --if-not-exists --topic "$topic" --partitions 3 --replication-factor 1
  docker exec "$CONTAINER" "$KAFKA_TOPICS" --bootstrap-server "$BOOTSTRAP" \
    --create --if-not-exists --topic "${topic}-dlq" --partitions 1 --replication-factor 1
done

echo "All topics created."
docker exec "$CONTAINER" "$KAFKA_TOPICS" --bootstrap-server "$BOOTSTRAP" --list
