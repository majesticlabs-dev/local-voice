"""Entry point for the packaged user service. Never downloads model assets."""
import os
from pathlib import Path
import secrets
import stat


def prepare(home: Path, runtime: Path, cache: Path) -> Path:
    data = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")) / "dev.majesticlabs.localvoice"
    models = data / "service-models"
    output = data / "service-output"
    cache_dir = cache / "dev.majesticlabs.localvoice/service-cache"
    if data.is_symlink():
        raise RuntimeError("Refusing symlink data directory")
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(data, 0o700)
    for directory in (models, output, cache_dir, runtime):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    token_file = data / "management-token"
    if token_file.is_symlink():
        raise RuntimeError("Refusing symlink management token")
    try:
        fd = os.open(token_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as file:
            file.write(secrets.token_hex(32))
    info = token_file.stat()
    if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise RuntimeError("Management token must be a private regular file owned by this user")
    token = token_file.read_text().strip()
    if len(token) != 64 or any(ch not in "0123456789abcdef" for ch in token):
        raise RuntimeError("Invalid management token")
    os.environ.update(
        LV_HOST="127.0.0.1", LV_PORT="5517", LV_MODELS_DIR=str(models),
        LV_OUTPUT_DIR=str(output), LV_CACHE_DIR=str(cache_dir),
        LV_MANAGEMENT_TOKEN=token,
    )
    return data


if __name__ == "__main__":
    home = Path.home()
    runtime = Path(os.environ["XDG_RUNTIME_DIR"]) / "local-voice"
    cache = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
    prepare(home, runtime, cache)
    root = Path(__file__).resolve().parent
    os.chdir(root)
    import uvicorn
    uvicorn.run("service.app:app", host="127.0.0.1", port=5517, workers=1)
