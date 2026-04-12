import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ..core.config import config
from ..core.models import SynthesizeRequest
from ..core.cache import cache_key, get_cached, put_cached

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_provider():
    from ..app import get_provider
    return get_provider()


MIME = {"mp3": "audio/mpeg", "wav": "audio/wav"}


@router.post("/synthesize")
async def synthesize(req: SynthesizeRequest):
    logger.info("Synthesize: %d chars, first 80: %s", len(req.text), repr(req.text[:80]))
    if len(req.text) > config.max_input_length:
        raise HTTPException(400, f"Text exceeds max length ({config.max_input_length})")

    if not req.text.strip():
        raise HTTPException(400, "Empty text")

    fmt = req.format if req.format in MIME else "mp3"
    key = cache_key(req.text, req.voice, req.rate, fmt)

    cached = get_cached(key, fmt)
    if cached:
        return Response(content=cached, media_type=MIME[fmt])

    provider = _get_provider()
    if not provider.is_ready():
        raise HTTPException(503, "TTS engine not ready")

    try:
        audio_bytes = provider.synthesize(req.text, req.voice, req.rate, fmt)
    except Exception as e:
        raise HTTPException(500, f"Synthesis error: {e}")

    put_cached(key, fmt, audio_bytes)
    return Response(content=audio_bytes, media_type=MIME[fmt])
