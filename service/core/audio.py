import io
import struct
import subprocess
import tempfile
from pathlib import Path

from .dependencies import resolve_executable


def wav_from_pcm(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
    buf = io.BytesIO()
    data_size = len(pcm_data)
    buf.write(b'RIFF')
    buf.write(struct.pack('<I', 36 + data_size))
    buf.write(b'WAVE')
    buf.write(b'fmt ')
    buf.write(struct.pack('<I', 16))
    buf.write(struct.pack('<H', 1))  # PCM
    buf.write(struct.pack('<H', channels))
    buf.write(struct.pack('<I', sample_rate))
    buf.write(struct.pack('<I', sample_rate * channels * sample_width))
    buf.write(struct.pack('<H', channels * sample_width))
    buf.write(struct.pack('<H', sample_width * 8))
    buf.write(b'data')
    buf.write(struct.pack('<I', data_size))
    buf.write(pcm_data)
    return buf.getvalue()


def convert_to_mp3(wav_data: bytes) -> bytes:
    ffmpeg = resolve_executable("ffmpeg", env_var="LV_FFMPEG_PATH")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found — install it for mp3 output or set a custom ffmpeg path")
    proc = subprocess.run(
        [str(ffmpeg), "-i", "pipe:0", "-f", "mp3", "-ab", "128k", "-y", "pipe:1"],
        input=wav_data,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {proc.stderr.decode()}")
    return proc.stdout


def concat_audio_files(audio_files: list[Path], output_format: str = "mp3") -> bytes:
    if not audio_files:
        raise RuntimeError("No audio files to concatenate")

    if len(audio_files) == 1:
        source = audio_files[0]
        if source.suffix.lstrip(".") == output_format:
            return source.read_bytes()
        if source.suffix.lstrip(".") == "wav" and output_format == "mp3":
            return convert_to_mp3(source.read_bytes())

    ffmpeg = resolve_executable("ffmpeg", env_var="LV_FFMPEG_PATH")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found — install it for mp3 output or set a custom ffmpeg path")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as manifest:
        for audio_file in audio_files:
            escaped = str(audio_file).replace("'", "'\\''")
            manifest.write(f"file '{escaped}'\n")
        manifest_path = manifest.name

    codec_args = ["-c:a", "libmp3lame", "-b:a", "128k"] if output_format == "mp3" else ["-c", "copy"]
    try:
        proc = subprocess.run(
            [
                str(ffmpeg),
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                manifest_path,
                *codec_args,
                "-f",
                output_format,
                "-y",
                "pipe:1",
            ],
            capture_output=True,
        )
    finally:
        Path(manifest_path).unlink(missing_ok=True)

    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {proc.stderr.decode()}")
    return proc.stdout
