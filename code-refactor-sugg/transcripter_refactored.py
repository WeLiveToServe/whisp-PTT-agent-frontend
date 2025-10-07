"""Audio transcription module using OpenAI APIs."""
import base64
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openai import OpenAI, OpenAIError

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI()

# Configuration from environment
APP_TRANSCRIBE_MODEL = (
    os.getenv("WHISP_TRANSCRIBE_APP_ID")
    or os.getenv("WHISP_APP_TRANSCRIBE_ID")
    or os.getenv("OPENAI_APP_TRANSCRIBE_ID")
)
APP_TRANSCRIBE_INSTRUCTIONS = os.getenv("WHISP_TRANSCRIBE_APP_INSTRUCTIONS")
APP_TRANSCRIBE_REQUIRED = os.getenv("WHISP_TRANSCRIBE_APP_REQUIRED", "").lower() in {
    "1", "true", "yes", "on"
}


class TranscriptionError(Exception):
    """Raised when transcription fails."""
    pass


def transcribe_audio(audio_path: str, prompt: Optional[str] = None) -> str:
    """
    Transcribe audio file using OpenAI App SDK or Whisper.
    
    Tries App SDK first if configured, falls back to Whisper.
    Logs transcript to sessions/transcripts.log.
    
    Args:
        audio_path: Path to audio file (WAV or MP3)
        prompt: Optional context/prompt for transcription
    
    Returns:
        Transcript text
    
    Raises:
        TranscriptionError: If transcription fails and fallback is disabled
    """
    audio_path = str(Path(audio_path).resolve())
    
    # Try App SDK if configured
    if APP_TRANSCRIBE_MODEL:
        try:
            text = _transcribe_with_app(audio_path, prompt)
            _log_transcript(audio_path, text)
            return text
        except Exception as e:
            if APP_TRANSCRIBE_REQUIRED:
                raise TranscriptionError(f"App transcription required but failed: {e}") from e
            logger.warning("App transcription failed, falling back to Whisper: %s", e)
    
    # Fallback to Whisper
    try:
        text = _transcribe_with_whisper(audio_path, prompt)
        _log_transcript(audio_path, text)
        return text
    except Exception as e:
        logger.exception("Whisper transcription failed")
        raise TranscriptionError(f"Transcription failed: {e}") from e


def _transcribe_with_app(audio_path: str, prompt: Optional[str] = None) -> str:
    """Transcribe using OpenAI App SDK."""
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    
    # Determine audio format
    audio_format = path.suffix.lower().lstrip(".")
    if audio_format not in {"wav", "mp3"}:
        raise ValueError(f"Unsupported format: {audio_format}")
    
    # Encode audio
    audio_bytes = path.read_bytes()
    encoded = base64.b64encode(audio_bytes).decode("ascii")
    
    # Build request
    content = []
    if prompt:
        content.append({"type": "input_text", "text": prompt})
    content.append({
        "type": "input_audio",
        "input_audio": {"data": encoded, "format": audio_format}
    })
    
    request_body = {
        "model": APP_TRANSCRIBE_MODEL,
        "input": [{"role": "user", "content": content}]
    }
    if APP_TRANSCRIBE_INSTRUCTIONS:
        request_body["instructions"] = APP_TRANSCRIBE_INSTRUCTIONS
    
    # Call API
    response = client.responses.create(**request_body)
    
    # Extract text from response
    text = (response.output_text or "").strip()
    if text:
        return text
    
    # Fallback: aggregate message content
    fragments = []
    for item in response.output:
        if getattr(item, "type", None) == "message":
            for block in getattr(item, "content", []) or []:
                if getattr(block, "type", None) == "output_text":
                    if text_content := getattr(block, "text", None):
                        fragments.append(text_content)
    
    result = " ".join(fragments).strip()
    if not result:
        raise TranscriptionError("App returned empty transcript")
    
    return result


def _transcribe_with_whisper(audio_path: str, prompt: Optional[str] = None) -> str:
    """Transcribe using Whisper API."""
    with open(audio_path, "rb") as audio_file:
        kwargs = {"model": "whisper-1", "file": audio_file}
        if prompt:
            kwargs["prompt"] = prompt
        transcript = client.audio.transcriptions.create(**kwargs)
    
    text = (getattr(transcript, "text", "") or "").strip()
    if not text:
        raise TranscriptionError("Whisper returned empty transcript")
    
    return text


def _log_transcript(audio_path: str, text: str) -> None:
    """Append transcript to session log."""
    log_path = Path("sessions/transcripts.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now(timezone.utc).isoformat()
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {audio_path} :: {text}\n")
