"""Explicit Wayland clipboard playback, separate from desktop and browser sessions.

CLI: python -m service.clipboard_controller {read-clipboard|stop|status|quit|start}
The first read starts a per-user controller process. Status and stop never start it.
"""
import ctypes
import fcntl
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from urllib import error, request

from .core.chunking import chunk_text
from .core.speakable import prepare

MAX_TEXT = 50000
MAX_AUDIO = 32 * 1024 * 1024
PROTOCOL_VERSION = 1


class ProtocolMismatch(Exception):
    def __init__(self, pid):
        self.pid = pid
        super().__init__("Controller version mismatch")


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

    def read_clipboard(self, selection=False):
        self.stop()
        with self.lock:
            self.cancel = threading.Event()
            generation = self.generation
            self.state = "reading"
            thread = threading.Thread(target=self._run, args=(generation, self.cancel, selection), daemon=True)
            thread.start()

    def toggle_selection(self):
        with self.lock:
            active = self.state in ("reading", "synthesizing", "playing")
        if active:
            self.stop()
        else:
            self.read_clipboard(selection=True)

    def _set(self, generation, state, message=None):
        with self.lock:
            if self.generation != generation:
                return False
            self.state, self.error = state, message
            return True

    def _run(self, generation, cancelled, selection=False):
        try:
            # --type text/plain refuses images and other non-text offers.
            command = ["wl-paste", "--no-newline", "--type", "text/plain"]
            if selection:
                command.insert(1, "--primary")
            try:
                clip = subprocess.run(command,
                                      capture_output=True, timeout=5, check=True)
            except subprocess.CalledProcessError:
                # wl-paste exits nonzero when no text/plain offer exists. Do not
                # expose its stderr or any clipboard data in the status.
                raise ValueError("Selection has no text" if selection else "Clipboard has no text") from None
            if len(clip.stdout) > MAX_TEXT * 4:
                raise ValueError("Clipboard text is too large")
            text = clip.stdout.decode("utf-8").strip()
            if len(text) > MAX_TEXT:
                raise ValueError("Clipboard text is too large")
            text = prepare(text)
            if not text:
                raise ValueError("Selection has no speakable text" if selection else "Clipboard has no speakable text")
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


def desktop_windows():
    result = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True,
                            check=True, timeout=5)
    clients = json.loads(result.stdout)
    if not isinstance(clients, list):
        raise ValueError("Cannot inspect desktop windows")
    addresses = []
    for client in clients:
        if not isinstance(client, dict):
            raise ValueError("Invalid desktop window list")
        if (client.get("class") in ("dev.majesticlabs.localvoice", "local-voice-desktop")
                and str(client.get("title", "")).startswith("Local Voice Desktop")):
            address = str(client.get("address", ""))
            if not re.fullmatch(r"0x[0-9a-fA-F]+", address):
                raise ValueError("Invalid desktop window address")
            addresses.append(address)
    return addresses


def service_action(action):
    subprocess.run(["systemctl", "--user", action, "local-voice.service"],
                   capture_output=True, text=True, check=True, timeout=15)


def quit_local_voice(path, marker):
    controller_command(path, "stop")  # An absent controller has no playback to stop.
    for address in desktop_windows():
        # Hyprland sends a normal window close request. Tauri handles CloseRequested.
        subprocess.run(["hyprctl", "dispatch", "closewindow", "address:" + address],
                       capture_output=True, text=True, check=True, timeout=5)
    service_action("stop")
    marker.touch(mode=0o600)
    return {"state": "off", "error": None}


def start_local_voice(marker):
    service_action("start")
    marker.unlink(missing_ok=True)
    return {"state": "idle", "error": None}


def exchange(path, command):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(2)
        connection.connect(str(path))
        pid, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.getuid():
            raise ValueError("Controller belongs to another user")
        connection.sendall((command + "\n").encode())
        return json.loads(connection.recv(4096)), pid


def send(path, command):
    result, pid = exchange(path, f"{PROTOCOL_VERSION} {command}")
    if result.get("protocol") != PROTOCOL_VERSION:
        raise ProtocolMismatch(pid)
    return result


