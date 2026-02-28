from redis import Redis
import os
import json
import socket
from typing import Any, Optional


REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
# Get password - use getenv with default None to distinguish between unset and empty string
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
# Use SSL only for non-localhost connections (e.g., Azure Redis)
USE_SSL = os.getenv("REDIS_SSL", "false").lower() == "true" or (REDIS_HOST and REDIS_HOST != "localhost" and REDIS_HOST != "127.0.0.1")

# Configure socket keepalive options properly using socket constants
# Note: TCP keepalive options vary by platform (Linux vs macOS)
socket_keepalive_opts: Optional[dict] = None
try:
    # Try to use platform-specific TCP keepalive constants
    # Linux uses TCP_KEEPIDLE, TCP_KEEPINTVL, TCP_KEEPCNT
    # macOS uses different constants or may not support all of them
    if hasattr(socket, 'TCP_KEEPIDLE') and hasattr(socket, 'TCP_KEEPINTVL') and hasattr(socket, 'TCP_KEEPCNT'):
        socket_keepalive_opts = {
            socket.TCP_KEEPIDLE: 30,
            socket.TCP_KEEPINTVL: 10,
            socket.TCP_KEEPCNT: 3,
        }
except (AttributeError, OSError):
    # If socket constants are not available or invalid, skip keepalive options
    # socket_keepalive=True will still work without the options dict
    socket_keepalive_opts = None

# Build Redis connection parameters
# Only include password if it's actually set and not empty
redis_params: dict = {
    "host": REDIS_HOST,
    "port": REDIS_PORT,
    "ssl": USE_SSL,
    "socket_keepalive": True,
    "health_check_interval": 30,
    "retry_on_timeout": True,
    "socket_timeout": 5,
    "socket_connect_timeout": 5,
    "max_connections": 50,
}

# Only add password if it's set, not None, and not empty after stripping
# This ensures we don't pass password parameter at all when not needed
if REDIS_PASSWORD is not None and isinstance(REDIS_PASSWORD, str) and REDIS_PASSWORD.strip():
    redis_params["password"] = REDIS_PASSWORD.strip()

# Only add SSL cert requirements if SSL is enabled
if USE_SSL:
    redis_params["ssl_cert_reqs"] = None

# Only add socket keepalive options if they're available
if socket_keepalive_opts:
    redis_params["socket_keepalive_options"] = socket_keepalive_opts

redis_client = Redis(**redis_params)

class RedisService:
    def __init__(self):
        self.redis_client = redis_client

    def set_value(self, key: str, value: Any, ttl: int):
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            self.redis_client.set(key, value, ex=ttl)
        except Exception as e:
            print(f"Error setting value in Redis: {e}")
            raise e

    def get_value(self, key: str):
        try:
            result = self.redis_client.get(key)
            if result is None:
                return None
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return result.decode('utf-8') if isinstance(result, bytes) else result

    def increment(self, key: str) -> int:
        """Atomically increment an integer counter. Returns the new value."""
        try:
            return self.redis_client.incr(key)
        except Exception as e:
            print(f"Error incrementing key in Redis: {e}")
            return 0

    def delete_value(self, key: str):
        try:
            self.redis_client.delete(key)
        except Exception as e:
            print(f"Error deleting value in Redis: {e}")
            raise e
