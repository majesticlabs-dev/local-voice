"""Fail-closed access to catalog-managed speech assets."""
from pathlib import Path

from .config import config
from .model_catalog import ASSETS, LANGUAGES, voice_assets


class SetupNeeded(Exception):
    def __init__(self, voice: str, assets: list[str]):
        self.voice = voice
        self.assets = assets
        super().__init__(f"Model setup required for {voice}: {', '.join(assets)}")


def voice_asset_ids(voice: str) -> tuple[str, ...]:
    for language, entry in LANGUAGES.items():
        if voice in entry["voices"]:
            return voice_assets(language, voice)
    raise ValueError(f"Unsupported voice: {voice}")


def local_voice_paths(voice: str) -> dict[str, Path]:
    required = voice_asset_ids(voice)
    # Only the catalog's verified state authorizes an engine to open a file.
    missing = [asset_id for asset_id in required
               if ASSETS[asset_id].inventory(config.models_dir)["state"] != "verified"]
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
