import logging
from pathlib import Path
import shutil
import tempfile

from .base import TTSProvider
from ..core.audio import wav_from_pcm, convert_to_mp3

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


def _prepare_espeak_data_root(data_path: Path) -> Path:
    direct_root = data_path.parent
    if " " not in str(direct_root):
        return direct_root

    staging_root = Path(tempfile.gettempdir()) / "local-voice-espeak"
    staging_data = staging_root / "espeak-ng-data"
    resolved_data_path = data_path.resolve()

    if staging_data.exists() or staging_data.is_symlink():
        try:
            if staging_data.resolve() == resolved_data_path:
                return staging_root
        except OSError:
            pass

        if staging_data.is_symlink() or staging_data.is_file():
            staging_data.unlink()
        else:
            shutil.rmtree(staging_data)

    staging_root.mkdir(parents=True, exist_ok=True)
    try:
        staging_data.symlink_to(resolved_data_path, target_is_directory=True)
    except OSError:
        shutil.copytree(resolved_data_path, staging_data)

    return staging_root


def _configure_espeak_backend() -> None:
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    data_root = _prepare_espeak_data_root(Path(espeakng_loader.get_data_path()))

    # phonemizer expects the parent directory that contains `espeak-ng-data`,
    # and espeak-ng fails to initialize when the prefix path contains spaces.
    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    EspeakWrapper.set_data_path(str(data_root))


def _load_kokoro(lang_code: str = DEFAULT_LANG_CODE):
    """Import kokoro once and return the pipeline for `lang_code`, creating it
    on first use. Pipelines are cached per language."""
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
        pipeline = _kokoro.KPipeline(lang_code=lang_code)
        _pipelines[lang_code] = pipeline
        logger.info("Kokoro pipeline loaded (lang_code=%s)", lang_code)
    return pipeline


class KokoroProvider(TTSProvider):
    name = "kokoro"
    model_name = "kokoro-82m"

    def is_ready(self) -> bool:
        try:
            _load_kokoro()
            return True
        except (Exception, SystemExit):
            # Some engine dependencies (e.g. spaCy model resolution) call
            # sys.exit() on failure, which raises SystemExit rather than
            # Exception. Treat that as "not ready" instead of crashing.
            return False

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
        pipeline = _load_kokoro(_lang_code_for_voice(voice))
        import numpy as np

        # samples is a numpy array of float32 [-1, 1]
        pcm = _collect_audio_samples(pipeline(text, voice=voice, speed=rate))
        pcm_int16 = (pcm * 32767).clip(-32768, 32767).astype(np.int16)
        pcm_bytes = pcm_int16.tobytes()

        wav_data = wav_from_pcm(pcm_bytes, sample_rate=24000)

        if audio_format == "mp3":
            return convert_to_mp3(wav_data)
        return wav_data

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
