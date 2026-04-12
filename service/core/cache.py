import hashlib
import time
from pathlib import Path

from .config import config

CACHE_FORMAT_VERSION = "v2"


def cache_key(text: str, voice: str, rate: float, fmt: str) -> str:
    h = hashlib.sha256(f"{CACHE_FORMAT_VERSION}|{text}|{voice}|{rate}|{fmt}".encode()).hexdigest()[:16]
    return h


def get_cached(key: str, fmt: str) -> bytes | None:
    path = config.cache_dir / f"{key}.{fmt}"
    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age < config.cache_ttl_seconds:
            return path.read_bytes()
        path.unlink(missing_ok=True)
    return None


def put_cached(key: str, fmt: str, data: bytes):
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    path = config.cache_dir / f"{key}.{fmt}"
    path.write_bytes(data)


def cleanup_expired():
    if not config.cache_dir.exists():
        return
    now = time.time()
    for f in config.cache_dir.iterdir():
        if f.is_file() and (now - f.stat().st_mtime) > config.cache_ttl_seconds:
            f.unlink(missing_ok=True)
