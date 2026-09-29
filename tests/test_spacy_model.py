import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
import zipfile

from fastapi.testclient import TestClient
from service.app import app, _release_provider_caches
from service.core import model_catalog, model_downloads, model_lifecycle, spacy_model


class SpacyModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("en_core_web_sm/__init__.py", "VERSION = 'fixture'\n")
            archive.writestr("en_core_web_sm-3.8.0.dist-info/METADATA",
                             "Metadata-Version: 2.1\nName: en-core-web-sm\nVersion: 3.8.0\n")
        self.wheel = payload.getvalue()
        asset = model_catalog.ASSETS[spacy_model.ASSET_ID]
        self.asset = model_catalog.Asset(asset.id, asset.path, len(self.wheel),
                                         "fixture", asset.revision, None,
                                         hashlib.sha256(self.wheel).hexdigest(), asset.upstream_path)
        patches = [mock.patch.object(model_catalog, "ASSETS", {self.asset.id: self.asset}),
                   mock.patch.object(model_catalog.config, "models_dir", self.root),
                   mock.patch.object(model_catalog, "voice_assets", side_effect=lambda lang, voice: (self.asset.id,) if lang == "en" else ()),
                   mock.patch.object(model_downloads, "urlopen", side_effect=self.fetch),
                   mock.patch.dict("os.environ", {"LV_MANAGEMENT_TOKEN": "test-secret"})]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        prior_release = model_lifecycle._release
        model_lifecycle.register_release(_release_provider_caches)
        self.addCleanup(model_lifecycle.register_release, prior_release)
        self.client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 12345))
        self.addCleanup(self.client.close)
        self.headers = {"X-Local-Voice-Management": "test-secret"}
        self.addCleanup(spacy_model.deactivate)

    def fetch(self, url, timeout):
        self.assertEqual(url, "fixture")
        return io.BytesIO(self.wheel)

    def wait(self, job_id):
        for _ in range(200):
            result = self.client.get(f"/models/downloads/{job_id}", headers=self.headers).json()
            if result["status"] not in ("queued", "downloading"):
                return result
            time.sleep(.01)
        self.fail("job did not finish")

    @unittest.skipUnless(importlib.util.find_spec("spacy"), "spaCy runtime is not installed in lean CI")
    def test_verified_download_activation_restart_and_removal(self):
        import spacy.util
        self.assertFalse(spacy_model.activate())
        result = self.client.post("/models/downloads", json={"languages": ["en"]}, headers=self.headers)
        self.assertEqual(result.status_code, 202, result.text)
        self.assertEqual(self.wait(result.json()["job_id"])["status"], "completed")
        self.assertTrue(spacy_model.activate())
        self.assertTrue(spacy.util.is_package("en_core_web_sm"))
        spacy_model.deactivate()
        self.assertFalse(spacy.util.is_package("en_core_web_sm"))
        self.assertTrue(spacy_model.activate())
        removed = self.client.post("/models/removals", json={"languages": ["en"]}, headers=self.headers)
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertFalse(spacy.util.is_package("en_core_web_sm"))
        self.assertFalse(spacy_model.activate())

    def test_invalid_digest_never_activates(self):
        (self.root / self.asset.path).parent.mkdir(parents=True)
        (self.root / self.asset.path).write_bytes(b"x" * len(self.wheel))
        self.assertFalse(spacy_model.activate())
        self.assertFalse((self.root / "spacy/.active").exists())


if __name__ == "__main__":
    unittest.main()
