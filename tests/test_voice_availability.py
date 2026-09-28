import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from service.app import app
from service.core.config import config
from service.core.model_catalog import ASSETS, Asset, voice_assets


class VoiceAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        models = mock.patch.object(config, "models_dir", self.root)
        models.start()
        self.addCleanup(models.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def voices(self):
        response = self.client.get("/voices")
        self.assertEqual(response.status_code, 200)
        return {voice["id"]: voice for voice in response.json()["voices"]}

    def install_fixture(self, asset_id):
        original = ASSETS[asset_id]
        content = asset_id.encode()
        path = self.root / original.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return Asset(original.id, original.path, len(content), original.source,
                     original.revision, original.license,
                     hashlib.sha256(content).hexdigest())

    def test_zero_models_all_voices_unavailable(self):
        voices = self.voices()
        self.assertTrue(voices)
        self.assertTrue(all(voice["available"] is False for voice in voices.values()))
        self.assertEqual(set(voices["af_bella"]),
                         {"id", "label", "language", "gender", "sample_rate", "available"})

    def test_verified_spanish_language_only_its_voices_available(self):
        required = {asset for voice in ("ef_dora", "em_alex", "em_santa")
                    for asset in voice_assets("es", voice)}
        fixtures = {asset: self.install_fixture(asset) for asset in required}
        with mock.patch.dict(ASSETS, fixtures):
            voices = self.voices()
            self.assertTrue(all(voices[voice]["available"] for voice in ("ef_dora", "em_alex", "em_santa")))
            self.assertFalse(any(voice["available"] for key, voice in voices.items()
                                 if key not in ("ef_dora", "em_alex", "em_santa")))

    def test_partial_and_unverified_files_never_make_voice_available(self):
        required = voice_assets("ru", "ru_RU-dmitri-medium")
        fixture = self.install_fixture(required[0])
        with mock.patch.dict(ASSETS, {required[0]: fixture}):
            self.assertFalse(self.voices()["ru_RU-dmitri-medium"]["available"])
            unverified = self.install_fixture(required[1])
            unverified = Asset(unverified.id, unverified.path, unverified.size_bytes,
                               unverified.source, unverified.revision, unverified.license, None)
            with mock.patch.dict(ASSETS, {required[1]: unverified}):
                self.assertFalse(self.voices()["ru_RU-dmitri-medium"]["available"])


if __name__ == "__main__":
    unittest.main()
