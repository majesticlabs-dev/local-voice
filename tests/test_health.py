import unittest
from unittest import mock

from service.api import health as health_api
from service.core.config import config
from service.core.dependencies import ProviderStatus


class HealthApiTests(unittest.IsolatedAsyncioTestCase):
    def _patch_health(self, statuses):
        dependency_payload = [
            {
                "name": config.engine,
                "available": False,
                "required": True,
                "detail": "kokoro failed to initialize: missing dependency",
                "location": None,
            },
            {
                "name": "ffmpeg",
                "available": True,
                "required": True,
                "detail": "MP3 support ready (/opt/homebrew/bin/ffmpeg)",
                "location": "/opt/homebrew/bin/ffmpeg",
            },
        ]
        return (
            mock.patch.object(health_api, "_get_provider_statuses", return_value=statuses),
            mock.patch.object(
                health_api,
                "runtime_dependencies",
                return_value=dependency_payload,
            ),
        )

    async def test_health_returns_structured_response_when_provider_load_fails(self):
        statuses = [
            ProviderStatus(name=config.engine, error=RuntimeError("missing dependency")),
        ]
        provider_patch, deps_patch = self._patch_health(statuses)

        with provider_patch, deps_patch:
            response = await health_api.health()

        self.assertEqual(response.status, "degraded")
        self.assertEqual(response.engine, config.engine)
        self.assertFalse(response.ready)
        self.assertEqual(response.dependencies[0].detail, "kokoro failed to initialize: missing dependency")

    async def test_health_is_ok_when_only_english_is_installed(self):
        statuses = [
            ProviderStatus(name="kokoro", model_name="kokoro-82m", ready=True, installed=True),
            ProviderStatus(name="piper", model_name="piper-voices", ready=False),
        ]
        provider_patch, deps_patch = self._patch_health(statuses)

        with provider_patch, deps_patch:
            response = await health_api.health()

        self.assertEqual(response.status, "ok")
        self.assertTrue(response.ready)
        self.assertEqual(response.engine, "kokoro+piper")

    async def test_health_is_setup_needed_without_installed_languages(self):
        statuses = [ProviderStatus(name="kokoro"), ProviderStatus(name="piper")]
        provider_patch, deps_patch = self._patch_health(statuses)
        with provider_patch, deps_patch:
            response = await health_api.health()
        self.assertEqual(response.status, "setup_needed")
        self.assertFalse(response.ready)

    async def test_health_is_degraded_when_installed_engine_fails(self):
        statuses = [ProviderStatus(name="kokoro", installed=True, ready=False),
                    ProviderStatus(name="piper", ready=False)]
        provider_patch, deps_patch = self._patch_health(statuses)
        with provider_patch, deps_patch:
            response = await health_api.health()
        self.assertEqual(response.status, "degraded")
        self.assertFalse(response.ready)

    async def test_optional_uninstalled_engine_error_does_not_block_ready_language(self):
        statuses = [ProviderStatus(name="kokoro", ready=True, installed=True),
                    ProviderStatus(name="piper", error=RuntimeError("piper unavailable"))]
        with mock.patch.object(health_api, "_get_provider_statuses", return_value=statuses), \
             mock.patch("service.core.dependencies.resolve_executable", return_value=None):
            response = await health_api.health()
        self.assertEqual(response.status, "ok")
        self.assertTrue(response.ready)
        self.assertFalse(response.dependencies[1].available)
        self.assertFalse(response.dependencies[1].required)
        self.assertTrue(response.dependencies[0].required)

    async def test_health_is_ok_when_all_engines_ready(self):
        statuses = [
            ProviderStatus(name="kokoro", model_name="kokoro-82m", ready=True, installed=True),
            ProviderStatus(name="piper", model_name="piper-voices", ready=True, installed=True),
        ]
        provider_patch, deps_patch = self._patch_health(statuses)

        with provider_patch, deps_patch:
            response = await health_api.health()

        self.assertEqual(response.status, "ok")
        self.assertTrue(response.ready)


if __name__ == "__main__":
    unittest.main()
