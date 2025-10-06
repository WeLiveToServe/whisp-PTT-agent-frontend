"""Device-side transcription helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

try:
    import transcripter_redline
except Exception:  # pragma: no cover - optional dependency
    transcripter_redline = None  # type: ignore


def transcribe(audio_path: str) -> Tuple[str, bool]:
    """Transcribe audio locally, falling back to mock text if unavailable."""
    if transcripter_redline is None:
        filename = Path(audio_path).name
        return f"[Transcript unavailable for {filename}]", True

    raw_text, enhanced_text = transcripter_redline.transcribe_and_enhance(audio_path)
    transcript = (enhanced_text or raw_text or "").strip()
    mocked = False
    if not transcript:
        transcript = "[Empty transcript]"
        mocked = True
    return transcript, mocked
