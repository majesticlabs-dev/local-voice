"""Silent, isolated inference check for an installed voice.

Usage: python -m service.voice_probe <voice-id>
"""
import os
from pathlib import Path
import subprocess
import sys


def probe(voice):
    from .core.model_catalog import LANGUAGES
    if not any(voice in entry["voices"] for entry in LANGUAGES.values()):
        print("Unknown voice", file=sys.stderr)
        return 2
    try:
        result = subprocess.run([sys.executable, "-m", "service.voice_probe", "--child", voice],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=90)
    except subprocess.TimeoutExpired:
        print("Voice probe timed out", file=sys.stderr)
        return 1
    if result.returncode:
        print("Voice probe failed (child process exited without audio)", file=sys.stderr)
        return 1
    print("Voice produced audio")
    return 0


def child(voice):
    from .app import get_provider
    audio = get_provider().synthesize("Hello.", voice, 1.0, "wav")
    return 0 if isinstance(audio, bytes) and len(audio) > 0 else 1


def packaged_paths():
    # The installed launcher is on PYTHONPATH; no service startup or token creation.
    from service_launcher import asset_directories
    home = Path.home()
    cache = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
    models, output, cache_dir = asset_directories(home, cache)
    os.environ.update(LV_MODELS_DIR=str(models), LV_OUTPUT_DIR=str(output), LV_CACHE_DIR=str(cache_dir))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "--packaged":
        packaged_paths()
        return probe(argv[1])
    if len(argv) == 2 and argv[0] == "--child":
        return child(argv[1])
    if len(argv) != 1:
        print("Usage: python -m service.voice_probe <voice-id>", file=sys.stderr)
        return 2
    return probe(argv[0])


if __name__ == "__main__":
    sys.exit(main())
