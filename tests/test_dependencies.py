import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from service.core import dependencies


class ResolveExecutableTests(unittest.TestCase):
    def test_prefers_explicit_env_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ffmpeg_path = Path(temp_dir) / "ffmpeg"
            ffmpeg_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            ffmpeg_path.chmod(ffmpeg_path.stat().st_mode | stat.S_IXUSR)

            with mock.patch.dict(
                os.environ,
                {"LV_FFMPEG_PATH": str(ffmpeg_path), "PATH": ""},
                clear=False,
            ):
                resolved = dependencies.resolve_executable("ffmpeg", env_var="LV_FFMPEG_PATH")

        self.assertEqual(resolved, ffmpeg_path.resolve())

    def test_uses_fallback_search_dirs_when_path_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ffmpeg_path = Path(temp_dir) / "ffmpeg"
            ffmpeg_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            ffmpeg_path.chmod(ffmpeg_path.stat().st_mode | stat.S_IXUSR)

            with mock.patch.dict(os.environ, {"PATH": ""}, clear=False):
                with mock.patch.object(
                    dependencies,
                    "_candidate_executable_dirs",
                    return_value=[Path(temp_dir)],
                ):
                    resolved = dependencies.resolve_executable("ffmpeg")

        self.assertEqual(resolved, ffmpeg_path.resolve())


class DependencyStatusTests(unittest.TestCase):
    def test_ffmpeg_dependency_reports_install_guidance_when_missing(self):
        with mock.patch.object(dependencies, "resolve_executable", return_value=None):
            status = dependencies.ffmpeg_dependency_status()

        self.assertFalse(status["available"])
        self.assertIn("brew install ffmpeg", status["detail"])
        self.assertIn("LV_FFMPEG_PATH", status["detail"])

    def test_runtime_dependencies_include_provider_and_ffmpeg(self):
        with mock.patch.object(
            dependencies,
            "resolve_executable",
            return_value=Path("/opt/homebrew/bin/ffmpeg"),
        ):
            checks = dependencies.runtime_dependencies(
                provider_name="kokoro",
                model_name="kokoro-82m",
                provider_ready=True,
            )

        self.assertEqual([check["name"] for check in checks], ["kokoro", "ffmpeg"])
        self.assertTrue(all(check["required"] for check in checks))
        self.assertTrue(checks[0]["available"])
        self.assertEqual(checks[1]["location"], "/opt/homebrew/bin/ffmpeg")


if __name__ == "__main__":
    unittest.main()
