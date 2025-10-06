"""Utility wrappers for invoking whisper.cpp."""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)

WHISPER_CPP_BIN = Path(os.environ.get("WHISPER_CPP_BIN", "whisper.cpp/main"))
WHISPER_CPP_MODEL = Path(os.environ.get("WHISPER_CPP_MODEL", "models/ggml-tiny.en.bin"))
WHISPER_LANGUAGE = os.environ.get("WHISPER_CPP_LANGUAGE", "en")
_CPU_COUNT = os.cpu_count() or 1
DEFAULT_THREADS = max(1, int(os.environ.get("WHISPER_CPP_THREADS", max(_CPU_COUNT - 1, 1))))


def _ensure_available() -> None:
    if not WHISPER_CPP_BIN.exists():
        raise RuntimeError(
            "whisper.cpp binary not found. Set WHISPER_CPP_BIN to the compiled 'main' executable."
        )
    if not WHISPER_CPP_MODEL.exists():
        raise RuntimeError(
            "whisper.cpp model not found. Set WHISPER_CPP_MODEL to a ggml model file (e.g., ggml-tiny.en.bin)."
        )


def transcribe_chunk(audio_path: Path | str, prompt_text: Optional[str] = None) -> Tuple[str, bool]:
    """Run whisper.cpp on a chunk of audio and return (text, mocked)."""
    _ensure_available()

    audio_path = Path(audio_path)
    output_base = Path(tempfile.gettempdir()) / f"whcpp-{audio_path.stem}-{uuid4()}"
    cmd = [
        str(WHISPER_CPP_BIN),
        "-m",
        str(WHISPER_CPP_MODEL),
        "-f",
        str(audio_path),
        "-otxt",
        "-of",
        str(output_base),
        "-l",
        WHISPER_LANGUAGE,
        "-t",
        str(DEFAULT_THREADS),
        "--temperature",
        "0",
    ]
    if prompt_text:
        cmd += ["--prompt", prompt_text]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:  # pragma: no cover - environment setup issue
        raise RuntimeError(f"Failed to execute whisper.cpp binary: {exc}") from exc

    if result.returncode != 0:
        logger.error("whisper.cpp failed: %s", result.stderr.strip())
        raise RuntimeError(result.stderr.strip() or "whisper.cpp transcription failed")

    txt_path = output_base.with_suffix(".txt")
    text = ""
    if txt_path.exists():
        text = txt_path.read_text(encoding="utf-8").strip()
        txt_path.unlink()

    # Clean up any other artefacts whisper.cpp may have produced
    for suffix in (".wav", ".json", ".srt", ".vtt", ".tsv"):
        artefact = output_base.with_suffix(suffix)
        if artefact.exists():
            artefact.unlink(missing_ok=True)

    mocked = not bool(text)
    return text, mocked
