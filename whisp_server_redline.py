import json
import queue
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
import logging

import recorder_redline as recorder_latest  # reuses push-to-talk logic

try:
    import transcripter_redline as transcripter_latest
except Exception:  # fallback when transcription module or credentials are unavailable
    transcripter_latest = None  # type: ignore

# Lazy import to avoid loading keyboard globally until we patch it per recording
import keyboard  # type: ignore
from unittest.mock import patch

# <span style="color: blue;">
# ADDED: Configure logging at module level for better debugging and production monitoring
# </span>
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

SESSIONS_DIR = Path("sessions")
SESSIONS_DIR.mkdir(exist_ok=True)


class RecorderBusyError(RuntimeError):
    pass


class RecorderIdleError(RuntimeError):
    pass


class VirtualKeypad:
    """Lightweight shim that mimics keyboard.is_pressed for space/backspace."""

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
                        path = recorder_latest.record_push_to_talk()
                    self._result_queue.put({"audio_path": path})
                except Exception as exc:  # pragma: no cover - defensive logging
                    # <span style="color: blue;">
                    # ADDED: Log exceptions for debugging
                    # </span>
                    logger.error(f"Recorder worker failed: {exc}", exc_info=True)
                    self._result_queue.put({"error": str(exc)})

            self._thread = threading.Thread(target=worker, daemon=True)
            self._thread.start()
            # Signal the recorder loop immediately so quick taps still start capture
            self._virtual_keys.set_space(True)

        PORTAUDIO_INIT_DELAY_SECONDS = 0.1
        time.sleep(PORTAUDIO_INIT_DELAY_SECONDS)

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
            # <span style="color: red;">
            # thread.join(timeout=10)
            # </span>
            # <span style="color: blue;">
            # CHANGED: Magic number 10 replaced with named constant. This timeout prevents
            # the server from hanging indefinitely if the recorder thread doesn't respond
            # to the backspace signal (e.g., due to a deadlock or audio driver freeze).
            # </span>
            RECORDER_SHUTDOWN_TIMEOUT_SECONDS = 10
            thread.join(timeout=RECORDER_SHUTDOWN_TIMEOUT_SECONDS)
            if thread.is_alive():
                logger.warning("Recorder thread did not shut down cleanly within timeout")
                raise RuntimeError("Recorder did not shut down cleanly")
        else:
            thread.join(timeout=0)

        try:
            result = self._result_queue.get_nowait()
        except queue.Empty as exc:
            raise RuntimeError("Recorder finished without result") from exc
        finally:
            with self._lock:
                self._thread = None

        if "error" in result:
            with self._lock:
                self._last_error = result["error"]
            raise RuntimeError(result["error"])

        with self._lock:
            self._last_result = result
        return result

    def status(self) -> str:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return "recording"
            if self._last_error:
                return "error"
            return "idle"

    def last_error(self) -> Optional[str]:
        with self._lock:
            return self._last_error



def run_transcription(audio_path: str) -> tuple[str, bool]:
    # <span style="color: red;">
    # timestamp = datetime.utcnow().strftime("%H:%M:%S")
    # </span>
    # <span style="color: blue;">
    # CHANGED: datetime.utcnow() is deprecated in Python 3.12+. Replaced with
    # timezone-aware datetime.now(timezone.utc) which is the recommended approach.
    # This ensures proper timezone handling and future compatibility.
    # </span>
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")

    if transcripter_latest is None:
        mock_text = f"[Mock transcript @ {timestamp}]"
        return mock_text, True

    try:
        raw_text, enhanced_text = transcripter_latest.transcribe_and_enhance(audio_path)
        transcript = enhanced_text.strip() or raw_text.strip()
        if not transcript:
            transcript = f"[Empty transcript @ {timestamp}]"
        return transcript, False
    except Exception as exc:
        # <span style="color: blue;">
        # ADDED: Log transcription failures for debugging
        # </span>
        logger.error(f"Transcription failed for {audio_path}: {exc}", exc_info=True)
        fallback = f"[Mock transcript @ {timestamp}: {exc}]"
        return fallback, True


class TranscriptStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[dict] = []

    def add(self, transcript: str, audio_path: str, mocked: bool) -> dict:
        # <span style="color: red;">
        # entry = {
        #     "transcript": transcript,
        #     "audio_path": audio_path,
        #     "mocked": mocked,
        #     "timestamp": datetime.utcnow().isoformat(),
        # }
        # </span>
        # <span style="color: blue;">
        # CHANGED: datetime.utcnow() is deprecated. Using datetime.now(timezone.utc)
        # for consistency and to avoid deprecation warnings in Python 3.12+.
        # </span>
        entry = {
            "transcript": transcript,
            "audio_path": audio_path,
            "mocked": mocked,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._entries.append(entry)
        return entry

    def all(self) -> list[dict]:
        with self._lock:
            return list(self._entries)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


recorder_service = RecorderService()
transcript_store = TranscriptStore()


class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:  # pragma: no cover - silence default logs
        # <span style="color: blue;">
        # CHANGED: Instead of completely silencing HTTP logs, route them through
        # the logging framework so they can be controlled via log level configuration
        # </span>
        logger.debug(format % args)

    def _set_headers(self, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _write_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._set_headers(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._set_headers(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/status":
            payload = {
                "status": recorder_service.status(),
                "history": transcript_store.all(),
                "last_error": recorder_service.last_error(),
            }
            self._write_json(payload)
        else:
            self._write_json({"error": "Not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/record/start":
            self._handle_start()
        elif self.path == "/api/record/stop":
            self._handle_stop()
        elif self.path == "/api/session/export":
            self._handle_export()
        elif self.path == "/api/transcript/clear":
            self._handle_transcript_clear()
        else:
            self._write_json({"error": "Not found"}, status=404)

    def _handle_start(self) -> None:
        try:
            recorder_service.start()
        except RecorderBusyError as exc:
            self._write_json({"error": str(exc)}, status=409)
            return
        except Exception as exc:  # pragma: no cover - unexpected failures
            logger.error(f"Start recording failed: {exc}", exc_info=True)
            self._write_json({"error": str(exc)}, status=500)
            return
        self._write_json({"status": "recording"})

    def _handle_stop(self) -> None:
        try:
            result = recorder_service.stop()
            audio_path = result["audio_path"]
        except RecorderIdleError as exc:
            self._write_json({"error": str(exc)}, status=409)
            return
        except Exception as exc:  # pragma: no cover - unexpected failures
            logger.error(f"Stop recording failed: {exc}", exc_info=True)
            self._write_json({"error": str(exc)}, status=500)
            return

        transcript_text, mocked = run_transcription(audio_path)
        entry = transcript_store.add(transcript_text, audio_path, mocked)
        try:
            Path(audio_path).unlink(missing_ok=True)
        except Exception as cleanup_error:  # pragma: no cover - best effort cleanup
            logger.debug(f"Failed to remove audio file {audio_path}: {cleanup_error}")
        self._write_json({"status": "completed", **entry})

    def _handle_transcript_clear(self) -> None:
        transcript_store.clear()
        self._write_json({"status": "cleared"})

    def _handle_export(self) -> None:
        history = transcript_store.snapshot()
        export_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        export_path = SESSIONS_DIR / f"session-{export_timestamp}.txt"

        if not history:
            transcript_store.clear()
            export_path.touch(exist_ok=True)
            self._write_json({"status": "exported", "export_path": str(export_path), "entries": 0})
            return

        lines = []
        for entry in history:
            stamp = entry.get("timestamp", "")
            transcript = entry.get("transcript", "").strip()
            lines.append(f"[{stamp}] {transcript}")

        export_contents = "\n\n".join(lines) + "\n"
        export_path.write_text(export_contents, encoding="utf-8")
        transcript_store.clear()

        combined_transcript = "\n\n".join(entry.get("transcript", "").strip() for entry in history if entry.get("transcript"))
        self._write_json({"status": "exported", "export_path": str(export_path), "entries": len(history), "combined_transcript": combined_transcript})


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), RequestHandler)
    # <span style="color: red;">
    # print(f"Server running on http://{host}:{port}")
    # </span>
    # <span style="color: blue;">
    # CHANGED: Replaced print() with logger.info() for consistent logging.
    # This allows log levels to be controlled and logs to be redirected to files.
    # </span>
    logger.info(f"Server running on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        # <span style="color: red;">
        # print("\nStopping server...")
        # </span>
        # <span style="color: blue;">
        # CHANGED: Replaced print() with logger.info() for consistency
        # </span>
        logger.info("Stopping server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()