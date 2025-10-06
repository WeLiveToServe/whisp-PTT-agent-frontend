"""Recorder management for the local device server."""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Optional
import logging

import keyboard  # type: ignore
from unittest.mock import patch

import recorder_redline

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
    """Wraps recorder_redline to provide explicit start/stop control."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._result_queue: "queue.Queue[dict]" = queue.Queue()
        self._virtual_keys = VirtualKeypad()
        self._last_result: Optional[dict] = None
        self._last_error: Optional[str] = None

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RecorderBusyError("Recorder already running")

            self._result_queue = queue.Queue()
            self._last_result = None
            self._last_error = None
            self._virtual_keys.reset()

            def worker() -> None:
                try:
                    with patch.object(keyboard, "is_pressed", self._virtual_keys.is_pressed):
                        path = recorder_redline.record_push_to_talk()
                    self._result_queue.put({"audio_path": path})
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
            return

        try:
            result = self._result_queue.get_nowait()
        except queue.Empty as exc:
            raise RuntimeError("Recorder failed to start") from exc

        if "error" in result:
            with self._lock:
                self._last_error = result["error"]
                self._thread = None
            raise RuntimeError(result["error"])

        with self._lock:
            self._last_result = result
            self._thread = None

    def stop(self) -> dict:
        with self._lock:
            thread = self._thread
            cached_result = self._last_result
            cached_error = self._last_error

        if not thread:
            if cached_error:
                with self._lock:
                    self._last_error = None
                raise RuntimeError(cached_error)
            if cached_result:
                with self._lock:
                    self._last_result = None
                return cached_result
            raise RecorderIdleError("Recorder is not running")

        if thread.is_alive():
            with self._lock:
                self._virtual_keys.set_space(False)
                self._virtual_keys.tap_backspace()

        thread.join(timeout=10)

        try:
            result = self._result_queue.get_nowait()
        except queue.Empty as exc:
            raise RuntimeError("Recorder produced no output") from exc

        if "error" in result:
            with self._lock:
                self._last_error = result["error"]
                self._thread = None
            raise RuntimeError(result["error"])

        with self._lock:
            self._thread = None
            self._last_result = None
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


recorder_service = RecorderService()
