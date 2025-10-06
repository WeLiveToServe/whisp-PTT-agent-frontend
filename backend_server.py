"""Backend server placeholder for cloud-facing APIs."""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from backend.database import BackendChit, db_session, init_db

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="WhisPTT Backend Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


class ChitIn(BaseModel):
    audio_path: str
    transcript: str
    mocked: bool = False
    conversation_id: Optional[str] = None


class ChitOut(ChitIn):
    id: str
    final_transcript: Optional[str]
    created_at: str


@app.on_event("startup")
async def on_startup() -> None:
    init_db()


@app.get("/api/status")
async def api_status() -> dict:
    return {"status": "ok"}


@app.post("/api/chits", response_model=ChitOut)
async def api_create_chit(payload: ChitIn) -> ChitOut:
    with db_session() as session:
        record = BackendChit(
            audio_path=payload.audio_path,
            draft_transcript=payload.transcript,
            mocked=payload.mocked,
            conversation_id=payload.conversation_id,
        )
        session.add(record)
        session.flush()
        return ChitOut(
            id=record.id,
            audio_path=record.audio_path,
            transcript=record.draft_transcript or "",
            final_transcript=record.final_transcript,
            mocked=record.mocked,
            conversation_id=record.conversation_id,
            created_at=record.created_at.isoformat(),
        )


@app.get("/api/chits", response_model=List[ChitOut])
async def api_list_chits() -> List[ChitOut]:
    with db_session() as session:
        records = session.query(BackendChit).order_by(BackendChit.created_at.desc()).all()
        return [
            ChitOut(
                id=record.id,
                audio_path=record.audio_path,
                transcript=record.draft_transcript or "",
                final_transcript=record.final_transcript,
                mocked=record.mocked,
                conversation_id=record.conversation_id,
                created_at=record.created_at.isoformat(),
            )
            for record in records
        ]


class UpgradePayload(BaseModel):
    final_transcript: str


@app.post("/api/chits/{chit_id}/upgrade", response_model=ChitOut)
async def api_upgrade_chit(chit_id: str, payload: UpgradePayload) -> ChitOut:
    with db_session() as session:
        record = session.query(BackendChit).filter(BackendChit.id == chit_id).one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail="Chit not found")
        record.final_transcript = payload.final_transcript
        session.add(record)
        session.flush()
        return ChitOut(
            id=record.id,
            audio_path=record.audio_path,
            transcript=record.draft_transcript or "",
            final_transcript=record.final_transcript,
            mocked=record.mocked,
            conversation_id=record.conversation_id,
            created_at=record.created_at.isoformat(),
        )


if __name__ == "__main__":
    uvicorn.run("backend_server:app", host="127.0.0.1", port=8001, reload=False)
