import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from service.app import app
from service.core import model_catalog, model_downloads


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.endswith("bad"):
            self.send_error(503)
            return
        body = b"fixture-model"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.asset = model_catalog.Asset("piper-dmitri-onnx", "piper/test.onnx", 13,
                                         "fixture", "test", "CC0", hashlib.sha256(b"fixture-model").hexdigest(), "ok")
        self.config_asset = model_catalog.Asset("piper-dmitri-config", "piper/test.json", 13,
                                                "fixture", "test", "CC0", self.asset.sha256, "ok")
        patches = [mock.patch.object(model_catalog, "ASSETS", {a.id: a for a in (self.asset, self.config_asset)}),
                   mock.patch.object(model_catalog.config, "models_dir", self.root),
                   mock.patch.dict("os.environ", {"LV_MANAGEMENT_TOKEN": "test-secret"}),
                   mock.patch.object(model_downloads, "source_url", side_effect=self.url)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 12345))
        self.addCleanup(self.client.close)
        self.headers = {"X-Local-Voice-Management": "test-secret"}

    def url(self, asset):
        return f"http://127.0.0.1:{self.server.server_port}/{asset.upstream_path}"

    def wait(self, job_id):
        for _ in range(200):
            response = self.client.get(f"/models/downloads/{job_id}", headers=self.headers).json()
            if response["status"] not in ("queued", "downloading"):
                return response
            time.sleep(.01)
        self.fail("job did not finish")

    def test_download_integrity_and_repeat(self):
        response = self.client.post("/models/downloads", json={"languages": ["ru"]}, headers=self.headers)
        self.assertEqual(response.status_code, 202)
        done = self.wait(response.json()["job_id"])
        self.assertEqual(done["status"], "completed", done)
        self.assertEqual(done["bytes_done"], 26)
        self.assertEqual(self.asset.inventory(self.root)["state"], "verified")
        self.assertEqual(self.config_asset.inventory(self.root)["state"], "verified")
        again = self.client.post("/models/downloads", json={"languages": ["ru"]}, headers=self.headers)
        self.assertEqual(self.wait(again.json()["job_id"])["bytes_total"], 0)
        (self.root / self.asset.path).write_bytes(b"corrupt-model")
        self.assertEqual(self.asset.inventory(self.root)["state"], "invalid")

    def test_failure_keeps_partial_assets_uninstalled_and_retry(self):
        broken = model_catalog.Asset("piper-dmitri-config", "piper/test.json", 13,
                                     "fixture", "test", "CC0", self.asset.sha256, "bad")
        with mock.patch.dict(model_catalog.ASSETS, {broken.id: broken}):
            response = self.client.post("/models/downloads", json={"languages": ["ru"]}, headers=self.headers)
            done = self.wait(response.json()["job_id"])
            self.assertEqual(done["status"], "failed")
            self.assertFalse((self.root / self.asset.path).exists())
            self.assertFalse((self.root / broken.path).exists())
        response = self.client.post("/models/downloads", json={"languages": ["ru"]}, headers=self.headers)
        self.assertEqual(self.wait(response.json()["job_id"])["status"], "completed")

    def test_cancel_and_duplicate(self):
        entered = threading.Event()
        release = threading.Event()
        original = model_downloads.urlopen

        def slow(url, timeout):
            entered.set()
            release.wait(2)
            return original(url, timeout=timeout)

        with mock.patch.object(model_downloads, "urlopen", side_effect=slow):
            first = self.client.post("/models/downloads", json={"languages": ["ru"]}, headers=self.headers).json()
            self.assertTrue(entered.wait(2))
            duplicate = self.client.post("/models/downloads", json={"languages": ["ru", "ru"]}, headers=self.headers).json()
            self.assertEqual(first["job_id"], duplicate["job_id"])
            self.assertEqual(self.client.post("/models/downloads", json={"languages": ["en"]}, headers=self.headers).status_code, 409)
            self.client.post(f"/models/downloads/{first['job_id']}/cancel", headers=self.headers)
            release.set()
            self.assertEqual(self.wait(first["job_id"])["status"], "cancelled")
            self.assertFalse((self.root / self.asset.path).exists())

    def test_digest_failure_does_not_promote(self):
        wrong = model_catalog.Asset("piper-dmitri-config", "piper/test.json", 13,
                                    "fixture", "test", "CC0", "0" * 64, "ok")
        with mock.patch.dict(model_catalog.ASSETS, {wrong.id: wrong}):
            response = self.client.post("/models/downloads", json={"languages": ["ru"]}, headers=self.headers)
            done = self.wait(response.json()["job_id"])
        self.assertEqual(done["status"], "failed")
        self.assertIn("checksum", done["error"])
        self.assertFalse((self.root / self.asset.path).exists())

    def test_insufficient_space(self):
        usage = type("Usage", (), {"free": 0})()
        with mock.patch.object(model_downloads.shutil, "disk_usage", return_value=usage):
            response = self.client.post("/models/downloads", json={"languages": ["ru"]}, headers=self.headers)
            done = self.wait(response.json()["job_id"])
        self.assertEqual(done["status"], "failed")
        self.assertIn("Insufficient space", done["error"])
        self.assertFalse((self.root / self.asset.path).exists())


if __name__ == "__main__":
    unittest.main()
