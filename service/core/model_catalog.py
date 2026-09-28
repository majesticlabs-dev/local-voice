"""Bounded language catalog. File sizes are upstream repository metadata, not disk estimates.

No asset is downloaded or loaded by this module. Integrity hashes are not yet frozen;
file presence alone cannot authorize synthesis or removal.
"""
from dataclasses import dataclass
from pathlib import Path

from .config import config

KOKORO_SOURCE = "https://huggingface.co/hexgrad/Kokoro-82M"
PIPER_SOURCE = "https://huggingface.co/rhasspy/piper-voices"
SPACY_SOURCE = "https://github.com/explosion/spacy-models/releases/tag/en_core_web_sm-3.8.0"


@dataclass(frozen=True)
class Asset:
    id: str
    path: str
    size_bytes: int | None
    source: str
    revision: str | None
    license: str | None
    sha256: str | None = None

    def inventory(self, root: Path) -> dict:
        path = root / self.path
        # Refuse symlinks at every component, including the data root. Do not
        # follow user-controlled links while inspecting a shared model store.
        components = (root, *[root.joinpath(*Path(self.path).parts[:i]) for i in range(1, len(Path(self.path).parts) + 1)])
        safe = not any(part.is_symlink() for part in components)
        try:
            size = path.stat().st_size if safe and path.is_file() else None
        except OSError:
            size = None
        return {
            "id": self.id,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "source": self.source,
            "revision": self.revision,
            "license": self.license,
            "sha256": self.sha256,
            "state": "absent" if size is None else (
                "present_unverified" if self.size_bytes == size else "invalid"
            ),
        }


_ASSETS = (
    Asset("kokoro-config", "kokoro/config.json", 2351, KOKORO_SOURCE, None, "Apache-2.0"),
    Asset("kokoro-weights", "kokoro/kokoro-v1_0.pth", 327212226, KOKORO_SOURCE, None, "Apache-2.0"),
    Asset("spacy-en-core-web-sm", "spacy/en_core_web_sm-3.8.0-py3-none-any.whl", 12806118, SPACY_SOURCE, "3.8.0", None),
    *(
        Asset(f"kokoro-{voice}", f"kokoro/voices/{voice}.pt", size, KOKORO_SOURCE, None, "Apache-2.0")
        for voice, size in (
            ("af_bella", 523425), ("af_sarah", 523425), ("am_adam", 523420),
            ("am_michael", 523435), ("bf_emma", 523420), ("bm_george", 523430),
            ("ef_dora", 523420), ("em_alex", 523420), ("em_santa", 523430),
        )
    ),
    Asset("piper-dmitri-onnx", "piper/ru_RU-dmitri-medium.onnx", 63201294, PIPER_SOURCE, "v1.0.0", "CC0"),
    Asset("piper-dmitri-config", "piper/ru_RU-dmitri-medium.onnx.json", 4824, PIPER_SOURCE, "v1.0.0", "CC0"),
)
ASSETS = {asset.id: asset for asset in _ASSETS}
COMMON_KOKORO = ("kokoro-config", "kokoro-weights")

LANGUAGES = {
    "en": {
        "label": "English", "engine": "kokoro", "assets": (*COMMON_KOKORO, "spacy-en-core-web-sm"),
        "voices": {
            "af_bella": "Bella", "af_sarah": "Sarah", "am_adam": "Adam",
            "am_michael": "Michael", "bf_emma": "Emma (British)", "bm_george": "George (British)",
        },
    },
    "es": {
        "label": "Spanish", "engine": "kokoro", "assets": COMMON_KOKORO,
        "voices": {"ef_dora": "Dora", "em_alex": "Alex", "em_santa": "Santa"},
    },
    "ru": {
        "label": "Russian", "engine": "piper", "assets": (),
        "voices": {"ru_RU-dmitri-medium": "Dmitri"},
    },
}


def voice_assets(language: str, voice: str) -> tuple[str, ...]:
    if language == "ru":
        return ("piper-dmitri-onnx", "piper-dmitri-config")
    return (*LANGUAGES[language]["assets"], f"kokoro-{voice}")


def catalog(root: Path | None = None) -> dict:
    root = root if root is not None else config.models_dir
    assets = {key: asset.inventory(root) for key, asset in ASSETS.items()}
    languages = []
    for code, entry in LANGUAGES.items():
        voices = []
        for voice, label in entry["voices"].items():
            required = voice_assets(code, voice)
            voices.append({"id": voice, "label": label, "assets": required,
                           "installed": all(assets[key]["state"] == "verified" for key in required)})
        required = sorted({key for voice in voices for key in voice["assets"]})
        languages.append({"id": code, "label": entry["label"], "engine": entry["engine"],
                          "assets": required, "voices": voices,
                          "installed": all(voice["installed"] for voice in voices)})
    return {"languages": languages, "assets": list(assets.values())}
