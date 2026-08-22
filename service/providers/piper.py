import logging
import os
import tempfile
import threading
import urllib.request
from pathlib import Path

from .base import TTSProvider
from ..core.audio import wav_from_pcm, convert_to_mp3
from ..core.config import config

logger = logging.getLogger(__name__)

# Piper voices are hosted on HuggingFace; downloaded on first use.
HF_VOICES_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"


def _models_dir() -> Path:
    return config.models_dir / "piper"

# espeak-ng keeps its data directory in a fixed-size internal buffer (~160
# bytes). Longer paths are silently rejected and espeak falls back to the
# wheel's compile-time build path (a nonexistent CI path), then exits the
# process. Deep app-bundle install paths can exceed the limit, so in that case
# we hand espeak a short symlink to the same directory instead.
_ESPEAK_MAX_PATH = 140
_espeak_dir_lock = threading.Lock()


def _espeak_data_dir() -> str:
    """Data dir espeak-ng can actually use; see _ESPEAK_MAX_PATH."""
    from piper.phonemize_espeak import ESPEAK_DATA_DIR

    if len(str(ESPEAK_DATA_DIR)) < _ESPEAK_MAX_PATH:
        return str(ESPEAK_DATA_DIR)

    with _espeak_dir_lock:
        link = Path(tempfile.gettempdir()) / "local-voice-espeak-ng-data"
        try:
            try:
                if link.is_symlink() and link.resolve() == ESPEAK_DATA_DIR.resolve():
                    return str(link)
                link.unlink()
            except FileNotFoundError:
                pass
            link.symlink_to(ESPEAK_DATA_DIR, target_is_directory=True)
            return str(link)
        except OSError:
            logger.warning("Could not shorten espeak data path", exc_info=True)
            return str(ESPEAK_DATA_DIR)

# voice id -> (label, gender, path under HF_VOICES_BASE)
RUSSIAN_VOICES = {
    "ru_RU-irina-medium": (
        "Irina (Russian)",
        "f",
        "ru/ru_RU/irina/medium/ru_RU-irina-medium",
    ),
    "ru_RU-dmitri-medium": (
        "Dmitri (Russian)",
        "m",
        "ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium",
    ),
    "ru_RU-ruslan-medium": (
        "Ruslan (Russian)",
        "m",
        "ru/ru_RU/ruslan/medium/ru_RU-ruslan-medium",
    ),
}

_voices: dict = {}
_voice_locks: dict[str, threading.Lock] = {}
_voice_locks_guard = threading.Lock()


def _lock_for(voice_id: str) -> threading.Lock:
    with _voice_locks_guard:
        lock = _voice_locks.get(voice_id)
        if lock is None:
            lock = threading.Lock()
            _voice_locks[voice_id] = lock
        return lock


def _download_file(url: str, dest: Path) -> None:
    """Atomic via .part rename: a truncated file must never look complete."""
    part_path = Path(f"{dest}.part")
    try:
        with urllib.request.urlopen(url, timeout=30) as response, part_path.open("wb") as fh:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
        os.replace(part_path, dest)
    except BaseException:
        part_path.unlink(missing_ok=True)
        raise


def _ensure_model_files(voice_id: str) -> Path:
    """Download the ONNX model and its JSON config if missing. Returns the
    local model path."""
    if voice_id not in RUSSIAN_VOICES:
        raise ValueError(f"Unknown Piper voice: {voice_id}")

    hf_path = RUSSIAN_VOICES[voice_id][2]
    models_dir = _models_dir()
    model_path = models_dir / f"{voice_id}.onnx"
    config_path = models_dir / f"{voice_id}.onnx.json"

    models_dir.mkdir(parents=True, exist_ok=True)
    for url_suffix, local_path in (
        (f"{hf_path}.onnx", model_path),
        (f"{hf_path}.onnx.json", config_path),
    ):
        if local_path.exists():
            continue
        url = f"{HF_VOICES_BASE}/{url_suffix}"
        logger.info("Downloading Piper voice %s from %s", voice_id, url)
        _download_file(url, local_path)

    return model_path


def _load_voice(voice_id: str):
    # /stream synthesizes in background threads; serialize per-voice so
    # concurrent requests cannot race on the download or the cache dict.
    with _lock_for(voice_id):
        if voice_id in _voices:
            return _voices[voice_id]

        try:
            from piper import PiperVoice
        except ImportError:
            logger.warning("piper-tts package not installed — run: pip install piper-tts")
            raise

        model_path = _ensure_model_files(voice_id)
        voice = PiperVoice.load(
            model_path,
            download_dir=model_path.parent,
            espeak_data_dir=_espeak_data_dir(),
        )
        _voices[voice_id] = voice
        logger.info("Piper voice loaded: %s", voice_id)
        return voice


class PiperProvider(TTSProvider):
    name = "piper"
    model_name = "piper-voices"

    def owns_voice(self, voice: str) -> bool:
        return voice.startswith("ru_")

    def is_ready(self) -> bool:
        try:
            import piper  # noqa: F401
            return True
        except (Exception, SystemExit):
            return False

    def list_voices(self) -> list[dict]:
        return [
            {
                "id": voice_id,
                "label": label,
                "language": "ru",
                "gender": gender,
                "sample_rate": 22050,
            }
            for voice_id, (label, gender, _path) in RUSSIAN_VOICES.items()
        ]

    def synthesize(
        self, text: str, voice: str, rate: float, audio_format: str
    ) -> bytes:
        from piper import SynthesisConfig

        piper_voice = _load_voice(voice)

        # Piper speeds up when length_scale shrinks; invert the rate.
        voice_cfg = piper_voice.config
        syn_config = SynthesisConfig(
            length_scale=(getattr(voice_cfg, "length_scale", None) or 1.0) / rate
        )
        for attr in ("noise_scale", "noise_w_scale"):
            value = getattr(voice_cfg, attr, None)
            if value is not None:
                setattr(syn_config, attr, value)

        pcm_bytes = b"".join(
            chunk.audio_int16_bytes
            for chunk in piper_voice.synthesize(text, syn_config)
        )
        if not pcm_bytes:
            raise RuntimeError("Piper produced no audio output")

        wav_data = wav_from_pcm(pcm_bytes, sample_rate=voice_cfg.sample_rate)

        if audio_format == "mp3":
            return convert_to_mp3(wav_data)
        return wav_data

    def cancel(self, job_id: str) -> None:
        # Piper runs synchronously per call — cancellation handled at job layer
        pass
