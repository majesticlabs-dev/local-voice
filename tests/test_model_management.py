import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from service.app import app
from service.core.model_catalog import catalog


class ModelManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 31000))
        self.addCleanup(self.client.close)
        self.env = mock.patch.dict("os.environ", {"LV_MANAGEMENT_TOKEN": "test-secret"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.models = mock.patch("service.core.model_catalog.config.models_dir", self.root)
        self.models.start()
        self.addCleanup(self.models.stop)

    def test_zero_models_and_language_dependencies(self):
        response = self.client.get("/models", headers={"X-Local-Voice-Management": "test-secret"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([x["id"] for x in body["languages"]], ["en", "es", "ru"])
        self.assertFalse(any(x["installed"] for x in body["languages"]))
        en, es, ru = body["languages"]
        self.assertIn("spacy-en-core-web-sm", en["assets"])
        self.assertNotIn("spacy-en-core-web-sm", es["assets"])
        self.assertEqual([v["id"] for v in ru["voices"]], ["ru_RU-dmitri-medium"])
        self.assertEqual(len([a for a in body["assets"] if a["id"] == "kokoro-weights"]), 1)

    def test_files_are_not_declared_installed_without_integrity(self):
        target = self.root / "kokoro" / "config.json"
        target.parent.mkdir()
        target.write_bytes(b"x" * 2351)
        assets = {a["id"]: a for a in catalog(self.root)["assets"]}
        self.assertEqual(assets["kokoro-config"]["state"], "invalid")
        target.write_bytes(b"bad")
        self.assertEqual({a["id"]: a for a in catalog(self.root)["assets"]}["kokoro-config"]["state"], "invalid")
        target.unlink()
        outside = self.root / "outside"
        outside.write_bytes(b"x" * 2351)
        target.symlink_to(outside)
        self.assertEqual({a["id"]: a for a in catalog(self.root)["assets"]}["kokoro-config"]["state"], "absent")

    def test_management_rejects_browser_lan_and_missing_token(self):
        headers = {"X-Local-Voice-Management": "test-secret"}
        self.assertEqual(self.client.get("/models").status_code, 403)
        self.assertEqual(self.client.get("/models", headers={**headers, "Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.get("/models", headers={**headers, "Origin": "chrome-extension://abc"}).status_code, 403)
        with TestClient(app, base_url="http://127.0.0.1", client=("192.0.2.10", 1234)) as remote:
            self.assertEqual(remote.get("/models", headers=headers).status_code, 403)
        self.assertEqual(self.client.get("/models", headers={**headers, "Host": "evil.example"}).status_code, 403)
        self.assertEqual(self.client.get("/models", headers={**headers, "Origin": "http://tauri.localhost"}).status_code, 200)
        with mock.patch.dict("os.environ", {"LV_MANAGEMENT_TOKEN": ""}):
            self.assertEqual(self.client.get("/models", headers=headers).status_code, 403)

    def test_reserved_removal_and_invalid_request(self):
        headers = {"X-Local-Voice-Management": "test-secret"}
        self.assertEqual(self.client.post("/models/removals", json={"languages": ["ru"]}, headers=headers).status_code, 501)
        self.assertEqual(self.client.post("/models/downloads", json={"languages": ["other"]}, headers=headers).status_code, 422)
        blocked = self.client.post("/models/downloads", json={"languages": ["en"]}, headers=headers)
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("integrity metadata", blocked.json()["detail"])
        self.assertEqual(self.client.get("/models/downloads/job", headers=headers).status_code, 404)
        self.assertEqual(self.client.post("/models/downloads/job/cancel", headers=headers).status_code, 404)
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
