from .base import TTSProvider


class RouterProvider(TTSProvider):
    """Dispatches synthesis to the provider that owns the requested voice ID.

    A voice is routed to the first provider whose owns_voice() accepts it;
    everything else falls through to the default provider. This keeps the API
    layer agnostic of which engine backs a given voice.
    """

    name = "router"

    def __init__(self, providers: list[TTSProvider], default: TTSProvider):
        self._providers = providers
        self._default = default
        self.model_name = default.model_name

    @property
    def providers(self) -> list[TTSProvider]:
        return list(self._providers)

    def _route(self, voice: str) -> TTSProvider:
        for provider in self._providers:
            if provider.owns_voice(voice):
                return provider
        return self._default

    def is_ready(self) -> bool:
        return all(provider.is_ready() for provider in self._providers)

    def list_voices(self) -> list[dict]:
        voices: list[dict] = []
        for provider in self._providers:
            voices.extend(provider.list_voices())
        return voices

    def synthesize(
        self, text: str, voice: str, rate: float, audio_format: str
    ) -> bytes:
        return self._route(voice).synthesize(text, voice, rate, audio_format)

    def cancel(self, job_id: str) -> None:
        for provider in self._providers:
            provider.cancel(job_id)