def replace_stale_controller(path, pid):
    # The packaged Python lacks os.pidfd_open. Use glibc's pidfd interface so
    # PID reuse cannot redirect SIGTERM to an unrelated process.
    libc = ctypes.CDLL(None, use_errno=True)
    libc.pidfd_open.argtypes = [ctypes.c_int, ctypes.c_uint]
    libc.pidfd_open.restype = ctypes.c_int
    libc.pidfd_send_signal.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
    libc.pidfd_send_signal.restype = ctypes.c_int
    fd = libc.pidfd_open(pid, 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "Cannot identify old controller")
    try:
        proc = Path("/proc") / str(pid)
        args = (proc / "cmdline").read_bytes().rstrip(b"\0").split(b"\0")
        if (proc.stat().st_uid != os.getuid() or len(args) != 4
                or args[1:] != [b"-m", b"service.clipboard_controller", b"serve"]
                or not Path(os.fsdecode(args[0])).name.startswith("python")):
            raise ValueError("Controller socket belongs to an unrecognized process; refusing to replace it")
        try:
            # Old servers understand this command; stop their player first.
            _, peer = exchange(path, "stop")
            if peer != pid:
                raise ValueError("Controller changed during replacement")
        except (OSError, json.JSONDecodeError):
            pass
        if libc.pidfd_send_signal(fd, signal.SIGTERM, None, 0) != 0:
            raise OSError(ctypes.get_errno(), "Cannot stop old controller")
        poller = select.poll()
        poller.register(fd, select.POLLIN)
        if not poller.poll(3000):
            raise RuntimeError("Old controller did not exit after SIGTERM")
    finally:
        os.close(fd)


def launch_and_send(path, command):
    subprocess.Popen([sys.executable, "-m", "service.clipboard_controller", "serve"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(100):
        time.sleep(0.05)
        try:
            return send(path, command)
        except (OSError, ValueError):
            continue
    raise RuntimeError("Controller could not start")


def controller_command(path, command, start_if_missing=False):
    try:
        return send(path, command)
    except ProtocolMismatch as exc:
        replace_stale_controller(path, exc.pid)
        return launch_and_send(path, command)
    except (OSError, ValueError):
        if start_if_missing:
            return launch_and_send(path, command)
        return {"state": "offline", "error": None}


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
                            message = connection.recv(128).decode().strip()
                            prefix = f"{PROTOCOL_VERSION} "
                            if not message.startswith(prefix):
                                connection.sendall(b'{"state":"error","error":"Controller version mismatch"}')
                                continue
                            command = message[len(prefix):]
                            if command == "read-clipboard":
                                controller.read_clipboard()
                            elif command == "read-selection":
                                controller.read_clipboard(selection=True)
                            elif command == "toggle-selection":
                                controller.toggle_selection()
                            elif command == "stop":
                                controller.stop()
                            elif command != "status":
                                connection.sendall(json.dumps({"state": "error", "error": "Unknown command", "protocol": PROTOCOL_VERSION}).encode())
                                continue
                            connection.sendall(json.dumps({**controller.status(), "protocol": PROTOCOL_VERSION}).encode())
                        except (OSError, UnicodeDecodeError):
                            continue
            finally:
                controller.stop()
                path.unlink(missing_ok=True)


def main():
    reads = ("read-clipboard", "read-selection", "toggle-selection")
    if len(sys.argv) != 2 or sys.argv[1] not in (*reads, "stop", "status", "quit", "start", "serve"):
        print("Usage: controller {read-clipboard|read-selection|toggle-selection|stop|status|quit|start}", file=sys.stderr)
        return 2
    command = sys.argv[1]
    directory = runtime_dir()
    path = directory / "controller.sock"
    marker = directory / "off"
    if command in ("quit", "start"):
        try:
            result = quit_local_voice(path, marker) if command == "quit" else start_local_voice(marker)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            result = {"state": "error", "error": f"Local Voice {command} failed: {exc}"}
        print(json.dumps(result))
        return 1 if result["state"] == "error" else 0
    if command == "serve":
        serve(path)
        return 0
    try:
        result = controller_command(path, command, start_if_missing=command in reads)
    except (OSError, ValueError, RuntimeError) as exc:
        result = {"state": "error", "error": str(exc)}
    if command == "status" and marker.exists() and result["state"] != "error":
        result = {"state": "off", "error": None}
    print(json.dumps(result))
    return 1 if result["state"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
