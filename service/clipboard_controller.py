"""Explicit Wayland clipboard playback, separate from desktop and browser sessions.

CLI: python -m service.clipboard_controller {read-clipboard|stop|status}
The first read starts a per-user controller process. Status and stop never start it.
"""
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib import error, request

from .core.chunking import chunk_text

MAX_TEXT = 50000
MAX_AUDIO = 32 * 1024 * 1024


def runtime_dir():
    base = os.environ.get("XDG_RUNTIME_DIR")
    if not base:
        raise RuntimeError("XDG_RUNTIME_DIR is required")
    path = Path(base) / "local-voice"
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if path.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("Controller runtime directory must be private")
    return path


class Controller:
    def __init__(self):
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.player = None
        self.state = "idle"
        self.error = None
        self.generation = 0

    def status(self):
        with self.lock:
            return {"state": self.state, "error": self.error}

    def stop(self):
        with self.lock:
            self.cancel.set()
            self.generation += 1
            player = self.player
            self.player = None
            self.state = "idle"
            self.error = None
            if player is not None:
                player.terminate()

    def read_clipboard(self):
        self.stop()
        with self.lock:
            self.cancel = threading.Event()
            generation = self.generation
            self.state = "reading"
            thread = threading.Thread(target=self._run, args=(generation, self.cancel), daemon=True)
            thread.start()

    def _set(self, generation, state, message=None):
        with self.lock:
            if self.generation != generation:
                return False
            self.state, self.error = state, message
            return True

    def _run(self, generation, cancelled):
        try:
            # --type text/plain refuses images and other non-text clipboard offers.
            clip = subprocess.run(["wl-paste", "--no-newline", "--type", "text/plain"],
                                  capture_output=True, timeout=5, check=True)
            if len(clip.stdout) > MAX_TEXT * 4:
                raise ValueError("Clipboard text is too large")
            text = clip.stdout.decode("utf-8").strip()
            if not text:
                raise ValueError("Clipboard has no text")
            if len(text) > MAX_TEXT:
                raise ValueError("Clipboard text is too large")
            if not self._set(generation, "synthesizing"):
                return
            for chunk in chunk_text(text, target_chars=500, max_chars=1000):
                if cancelled.is_set():
                    return
                payload = json.dumps({"text": chunk, "format": "mp3"}).encode()
                port = int(os.environ.get("LV_CONTROLLER_SERVICE_PORT", "5517"))
                if not 1 <= port <= 65535:
                    raise ValueError("Invalid service port")
                req = request.Request(f"http://127.0.0.1:{port}/synthesize", payload,
                                      {"Content-Type": "application/json"}, method="POST")
                with request.urlopen(req, timeout=60) as response:
                    audio = response.read(MAX_AUDIO + 1)
                if len(audio) > MAX_AUDIO or not audio:
                    raise ValueError("Invalid audio response")
                with self.lock:
                    if self.generation != generation:
                        return
                    self.state = "playing"
                    self.player = subprocess.Popen(
                        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-i", "pipe:0"],
                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    player = self.player
                try:
                    player.communicate(audio)
                    if player.returncode != 0 and not cancelled.is_set():
                        raise RuntimeError("Audio player failed")
                finally:
                    with self.lock:
                        if self.player is player:
                            self.player = None
                if not self._set(generation, "synthesizing"):
                    return
            self._set(generation, "idle")
        except FileNotFoundError as exc:
            self._set(generation, "error", f"Missing command: {exc.filename}")
        except error.HTTPError as exc:
            try:
                # Parse only the bounded error code, never expose the response text.
                body = json.loads(exc.read(4096))
                missing = exc.code == 503 and body.get("error") == "setup_needed"
            except (ValueError, AttributeError):
                missing = False
            finally:
                exc.close()
            if missing:
                self._set(generation, "setup_needed", "Install a voice in the desktop model manager")
            else:
                self._set(generation, "error", f"Service request failed (HTTP {exc.code})")
        except error.URLError:
            self._set(generation, "error", "Shared service unavailable; start local-voice.service")
        except (subprocess.SubprocessError, UnicodeError, ValueError, RuntimeError) as exc:
            # Never include clipboard or service response bodies in status or logs.
            message = str(exc) if isinstance(exc, ValueError) else "Clipboard or playback failed"
            self._set(generation, "error", message)
        except OSError:
            self._set(generation, "error", "Clipboard or playback failed")


def send(path, command):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(2)
        connection.connect(str(path))
        connection.sendall((command + "\n").encode())
        return json.loads(connection.recv(4096))


def serve(path):
    lock_path = path.with_suffix(".lock")
    with open(lock_path, "a+b") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path.unlink(missing_ok=True)
        controller = Controller()
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(str(path))
            os.chmod(path, 0o600)
            listener.listen(8)
            try:
                while True:
                    connection, _ = listener.accept()
                    with connection:
                        connection.settimeout(2)
                        try:
                            command = connection.recv(128).decode().strip()
                            if command == "read-clipboard":
                                controller.read_clipboard()
                            elif command == "stop":
                                controller.stop()
                            elif command != "status":
                                connection.sendall(b'{"state":"error","error":"Unknown command"}')
                                continue
                            connection.sendall(json.dumps(controller.status()).encode())
                        except (OSError, UnicodeDecodeError):
                            continue
            finally:
                controller.stop()
                path.unlink(missing_ok=True)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("read-clipboard", "stop", "status", "serve"):
        print("Usage: controller {read-clipboard|stop|status}", file=sys.stderr)
        return 2
    command = sys.argv[1]
    path = runtime_dir() / "controller.sock"
    if command == "serve":
        serve(path)
        return 0
    try:
        result = send(path, command)
    except (OSError, ValueError):
        if command != "read-clipboard":
            result = {"state": "offline", "error": None}
        else:
            subprocess.Popen([sys.executable, "-m", "service.clipboard_controller", "serve"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            for _ in range(30):
                time.sleep(0.05)
                try:
                    result = send(path, command)
                    break
                except (OSError, ValueError):
                    continue
            else:
                result = {"state": "error", "error": "Controller could not start"}
    print(json.dumps(result))
    return 1 if result["state"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
