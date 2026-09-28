"""Bounded language catalog. File sizes are upstream repository metadata, not disk estimates.

No asset is downloaded or loaded by this module. Digests are pinned to upstream
revisions; inventory verifies file content rather than trusting file size.
"""
from dataclasses import dataclass
import hashlib
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
    upstream_path: str | None = None

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
        try:
            state = "absent" if size is None else (
                "invalid" if self.size_bytes != size else (
                    "verified" if self.sha256 and _digest(path) == self.sha256 else
                    "present_unverified" if not self.sha256 else "invalid"
                )
            )
        except OSError:
            state = "invalid"
        return {
            "id": self.id,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "source": self.source,
            "revision": self.revision,
            "license": self.license,
            "sha256": self.sha256,
            "state": state,
        }


def _digest(path: Path) -> str:
    hash_value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hash_value.update(block)
    return hash_value.hexdigest()


KOKORO_REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"
PIPER_REVISION = "375a0fe641dea077c2a47b4e9a056d6da521eed3"
VOICE_DIGESTS = {
    "af_bella": "8cb64e02fcc8de0327a8e13817e49c76c945ecf0052ceac97d3081480e8e48d6",
    "af_sarah": "49bd364ea3be9eb3e9685e8f9a15448c4883112a7c0ff7ab139fa4088b08cef9",
    "am_adam": "ced7e284aba12472891be1da3ab34db84cc05cc02b5889535796dbf2d8b0cb34",
    "am_michael": "9a443b79a4b22489a5b0ab7c651a0bcd1a30bef675c28333f06971abbd47bd37",
    "bf_emma": "d0a423deabf4a52b4f49318c51742c54e21bb89bbbe9a12141e7758ddb5da701",
    "bm_george": "f1bc812213dc59774769e5c80004b13eeb79bd78130b11b2d7f934542dab811b",
    "ef_dora": "d9d69b0f8a2b87a345f269d89639f89dfbd1a6c9da0c498ae36dd34afcf35530",
    "em_alex": "5eac53f767c3f31a081918ba531969aea850bed18fe56419b804d642c6973431",
    "em_santa": "aa8620cb96cec705823efca0d956a63e158e09ad41aca934d354b7f0778f63cb",
}

_ASSETS = (
    Asset("kokoro-config", "kokoro/config.json", 2351, KOKORO_SOURCE, KOKORO_REVISION, "Apache-2.0", "5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f", "config.json"),
    Asset("kokoro-weights", "kokoro/kokoro-v1_0.pth", 327212226, KOKORO_SOURCE, KOKORO_REVISION, "Apache-2.0", "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4", "kokoro-v1_0.pth"),
    Asset("spacy-en-core-web-sm", "spacy/en_core_web_sm-3.8.0-py3-none-any.whl", 12806118, SPACY_SOURCE, "en_core_web_sm-3.8.0", None, None, "en_core_web_sm-3.8.0-py3-none-any.whl"),
    *(
        Asset(f"kokoro-{voice}", f"kokoro/voices/{voice}.pt", size, KOKORO_SOURCE, KOKORO_REVISION, "Apache-2.0", VOICE_DIGESTS[voice], f"voices/{voice}.pt")
        for voice, size in (
            ("af_bella", 523425), ("af_sarah", 523425), ("am_adam", 523420),
            ("am_michael", 523435), ("bf_emma", 523420), ("bm_george", 523430),
            ("ef_dora", 523420), ("em_alex", 523420), ("em_santa", 523430),
        )
    ),
    Asset("piper-dmitri-onnx", "piper/ru_RU-dmitri-medium.onnx", 63201294, PIPER_SOURCE, PIPER_REVISION, "CC0", "f073356ebc4bd0f80c5af58df2953a5988bd5bdab1eb38635ce960b071fbefcb", "ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium.onnx"),
    Asset("piper-dmitri-config", "piper/ru_RU-dmitri-medium.onnx.json", 4824, PIPER_SOURCE, PIPER_REVISION, "CC0", "667ef3117bc642c2892dff7690d8bdc8ca4228aeaa783b2dc1416df632855e0d", "ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium.onnx.json"),
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
