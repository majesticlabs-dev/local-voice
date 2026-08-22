import unittest

from service.providers.base import TTSProvider
from service.providers.router import RouterProvider


class FakeProvider(TTSProvider):
    def __init__(self, name, voices, ready=True):
        self.name = name
        self.model_name = f"{name}-model"
        self._voices = voices
        self.ready = ready
        self.synthesized = []

    def is_ready(self) -> bool:
        return self.ready

    def list_voices(self) -> list[dict]:
        return self._voices

    def owns_voice(self, voice: str) -> bool:
        return any(v["id"] == voice for v in self._voices)

    def synthesize(self, text: str, voice: str, rate: float, audio_format: str) -> bytes:
        self.synthesized.append(voice)
        return b"audio"

    def cancel(self, job_id: str) -> None:
        pass


def make_router(kokoro_ready=True, piper_ready=True):
    kokoro = FakeProvider(
        "kokoro",
        [{"id": "af_bella", "label": "Bella", "language": "en"}],
        ready=kokoro_ready,
    )
    piper = FakeProvider(
        "piper",
        [{"id": "ru_RU-irina-medium", "label": "Irina", "language": "ru"}],
        ready=piper_ready,
    )
    return RouterProvider([kokoro, piper], default=kokoro), kokoro, piper


class RoutingTests(unittest.TestCase):
    def test_voice_routes_to_owner_not_default(self):
        router, _kokoro, piper = make_router()

        self.assertIs(router._route("ru_RU-irina-medium"), piper)

    def test_unknown_voice_falls_back_to_default(self):
        router, kokoro, _piper = make_router()

        self.assertIs(router._route("af_bella"), kokoro)
        self.assertIs(router._route("zz_nope"), kokoro)

    def test_synthesize_dispatches_to_owner(self):
        router, kokoro, piper = make_router()
        router.synthesize("text", "ru_RU-irina-medium", 1.0, "mp3")

        self.assertEqual(piper.synthesized, ["ru_RU-irina-medium"])
        self.assertEqual(kokoro.synthesized, [])

    def test_list_voices_merges_all_engines(self):
        router, _kokoro, _piper = make_router()
        ids = [v["id"] for v in router.list_voices()]

        self.assertEqual(ids, ["af_bella", "ru_RU-irina-medium"])

    def test_is_ready_requires_every_engine(self):
        router, _kokoro, _piper = make_router(piper_ready=False)
        self.assertFalse(router.is_ready())

        router, _kokoro, _piper = make_router()
        self.assertTrue(router.is_ready())

    def test_providers_property_lists_children(self):
        router, kokoro, piper = make_router()

        self.assertEqual(router.providers, [kokoro, piper])


if __name__ == "__main__":
    unittest.main()
