import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yml"
DEFAULT_CACHE_DIR = Path(__file__).parent.parent / "artifacts" / "cache"
DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "artifacts" / "output"


def _load_yaml_config() -> dict:
    config_path = Path(os.getenv("LV_CONFIG_FILE", DEFAULT_CONFIG_PATH))
    if not config_path.exists():
        return {}

    with config_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 5517
    engine: str = "kokoro"
    default_voice: str = "af_bella"
    default_rate: float = 1.0
    default_format: str = "mp3"
    max_input_length: int = 50000
    desktop_api_host: str = "127.0.0.1"
    desktop_server_mode_host: str = "0.0.0.0"
    desktop_chunk_threshold: int = 800
    cache_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "artifacts" / "cache")
    output_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "artifacts" / "output")
    cache_ttl_seconds: int = 3600
    allowed_origins: list[str] = field(default_factory=lambda: [
        "chrome-extension://*",
    ])

    @classmethod
    def from_env(cls) -> "Config":
        payload = _load_yaml_config()
        service = payload.get("service") or {}
        desktop = payload.get("desktop") or {}

        return cls(
            host=os.getenv("LV_HOST", str(service.get("host", "127.0.0.1"))),
            port=int(os.getenv("LV_PORT", str(service.get("port", "5517")))),
            engine=os.getenv("LV_ENGINE", str(service.get("engine", "kokoro"))),
            default_voice=os.getenv("LV_VOICE", str(service.get("default_voice", "af_bella"))),
            default_rate=float(service.get("default_rate", 1.0)),
            default_format=str(service.get("default_format", "mp3")),
            max_input_length=int(os.getenv("LV_MAX_INPUT", str(service.get("max_input_length", "50000")))),
            desktop_api_host=str(desktop.get("api_host", "127.0.0.1")),
            desktop_server_mode_host=str(desktop.get("server_mode_host", "0.0.0.0")),
            desktop_chunk_threshold=int(desktop.get("chunk_threshold", 800)),
            cache_dir=Path(os.getenv("LV_CACHE_DIR", str(DEFAULT_CACHE_DIR))).expanduser(),
            output_dir=Path(os.getenv("LV_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR))).expanduser(),
        )


config = Config.from_env()
