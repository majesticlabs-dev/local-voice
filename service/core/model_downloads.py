"""Explicit, service-owned model transfers. No transfer happens on import or inspection."""
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import shutil
import threading
import uuid
from urllib.request import urlopen

from . import model_catalog as catalog
from . import model_lifecycle
from .config import config


@dataclass
class Job:
    id: str
    languages: tuple[str, ...]
    root: Path
    assets: tuple[catalog.Asset, ...]
    status: str = "queued"
    bytes_done: int = 0
    bytes_total: int | None = None
    error: str | None = None
    cancelled: threading.Event = field(default_factory=threading.Event, repr=False)

    def response(self):
        return {"job_id": self.id, "languages": self.languages, "status": self.status,
                "bytes_done": self.bytes_done, "bytes_total": self.bytes_total, "error": self.error}


_lock = threading.Lock()
_jobs: dict[str, Job] = {}
_active: str | None = None


def source_url(asset: catalog.Asset) -> str:
    if asset.id == "spacy-en-core-web-sm":
        return ("https://github.com/explosion/spacy-models/releases/download/"
                f"{asset.revision}/{asset.upstream_path}")
    return f"{asset.source}/resolve/{asset.revision}/{asset.upstream_path}"


def _safe_path(root: Path, relative: str) -> Path:
    path = root / relative
    for component in (root, *[root.joinpath(*Path(relative).parts[:i])
                              for i in range(1, len(Path(relative).parts) + 1)]):
        if component.is_symlink():
            raise ValueError("Model directory contains a symlink")
    return path


def start(languages: list[str]) -> tuple[Job, bool]:
    global _active
    selected = tuple(sorted(set(languages)))
    root = config.models_dir
    with model_lifecycle._lock, _lock:
        if _active and _jobs[_active].status in ("queued", "downloading"):
            job = _jobs[_active]
            if job.languages == selected and job.root == root:
                return job, False
            raise RuntimeError("Another model download is active")
        required = {key for code in selected for voice in catalog.LANGUAGES[code]["voices"]
                    for key in catalog.voice_assets(code, voice)}
        assets = tuple(catalog.ASSETS[key] for key in sorted(required)
                       if catalog.ASSETS[key].inventory(root)["state"] != "verified")
        if any(not a.sha256 or not a.revision or not a.upstream_path for a in assets):
            raise ValueError("Verified upstream integrity metadata is missing for requested assets")
        job = Job(uuid.uuid4().hex, selected, root, assets,
                  bytes_total=sum(a.size_bytes for a in assets) if all(a.size_bytes is not None for a in assets) else None)
        # Keep a bounded in-process history. After restart, inventory remains
        # authoritative and old job IDs correctly return 404.
        if len(_jobs) >= 100:
            for old_id in list(_jobs):
                if old_id != _active and _jobs[old_id].status not in ("queued", "downloading"):
                    del _jobs[old_id]
                    break
        _jobs[job.id] = job
        _active = job.id
        threading.Thread(target=_run, args=(job,), daemon=True).start()
        return job, True


def get(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def cancel(job_id: str) -> Job | None:
    with _lock:
        job = _jobs.get(job_id)
        if job and job.status in ("queued", "downloading"):
            job.cancelled.set()
        return job


def _run(job: Job) -> None:
    global _active
    stage = None
    try:
        with _lock:
            job.status = "downloading"
        root = job.root
        _safe_path(root, ".downloads")
        root.mkdir(parents=True, exist_ok=True)
        stage = _safe_path(root, f".downloads/{job.id}")
        stage.mkdir(parents=True, exist_ok=False)
        needed = sum(a.size_bytes or 0 for a in job.assets)
        if shutil.disk_usage(root).free < needed:
            raise OSError("Insufficient space for model download")
        for asset in job.assets:
            if job.cancelled.is_set():
                break
            destination = _safe_path(stage, asset.path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with urlopen(source_url(asset), timeout=30) as response, destination.open("xb") as output:
                while True:
                    if job.cancelled.is_set():
                        break
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    size += len(block)
                    if asset.size_bytes is not None and size > asset.size_bytes:
                        raise ValueError(f"Invalid size for {asset.id}")
                    output.write(block)
                    digest.update(block)
                    with _lock:
                        job.bytes_done += len(block)
                output.flush()
                os.fsync(output.fileno())
            if job.cancelled.is_set():
                break
            if size != asset.size_bytes or digest.hexdigest() != asset.sha256:
                raise ValueError(f"Invalid checksum or size for {asset.id}")
        if not job.cancelled.is_set():
            # No asset is promoted until all missing files have passed validation.
            with model_lifecycle._lock:
                if any(model_lifecycle._in_use.get(asset.id) for asset in job.assets):
                    raise RuntimeError("Model assets are in use")
                for asset in job.assets:
                    dest = _safe_path(root, asset.path)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(_safe_path(stage, asset.path), dest)
                with _lock:
                    job.status = "completed"
        else:
            with _lock:
                job.status = "cancelled"
    except Exception as exc:
        with _lock:
            job.status = "cancelled" if job.cancelled.is_set() else "failed"
            if job.status == "failed":
                job.error = str(exc)
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
        with _lock:
            if _active == job.id:
                _active = None
