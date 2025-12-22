from redis import Redis
import os
import json
from typing import Any


REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = os.getenv("REDIS_PORT")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

redis_client = Redis(host=REDIS_HOST, port=REDIS_PORT)

class RedisService:
    def __init__(self):
        self.redis_client = redis_client
    def set_value(self, key: str, value: Any, ttl: int):
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        self.redis_client.set(key, value, ex=ttl)

    def get_value(self, key: str):
        result = self.redis_client.get(key)
        if result is None:
            return None
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return result.decode('utf-8') if isinstance(result, bytes) else result

    def delete_value(self, key: str):
        self.redis_client.delete(key)