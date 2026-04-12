import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ..core.audio import concat_audio_files
from ..core.cache import cache_key, get_cached, put_cached
from ..core.chunking import chunk_text
from ..core.config import config
from ..core.jobs import registry
from ..core.models import ExportRequest

router = APIRouter()

MIME = {"mp3": "audio/mpeg", "wav": "audio/wav"}


def _get_provider():
    from ..app import get_provider
    return get_provider()


def _sorted_chunk_files(chunk_dir: Path) -> list[Path]:
    files = [path for path in chunk_dir.iterdir() if path.is_file() and path.suffix.lstrip(".") in MIME]
    return sorted(files, key=lambda path: int(path.stem))


def _synthesize_cached(text: str, voice: str, rate: float, fmt: str) -> bytes:
    key = cache_key(text, voice, rate, fmt)
    cached = get_cached(key, fmt)
    if cached:
        return cached

    provider = _get_provider()
    if not provider.is_ready():
        raise HTTPException(503, "TTS engine not ready")

    try:
        audio_bytes = provider.synthesize(text, voice, rate, fmt)
    except Exception as exc:
        raise HTTPException(500, f"Synthesis error: {exc}") from exc

    put_cached(key, fmt, audio_bytes)
    return audio_bytes


@router.post("/export")
async def export_audio(req: ExportRequest):
    fmt = req.format if req.format in MIME else "mp3"
    if fmt != "mp3":
        raise HTTPException(400, "Export currently supports mp3 only")

    if req.job_id:
        chunk_dir = config.output_dir / req.job_id
        if not chunk_dir.exists():
            raise HTTPException(404, "Job not found")

        job = registry.get(req.job_id)
        if job is not None:
            snapshot = job.snapshot()
            if snapshot["error"]:
                raise HTTPException(500, str(snapshot["error"]))
            if snapshot["cancelled"]:
                raise HTTPException(409, "Job cancelled")
            if not snapshot["complete"]:
                job.wait(timeout=60)
                snapshot = job.snapshot()
                if snapshot["error"]:
                    raise HTTPException(500, str(snapshot["error"]))
                if snapshot["cancelled"]:
                    raise HTTPException(409, "Job cancelled")
                if not snapshot["complete"]:
                    raise HTTPException(425, "Audio export is still being prepared")

        chunk_files = _sorted_chunk_files(chunk_dir)
        if not chunk_files:
            raise HTTPException(404, "No audio chunks found for job")
        try:
            audio_bytes = concat_audio_files(chunk_files, output_format="mp3")
        except Exception as exc:
            raise HTTPException(500, f"Export error: {exc}") from exc
        return Response(content=audio_bytes, media_type=MIME["mp3"])

    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "Provide either job_id or text")
    if len(text) > config.max_input_length:
        raise HTTPException(400, f"Text exceeds max length ({config.max_input_length})")

    chunks = chunk_text(
        text,
        strategy=req.chunking.strategy,
        target_chars=req.chunking.target_chars,
        max_chars=req.chunking.max_chars,
    )
    try:
        with tempfile.TemporaryDirectory(prefix="local-voice-export-") as temp_dir:
            paths: list[Path] = []
            for index, chunk in enumerate(chunks):
                chunk_bytes = _synthesize_cached(chunk, req.voice, req.rate, "mp3")
                chunk_path = Path(temp_dir) / f"{index}.mp3"
                chunk_path.write_bytes(chunk_bytes)
                paths.append(chunk_path)
            audio_bytes = concat_audio_files(paths, output_format="mp3")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Export error: {exc}") from exc

    return Response(content=audio_bytes, media_type=MIME["mp3"])
