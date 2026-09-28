"""Fail-closed access to catalog-managed speech assets."""
import hashlib
from pathlib import Path

from .config import config
from .model_catalog import ASSETS, LANGUAGES, voice_assets


class SetupNeeded(Exception):
    def __init__(self, voice: str, assets: list[str]):
        self.voice = voice
        self.assets = assets
        super().__init__(f"Model setup required for {voice}: {', '.join(assets)}")


def local_voice_paths(voice: str) -> dict[str, Path]:
    for language, entry in LANGUAGES.items():
        if voice in entry["voices"]:
            required = voice_assets(language, voice)
            break
    else:
        raise ValueError(f"Unsupported voice: {voice}")

    # Inventory rejects symlinks and invalid sizes. Verify the bytes here too
    # until the catalog downloader publishes verified inventory states.
    missing = []
    for asset_id in required:
        asset = ASSETS[asset_id]
        state = asset.inventory(config.models_dir)["state"]
        if state == "verified":
            continue
        if state != "present_unverified" or not asset.sha256:
            missing.append(asset_id)
            continue
        path = config.models_dir / asset.path
        try:
            with path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
        except OSError:
            missing.append(asset_id)
            continue
        if digest != asset.sha256:
            missing.append(asset_id)
    if missing:
        raise SetupNeeded(voice, missing)
    return {asset_id: config.models_dir / ASSETS[asset_id].path for asset_id in required}


def has_local_voice(engine: str) -> bool:
    for entry in LANGUAGES.values():
        if entry["engine"] != engine:
            continue
        for voice in entry["voices"]:
            try:
                local_voice_paths(voice)
                return True
            except SetupNeeded:
                pass
    return False
