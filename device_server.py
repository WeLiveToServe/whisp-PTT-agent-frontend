"""Device server orchestrating recording, local transcription, and caching."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from device.database import ChitRecord, LiveSegment, db_session, init_db
from device.recorder_service import RecorderBusyError, RecorderIdleError, recorder_service
from device.transcription import transcribe

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="WhisPTT Device Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)


class ChitResponse(BaseModel):
    id: str
    recording_id: str | None
    audio_path: str
    transcript: str
    mocked: bool
    created_at: str


class StatusResponse(BaseModel):
    status: str
    recording_id: str | None = None
    last_error: str | None = None


class LiveSegmentResponse(BaseModel):
    recording_id: str
    chunk_index: int
    start_ms: float
    end_ms: float
    text: str
    mocked: bool
    finalized: bool


class LiveStatusResponse(BaseModel):
    status: str
    recording_id: str | None
    segments: List[LiveSegmentResponse]


@app.on_event("startup")
async def on_startup() -> None:
    init_db()


@app.post("/api/record/start", response_model=StatusResponse)
async def api_record_start() -> StatusResponse:
    try:
        recording_id = recorder_service.start()
    except RecorderBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Failed to start recording")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return StatusResponse(status="recording", recording_id=recording_id, last_error=None)


@app.post("/api/record/stop", response_model=ChitResponse)
async def api_record_stop() -> ChitResponse:
    try:
        result = recorder_service.stop()
    except RecorderIdleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to stop recording")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    audio_path = result.get("audio_path")
    if not audio_path:
        raise HTTPException(status_code=500, detail="Recorder did not provide audio path")

    transcript_text, mocked = transcribe(audio_path)
    recording_id = result.get("recording_id")

    with db_session() as session:
        record = ChitRecord(
            recording_id=recording_id,
            audio_path=audio_path,
            transcript=transcript_text,
            mocked=mocked,
        )
        session.add(record)
        session.flush()
        payload = ChitResponse(
            id=record.id,
            recording_id=recording_id,
            audio_path=audio_path,
            transcript=transcript_text,
            mocked=mocked,
            created_at=record.created_at.isoformat()
        )

    return payload


@app.get("/api/chits", response_model=List[ChitResponse])
async def api_list_chits() -> List[ChitResponse]:
    with db_session() as session:
        records = session.query(ChitRecord).order_by(ChitRecord.created_at.asc()).all()
        return [
            ChitResponse(
                id=record.id,
                recording_id=record.recording_id,
                audio_path=record.audio_path,
                transcript=record.transcript,
                mocked=record.mocked,
                created_at=record.created_at.isoformat(),
            )
            for record in records
        ]



@app.get("/api/live", response_model=LiveStatusResponse)
async def api_live() -> LiveStatusResponse:
    recording_id = recorder_service.current_recording_id()
    segments: List[LiveSegmentResponse] = []
    with db_session() as session:
        if recording_id:
            records = (
                session.query(LiveSegment)
                .filter(LiveSegment.recording_id == recording_id)
                .order_by(LiveSegment.chunk_index.asc())
                .all()
            )
        else:
            records = []
        for record in records:
            segments.append(
                LiveSegmentResponse(
                    recording_id=record.recording_id,
                    chunk_index=record.chunk_index,
                    start_ms=record.start_ms,
                    end_ms=record.end_ms,
                    text=record.text,
                    mocked=record.mocked,
                    finalized=record.finalized,
                )
            )
    return LiveStatusResponse(
        status=recorder_service.status(),
        recording_id=recording_id,
        segments=segments,
    )


@app.get("/api/status", response_model=StatusResponse)
async def api_status() -> StatusResponse:
    return StatusResponse(
        status=recorder_service.status(),
        recording_id=recorder_service.current_recording_id(),
        last_error=recorder_service.last_error(),
    )


@app.post("/api/session/export")
async def api_export_session() -> dict:
    with db_session() as session:
        records = session.query(ChitRecord).order_by(ChitRecord.created_at.asc()).all()
        if not records:
            export_path = Path("sessions") / "session-empty.txt"
            export_path.parent.mkdir(parents=True, exist_ok=True)
            export_path.touch(exist_ok=True)
            return {"status": "exported", "export_path": str(export_path), "entries": 0}

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        export_path = Path("sessions") / f"session-{timestamp}.txt"
        export_lines = []
        combined = []
        for record in records:
            export_lines.append(f"[{record.created_at.isoformat()}] {record.transcript.strip()}")
            combined.append(record.transcript.strip())
        export_path.write_text("\n".join(export_lines) + "\n", encoding="utf-8")

    combined_text = "\n\n".join(filter(None, combined))
    with db_session() as session:
        session.query(ChitRecord).delete()
        session.query(LiveSegment).delete()
    return {"status": "exported", "export_path": str(export_path), "entries": len(records), "combined_transcript": combined_text}


@app.post("/api/transcript/clear")
async def api_clear_transcripts() -> StatusResponse:
    with db_session() as session:
        session.query(ChitRecord).delete()
        session.query(LiveSegment).delete()
    return StatusResponse(status="cleared", last_error=None)


if __name__ == "__main__":
    port = int("7000")
    uvicorn.run("device_server:app", host="127.0.0.1", port=port, reload=False)

