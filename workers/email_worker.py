"""
Consumes email-events and sends emails via SMTP.

Replaces background threads in user_service.py.

Usage:
    python -m workers.email_worker
"""

import logging

from events.consumer import BaseConsumer
from events.config import CONSUMER_GROUP_EMAIL_SENDER
from events.topics import EMAIL_EVENTS, EMAIL_EVENTS_DLQ

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmailWorker(BaseConsumer):
    def __init__(self):
        super().__init__(
            group_id=CONSUMER_GROUP_EMAIL_SENDER,
            topics=[EMAIL_EVENTS],
            dlq_topic=EMAIL_EVENTS_DLQ,
            max_retries=5,
        )
        from users.service.user_service import EmailService
        self.email_service = EmailService()

    def handle(self, event_type: str, payload: dict) -> None:
        if event_type == "email.verification":
            self.email_service.send_verification_email(
                email_id=payload["email"],
                verification_code=payload["verification_code"],
                user_id=payload["user_id"],
            )
            logger.info(f"Verification email sent to {payload['email']}")

        elif event_type == "email.password_reset":
            self.email_service.send_password_reset_email(
                email_id=payload["email"],
                reset_code=payload["reset_code"],
            )
            logger.info(f"Password reset email sent to {payload['email']}")

        elif event_type == "email.verification_success":
            self.email_service.send_verification_success_email(
                email_id=payload["email"],
            )
            logger.info(f"Verification success email sent to {payload['email']}")


if __name__ == "__main__":
    EmailWorker().start()
