from abc import ABC, abstractmethod


class TTSProvider(ABC):
    name: str = "base"
    model_name: str = ""

    @abstractmethod
    def is_ready(self) -> bool:
        ...

    @abstractmethod
    def list_voices(self) -> list[dict]:
        ...

    @abstractmethod
    def synthesize(self, text: str, voice: str, rate: float, audio_format: str) -> bytes:
        """Return audio bytes in the requested format (wav or mp3)."""
        ...

    def synthesize_chunks(
        self, chunks: list[str], voice: str, rate: float, audio_format: str
    ) -> list[bytes]:
        """Synthesize multiple chunks. Default: sequential calls to synthesize()."""
        return [self.synthesize(chunk, voice, rate, audio_format) for chunk in chunks]

    def cancel(self, job_id: str) -> None:
        """Cancel a running job. Default: no-op (override for async engines)."""
        pass
