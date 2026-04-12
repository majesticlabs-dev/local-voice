import sys
import types
import unittest
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

    def test_prepare_espeak_data_root_stages_spacey_path(self):
        with patch.object(
            kokoro.tempfile, "gettempdir", return_value="/tmp/space-free"
        ):
            with patch.object(kokoro.shutil, "copytree") as copytree:
                data_dir = kokoro.Path(
                    "/tmp/Local Voice/espeakng_loader/espeak-ng-data"
                )

                with patch.object(kokoro.Path, "resolve", return_value=data_dir):
                    with patch.object(kokoro.Path, "symlink_to") as symlink_to:
                        staged_root = kokoro._prepare_espeak_data_root(data_dir)

        self.assertEqual(staged_root, kokoro.Path("/tmp/space-free/local-voice-espeak"))
        symlink_to.assert_called_once_with(data_dir, target_is_directory=True)
        copytree.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
