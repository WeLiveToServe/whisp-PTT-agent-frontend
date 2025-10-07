"""Device-side transcription helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

try:
    import transcripter
except Exception:  # pragma: no cover - optional dependency
    transcripter = None  # type: ignore


def transcribe(audio_path: str) -> Tuple[str, bool]:
    """Transcribe audio locally, falling back to mock text if unavailable."""
    if transcripter is None:
        filename = Path(audio_path).name
        return f"[Transcript unavailable for {filename}]", True

    # NEW: transcribe_audio() replaces transcribe_and_enhance()
    transcript = transcripter.transcribe_audio(audio_path)
    transcript = (transcript or "").strip()
    mocked = False
    if not transcript:
        transcript = "[Empty transcript]"
        mocked = True
    return transcript, mocked


def transcribe_live_chunk(audio_path: str, prompt_text: Optional[str] = None) -> Tuple[str, bool]:
    """Transcribe a short audio chunk via OpenAI Whisper."""
    if transcripter is None:
        filename = Path(audio_path).name
        return f"[Transcript unavailable for {filename}]", True

    try:
        # NEW: transcribe_audio() replaces transcribe_whisper_file()
        raw_text = transcripter.transcribe_audio(audio_path, prompt_text)
    except Exception as exc:  # pragma: no cover - network failure or client issues
        return f"[transcription error: {exc}]", True

    transcript = (raw_text or "").strip()
    if not transcript:
        return "[Empty transcript]", True
    return transcript, False
