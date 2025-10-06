"""Device-side database setup using SQLAlchemy on top of SQLite."""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import Column, DateTime, String, Boolean, Integer, Float, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = Path("sessions") / "device.db"
DB_URL = f"sqlite:///{DB_PATH}"

Base = declarative_base()
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class ChitRecord(Base):
    __tablename__ = "chits"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    recording_id = Column(String, nullable=True)
    audio_path = Column(String, nullable=False)
    transcript = Column(String, nullable=False)
    mocked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class LiveSegment(Base):
    __tablename__ = "live_segments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    recording_id = Column(String, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    start_ms = Column(Float, nullable=False)
    end_ms = Column(Float, nullable=False)
    text = Column(String, nullable=False)
    mocked = Column(Boolean, default=False, nullable=False)
    finalized = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


@contextmanager
def db_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
