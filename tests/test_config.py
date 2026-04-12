import os
import tempfile
import textwrap
import unittest
from unittest import mock

from service.core.config import Config


class ConfigTests(unittest.TestCase):
    def test_reads_values_from_yaml_config(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as handle:
            handle.write(
                textwrap.dedent(
                    """
                    service:
                      host: 127.0.0.9
                      port: 6611
                      engine: kokoro
                      default_voice: af_sarah
                      max_input_length: 12345
                    desktop:
                      api_host: 127.0.0.8
                      server_mode_host: 0.0.0.0
                      chunk_threshold: 222
                    """
                ).strip()
            )
            handle.flush()
            config_path = handle.name

        try:
            with mock.patch.dict(os.environ, {"LV_CONFIG_FILE": config_path}, clear=False):
                config = Config.from_env()
        finally:
            os.unlink(config_path)

        self.assertEqual(config.host, "127.0.0.9")
        self.assertEqual(config.port, 6611)
        self.assertEqual(config.default_voice, "af_sarah")
        self.assertEqual(config.max_input_length, 12345)
        self.assertEqual(config.desktop_api_host, "127.0.0.8")
        self.assertEqual(config.desktop_chunk_threshold, 222)

    def test_env_vars_override_yaml_config(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as handle:
            handle.write(
                textwrap.dedent(
                    """
                    service:
                      host: 127.0.0.9
                      port: 6611
                      max_input_length: 12345
                    """
                ).strip()
            )
            handle.flush()
            config_path = handle.name

        try:
            with mock.patch.dict(
                os.environ,
                {
                    "LV_CONFIG_FILE": config_path,
                    "LV_HOST": "127.0.0.2",
                    "LV_PORT": "7777",
                    "LV_MAX_INPUT": "9876",
                },
                clear=False,
            ):
                config = Config.from_env()
        finally:
            os.unlink(config_path)

        self.assertEqual(config.host, "127.0.0.2")
        self.assertEqual(config.port, 7777)
        self.assertEqual(config.max_input_length, 9876)

    def test_cache_and_output_dirs_can_be_overridden_from_env(self):
        with mock.patch.dict(
            os.environ,
            {
                "LV_CACHE_DIR": "~/Library/Caches/local-voice-test",
                "LV_OUTPUT_DIR": "/tmp/local-voice-output",
            },
            clear=False,
        ):
            config = Config.from_env()

        self.assertTrue(str(config.cache_dir).endswith("Library/Caches/local-voice-test"))
        self.assertEqual(str(config.output_dir), "/tmp/local-voice-output")


if __name__ == "__main__":
    unittest.main()
