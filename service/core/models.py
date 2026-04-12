from pydantic import BaseModel, Field


class SynthesizeRequest(BaseModel):
    text: str
    voice: str = "af_bella"
    rate: float = 1.0
    format: str = "mp3"
    lang: str = "en"
    session_id: str | None = None
    normalize_audio: bool = True


class StreamChunkingConfig(BaseModel):
    strategy: str = "sentence"
    target_chars: int = 500
    max_chars: int = 1000


class StreamRequest(BaseModel):
    text: str
    voice: str = "af_bella"
    rate: float = 1.0
    format: str = "mp3"
    chunking: StreamChunkingConfig = Field(default_factory=StreamChunkingConfig)
    session_id: str | None = None


class StopRequest(BaseModel):
    job_id: str


class HealthResponse(BaseModel):
    status: str = "ok"
    engine: str = ""
    model: str = ""
    ready: bool = True
    platform: str = ""


class VoiceInfo(BaseModel):
    id: str
    label: str
    language: str = "en"
    gender: str = "f"
    sample_rate: int = 24000


class VoicesResponse(BaseModel):
    voices: list[VoiceInfo]


class StreamChunkInfo(BaseModel):
    index: int
    url: str
    text_range: list[int]


class StreamResponse(BaseModel):
    job_id: str
    chunks: list[StreamChunkInfo]


class PreprocessRequest(BaseModel):
    markdown: str


class PreprocessResponse(BaseModel):
    text: str


class ExportRequest(BaseModel):
    job_id: str | None = None
    text: str | None = None
    voice: str = "af_bella"
    rate: float = 1.0
    format: str = "mp3"
    chunking: StreamChunkingConfig = Field(default_factory=StreamChunkingConfig)
