"""Realtime transcription bridge using the OpenAI Realtime API."""
from __future__ import annotations

import base64
import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

import numpy as np
from openai import OpenAI
from openai import OpenAIError  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)


class RealtimeBridgeError(RuntimeError):
    """Raised when a realtime session cannot be established."""


@dataclass
class _ResponseState:
    metadata: Dict[str, str] = field(default_factory=dict)
    text: str = ""


class RealtimeBridge:
    """Small helper that forwards PCM frames to the Realtime API and streams transcripts back."""

    def __init__(
        self,
        *,
        client: OpenAI,
        model: str,
        recording_id: str,
        input_sample_rate: int,
        target_sample_rate: int = 24000,
        instructions: Optional[str] = None,
        on_transcript: Callable[[Dict[str, str], str, bool], None],
        metadata_base: Optional[Dict[str, str]] = None,
    ) -> None:
        self._client = client
        self._model = model
        self._recording_id = recording_id
        self._input_sample_rate = max(1, int(input_sample_rate))
        self._target_sample_rate = max(1, int(target_sample_rate))
        self._instructions = instructions or ""
        self._metadata_base = metadata_base or {}
        self._on_transcript = on_transcript

        self._manager = None
        self._connection = None
        self._event_thread = None
        self._running = threading.Event()
        self._lock = threading.Lock()
        self._responses: Dict[str, _ResponseState] = {}
        self._min_commit_samples = max(1, int(round(self._target_sample_rate * 0.1)))
        self._fatal_error: Optional[str] = None
        self._min_commit_samples = max(1, int(round(self._target_sample_rate * 0.1)))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Open the websocket connection and start the event listener."""
        try:
            manager = self._client.realtime.connect(model=self._model)
            connection = manager.enter()
        except Exception as exc:  # pragma: no cover - network / dependency issues
            logger.error("Failed to open realtime connection: %s", exc, exc_info=True)
            raise RealtimeBridgeError(str(exc)) from exc

        # Configure session for text-only output and optional instructions.
        session_payload: Dict[str, object] = {
            "type": "realtime",
            "output_modalities": ["text"],
            "audio": {
                "input": {
                    "format": "pcm16",
                    "turn_detection": None,
                },
                "output": {"format": "pcm16"},
            },
        }
        if self._instructions:
            session_payload["instructions"] = self._instructions
        try:
            connection.session.update(session=session_payload)
        except OpenAIError as exc:
            logger.warning("Unable to apply realtime session instructions: %s", exc, exc_info=True)

        self._manager = manager
        self._connection = connection
        self._fatal_error = None
        self._running.set()
        self._event_thread = threading.Thread(target=self._event_loop, name="RealtimeBridgeEvents", daemon=True)
        self._event_thread.start()

    def stop(self) -> None:
        """Terminate the session and wait for the event thread to exit."""
        self._running.clear()
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:  # pragma: no cover - defensive
                logger.debug("Failed to close realtime connection cleanly", exc_info=True)
        if self._manager is not None:
            try:
                self._manager.__exit__(None, None, None)
            except Exception:  # pragma: no cover - defensive
                logger.debug("Failed to exit realtime manager cleanly", exc_info=True)
        if self._event_thread is not None:
            self._event_thread.join(timeout=2)
        self._connection = None
        self._manager = None
        self._event_thread = None
        with self._lock:
            self._responses.clear()

    # ------------------------------------------------------------------
    # Audio ingest
    # ------------------------------------------------------------------
    def send_window(
        self,
        *,
        chunk_index: int,
        start_ms: float,
        end_ms: float,
        audio: np.ndarray,
    ) -> bool:
        """Append a chunk of audio and trigger transcription.

        Returns True when the chunk was streamed successfully; False when the caller should
        fall back to the legacy Whisper path (e.g. the chunk was too short to satisfy the
        realtime minimum).
        """
        if not self._running.is_set() or self._connection is None:
            raise RealtimeBridgeError("Realtime session is not active")
        with self._lock:
            if self._fatal_error:
                raise RealtimeBridgeError(self._fatal_error)

        pcm_bytes = self._encode_audio(audio)
        if not pcm_bytes:
            return False
        sample_count = len(pcm_bytes) // 2
        if sample_count < self._min_commit_samples:
            return False

        audio_b64 = base64.b64encode(pcm_bytes).decode("ascii")
        metadata = {
            "recording_id": self._recording_id,
            **self._metadata_base,
            "chunk_index": str(chunk_index),
            "start_ms": f"{start_ms:.3f}",
            "end_ms": f"{end_ms:.3f}",
        }

        try:
            self._connection.input_audio_buffer.append(audio=audio_b64)
            self._connection.input_audio_buffer.commit()
            response_payload: Dict[str, object] = {
                "output_modalities": ["text"],
                "conversation": "none",
                "metadata": metadata,
            }
            if self._instructions:
                response_payload["instructions"] = self._instructions
            self._connection.response.create(response=response_payload)
        except OpenAIError as exc:  # pragma: no cover - realtime invocation failure
            logger.error("Realtime API rejected audio chunk: %s", exc, exc_info=True)
            raise RealtimeBridgeError(str(exc)) from exc
        with self._lock:
            if self._fatal_error:
                raise RealtimeBridgeError(self._fatal_error)
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _event_loop(self) -> None:
        assert self._connection is not None
        try:
            for event in self._connection:
                if not self._running.is_set():
                    break
                event_type = getattr(event, "type", None)
                if event_type == "response.created":
                    response = getattr(event, "response", None)
                    if response is None:
                        continue
                    metadata = {}
                    if getattr(response, "metadata", None):
                        metadata = dict(response.metadata)
                    with self._lock:
                        self._responses[getattr(response, "id")] = _ResponseState(metadata=metadata)
                elif event_type == "response.output_text.delta":
                    response_id = getattr(event, "response_id", "")
                    delta = getattr(event, "delta", "")
                    if not response_id:
                        continue
                    with self._lock:
                        state = self._responses.get(response_id)
                        if state is None:
                            continue
                        state.text += delta
                        self._emit(state.metadata, state.text, finalized=False)
                elif event_type == "response.output_text.done":
                    response_id = getattr(event, "response_id", "")
                    text = getattr(event, "text", "")
                    if not response_id:
                        continue
                    with self._lock:
                        state = self._responses.pop(response_id, _ResponseState(metadata={}))
                    if text:
                        state.text = text
                    self._emit(state.metadata, state.text, finalized=True)
                elif event_type == "error":  # pragma: no cover - server-side error path
                    error_obj = getattr(event, "error", None)
                    message = getattr(error_obj, "message", None) or str(error_obj or event)
                    logger.error("Realtime server error: %s", error_obj or event)
                    with self._lock:
                        self._fatal_error = message
                    break
        except Exception:  # pragma: no cover - defensive
            logger.exception("Realtime event loop terminated unexpectedly")
        finally:
            self._running.clear()

    def _emit(self, metadata: Dict[str, str], text: str, finalized: bool) -> None:
        try:
            self._on_transcript(metadata, text or "", finalized)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Realtime transcript callback failed")

    def _encode_audio(self, audio: np.ndarray) -> bytes:
        """Convert a float32 numpy buffer into base64-ready PCM16 at the target sample rate."""
        if audio.size == 0:
            return b""
        mono = audio
        if audio.ndim > 1:
            mono = audio[:, 0]
        resampled = self._resample(mono.astype(np.float32))
        clipped = np.clip(resampled, -1.0, 1.0)
        pcm = (clipped * 32767.0).astype("<i2")
        return pcm.tobytes()

    def _resample(self, audio: np.ndarray) -> np.ndarray:
        if self._input_sample_rate == self._target_sample_rate or audio.size == 0:
            return audio
        input_rate = float(self._input_sample_rate)
        target_rate = float(self._target_sample_rate)
        duration = audio.shape[0] / input_rate
        new_length = max(1, int(round(duration * target_rate)))
        if new_length == audio.shape[0]:
            return audio
        old_indices = np.linspace(0.0, audio.shape[0] - 1, num=audio.shape[0], dtype=np.float64)
        new_indices = np.linspace(0.0, audio.shape[0] - 1, num=new_length, dtype=np.float64)
        resampled = np.interp(new_indices, old_indices, audio.astype(np.float64))
        return resampled.astype(np.float32)
