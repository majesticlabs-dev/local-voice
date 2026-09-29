import hashlib
import importlib.util
import threading
from concurrent.futures import ThreadPoolExecutor
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from service.app import app, _release_provider_caches
from service.core import model_catalog, model_lifecycle
from service.core.config import config
from service.core.model_catalog import Asset, ASSETS
from service.core.setup import SetupNeeded, local_voice_paths
from service.providers import kokoro, piper


class LocalOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.models = mock.patch.object(config, "models_dir", root)
        self.models.start()
        self.addCleanup(self.models.stop)
        # Deny actual network operations rather than intercepting one downloader.
        def deny(*_args, **_kwargs):
            raise AssertionError("network attempted")
        self.network = mock.patch.object(socket.socket, "connect", deny)
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_zero_model_startup_health_voices_and_synthesis_are_offline(self):
        with TestClient(app) as client:
            health = client.get("/health").json()
            voices = client.get("/voices").json()["voices"]
            self.assertFalse(health["ready"])
            self.assertIn("af_bella", [voice["id"] for voice in voices])
            self.assertNotIn("ru_RU-irina-medium", [voice["id"] for voice in voices])
            for voice in ("af_bella", "ef_dora", "ru_RU-dmitri-medium"):
                response = client.post("/synthesize", json={"text": "hello", "voice": voice})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"], "setup_needed")
                self.assertTrue(response.json()["assets"])
            self.assertEqual(client.post("/stream", json={"text": "hello"}).status_code, 503)
            self.assertEqual(client.post("/export", json={"text": "hello"}).status_code, 503)

    def test_unverified_files_and_symlinks_are_not_loaded(self):
        (Path(self.temp.name) / "piper").mkdir()
        for name in ("ru_RU-dmitri-medium.onnx", "ru_RU-dmitri-medium.onnx.json"):
            (Path(self.temp.name) / "piper" / name).write_bytes(b"unverified")
        with self.assertRaises(SetupNeeded):
            piper._load_voice("ru_RU-dmitri-medium")
        self.assertFalse(piper.PiperProvider().is_ready())

    def test_piper_loader_receives_only_validated_local_fixture_paths(self):
        fixture_assets = {}
        for asset_id in ("piper-dmitri-onnx", "piper-dmitri-config"):
            asset = ASSETS[asset_id]
            content = asset_id.encode()
            path = Path(self.temp.name) / asset.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            fixture_assets[asset_id] = Asset(asset.id, asset.path, len(content),
                                              asset.source, asset.revision, asset.license,
                                              hashlib.sha256(content).hexdigest())
        fake_piper = mock.Mock()
        with mock.patch.dict(ASSETS, fixture_assets), \
             mock.patch.object(piper, "_espeak_data_dir", return_value="/fixture/espeak"), \
             mock.patch.dict("sys.modules", {"piper": fake_piper}):
            piper._voices.clear()
            self.addCleanup(piper._voices.clear)
            voice = piper._load_voice("ru_RU-dmitri-medium")
            self.assertIsNotNone(voice)
            loaded = fake_piper.PiperVoice.load.call_args
            self.assertEqual(loaded.args[0], Path(self.temp.name) / "piper/ru_RU-dmitri-medium.onnx")
            self.assertEqual(loaded.kwargs["config_path"], Path(self.temp.name) / "piper/ru_RU-dmitri-medium.onnx.json")
            (Path(self.temp.name) / "piper/ru_RU-dmitri-medium.onnx").write_bytes(b"tampered")
            with self.assertRaises(SetupNeeded):
                piper._load_voice("ru_RU-dmitri-medium")

    @unittest.skipUnless(importlib.util.find_spec("kokoro"), "Kokoro runtime is not installed in lean CI")
    def test_real_kokoro_loader_with_invalid_local_fixture_does_not_fetch(self):
        assets = {}
        for asset_id in ("kokoro-config", "kokoro-weights", "kokoro-ef_dora"):
            asset = ASSETS[asset_id]
            content = b"invalid fixture"
            path = Path(self.temp.name) / asset.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            assets[asset_id] = Asset(asset.id, asset.path, len(content), asset.source,
                                     asset.revision, asset.license,
                                     hashlib.sha256(content).hexdigest())
        kokoro._pipelines.clear()
        self.addCleanup(kokoro._pipelines.clear)
        with mock.patch.dict(ASSETS, assets):
            with self.assertRaises((ValueError, RuntimeError)):
                kokoro.KokoroProvider().synthesize("hola", "ef_dora", 1.0, "wav")

    @unittest.skipUnless(importlib.util.find_spec("spacy"), "spaCy runtime is not installed in lean CI")
    def test_kokoro_english_refuses_misaki_downloader_without_installed_spacy(self):
        import spacy.util
        kokoro._pipelines.clear()
        self.addCleanup(kokoro._pipelines.clear)
        with mock.patch.object(Asset, "inventory", return_value={"state": "verified"}), \
             mock.patch.object(spacy.util, "is_package", return_value=False), \
             mock.patch("spacy.cli.download", side_effect=AssertionError("Misaki downloaded")), \
             mock.patch.object(kokoro, "_kokoro", mock.Mock()):
            with self.assertRaises(SetupNeeded):
                kokoro._load_kokoro("a")

    def test_removal_waits_for_synthesis_then_evicts_cached_voice(self):
        assets = {}
        for asset_id in ("piper-dmitri-onnx", "piper-dmitri-config"):
            original = ASSETS[asset_id]
            content = asset_id.encode()
            path = Path(self.temp.name) / original.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            assets[asset_id] = Asset(original.id, original.path, len(content),
                                     original.source, original.revision, original.license,
                                     hashlib.sha256(content).hexdigest())
        started = threading.Event()
        finish = threading.Event()
        fake_voice = mock.Mock()
        fake_voice.config.sample_rate = 22050
        fake_voice.config.length_scale = 1.0

        def generate(*_args):
            started.set()
            if not finish.wait(5):
                raise TimeoutError("synthesis not released")
            yield mock.Mock(audio_int16_bytes=b"\x00\x00")

        fake_voice.synthesize.side_effect = generate
        fake_piper = mock.Mock()
        fake_piper.PiperVoice.load.return_value = fake_voice
        piper._voices.clear()
        self.addCleanup(piper._voices.clear)
        model_lifecycle.register_release(_release_provider_caches)
        self.addCleanup(model_lifecycle.register_release, None)
        headers = {"X-Local-Voice-Management": "secret"}
        with mock.patch.dict(ASSETS, assets, clear=True), \
             mock.patch.dict(model_catalog.LANGUAGES, {"ru": model_catalog.LANGUAGES["ru"]}, clear=True), \
             mock.patch.dict("sys.modules", {"piper": fake_piper}), \
             mock.patch.object(piper, "_espeak_data_dir", return_value="/fixture/espeak"), \
             mock.patch.dict("os.environ", {"LV_MANAGEMENT_TOKEN": "secret"}), \
             TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as client, \
             ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.post, "/synthesize", json={
                "text": "unique concurrent test", "voice": "ru_RU-dmitri-medium", "format": "wav"})
            try:
                self.assertTrue(started.wait(5))
                blocked = client.post("/models/removals", json={"languages": ["ru"]}, headers=headers)
                self.assertEqual(blocked.status_code, 409, blocked.text)
                self.assertTrue((Path(self.temp.name) / assets["piper-dmitri-onnx"].path).exists())
            finally:
                finish.set()
            self.assertEqual(future.result(timeout=5).status_code, 200)
            self.assertIn("ru_RU-dmitri-medium", piper._voices)
            removed = client.post("/models/removals", json={"languages": ["ru"]}, headers=headers)
            self.assertEqual(removed.status_code, 200, removed.text)
            self.assertEqual(set(removed.json()["removed"]), set(assets))
            self.assertNotIn("ru_RU-dmitri-medium", piper._voices)

    def test_unsupported_voice_rejected_before_loader(self):
        for voice in ("ru_RU-irina-medium", "af_unknown", "../../file"):
            with self.assertRaises(ValueError):
                local_voice_paths(voice)


if __name__ == "__main__":
    unittest.main()
