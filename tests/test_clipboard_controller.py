import json
import io
import os
from pathlib import Path
import socket
import subprocess
import textwrap
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from service import clipboard_controller
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

    def test_image_only_clipboard_has_clear_private_error(self):
        paste = Path(self.tmp.name) / "bin/wl-paste"
        paste.write_text('#!/bin/sh\necho "private image data" >&2\nexit 1\n')
        controller = Controller()
        controller.read_clipboard()
        self.wait_for(lambda: controller.status()["state"] == "error")
        self.assertEqual(controller.status()["error"], "Clipboard has no text")
        controller.read_clipboard(selection=True)
        self.wait_for(lambda: controller.status()["state"] == "error"
                      and controller.status()["error"] == "Selection has no text")
        self.assertNotIn("private image data", json.dumps(controller.status()))
        self.assertEqual(Fixture.received, [])

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

    def test_quit_closes_only_matching_desktop_and_stops_service(self):
        marker = Path(self.tmp.name) / "local-voice/off"
        marker.parent.mkdir(exist_ok=True)
        clients = [
            {"class": "dev.majesticlabs.localvoice", "title": "Local Voice Desktop · Majestic Labs", "address": "0xabc"},
            {"class": "other", "title": "Local Voice Desktop · Majestic Labs", "address": "0xdef"},
        ]
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            if args[:3] == ["hyprctl", "clients", "-j"]:
                return subprocess.CompletedProcess(args, 0, json.dumps(clients), "")
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(clipboard_controller, "send", side_effect=lambda path, command: calls.append([command])), \
             patch.object(clipboard_controller.subprocess, "run", side_effect=run):
            self.assertEqual(clipboard_controller.quit_local_voice(marker.parent / "controller.sock", marker)["state"], "off")
            self.assertEqual(clipboard_controller.start_local_voice(marker)["state"], "idle")
        self.assertEqual(calls, [["stop"], ["hyprctl", "clients", "-j"],
                                 ["hyprctl", "dispatch", "closewindow", "address:0xabc"],
                                 ["systemctl", "--user", "stop", "local-voice.service"],
                                 ["systemctl", "--user", "start", "local-voice.service"]])
        self.assertFalse(marker.exists())

    def test_quit_failure_does_not_mark_off_or_stop_service(self):
        marker = Path(self.tmp.name) / "local-voice/off"
        marker.parent.mkdir(exist_ok=True)
        with patch.object(clipboard_controller, "send"), \
             patch.object(clipboard_controller.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "hyprctl")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                clipboard_controller.quit_local_voice(marker.parent / "controller.sock", marker)
        self.assertEqual(run.call_count, 1)
        self.assertFalse(marker.exists())

    def test_status_reports_off_marker_and_start_failure_preserves_it(self):
        directory = clipboard_controller.runtime_dir()
        marker = directory / "off"
        marker.touch()
        with patch.object(sys, "argv", ["controller", "status"]), \
             patch.object(clipboard_controller, "send", return_value={"state": "idle", "error": None}), \
             patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(clipboard_controller.main(), 0)
            self.assertEqual(json.loads(output.getvalue())["state"], "off")
        with patch.object(clipboard_controller, "service_action", side_effect=RuntimeError("start failed")):
            with self.assertRaises(RuntimeError):
                clipboard_controller.start_local_voice(marker)
        self.assertTrue(marker.exists())

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
                client.sendall(b"1 status\n")
                response = json.loads(client.recv(4096))
                self.assertEqual(response["state"], "idle")
                self.assertEqual(response["protocol"], clipboard_controller.PROTOCOL_VERSION)

    def test_stale_controller_is_replaced_before_status(self):
        root = Path(self.tmp.name)
        legacy = root / "legacy/service"
        legacy.mkdir(parents=True)
        (legacy / "__init__.py").write_text("")
        (legacy / "clipboard_controller.py").write_text(textwrap.dedent('''\
            import fcntl, json, os, socket
            from pathlib import Path
            path = Path(os.environ["XDG_RUNTIME_DIR"]) / "local-voice/controller.sock"
            path.parent.mkdir(mode=0o700, exist_ok=True)
            os.chmod(path.parent, 0o700)
            with open(path.with_suffix(".lock"), "a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                path.unlink(missing_ok=True)
                with socket.socket(socket.AF_UNIX) as listener:
                    listener.bind(str(path))
                    listener.listen(8)
                    while True:
                        client, _ = listener.accept()
                        with client:
                            command = client.recv(128).decode().strip()
                            value = {"state": "idle", "error": None} if command in ("status", "stop") else {"state": "error", "error": "Unknown command"}
                            client.sendall(json.dumps(value).encode())
        '''))
        old = subprocess.Popen([sys.executable, "-m", "service.clipboard_controller", "serve"],
                               env={**os.environ, "PYTHONPATH": str(root / "legacy")}, cwd=root / "legacy",
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (old.terminate(), old.wait(timeout=3)) if old.poll() is None else None)
        path = root / "local-voice/controller.sock"
        self.wait_for(path.exists)
        with self.assertRaises(clipboard_controller.ProtocolMismatch) as mismatch:
            clipboard_controller.send(path, "status")
        self.assertEqual(mismatch.exception.pid, old.pid)
        original_popen = subprocess.Popen
        spawned = []
        with open(root / "replacement.log", "w+") as log:
            def launch(*args, **kwargs):
                process = original_popen(*args, **{**kwargs, "stderr": log})
                spawned.append(process)
                return process
            with patch.object(clipboard_controller.subprocess, "Popen", side_effect=launch):
                try:
                    result = clipboard_controller.controller_command(path, "status")
                except RuntimeError as exc:
                    log.seek(0)
                    self.fail(f"{exc}: {log.read()}")
        self.assertEqual(result["state"], "idle")
        self.assertEqual(result["protocol"], clipboard_controller.PROTOCOL_VERSION)
        old.wait(timeout=3)
        _, replacement_pid = clipboard_controller.exchange(path, "1 status")
        self.assertNotEqual(replacement_pid, old.pid)
        self.addCleanup(lambda: (spawned[0].terminate(), spawned[0].wait(timeout=3)) if spawned[0].poll() is None else None)

    def test_unrelated_socket_owner_is_not_terminated(self):
        with self.assertRaisesRegex(ValueError, "unrecognized process"):
            clipboard_controller.replace_stale_controller(Path(self.tmp.name) / "controller.sock", os.getpid())

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
