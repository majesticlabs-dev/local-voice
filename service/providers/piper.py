import importlib.util
import logging
import tempfile
import threading
from pathlib import Path

from .base import TTSProvider
from ..core.audio import wav_from_pcm, convert_to_mp3
from ..core.setup import local_voice_paths, has_local_voice

logger = logging.getLogger(__name__)

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
    "ru_RU-dmitri-medium": ("Dmitri (Russian)", "m"),
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


def _load_voice(voice_id: str):
    paths = local_voice_paths(voice_id)
    # /stream synthesizes in background threads; serialize per-voice loading.
    with _lock_for(voice_id):
        if voice_id in _voices:
            return _voices[voice_id]

        try:
            from piper import PiperVoice
        except ImportError:
            logger.warning("piper-tts package not installed — run: pip install piper-tts")
            raise

        voice = PiperVoice.load(
            paths["piper-dmitri-onnx"],
            config_path=paths["piper-dmitri-config"],
            download_dir=paths["piper-dmitri-onnx"].parent,
            espeak_data_dir=_espeak_data_dir(),
        )
        _voices[voice_id] = voice
        logger.info("Piper voice loaded: %s", voice_id)
        return voice


class PiperProvider(TTSProvider):
    name = "piper"
    model_name = "piper-voices"

    def owns_voice(self, voice: str) -> bool:
        return voice in RUSSIAN_VOICES

    def is_ready(self) -> bool:
        return importlib.util.find_spec("piper") is not None and has_local_voice(self.name)

    def list_voices(self) -> list[dict]:
        return [
            {
                "id": voice_id,
                "label": label,
                "language": "ru",
                "gender": gender,
                "sample_rate": 22050,
            }
            for voice_id, (label, gender) in RUSSIAN_VOICES.items()
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
