"""Backend database models using SQLAlchemy."""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import Column, DateTime, String, Boolean, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = Path("sessions") / "backend.db"
DB_URL = f"sqlite:///{DB_PATH}"

Base = declarative_base()
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class BackendChit(Base):
    __tablename__ = "backend_chits"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, nullable=True)
    audio_path = Column(String, nullable=False)
    draft_transcript = Column(String, nullable=True)
    final_transcript = Column(String, nullable=True)
    mocked = Column(Boolean, default=False, nullable=False)
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
