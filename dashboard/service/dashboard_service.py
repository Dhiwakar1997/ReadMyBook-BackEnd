import secrets
from datetime import date
from shared.redis import RedisService
from shared.azure_blob import blob_service_client

DASHBOARD_KEY_REDIS = "dashboard:api_key"
DASHBOARD_KEY_BLOB = "dashboard_key.txt"
CONTAINER = "pdfs"


class DashboardKeyService:
    def __init__(self):
        self.redis = RedisService()

    def get_or_create_today_key(self) -> str:
        cached = self.redis.get_value(DASHBOARD_KEY_REDIS)
        if cached and isinstance(cached, dict) and cached.get("date") == str(date.today()):
            return cached["key"]

        new_key = secrets.token_urlsafe(32)
        key_data = {"key": new_key, "date": str(date.today())}

        self.redis.set_value(DASHBOARD_KEY_REDIS, key_data, ttl=86400)
        self._upload_key_to_blob(new_key)

        return new_key

    def validate_key(self, provided_key: str) -> bool:
        today_key = self.get_or_create_today_key()
        return secrets.compare_digest(provided_key, today_key)

    def _upload_key_to_blob(self, key: str):
        try:
            container_client = blob_service_client.get_container_client(CONTAINER)
            blob_client = container_client.get_blob_client(DASHBOARD_KEY_BLOB)
            blob_client.upload_blob(
                f"Dashboard API Key (rotates daily)\nDate: {date.today()}\nKey: {key}\n",
                overwrite=True
            )
        except Exception as e:
            print(f"[DashboardKeyService] Failed to upload key to blob: {e}")
