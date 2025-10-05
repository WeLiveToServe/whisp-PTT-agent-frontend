import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import whisp_server_redline


class RecordingWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self._original_sessions_dir = whisp_server_redline.SESSIONS_DIR
        self._sessions_dir = (PROJECT_ROOT / "sessions")
        self._sessions_dir.mkdir(exist_ok=True)
        whisp_server_redline.SESSIONS_DIR = self._sessions_dir
        self.addCleanup(lambda: setattr(whisp_server_redline, "SESSIONS_DIR", self._original_sessions_dir))

        self.fake_audio_files: list[Path] = []
        self.recorder_patch = mock.patch(
            "whisp_server_redline.recorder_latest.record_push_to_talk",
            side_effect=self._fake_record,
        )
        self.recorder_patch.start()
        self.addCleanup(self.recorder_patch.stop)

        def fake_transcribe(path: str):
            filename = Path(path).stem
            return f"raw-{filename}", f"enhanced-{filename}"

        target = "whisp_server_redline.transcripter_latest.transcribe_and_enhance"
        if whisp_server_redline.transcripter_latest is None:
            stub = mock.Mock()
            stub.transcribe_and_enhance = fake_transcribe
            self.transcriber_patch = mock.patch("whisp_server_redline.transcripter_latest", new=stub)
            self.transcriber_patch.start()
            self.addCleanup(self.transcriber_patch.stop)
        self.transcribe_patch = mock.patch(target, side_effect=fake_transcribe)
        self.transcribe_patch.start()
        self.addCleanup(self.transcribe_patch.stop)

        self._server = whisp_server_redline.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            whisp_server_redline.RequestHandler,
        )
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.addCleanup(self._shutdown_server)

    def _shutdown_server(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def _fake_record(self) -> str:
        fd, temp_path = tempfile.mkstemp(prefix="snippet-", suffix=".wav", dir=self._sessions_dir)
        os.close(fd)
        path = Path(temp_path)
        path.write_bytes(b"fake audio data")
        self.fake_audio_files.append(path)
        return str(path)

    def _request(self, method: str, path: str) -> http.client.HTTPResponse:
        conn = http.client.HTTPConnection("127.0.0.1", self._port, timeout=5)
        conn.request(method, path)
        response = conn.getresponse()
        response.data = response.read()
        conn.close()
        return response

    def test_full_record_and_export_flow(self) -> None:
        transcripts = []

        for _ in range(3):
            response = self._request("POST", "/api/record/start")
            self.assertEqual(response.status, 200, response.data)
            time.sleep(0.05)

            response = self._request("POST", "/api/record/stop")
            self.assertEqual(response.status, 200, response.data)
            payload = json.loads(response.data)
            self.assertEqual(payload["status"], "completed")
            transcripts.append(payload["transcript"])

        for audio_file in self.fake_audio_files:
            self.assertFalse(audio_file.exists(), f"Audio file {audio_file} should have been removed")

        response = self._request("POST", "/api/session/export")
        self.assertEqual(response.status, 200, response.data)
        payload = json.loads(response.data)
        self.assertEqual(payload["status"], "exported")
        export_path = Path(payload["export_path"])
        self.assertTrue(export_path.exists(), "Export log file should exist")
        self.assertEqual(payload["entries"], len(transcripts))
        combined = payload.get("combined_transcript", "")
        self.assertTrue(combined, "Combined transcript should be populated")

        log_path = self._sessions_dir / f"test-workflow-{int(time.time())}.txt"
        with log_path.open("w", encoding="utf-8") as handle:
            for idx, snippet in enumerate(transcripts, 1):
                handle.write(f"Snippet {idx}: {snippet}\n")
            handle.write("\nCombined Transcript:\n")
            handle.write(combined + "\n")

        self.assertTrue(log_path.exists(), "Readable test log should be created")
        self.assertEqual(whisp_server_redline.transcript_store.all(), [])


if __name__ == "__main__":
    unittest.main()