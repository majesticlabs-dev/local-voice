"""Single-process model asset coordination and explicit legacy import."""
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import sys
import threading
import uuid
from typing import Callable

from . import model_catalog as catalog
from .config import config

_lock = threading.RLock()
_in_use: dict[str, int] = {}
_release: Callable[[set[str]], None] | None = None
_process_lock = None


def register_release(callback: Callable[[set[str]], None]) -> None:
    """T04 registers a provider-cache eviction callback before enabling removal."""
    global _release
    with _lock:
        _release = callback


@contextmanager
def using(assets: set[str]):
    """T04 must hold this for the full synthesis, including lazy model loading."""
    with _lock:
        for key in assets:
            _in_use[key] = _in_use.get(key, 0) + 1
    try:
        yield
    finally:
        with _lock:
            for key in assets:
                _in_use[key] -= 1
                if not _in_use[key]:
                    del _in_use[key]


def _required(languages):
    return {key for code in languages for voice in catalog.LANGUAGES[code]["voices"]
            for key in catalog.voice_assets(code, voice)}


def remove(languages: list[str]) -> dict:
    from . import model_downloads
    with _lock, model_downloads._lock:
        if model_downloads._active is not None:
            raise RuntimeError("Model download is active")
        requested = set(languages)
        retained = set(catalog.LANGUAGES) - requested
        needed = _required(requested) - _required(retained)
        if any(_in_use.get(key) for key in _required(requested)):
            raise RuntimeError("Model assets are in use")
        if _release is None:
            raise RuntimeError("Provider cache release is not configured")
        root = config.models_dir
        from .model_downloads import _safe_path
        paths = []
        for key in sorted(needed):
            asset = catalog.ASSETS[key]
            path = _safe_path(root, asset.path)
            if path.exists():
                if asset.inventory(root)["state"] != "verified":
                    raise RuntimeError(f"Unverified asset must be preserved: {key}")
                paths.append((key, path))
        _release(_required(requested))
        for _, path in paths:
            path.unlink()
            catalog.invalidate(path)
        return {"removed": [key for key, _ in paths], "languages": sorted(requested)}


def _legacy_roots() -> tuple[Path, ...]:
    home = Path.home()
    hf = Path(os.environ.get("HF_HUB_CACHE", Path(os.environ.get("HF_HOME", home / ".cache/huggingface")) / "hub"))
    app = (home / "Library/Application Support/dev.majesticlabs.localvoice" if sys.platform == "darwin"
           else Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")) / "dev.majesticlabs.localvoice")
    return (hf / "models--hexgrad--Kokoro-82M" / "snapshots", app / "service-models",
            Path(__file__).parent.parent / "artifacts/models")


def _candidates():
    roots = _legacy_roots()
    for asset in catalog.ASSETS.values():
        if not asset.sha256:
            continue
        relative = asset.upstream_path if asset.id.startswith("kokoro-") else asset.path
        bases = sorted(roots[0].glob("*")) if asset.id.startswith("kokoro-") else roots[1:]
        for base in bases:
            path = base / relative
            try:
                # HF snapshots use symlinks into the blob store. Read only.
                if not path.is_file() or path.stat().st_size != asset.size_bytes:
                    continue
                if catalog._digest(path) != asset.sha256:
                    continue
            except OSError:
                continue
            identity = hashlib.sha256(f"{asset.id}\0{path}".encode()).hexdigest()[:24]
            yield identity, asset, path


def discover() -> list[dict]:
    root = config.models_dir
    return [{"id": identity, "asset_id": asset.id, "source": str(path)}
            for identity, asset, path in _candidates()
            if asset.inventory(root)["state"] != "verified"]


def migrate(candidate_ids: list[str]) -> dict:
    from . import model_downloads
    with _lock, model_downloads._lock:
        if model_downloads._active is not None:
            raise RuntimeError("Model download is active")
        known = {identity: (asset, path) for identity, asset, path in _candidates()}
        if (len(set(candidate_ids)) != len(candidate_ids) or any(key not in known for key in candidate_ids)
                or len({known[key][0].id for key in candidate_ids}) != len(candidate_ids)):
            raise ValueError("Unknown or duplicate migration candidate")
        root = config.models_dir
        stage = model_downloads._safe_path(root, f".downloads/migration-{uuid.uuid4().hex}")
        staged = []
        try:
            stage.mkdir(parents=True, exist_ok=False)
            for identity in candidate_ids:
                asset, source = known[identity]
                dest = model_downloads._safe_path(root, asset.path)
                if dest.exists() or dest.is_symlink():
                    raise RuntimeError(f"Destination exists: {asset.id}")
                temporary = model_downloads._safe_path(stage, asset.path)
                temporary.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, temporary)
                if temporary.stat().st_size != asset.size_bytes or catalog._digest(temporary) != asset.sha256:
                    raise ValueError(f"Source changed during migration: {asset.id}")
                staged.append((asset, temporary, dest))
            for asset, temporary, dest in staged:
                model_downloads._safe_path(root, asset.path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temporary, dest)
                catalog.invalidate(dest)
            return {"migrated": [asset.id for asset, _, _ in staged]}
        finally:
            shutil.rmtree(stage, ignore_errors=True)


def startup() -> None:
    """Fail a second worker and discard staging left by an interrupted process."""
    global _process_lock
    with _lock:
        if _process_lock is not None:
            return
        from .model_downloads import _safe_path
        root = config.models_dir
        root.mkdir(parents=True, exist_ok=True)
        lock_path = _safe_path(root, ".management.lock")
        handle = lock_path.open("a+b")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            stage = _safe_path(root, ".downloads")
            if stage.exists():
                if not stage.is_dir():
                    raise RuntimeError("Invalid download staging directory")
                shutil.rmtree(stage)
            _process_lock = handle
        except BaseException:
            handle.close()
            raise


def shutdown() -> None:
    global _process_lock
    with _lock:
        if _process_lock is not None:
            _process_lock.close()
            _process_lock = None
