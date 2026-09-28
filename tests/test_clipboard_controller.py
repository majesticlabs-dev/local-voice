import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from service.clipboard_controller import Controller


class Fixture(BaseHTTPRequestHandler):
    received = []
    response = 200

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.received.append(body["text"])
        self.send_response(self.response)
        self.end_headers()
        if self.response == 503:
            self.wfile.write(b'{"error":"setup_needed"}')
        else:
            self.wfile.write(b"fixture audio")

    def log_message(self, *args):
        pass


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lv-t07-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        self.text = root / "clipboard"
        self.injection = root / "injected"
        self.text.write_text(f"quoted ' $(touch {self.injection}) ; text. " * 30)
        self.played = root / "played"
        for name, content in {
            "wl-paste": '#!/bin/sh\ncat "$LV_TEST_CLIPBOARD"\n',
            "ffplay": '#!/bin/sh\ncat >> "$LV_TEST_PLAYED"\nsleep 5\n',
        }.items():
            file = bin_dir / name
            file.write_text(content)
            file.chmod(0o755)
        self.env = patch.dict(os.environ, {
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "LV_TEST_CLIPBOARD": str(self.text), "LV_TEST_PLAYED": str(self.played),
            "XDG_RUNTIME_DIR": str(root), "TMPDIR": str(root),
            "XDG_CACHE_HOME": str(root / "cache"), "LV_MODELS_DIR": str(root / "models"),
            "LV_OUTPUT_DIR": str(root / "output"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        Fixture.received = []
        Fixture.response = 200
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.shutdown)
        self.port = patch.dict(os.environ, {"LV_CONTROLLER_SERVICE_PORT": str(self.server.server_port)})
        self.port.start()
        self.addCleanup(self.port.stop)

    def wait_for(self, predicate):
        for _ in range(100):
            if predicate():
                return
            time.sleep(.05)
        self.fail("Timed out waiting for controller")

    def test_explicit_read_chunks_plays_and_stop_cancels_session(self):
        controller = Controller()
        self.assertEqual(controller.status()["state"], "idle")
        self.assertEqual(Fixture.received, [])
        controller.read_clipboard()
        self.wait_for(lambda: controller.status()["state"] == "playing")
        self.assertIn("quoted ' $(touch injected) ; text.", Fixture.received[0])
        self.assertEqual(self.played.read_bytes(), b"fixture audio")
        controller.stop()
        self.assertEqual(controller.status()["state"], "idle")
        time.sleep(.1)
        self.assertEqual(len(Fixture.received), 1)
        controller.read_clipboard()
        self.wait_for(lambda: len(Fixture.received) == 2)
        controller.stop()
        self.assertFalse(self.injection.exists())

    def test_empty_nontext_missing_player_and_setup_needed(self):
        controller = Controller()
        self.text.write_text("")
        controller.read_clipboard()
        self.wait_for(lambda: controller.status()["state"] == "error")
        self.assertEqual(Fixture.received, [])
        self.text.write_bytes(b"\xff")
        controller.read_clipboard()
        self.wait_for(lambda: controller.status()["state"] == "error")
        self.assertEqual(Fixture.received, [])
        self.text.write_text("\x1b[31m\ue0b0 ── 😀\x1b[0m")
        controller.read_clipboard()
        self.wait_for(lambda: controller.status()["state"] == "error")
        self.assertIn("no speakable text", controller.status()["error"])
        self.assertEqual(Fixture.received, [])
        self.text.write_text("Hello")
        Fixture.response = 503
        controller.read_clipboard()
        self.wait_for(lambda: controller.status()["state"] == "setup_needed")
        self.assertNotIn("Hello", json.dumps(controller.status()))
        controller.stop()
        Fixture.response = 200
        with patch.dict(os.environ, {"PATH": str(Path(self.tmp.name) / "empty")}):
            controller.read_clipboard()
            self.wait_for(lambda: controller.status()["state"] == "error")
            self.assertIn("Missing command", controller.status()["error"])

    def test_selection_reads_primary_and_toggle_stops(self):
        paste = Path(self.tmp.name) / "bin/wl-paste"
        paste.write_text('#!/bin/sh\n[ "$1" = "--primary" ] || exit 3\ncat "$LV_TEST_CLIPBOARD"\n')
        self.text.write_text("Selected words")
        controller = Controller()
        controller.toggle_selection()
        self.wait_for(lambda: controller.status()["state"] == "playing")
        self.assertEqual(Fixture.received, ["Selected words"])
        controller.toggle_selection()
        self.assertEqual(controller.status()["state"], "idle")
        self.assertEqual(len(Fixture.received), 1)

    def test_long_text_plays_all_chunks_sequentially(self):
        player = Path(self.tmp.name) / "bin/ffplay"
        player.write_text('#!/bin/sh\ncat >> "$LV_TEST_PLAYED"\n')
        self.text.write_text("Sentence one. Sentence two. " * 120)
        controller = Controller()
        controller.read_clipboard()
        self.wait_for(lambda: controller.status()["state"] == "idle" and len(Fixture.received) > 1)
        self.assertEqual(self.played.read_bytes(), b"fixture audio" * len(Fixture.received))
        self.assertEqual(" ".join(Fixture.received).replace("  ", " "), self.text.read_text().strip())

    def test_missing_backend_reports_error_without_playback(self):
        self.server.shutdown()
        self.server.server_close()
        controller = Controller()
        self.text.write_text("Private phrase")
        controller.read_clipboard()
        self.wait_for(lambda: controller.status()["state"] == "error")
        self.assertIn("Shared service unavailable", controller.status()["error"])
        self.assertNotIn("Private phrase", json.dumps(controller.status()))
        self.assertFalse(self.played.exists())

    def test_bad_socket_clients_do_not_stop_daemon(self):
        root = Path(self.tmp.name)
        process = subprocess.Popen([sys.executable, "-m", "service.clipboard_controller", "serve"],
                                   env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (process.terminate(), process.wait(timeout=3)) if process.poll() is None else None)
        path = root / "local-voice/controller.sock"
        self.wait_for(path.exists)
        for payload in (b"\xff", None, b"unknown\n"):
            with socket.socket(socket.AF_UNIX) as client:
                client.connect(str(path))
                if payload is not None:
                    client.sendall(payload)
                else:
                    time.sleep(2.2)
            self.assertIsNone(process.poll())
            with socket.socket(socket.AF_UNIX) as client:
                client.connect(str(path))
                client.sendall(b"status\n")
                self.assertEqual(json.loads(client.recv(4096))["state"], "idle")

    def test_socket_status_and_stop_do_not_read_clipboard(self):
        root = Path(self.tmp.name)
        process = subprocess.Popen([sys.executable, "-m", "service.clipboard_controller", "serve"],
                                   env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (process.terminate(), process.wait(timeout=3)) if process.poll() is None else None)
        path = root / "local-voice/controller.sock"
        self.wait_for(path.exists)
        for command in ("status", "stop"):
            result = subprocess.run([sys.executable, "-m", "service.clipboard_controller", command],
                                    capture_output=True, text=True, env=os.environ.copy(), check=True)
            self.assertEqual(json.loads(result.stdout)["state"], "idle")
        self.assertEqual(Fixture.received, [])
        self.assertFalse(self.played.exists())


if __name__ == "__main__":
    unittest.main()
