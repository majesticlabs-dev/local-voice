import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "packaging/arch/service_launcher.py"
spec = importlib.util.spec_from_file_location("local_voice_launcher", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def test_token_and_model_paths_survive_restart_without_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(root / ".local/share")}, clear=True):
                launcher.prepare(root, root / "runtime", root / "cache")
                token = os.environ["LV_MANAGEMENT_TOKEN"]
                model_dir = Path(os.environ["LV_MODELS_DIR"])
                self.assertTrue(model_dir.is_dir())
                self.assertFalse(any(model_dir.iterdir()))
                data = root / ".local/share/dev.majesticlabs.localvoice"
                self.assertEqual(data.stat().st_mode & 0o777, 0o700)
                self.assertEqual((data / "management-token").stat().st_mode & 0o777, 0o600)
                launcher.prepare(root, root / "runtime", root / "cache")
                self.assertEqual(os.environ["LV_MANAGEMENT_TOKEN"], token)
                self.assertEqual(os.environ["LV_HOST"], "127.0.0.1")
                self.assertEqual(os.environ["LV_PORT"], "5517")

    def test_rejects_token_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / ".local/share/dev.majesticlabs.localvoice"
            data.mkdir(parents=True)
            (data / "management-token").symlink_to(root / "other")
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(root / ".local/share")}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "symlink"):
                    launcher.prepare(root, root / "runtime", root / "cache")
