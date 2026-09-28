"""Silent, isolated inference check for an installed voice.

Usage: python -m service.voice_probe <voice-id>
"""
import subprocess
import sys

from .core.model_catalog import LANGUAGES


def probe(voice):
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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "--child":
        return child(argv[1])
    if len(argv) != 1:
        print("Usage: python -m service.voice_probe <voice-id>", file=sys.stderr)
        return 2
    return probe(argv[0])


if __name__ == "__main__":
    sys.exit(main())
