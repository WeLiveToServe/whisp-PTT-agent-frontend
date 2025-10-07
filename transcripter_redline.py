import base64
import io
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openai import OpenAI
from openai import OpenAIError  # type: ignore[attr-defined]
from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)

# Create a client once per module import so connections can be reused.
client = OpenAI()

APP_TRANSCRIBE_MODEL = (
    os.getenv("WHISP_TRANSCRIBE_APP_ID")
    or os.getenv("WHISP_APP_TRANSCRIBE_ID")
    or os.getenv("OPENAI_APP_TRANSCRIBE_ID")
)
APP_TRANSCRIBE_INSTRUCTIONS = os.getenv("WHISP_TRANSCRIBE_APP_INSTRUCTIONS")
APP_TRANSCRIBE_REQUIRED = os.getenv("WHISP_TRANSCRIBE_APP_REQUIRED", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


class _AppTranscriber:
    """Lightweight wrapper around the OpenAI App SDK Responses API for audio transcripts."""

    def __init__(
        self,
        *,
        client: OpenAI,
        model: str,
        instructions: Optional[str] = None,
    ) -> None:
        self._client = client
        self._model = model
        self._instructions = instructions

    def transcribe_file(self, audio_path: str, prompt: Optional[str] = None) -> str:
        """Encode a file from disk and ask the App to transcribe it."""
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio path not found: {audio_path}")
        audio_format = self._normalize_format(path.suffix)
        audio_bytes = path.read_bytes()
        return self.transcribe_bytes(audio_bytes, audio_format=audio_format, prompt=prompt)

    def transcribe_bytes(
        self,
        audio_bytes: bytes,
        *,
        audio_format: str = "wav",
        prompt: Optional[str] = None,
    ) -> str:
        """Send raw audio bytes to the App for transcription."""
        normalized_format = self._normalize_format(audio_format)
        encoded = base64.b64encode(audio_bytes).decode("ascii")
        return self._invoke(encoded_audio=encoded, audio_format=normalized_format, prompt=prompt)

    def _invoke(
        self,
        *,
        encoded_audio: str,
        audio_format: str,
        prompt: Optional[str],
    ) -> str:
        content = []
        if prompt:
            content.append({"type": "input_text", "text": prompt})
        content.append(
            {
                "type": "input_audio",
                "input_audio": {"data": encoded_audio, "format": audio_format},
            }
        )

        request_body = {
            "model": self._model,
            "input": [{"role": "user", "content": content}],
        }
        if self._instructions:
            request_body["instructions"] = self._instructions

        response = self._client.responses.create(**request_body)
        text = (response.output_text or "").strip()
        if text:
            return text

        # Fallback: aggregate any textual content the App returned.
        fragments: list[str] = []
        for item in response.output:
            if getattr(item, "type", None) != "message":
                continue
            for block in getattr(item, "content", []) or []:
                if getattr(block, "type", None) == "output_text" and getattr(block, "text", None):
                    fragments.append(block.text)
        return " ".join(fragments).strip()

    @staticmethod
    def _normalize_format(extension_or_format: str) -> str:
        fmt = (extension_or_format or "").lower().lstrip(".")
        if not fmt:
            fmt = "wav"
        if fmt not in {"wav", "mp3"}:
            raise ValueError(
                f"Unsupported audio format '{extension_or_format}'. "
                "The App SDK currently accepts wav or mp3 encoded audio."
            )
        return fmt


_APP_TRANSCRIBER: Optional[_AppTranscriber] = None


def _get_app_transcriber() -> Optional[_AppTranscriber]:
    """Instantiate the App-based transcriber on first use if configured."""
    global _APP_TRANSCRIBER
    if not APP_TRANSCRIBE_MODEL:
        return None
    if _APP_TRANSCRIBER is None:
        try:
            _APP_TRANSCRIBER = _AppTranscriber(
                client=client,
                model=APP_TRANSCRIBE_MODEL,
                instructions=APP_TRANSCRIBE_INSTRUCTIONS,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.error("Failed to initialise App transcriber: %s", exc, exc_info=True)
            if APP_TRANSCRIBE_REQUIRED:
                raise
            return None
    return _APP_TRANSCRIBER


def _transcribe_with_whisper(audio_path: str, prompt: Optional[str] = None) -> str:
    with open(audio_path, "rb") as audio_file:
        kwargs = {"model": "whisper-1", "file": audio_file}
        if prompt:
            kwargs["prompt"] = prompt
        transcript = client.audio.transcriptions.create(**kwargs)
    return (getattr(transcript, "text", "") or "").strip()


def transcribe_whisper_file(audio_path: str, prompt: Optional[str] = None) -> str:
    """Transcribe a single audio file and return raw text."""
    app_transcriber = _get_app_transcriber()
    if app_transcriber is not None:
        try:
            return app_transcriber.transcribe_file(audio_path, prompt=prompt)
        except (OpenAIError, ValueError, FileNotFoundError) as exc:
            if APP_TRANSCRIBE_REQUIRED:
                raise
            logger.warning("App transcription failed for %s: %s", audio_path, exc, exc_info=True)
        except Exception as exc:  # pragma: no cover - unexpected App SDK failure
            if APP_TRANSCRIBE_REQUIRED:
                raise
            logger.exception("Unexpected App transcription failure for %s", audio_path)

    return _transcribe_with_whisper(audio_path, prompt)

def transcribe_and_enhance(audio_path):
    """
    Transcribes audio via the App SDK when available, falling back to Whisper.
    Returns (raw_transcript, enhanced_transcript).
    """
    raw_text = transcribe_whisper_file(audio_path)

    # <span style="color: red;">
    # with open("sessions/transcripts.log", "a", encoding="utf-8") as log_file:
    #     timestamp = datetime.now(timezone.utc).isoformat()
    #     log_file.write(f"[{timestamp}] {audio_path} :: {raw_text}\n")
    # </span>
    # <span style="color: blue;">
    # CHANGED: The above code was incorrectly indented at module level, causing it to run
    # on import rather than when the function is called. It also referenced local variables
    # (raw_text, audio_path) that don't exist in module scope. Moved inside the function.
    # </span>
    
    with open("sessions/transcripts.log", "a", encoding="utf-8") as log_file:
        timestamp = datetime.now(timezone.utc).isoformat()
        log_file.write(f"[{timestamp}] {audio_path} :: {raw_text}\n")

    # Enhance with GPT (future hook via App SDK tool call).
    # enhanced = client.chat.completions.create(
    #    model="gpt-4o-mini",
     #   messages=[
     #       {"role": "system", "content": "You are a helpful assistant that cleans up spoken transcripts for clarity."},
     #       {"role": "user", "content": raw_text}
     #   ]
    #)
    #enhanced_text = enhanced.choices[0].message.content.strip()
   
    enhanced_text = raw_text
    return raw_text, enhanced_text

def save_transcripts(session_file, raw_text, enhanced_text, audio_file):
    """
    Saves raw and enhanced transcripts into a .md debug log,
    and appends only enhanced text into the rolling .txt session file.
    """
    base_name = os.path.splitext(session_file)[0]
    md_path = base_name + ".md"
    txt_path = base_name + ".txt"

    # <span style="color: red;">
    # timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # </span>
    # <span style="color: blue;">
    # CHANGED: datetime.now() without timezone info creates naive datetime objects.
    # Better to use timezone-aware datetimes for consistency with other parts of the codebase.
    # </span>
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Write MD log (debugging)
    with open(md_path, "a", encoding="utf-8") as f:
        f.write(f"# Transcript Update - {os.path.basename(audio_file)}\n\n")
        f.write(f"**Generated:** {timestamp}\n")
        f.write(f"**Enhanced:** Yes\n\n")
        f.write("---\n\n")
        f.write("**Raw Whisper Output**\n\n")
        f.write(raw_text + "\n\n")
        f.write("**Enhanced Transcript**\n\n")
        f.write(enhanced_text + "\n\n")
        f.write("---------------------------\n\n")

    # Write rolling TXT (user log)
    with open(txt_path, "a", encoding="utf-8") as f:
        f.write(enhanced_text + "\n")
        f.write("\n---\n\n")

    return md_path, txt_path

# ===============================
# Experimental Live Transcription
# ===============================

def live_transcribe(stream_generator, chunk_seconds=1):
    """
    Near-live transcription using gpt-4o-mini-transcribe.
    stream_generator: yields small audio chunks (bytes-like).
    chunk_seconds: approximate duration of each chunk.
    
    Prints and yields partial transcripts as chunks are processed.
    """
    

    app_transcriber = _get_app_transcriber()
    prompt_text: Optional[str] = None

    for i, chunk in enumerate(stream_generator):
        try:
            if app_transcriber is not None:
                partial_text = app_transcriber.transcribe_bytes(
                    chunk,
                    audio_format="wav",
                    prompt=prompt_text,
                )
            else:
                audio_file = io.BytesIO(chunk)
                audio_file.name = f"chunk_{i}.wav"
                transcript = client.audio.transcriptions.create(
                    model="gpt-4o-mini-transcribe",
                    file=audio_file,
                    language="en",
                )
                partial_text = transcript.text.strip()
        except Exception as e:
            partial_text = f"[Error on chunk {i}: {e}]"
        else:
            if partial_text:
                prompt_text = f"{prompt_text or ''} {partial_text}".strip()
                if len(prompt_text) > 500:
                    prompt_text = prompt_text[-500:]

        # Pretty-print rolling text in green, typewriter style
        for char in partial_text + "\n":
            console.print(char, style="green", end="")
            sys.stdout.flush()
            time.sleep(0.01)

        yield partial_text
