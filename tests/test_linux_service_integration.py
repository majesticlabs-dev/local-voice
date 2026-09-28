"""Process-level zero-model readiness check with a disposable service data directory."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


class EmptyServiceTests(unittest.TestCase):
    def test_zero_model_service_is_live_and_setup_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = dict(os.environ, LV_MODELS_DIR=f"{tmp}/models",
                       LV_CACHE_DIR=f"{tmp}/cache", LV_OUTPUT_DIR=f"{tmp}/output",
                       LV_MANAGEMENT_TOKEN="fixture-token", PYTHONDONTWRITEBYTECODE="1")
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "service.app:app", "--host", "127.0.0.1",
                 "--port", str(port), "--workers", "1"], cwd=ROOT, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                            self.assertEqual(response.status, 200)
                            health = json.load(response)
                        break
                    except OSError:
                        if process.poll() is not None:
                            self.fail(f"Service exited early: {process.stderr.read().decode()[-1000:]}")
                        time.sleep(0.1)
                else:
                    self.fail("Service did not answer /health")
                self.assertEqual(health["status"], "setup_needed")
                self.assertFalse(health["ready"])
                self.assertTrue(Path(env["LV_MODELS_DIR"]).joinpath(".management.lock").is_file())
            finally:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
