import logging
import shutil
import threading
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ..core.config import config
from ..core.models import StreamRequest, StreamResponse, StreamChunkInfo
from ..core.chunking import chunk_text
from ..core.jobs import registry
from ..core.cache import cache_key, get_cached, put_cached

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_provider():
    from ..app import get_provider
    return get_provider()


MIME = {"mp3": "audio/mpeg", "wav": "audio/wav"}


def _synthesize_chunks(
    *,
    job_id: str,
    chunks: list[str],
    voice: str,
    rate: float,
    fmt: str,
):
    job = registry.get(job_id)
    if job is None:
        return

    chunk_dir = config.output_dir / job_id
    provider = _get_provider()

    try:
        for index, chunk_text_str in enumerate(chunks):
            if job.is_cancelled():
                return

            key = cache_key(chunk_text_str, voice, rate, fmt)
            cached = get_cached(key, fmt)

            if cached:
                audio_bytes = cached
            else:
                audio_bytes = provider.synthesize(chunk_text_str, voice, rate, fmt)
                put_cached(key, fmt, audio_bytes)

            if job.is_cancelled():
                return

            chunk_path = chunk_dir / f"{index}.{fmt}"
            chunk_path.write_bytes(audio_bytes)
            job.mark_chunk_ready()

        job.mark_complete()
    except Exception as exc:
        logger.exception("Background synthesis failed for job %s", job_id)
        job.fail(f"Synthesis error: {exc}")


@router.post("/stream", response_model=StreamResponse)
async def stream(req: StreamRequest):
    logger.info("Stream: %d chars, first 80: %s", len(req.text), repr(req.text[:80]))
    if len(req.text) > config.max_input_length:
        raise HTTPException(400, f"Text exceeds max length ({config.max_input_length})")

    if not req.text.strip():
        raise HTTPException(400, "Empty text")

    provider = _get_provider()
    if not provider.is_ready():
        raise HTTPException(503, "TTS engine not ready")

    job_id = req.session_id or str(uuid.uuid4())
    job = registry.create(job_id)

    chunks = chunk_text(
        req.text,
        strategy=req.chunking.strategy,
        target_chars=req.chunking.target_chars,
        max_chars=req.chunking.max_chars,
    )

    fmt = req.format if req.format in MIME else "mp3"
    chunk_dir = config.output_dir / job_id
    shutil.rmtree(chunk_dir, ignore_errors=True)
    chunk_dir.mkdir(parents=True, exist_ok=True)

    job.set_total_chunks(len(chunks))

    chunk_infos = []
    offset = 0
    for i, chunk_text_str in enumerate(chunks):
        end = offset + len(chunk_text_str)
        chunk_infos.append(StreamChunkInfo(
            index=i,
            url=f"/audio/{job_id}/{i}.{fmt}",
            text_range=[offset, end],
        ))
        offset = end + 1

    thread = threading.Thread(
        target=_synthesize_chunks,
        kwargs={
            "job_id": job_id,
            "chunks": chunks,
            "voice": req.voice,
            "rate": req.rate,
            "fmt": fmt,
        },
        daemon=True,
    )
    thread.start()

    return StreamResponse(job_id=job_id, chunks=chunk_infos)


@router.get("/audio/{job_id}/{filename}")
async def get_chunk_audio(job_id: str, filename: str):
    path = config.output_dir / job_id / filename
    if not path.exists():
        job = registry.get(job_id)
        if job is not None:
            snapshot = job.snapshot()
            if snapshot["error"]:
                raise HTTPException(500, str(snapshot["error"]))
            if snapshot["cancelled"]:
                raise HTTPException(409, "Job cancelled")
            if not snapshot["complete"]:
                raise HTTPException(425, "Chunk not ready")
        raise HTTPException(404, "Chunk not found")

    ext = path.suffix.lstrip(".")
    mime = MIME.get(ext, "application/octet-stream")
    return Response(content=path.read_bytes(), media_type=mime)
