import hashlib
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from service.app import app
from service.core import model_catalog as catalog, model_downloads, model_lifecycle


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "models"
        self.root.mkdir()
        content = b"fixture"
        digest = hashlib.sha256(content).hexdigest()
        self.shared = catalog.Asset("kokoro-config", "kokoro/config.json", len(content), "source", "rev", "license", digest, "config.json")
        self.en = catalog.Asset("kokoro-af_bella", "kokoro/voices/af_bella.pt", len(content), "source", "rev", "license", digest, "voices/af_bella.pt")
        self.es = catalog.Asset("kokoro-ef_dora", "kokoro/voices/ef_dora.pt", len(content), "source", "rev", "license", digest, "voices/ef_dora.pt")
        self.assets = {a.id: a for a in (self.shared, self.en, self.es)}
        self.languages = {"en": {"label": "English", "engine": "kokoro", "voices": {"af_bella": "Bella"}}, "es": {"label": "Spanish", "engine": "kokoro", "voices": {"ef_dora": "Dora"}}}
        self.patches = [mock.patch.object(catalog, "ASSETS", self.assets),
                        mock.patch.object(catalog, "LANGUAGES", self.languages),
                        mock.patch.object(catalog, "voice_assets", side_effect=lambda lang, voice: ("kokoro-config", f"kokoro-{voice}")),
                        mock.patch.object(catalog.config, "models_dir", self.root),
                        mock.patch.dict("os.environ", {"LV_MANAGEMENT_TOKEN": "secret"})]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(model_lifecycle.register_release, None)
        model_lifecycle.register_release(lambda keys: None)
        self.client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234))
        self.addCleanup(self.client.close)
        self.headers = {"X-Local-Voice-Management": "secret"}
        for asset in self.assets.values():
            path = self.root / asset.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def test_shared_retained_and_language_complete(self):
        result = self.client.post("/models/removals", json={"languages": ["en"]}, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["removed"], ["kokoro-af_bella"])
        self.assertEqual(self.shared.inventory(self.root)["state"], "verified")
        status = catalog.catalog(self.root)
        self.assertFalse(status["languages"][0]["installed"])
        self.assertTrue(status["languages"][1]["installed"])

    def test_busy_and_uncached_refusal(self):
        with model_lifecycle.using({"kokoro-config"}):
            self.assertEqual(self.client.post("/models/removals", json={"languages": ["en"]}, headers=self.headers).status_code, 409)
        model_lifecycle.register_release(None)
        self.assertEqual(self.client.post("/models/removals", json={"languages": ["en"]}, headers=self.headers).status_code, 409)
        self.assertTrue((self.root / self.en.path).exists())

    def test_active_download_blocks_removal_and_migration(self):
        with mock.patch.object(model_downloads, "_active", "fixture-job"):
            self.assertEqual(self.client.post("/models/removals", json={"languages": ["en"]}, headers=self.headers).status_code, 409)
            self.assertEqual(self.client.post("/models/migration", json={"candidates": ["unknown"]}, headers=self.headers).status_code, 409)
        self.assertTrue((self.root / self.en.path).exists())

    def test_migration_requires_explicit_action_and_preserves_source(self):
        source = Path(self.tmp.name) / "cache" / "snapshot"
        (source / "voices").mkdir(parents=True)
        legacy = source / "voices/af_bella.pt"
        legacy.write_bytes(b"fixture")
        (self.root / self.en.path).unlink()
        with mock.patch.object(model_lifecycle, "_legacy_roots", return_value=(source.parent, Path(self.tmp.name) / "old", Path(self.tmp.name) / "other")):
            candidates = self.client.get("/models/migration", headers=self.headers).json()["candidates"]
            selected = next(c for c in candidates if c["asset_id"] == self.en.id)
            self.assertFalse((self.root / self.en.path).exists())
            self.assertEqual(self.client.post("/models/migration", json={"candidates": ["bad"]}, headers=self.headers).status_code, 409)
            (self.root / self.en.path).write_bytes(b"other")
            self.assertEqual(self.client.post("/models/migration", json={"candidates": [selected["id"]]}, headers=self.headers).status_code, 409)
            self.assertEqual((self.root / self.en.path).read_bytes(), b"other")
            (self.root / self.en.path).unlink()
            result = self.client.post("/models/migration", json={"candidates": [selected["id"]]}, headers=self.headers)
            self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.en.inventory(self.root)["state"], "verified")
        self.assertEqual(legacy.read_bytes(), b"fixture")

    def test_abandoned_staging_and_single_process(self):
        stage = self.root / ".downloads" / "orphan"
        stage.mkdir(parents=True)
        (stage / "partial").write_bytes(b"broken")
        model_lifecycle.startup()
        try:
            self.assertFalse(stage.exists())
            ctx = multiprocessing.get_context("fork")
            queue = ctx.Queue()
            def competing():
                inherited = model_lifecycle._process_lock
                model_lifecycle._process_lock = None
                inherited.close()
                try:
                    model_lifecycle.startup()
                except BlockingIOError:
                    queue.put("blocked")
                else:
                    queue.put("unsafe")
            process = ctx.Process(target=competing)
            process.start()
            process.join(5)
            self.assertEqual(queue.get(timeout=2), "blocked")
        finally:
            model_lifecycle.shutdown()


if __name__ == "__main__":
    unittest.main()
