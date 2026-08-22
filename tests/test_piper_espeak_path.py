import tempfile
import unittest
from pathlib import Path
from unittest import mock

from service.providers import piper


class EspeakDataDirTests(unittest.TestCase):
    def setUp(self):
        self.data_dir = Path(tempfile.mkdtemp(prefix="espeak-data-"))
        # _espeak_data_dir caches nothing, but the symlink target is stable;
        # start from a clean link path each run.
        link = Path(tempfile.gettempdir()) / "local-voice-espeak-ng-data"
        if link.is_symlink():
            link.unlink()

    def tearDown(self):
        link = Path(tempfile.gettempdir()) / "local-voice-espeak-ng-data"
        if link.is_symlink():
            link.unlink()

    def test_short_path_used_directly(self):
        with mock.patch(
            "piper.phonemize_espeak.ESPEAK_DATA_DIR", self.data_dir
        ):
            self.assertEqual(piper._espeak_data_dir(), str(self.data_dir))

    def test_long_path_gets_short_symlink(self):
        long_dir = (
            Path(tempfile.gettempdir())
            / ("nested" * 30)
            / "site-packages/piper/espeak-ng-data"
        )
        long_dir.mkdir(parents=True)
        self.assertGreater(len(str(long_dir)), piper._ESPEAK_MAX_PATH)

        with mock.patch("piper.phonemize_espeak.ESPEAK_DATA_DIR", long_dir):
            resolved = piper._espeak_data_dir()

        self.assertLess(len(resolved), len(str(long_dir)))
        self.assertEqual(Path(resolved).resolve(), long_dir.resolve())

    def test_existing_correct_symlink_is_reused(self):
        long_dir = (
            Path(tempfile.gettempdir())
            / ("deep" * 30)
            / "espeak-ng-data"
        )
        long_dir.mkdir(parents=True)

        with mock.patch("piper.phonemize_espeak.ESPEAK_DATA_DIR", long_dir):
            first = piper._espeak_data_dir()
            second = piper._espeak_data_dir()

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
