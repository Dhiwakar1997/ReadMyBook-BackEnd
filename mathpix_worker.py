"""Mathpix-based PDF-to-Markdown queue worker.

Async event loop: the main loop polls the Azure Storage Queue and spawns
an asyncio task for each message. While one job waits for Mathpix to finish
converting (async polling with asyncio.sleep), the loop picks up the next
message and starts its conversion concurrently.

Concurrency is bounded at two levels:
  1. MAX_WORKER_TASKS  — caps total in-flight tasks (queue consumption pauses
                         when the cap is reached). Prevents memory/thread
                         exhaustion from blob downloads, post-processing, etc.
  2. MATHPIX_MAX_CONCURRENT_JOBS (in mathpix_client.py) — caps concurrent
                         Mathpix API submissions within those tasks.
"""

import os
from dotenv import load_dotenv

env_file = os.getenv("ENV_FILE", ".env.dev")
load_dotenv(env_file)

import json
import asyncio
import base64
from urllib.parse import urlparse

from azure.storage.queue import QueueClient

from mathpix_worker.processor import process_document


QUEUE_NAME = os.getenv("QUEUE_NAME")
STORAGE_CONN = os.getenv("AZURE_CONNECTION_STRING")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))

# Maximum number of documents being processed at the same time.
# This accounts for the full pipeline: PDF download, Mathpix wait,
# zip download, blob upload, metadata, vector DB — all of which
# consume memory and thread-pool slots.
# Set equal to or slightly above MATHPIX_MAX_CONCURRENT_JOBS.
MAX_WORKER_TASKS = int(os.getenv("MAX_WORKER_TASKS", "4"))

if not STORAGE_CONN:
    raise RuntimeError("AZURE_CONNECTION_STRING is not set")
if not QUEUE_NAME:
    raise RuntimeError("QUEUE_NAME is not set")

STORAGE_CONN_STR: str = STORAGE_CONN
QUEUE_NAME_STR: str = QUEUE_NAME

queue = QueueClient.from_connection_string(
    conn_str=STORAGE_CONN_STR, queue_name=QUEUE_NAME_STR
)


async def handle_message(msg) -> None:
    """Parse a single queue message and process it as an async task.

    On success the message is deleted from the queue.
    On failure the message visibility is extended for retry.
    """
    try:
        raw = base64.b64decode(msg.content).decode("utf-8")
        event = json.loads(raw)

        if event.get("eventType") != "Microsoft.Storage.BlobCreated":
            print("[MATHPIX] Skipping non-BlobCreated event")
            queue.delete_message(msg)
            return

        blob_url = event["data"]["url"]
        parsed = urlparse(blob_url)
        path_parts = parsed.path.lstrip("/").split("/", 1)

        container_name = path_parts[0]
        blob_name = path_parts[1]

        if "/batches/" in blob_name:
            print(f"[MATHPIX] Skipping batch blob: {blob_name}")
            return

        document_id = blob_name.split("/")[0]

        print(f"[MATHPIX] Processing: {container_name}/{blob_name}")
        success = await process_document(document_id, blob_name, container_name)

        if success:
            print(f"[MATHPIX] [{document_id}] Message processed successfully")
            queue.delete_message(msg)
        else:
            print(
                f"[MATHPIX] [{document_id}] Processing failed "
                f"(attempt {msg.dequeue_count}/3)"
            )
            queue.update_message(msg, visibility_timeout=300)

    except Exception as e:
        print(f"[MATHPIX] Error handling message (attempt {msg.dequeue_count}/3): {e}")
        try:
            queue.update_message(msg, visibility_timeout=300)
        except Exception:
            pass


async def main():
    print("[MATHPIX] Queue worker started (async)")
    print(
        f"[MATHPIX] Queue: {QUEUE_NAME_STR}, Poll interval: {POLL_INTERVAL}s, "
        f"Max tasks: {MAX_WORKER_TASKS}"
    )

    active_tasks: set[asyncio.Task] = set()

    while True:
        # Clean up finished tasks
        done = {t for t in active_tasks if t.done()}
        for t in done:
            exc = t.exception() if not t.cancelled() else None
            if exc:
                print(f"[MATHPIX] Task failed with exception: {exc}")
        active_tasks -= done

        # If at capacity, wait for at least one task to finish before polling
        if len(active_tasks) >= MAX_WORKER_TASKS:
            print(
                f"[MATHPIX] At capacity ({len(active_tasks)}/{MAX_WORKER_TASKS}), "
                f"waiting for a slot..."
            )
            # Wait until at least one running task completes
            _done, _pending = await asyncio.wait(
                active_tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for t in _done:
                exc = t.exception() if not t.cancelled() else None
                if exc:
                    print(f"[MATHPIX] Task failed with exception: {exc}")
            active_tasks -= _done
            print(f"[MATHPIX] Slot freed (active: {len(active_tasks)}/{MAX_WORKER_TASKS})")
            continue  # re-enter loop to poll queue

        # Poll queue for new messages
        messages = queue.receive_messages(
            messages_per_page=1, visibility_timeout=600
        )
        found = False

        for msg in messages:
            found = True

            if msg.dequeue_count >= 3:
                print(
                    f"[MATHPIX] Message exceeded retry limit "
                    f"({msg.dequeue_count} attempts), deleting..."
                )
                queue.delete_message(msg)
                continue

            # Spawn a task — it runs concurrently with other tasks
            task = asyncio.create_task(handle_message(msg))
            active_tasks.add(task)
            print(f"[MATHPIX] Spawned task (active: {len(active_tasks)}/{MAX_WORKER_TASKS})")

        if not found:
            await asyncio.sleep(POLL_INTERVAL)
        else:
            # Brief yield to let spawned tasks start their async submit
            await asyncio.sleep(0.1)


if __name__ == "__main__":
    asyncio.run(main())
