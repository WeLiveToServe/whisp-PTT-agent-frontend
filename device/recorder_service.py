"""Recorder management for the local device server."""
from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import keyboard  # type: ignore
from unittest.mock import patch

import recorder_redline
from device.database import LiveSegment, db_session
from device.transcription import transcribe_live_chunk

logger = logging.getLogger(__name__)


class RecorderBusyError(RuntimeError):
    """Raised when a recording session is requested while one is already running."""


class RecorderIdleError(RuntimeError):
    """Raised when stop is requested but no active recording exists."""


class VirtualKeypad:
    """Shim to drive recorder_redline's keyboard-centric logic programmatically."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._space = False
        self._backspace = False

    def set_space(self, pressed: bool) -> None:
        with self._lock:
            self._space = pressed

    def tap_backspace(self) -> None:
        with self._lock:
            self._backspace = True

    def reset(self) -> None:
        with self._lock:
            self._space = False
            self._backspace = False

    def is_pressed(self, key: str) -> bool:
        with self._lock:
            if key == "space":
                return self._space
            if key == "backspace":
                if self._backspace:
                    self._backspace = False
                    return True
                return False
            return False


class RecorderService:
    """Wraps recorder_redline to provide explicit start/stop control with streaming."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._result_queue: "queue.Queue[dict]" = queue.Queue()
        self._virtual_keys = VirtualKeypad()
        self._last_result: Optional[dict] = None
        self._last_error: Optional[str] = None

        self._stream_queue: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream_thread: Optional[threading.Thread] = None
        self._stream_stop = threading.Event()

        self._current_recording_id: Optional[str] = None
        self._window_seconds = 2.0
        self._hop_seconds = 1.0
        self._sample_rate = recorder_redline.DEFAULT_SAMPLE_RATE
        self._channels = recorder_redline.DEFAULT_CHANNELS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start(self) -> str:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RecorderBusyError("Recorder already running")

            recording_id = str(uuid.uuid4())
            self._current_recording_id = recording_id
            self._result_queue = queue.Queue()
            self._stream_queue = queue.Queue()
            self._stream_stop = threading.Event()
            self._last_result = None
            self._last_error = None
            self._virtual_keys.reset()

            self._stream_thread = threading.Thread(
                target=self._stream_worker,
                args=(recording_id, self._sample_rate, self._channels),
                daemon=True,
            )
            self._stream_thread.start()

            def worker() -> None:
                try:
                    with patch.object(keyboard, "is_pressed", self._virtual_keys.is_pressed):
                        path = recorder_redline.record_push_to_talk(
                            sample_rate=self._sample_rate,
                            channels=self._channels,
                            frame_consumer=self._enqueue_frame,
                        )
                    self._result_queue.put({"audio_path": path, "recording_id": recording_id})
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.exception("Recorder worker failed")
                    self._result_queue.put({"error": str(exc)})

            self._thread = threading.Thread(target=worker, daemon=True)
            self._thread.start()
            self._virtual_keys.set_space(True)

        time.sleep(0.1)

        with self._lock:
            thread = self._thread
        if thread and thread.is_alive():
            return recording_id

        try:
            result = self._result_queue.get_nowait()
        except queue.Empty as exc:
            raise RuntimeError("Recorder failed to start") from exc

        if "error" in result:
            with self._lock:
                self._last_error = result["error"]
                self._thread = None
                self._current_recording_id = None
            raise RuntimeError(result["error"])

        with self._lock:
            self._last_result = result
            self._thread = None
        return recording_id

    def stop(self) -> dict:
        with self._lock:
            thread = self._thread
            cached_result = self._last_result
            cached_error = self._last_error
            recording_id = self._current_recording_id

        if not thread:
            if cached_error:
                with self._lock:
                    self._last_error = None
                    self._current_recording_id = None
                raise RuntimeError(cached_error)
            if cached_result:
                with self._lock:
                    self._last_result = None
                    self._current_recording_id = None
                return cached_result
            raise RecorderIdleError("Recorder is not running")

        if thread.is_alive():
            with self._lock:
                self._virtual_keys.set_space(False)
                self._virtual_keys.tap_backspace()

        thread.join(timeout=10)

        self._stream_stop.set()
        if self._stream_thread:
            self._stream_thread.join(timeout=10)

        try:
            result = self._result_queue.get_nowait()
        except queue.Empty as exc:
            raise RuntimeError("Recorder produced no output") from exc

        if "error" in result:
            with self._lock:
                self._last_error = result["error"]
                self._thread = None
                self._current_recording_id = None
            raise RuntimeError(result["error"])

        if recording_id:
            self._finalize_segments(recording_id)

        with self._lock:
            self._thread = None
            self._stream_thread = None
            self._last_result = None
            self._current_recording_id = None
        return result

    def status(self) -> str:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return "recording"
        return "idle"

    def last_error(self) -> Optional[str]:
        with self._lock:
            error = self._last_error
            self._last_error = None
            return error

    def current_recording_id(self) -> Optional[str]:
        with self._lock:
            return self._current_recording_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _enqueue_frame(self, frame: np.ndarray) -> None:
        if self._stream_stop.is_set():
            return
        array = np.asarray(frame, dtype=np.float32)
        if array.ndim == 1:
            array = array.reshape(-1, self._channels)
        self._stream_queue.put(array)

    def _stream_worker(self, recording_id: str, sample_rate: int, channels: int) -> None:
        buffer = np.empty((0, channels), dtype=np.float32)
        window_samples = max(1, int(self._window_seconds * sample_rate))
        hop_samples = max(1, int(self._hop_seconds * sample_rate))
        chunk_index = 0
        prompt_text: Optional[str] = None
        chunks_dir = Path("sessions") / "chunks" / recording_id
        chunks_dir.mkdir(parents=True, exist_ok=True)

        while not self._stream_stop.is_set() or not self._stream_queue.empty():
            try:
                frame = self._stream_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            buffer = np.vstack((buffer, frame))

            while buffer.shape[0] >= window_samples:
                prompt_text = self._process_window(
                    recording_id,
                    chunk_index,
                    buffer[:window_samples],
                    chunks_dir,
                    sample_rate,
                    hop_samples,
                    prompt_text,
                )
                buffer = buffer[hop_samples:]
                chunk_index += 1

        min_samples = window_samples // 2
        if buffer.shape[0] >= min_samples:
            prompt_text = self._process_window(
                recording_id,
                chunk_index,
                buffer,
                chunks_dir,
                sample_rate,
                hop_samples,
                prompt_text,
            )

        try:
            chunks_dir.rmdir()
        except OSError:
            pass

    def _process_window(
        self,
        recording_id: str,
        chunk_index: int,
        data: np.ndarray,
        chunks_dir: Path,
        sample_rate: int,
        hop_samples: int,
        prompt_text: Optional[str],
    ) -> Optional[str]:
        start_sample = chunk_index * hop_samples
        start_ms = (start_sample / sample_rate) * 1000
        end_ms = ((start_sample + data.shape[0]) / sample_rate) * 1000

        temp_path = chunks_dir / f"chunk-{chunk_index:05d}.wav"
        writable = data if data.shape[1] > 1 else data.reshape(-1)
        sf.write(temp_path, writable, sample_rate)
        try:
            text, mocked = transcribe_live_chunk(temp_path, prompt_text)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Chunk transcription failed")
            text = f"[transcription error: {exc}]"
            mocked = True
        finally:
            temp_path.unlink(missing_ok=True)

        with db_session() as session:
            session.add(
                LiveSegment(
                    recording_id=recording_id,
                    chunk_index=chunk_index,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text,
                    mocked=mocked,
                )
            )

        if not text:
            return prompt_text

        merged_prompt = f"{prompt_text or ''} {text}".strip()
        if len(merged_prompt) > 500:
            merged_prompt = merged_prompt[-500:]
        return merged_prompt

    def _finalize_segments(self, recording_id: str) -> None:
        with db_session() as session:
            session.query(LiveSegment).filter(
                LiveSegment.recording_id == recording_id
            ).update({"finalized": True}, synchronize_session=False)


recorder_service = RecorderService()
