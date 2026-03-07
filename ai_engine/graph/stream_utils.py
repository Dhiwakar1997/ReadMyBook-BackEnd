"""Shared utilities for streaming graph responses (e.g. SSE)."""
import json


def sse_event(event_type: str, data: dict) -> str:
    """Formats a dictionary as an SSE message string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
