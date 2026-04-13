import unittest
from unittest import mock

from service.api import health as health_api
from service.core.config import config


class HealthApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_returns_structured_response_when_provider_load_fails(self):
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

        with mock.patch.object(
            health_api,
            "_get_provider",
            side_effect=RuntimeError("missing dependency"),
        ):
            with mock.patch.object(
                health_api,
                "runtime_dependencies",
                return_value=dependency_payload,
            ):
                response = await health_api.health()

        self.assertEqual(response.status, "degraded")
        self.assertEqual(response.engine, config.engine)
        self.assertFalse(response.ready)
        self.assertEqual(response.dependencies[0].detail, dependency_payload[0]["detail"])


if __name__ == "__main__":
    unittest.main()
