from sqlalchemy.orm import Session
from dashboard.data.model import EvalRecord
from datetime import datetime, timedelta


class EvalRecordRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, record: EvalRecord):
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def delete_all(self):
        count = self.db.query(EvalRecord).delete()
        self.db.commit()
        return count

    def get_daily_aggregates(self, days: int = 30):
        cutoff = datetime.utcnow() - timedelta(days=days)
        return self.db.query(EvalRecord).filter(
            EvalRecord.created_at >= cutoff
        ).order_by(EvalRecord.created_at.asc()).all()
