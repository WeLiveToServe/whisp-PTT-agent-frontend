import json
import queue
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import recorder_latest  # reuses push-to-talk logic

try:
    import transcripter_latest
except Exception:  # fallback when transcription module or credentials are unavailable
    transcripter_latest = None  # type: ignore

# Lazy import to avoid loading keyboard globally until we patch it per recording
import keyboard  # type: ignore
from unittest.mock import patch

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

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RecorderBusyError("Recorder already running")

            self._result_queue = queue.Queue()
            self._virtual_keys.reset()

            def worker() -> None:
                try:
                    with patch.object(keyboard, "is_pressed", self._virtual_keys.is_pressed):
                        path = recorder_latest.record_push_to_talk()
                    self._result_queue.put({"audio_path": path})
                except Exception as exc:  # pragma: no cover - defensive logging
                    self._result_queue.put({"error": str(exc)})

            self._thread = threading.Thread(target=worker, daemon=True)
            self._thread.start()

            # engage recording state once the thread is live
            time.sleep(0.05)
            self._virtual_keys.set_space(True)

    def stop(self) -> dict:
        with self._lock:
            if not self._thread or not self._thread.is_alive():
                raise RecorderIdleError("Recorder is not running")

            self._virtual_keys.set_space(False)
            self._virtual_keys.tap_backspace()

        self._thread.join(timeout=10)
        if self._thread.is_alive():
            raise RuntimeError("Recorder did not shut down cleanly")

        try:
            result = self._result_queue.get_nowait()
        except queue.Empty as exc:
            raise RuntimeError("Recorder finished without result") from exc
        finally:
            with self._lock:
                self._thread = None

        if "error" in result:
            raise RuntimeError(result["error"])
        return result

    def status(self) -> str:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return "recording"
            return "idle"


def run_transcription(audio_path: str) -> tuple[str, bool]:
    timestamp = datetime.utcnow().strftime("%H:%M:%S")

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
        fallback = f"[Mock transcript @ {timestamp}: {exc}]"
        return fallback, True


class TranscriptStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[dict] = []

    def add(self, transcript: str, audio_path: str, mocked: bool) -> dict:
        entry = {
            "transcript": transcript,
            "audio_path": audio_path,
            "mocked": mocked,
            "timestamp": datetime.utcnow().isoformat(),
        }
        with self._lock:
            self._entries.append(entry)
        return entry

    def all(self) -> list[dict]:
        with self._lock:
            return list(self._entries)


recorder_service = RecorderService()
transcript_store = TranscriptStore()


class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:  # pragma: no cover - silence default logs
        return

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
            payload = {"status": recorder_service.status(), "history": transcript_store.all()}
            self._write_json(payload)
        else:
            self._write_json({"error": "Not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/record/start":
            self._handle_start()
        elif self.path == "/api/record/stop":
            self._handle_stop()
        else:
            self._write_json({"error": "Not found"}, status=404)

    def _handle_start(self) -> None:
        try:
            recorder_service.start()
        except RecorderBusyError as exc:
            self._write_json({"error": str(exc)}, status=409)
            return
        except Exception as exc:  # pragma: no cover - unexpected failures
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
            self._write_json({"error": str(exc)}, status=500)
            return

        transcript_text, mocked = run_transcription(audio_path)
        entry = transcript_store.add(transcript_text, audio_path, mocked)
        self._write_json({"status": "completed", **entry})


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"Server running on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
