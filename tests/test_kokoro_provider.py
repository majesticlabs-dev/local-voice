import importlib.util
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from service.providers import kokoro


class FakeWrapper:
    library_path = None
    data_path = None

    @classmethod
    def set_library(cls, path):
        cls.library_path = path

    @classmethod
    def set_data_path(cls, path):
        cls.data_path = path


class ConfigureEspeakBackendTest(unittest.TestCase):
    def test_prepare_espeak_data_root_uses_parent_for_space_free_path(self):
        data_path = kokoro.Path("/tmp/espeakng_loader/espeak-ng-data")

        self.assertEqual(
            kokoro._prepare_espeak_data_root(data_path),
            kokoro.Path("/tmp/espeakng_loader"),
        )

    @unittest.skipUnless(importlib.util.find_spec("espeakng_loader"), "eSpeak runtime missing")
    def test_long_runtime_path_initializes_real_english_espeak_fallback(self):
        # Run in a child: the old path makes espeak-ng call exit(1), which must
        # fail this test without killing the whole suite. No model weights needed.
        code = """
import espeakng_loader
from phonemizer.backend.espeak.wrapper import EspeakWrapper
from misaki.espeak import EspeakFallback
from service.providers.kokoro import _prepare_espeak_data_root
from pathlib import Path
import os
root = _prepare_espeak_data_root(Path(os.environ['ESPEAK_TEST_DATA']))
EspeakWrapper.set_library(espeakng_loader.get_library_path())
EspeakWrapper.set_data_path(str(root))
fallback = EspeakFallback(british=False)
assert fallback.backend.phonemize(['hello'])
"""
        with tempfile.TemporaryDirectory(prefix="lv-espeak-test-") as temp:
            long_parent = Path(temp) / ("long-relocatable-package-path-" * 6)
            long_parent.mkdir()
            (long_parent / "espeak-ng-data").symlink_to(
                Path(__import__("espeakng_loader").get_data_path()), target_is_directory=True
            )
            env = {**os.environ, "ESPEAK_TEST_DATA": str(long_parent / "espeak-ng-data")}
            result = subprocess.run(
                [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                env=env, capture_output=True, text=True, timeout=30, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_configures_wrapper_with_prepared_data_root(self):
        fake_loader = types.SimpleNamespace(
            get_library_path=lambda: "/tmp/libespeak-ng.dylib",
            get_data_path=lambda: "/tmp/espeakng_loader/espeak-ng-data",
        )
        fake_wrapper_module = types.SimpleNamespace(EspeakWrapper=FakeWrapper)

        with patch.dict(
            sys.modules,
            {
                "espeakng_loader": fake_loader,
                "phonemizer.backend.espeak.wrapper": fake_wrapper_module,
            },
        ):
            with patch.object(
                kokoro,
                "_prepare_espeak_data_root",
                return_value=kokoro.Path("/tmp/espeakng_loader"),
            ):
                kokoro._configure_espeak_backend()

        self.assertEqual(FakeWrapper.library_path, "/tmp/libespeak-ng.dylib")
        self.assertEqual(FakeWrapper.data_path, "/tmp/espeakng_loader")


class ConcurrentLoadTest(unittest.TestCase):
    def test_espeak_copy_is_published_only_once_complete(self):
        with tempfile.TemporaryDirectory(prefix="lv spaced ") as temp:
            data = Path(temp) / "espeak-ng-data"
            data.mkdir()
            (data / "phontab").write_text("ready")
            original = kokoro.shutil.copytree
            def slow_copy(*args):
                time.sleep(.05)
                return original(*args)
            with patch.object(kokoro, "_espeak_staging", None), patch.object(kokoro.shutil, "copytree", side_effect=slow_copy) as copy:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    roots = list(pool.map(kokoro._prepare_espeak_data_root, [data] * 8))
                self.assertEqual(copy.call_count, 1)
                self.assertEqual(len(set(roots)), 1)
                self.assertTrue((roots[0] / "espeak-ng-data/phontab").exists())
                kokoro._espeak_staging.cleanup()

    def test_first_pipeline_created_once(self):
        from unittest.mock import Mock
        create = Mock(side_effect=lambda **kw: object())
        fake = types.SimpleNamespace(KPipeline=create)
        with patch.object(kokoro, "_kokoro", fake), patch.dict(sys.modules, {"kokoro": types.SimpleNamespace(KModel=lambda **kw: object())}), patch.object(kokoro, "_pipelines", {}):
            with ThreadPoolExecutor(max_workers=8) as pool:
                pipelines = list(pool.map(kokoro._load_kokoro, ["e"] * 8))
            self.assertTrue(all(p is pipelines[0] for p in pipelines))
            self.assertEqual(create.call_count, 1)


class IsReadyTest(unittest.TestCase):
    def test_readiness_does_not_enter_transitive_loader(self):
        with patch.object(kokoro, "_load_kokoro", side_effect=AssertionError("loaded")):
            self.assertFalse(kokoro.KokoroProvider().is_ready())


if __name__ == "__main__":
    unittest.main()
