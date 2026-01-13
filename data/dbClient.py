from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

env_file = os.getenv("ENV_FILE", ".env.dev")
load_dotenv(env_file)

DATABASE_URL = os.getenv("DATABASE_URL")

Base = declarative_base()

# API: Standard pooling for typical API server
_api_engine = create_engine(
    DATABASE_URL,
    pool_size=5,           # Default pool size
    max_overflow=10,       # Allow up to 15 total connections
    pool_recycle=300,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_api_engine)

# Worker: Strict pool limits for 1000+ replicas
_worker_engine = create_engine(
    DATABASE_URL,
    pool_size=1,           # Only 1 connection per worker
    max_overflow=0,        # No additional connections
    pool_recycle=300,      # Recycle every 5 minutes
    pool_pre_ping=True,    # Health check before use
)
WorkerSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_worker_engine)


def get_db():
    """Get API database session (standard pooling)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_worker_db():
    """Get Worker database session (minimal pooling for high replica count)."""
    db = WorkerSessionLocal()
    try:
        yield db
    finally:
        db.close()