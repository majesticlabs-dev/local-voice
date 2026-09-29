import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from service import voice_probe


class ProbeTests(unittest.TestCase):
    def test_packaged_probe_child_uses_service_model_directory_without_token(self):
        source = Path(__file__).resolve().parents[1] / "packaging/arch/service_launcher.py"
        spec = importlib.util.spec_from_file_location("service_launcher", source)
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            cache = Path(tmp) / "cache"
            with patch.dict(os.environ, {"XDG_DATA_HOME": str(data), "XDG_CACHE_HOME": str(cache)}, clear=True), \
                 patch.dict(sys.modules, {"service_launcher": launcher}):
                voice_probe.packaged_paths()
                expected = data / "dev.majesticlabs.localvoice/service-models"
                self.assertEqual(os.environ["LV_MODELS_DIR"], str(expected))
                self.assertEqual(os.environ["LV_OUTPUT_DIR"], str(expected.parent / "service-output"))
                self.assertEqual(os.environ["LV_CACHE_DIR"], str(cache / "dev.majesticlabs.localvoice/service-cache"))
                child = subprocess.run([sys.executable, "-c",
                                        "from service.core.config import config; print(config.models_dir)"],
                                       capture_output=True, text=True, check=True, env=os.environ.copy())
                self.assertEqual(child.stdout.strip(), str(expected))
                self.assertFalse((expected.parent / "management-token").exists())
                self.assertFalse(expected.parent.exists())

    def test_child_audio_and_no_audio(self):
        class Provider:
            def synthesize(self, *args):
                return b"RIFF"
        with patch("service.app.get_provider", return_value=Provider()):
            self.assertEqual(voice_probe.child("af_bella"), 0)
            Provider.synthesize = lambda self, *args: b""
            self.assertEqual(voice_probe.child("af_bella"), 1)

    def test_crashing_child_does_not_kill_caller(self):
        with patch("service.voice_probe.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
            self.assertEqual(voice_probe.probe("af_bella"), 1)
        with patch("service.voice_probe.subprocess.run", return_value=subprocess.CompletedProcess([], 0)):
            self.assertEqual(voice_probe.probe("af_bella"), 0)
        self.assertEqual(voice_probe.probe("not-a-voice"), 2)

    def test_fake_provider_in_child_exits_without_killing_caller(self):
        script = ("import sys; from unittest.mock import patch; "
                  "from service.voice_probe import child; "
                  "provider = type('Fake', (), {'synthesize': lambda self, *args: "
                  "sys.exit(1) if sys.argv[1] == 'fail' else b'audio'})(); "
                  "with_provider = patch('service.app.get_provider', return_value=provider); "
                  "with_provider.start(); sys.exit(child('af_bella'))")
        for mode, expected in (("fail", 1), ("ok", 0)):
            result = subprocess.run([sys.executable, "-c", script, mode],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, expected, result.stderr)
