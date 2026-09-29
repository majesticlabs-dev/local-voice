import importlib.util
import logging
import os
from pathlib import Path
import shutil
import tempfile
import threading

from .base import TTSProvider
from ..core.audio import wav_from_pcm, convert_to_mp3
from ..core.config import config
from ..core.setup import local_voice_paths, has_local_voice, voice_asset_ids, SetupNeeded
from ..core import model_lifecycle

logger = logging.getLogger(__name__)

# Lazy import — kokoro may not be installed yet
_kokoro = None
_pipelines: dict = {}

DEFAULT_LANG_CODE = "a"

# Kokoro voice IDs are prefixed with their language code:
# a=en-US, b=en-GB, e=es, f=fr, h=hi, i=it, p=pt-BR.
# ja (j) and zh (z) are excluded: they need misaki[ja]/misaki[zh].
SUPPORTED_LANG_CODES = {"a", "b", "e", "f", "h", "i", "p"}


def _lang_code_for_voice(voice: str) -> str:
    code = (voice or "")[:1].lower()
    return code if code in SUPPORTED_LANG_CODES else DEFAULT_LANG_CODE


_espeak_staging: tempfile.TemporaryDirectory | None = None
_load_lock = threading.RLock()


def _prepare_espeak_data_root(data_path: Path) -> Path:
    global _espeak_staging
    direct_root = data_path.parent
    # The phonemizer fork resolves symlinks before calling espeak_Initialize.
    # espeak-ng truncates long paths in its internal buffer, then looks for
    # phontab in the wrong directory. A symlink alone cannot shorten that path.
    if " " not in str(direct_root) and len(os.fsencode(data_path)) < 100:
        return direct_root

    with _load_lock:
        if _espeak_staging is None:
            staging = tempfile.TemporaryDirectory(prefix="lv-espeak-")
            try:
                shutil.copytree(data_path, Path(staging.name) / "espeak-ng-data")
            except Exception:
                staging.cleanup()
                raise
            _espeak_staging = staging
        return Path(_espeak_staging.name)


def _configure_espeak_backend() -> None:
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    data_root = _prepare_espeak_data_root(Path(espeakng_loader.get_data_path()))

    # phonemizer expects the parent directory that contains `espeak-ng-data`,
    # and espeak-ng fails to initialize when the prefix path contains spaces.
    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    EspeakWrapper.set_data_path(str(data_root))


def _load_kokoro(lang_code: str = DEFAULT_LANG_CODE):
    """Return the cached pipeline, or initialize it under the shared lock."""
    with _load_lock:
        return _load_kokoro_locked(lang_code)


def _load_kokoro_locked(lang_code):
    global _kokoro
    if _kokoro is None:
        try:
            import kokoro

            _configure_espeak_backend()
            _kokoro = kokoro
        except ImportError:
            logger.warning("kokoro package not installed — run: pip install kokoro")
            raise
        except Exception as e:
            logger.error("Failed to initialize Kokoro: %s", e)
            raise

    pipeline = _pipelines.get(lang_code)
    if pipeline is None:
        # Misaki's English constructor calls spacy.cli.download when its
        # package is missing. Never enter that constructor in that state.
        if lang_code in ("a", "b"):
            from ..core import spacy_model
            import spacy.util
            if not spacy_model.activate() or not spacy.util.is_package("en_core_web_sm"):
                raise SetupNeeded("en", ["spacy-en-core-web-sm"])
        from kokoro import KModel
        root = config.models_dir / "kokoro"
        model = KModel(repo_id="hexgrad/Kokoro-82M",
                       config=str(root / "config.json"),
                       model=str(root / "kokoro-v1_0.pth"))
        pipeline = _kokoro.KPipeline(lang_code=lang_code, model=model,
                                     repo_id="hexgrad/Kokoro-82M")
        _pipelines[lang_code] = pipeline
        logger.info("Kokoro pipeline loaded (lang_code=%s)", lang_code)
    return pipeline


class KokoroProvider(TTSProvider):
    name = "kokoro"
    model_name = "kokoro-82m"

    def is_ready(self) -> bool:
        return importlib.util.find_spec("kokoro") is not None and has_local_voice(self.name)

    def list_voices(self) -> list[dict]:
        # Kokoro voices — return known defaults
        # Full list depends on installed voice packs
        return [
            {
                "id": "af_bella",
                "label": "Bella",
                "language": "en",
                "gender": "f",
                "sample_rate": 24000,
            },
            {
                "id": "af_sarah",
                "label": "Sarah",
                "language": "en",
                "gender": "f",
                "sample_rate": 24000,
            },
            {
                "id": "am_adam",
                "label": "Adam",
                "language": "en",
                "gender": "m",
                "sample_rate": 24000,
            },
            {
                "id": "am_michael",
                "label": "Michael",
                "language": "en",
                "gender": "m",
                "sample_rate": 24000,
            },
            {
                "id": "bf_emma",
                "label": "Emma (British)",
                "language": "en",
                "gender": "f",
                "sample_rate": 24000,
            },
            {
                "id": "bm_george",
                "label": "George (British)",
                "language": "en",
                "gender": "m",
                "sample_rate": 24000,
            },
            {
                "id": "ef_dora",
                "label": "Dora (Spanish)",
                "language": "es",
                "gender": "f",
                "sample_rate": 24000,
            },
            {
                "id": "em_alex",
                "label": "Alex (Spanish)",
                "language": "es",
                "gender": "m",
                "sample_rate": 24000,
            },
            {
                "id": "em_santa",
                "label": "Santa (Spanish)",
                "language": "es",
                "gender": "m",
                "sample_rate": 24000,
            },
        ]

    def synthesize(
        self, text: str, voice: str, rate: float, audio_format: str
    ) -> bytes:
        with model_lifecycle.using(set(voice_asset_ids(voice))):
            paths = local_voice_paths(voice)
            pipeline = _load_kokoro(_lang_code_for_voice(voice))
            # Passing the path (with .pt) bypasses Kokoro's HF voice loader.
            voice_path = str(paths[f"kokoro-{voice}"])
            import numpy as np

            # samples is a numpy array of float32 [-1, 1]
            pcm = _collect_audio_samples(pipeline(text, voice=voice_path, speed=rate))
            pcm_int16 = (pcm * 32767).clip(-32768, 32767).astype(np.int16)
            pcm_bytes = pcm_int16.tobytes()

            wav_data = wav_from_pcm(pcm_bytes, sample_rate=24000)

            if audio_format == "mp3":
                return convert_to_mp3(wav_data)
            return wav_data

    def release_assets(self, assets: set[str]) -> None:
        if any(key.startswith("kokoro-") or key == "spacy-en-core-web-sm" for key in assets):
            with _load_lock:
                _pipelines.clear()

    def cancel(self, job_id: str) -> None:
        # Kokoro runs synchronously per call — cancellation handled at job layer
        pass


def _collect_audio_samples(results) -> "numpy.ndarray":
    import numpy as np

    segments = []
    for result in results:
        audio = getattr(result, "audio", None)
        if audio is None:
            continue
        pcm = audio.cpu().numpy() if hasattr(audio, "cpu") else np.asarray(audio)
        if pcm.size:
            segments.append(pcm)

    if not segments:
        raise RuntimeError("Kokoro produced no audio output")

    return np.concatenate(segments)
