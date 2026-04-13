import os
import shutil
from pathlib import Path


COMMON_EXECUTABLE_DIRS = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
    Path("/usr/bin"),
    Path("/bin"),
)


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _candidate_executable_dirs() -> list[Path]:
    dirs: list[Path] = []
    path_value = os.getenv("PATH")
    if path_value:
        dirs.extend(Path(entry).expanduser() for entry in path_value.split(os.pathsep) if entry)

    dirs.extend(COMMON_EXECUTABLE_DIRS)

    home = Path.home()
    dirs.extend(
        [
            home / ".local" / "bin",
            home / ".cargo" / "bin",
        ]
    )

    unique_dirs: list[Path] = []
    seen: set[Path] = set()
    for directory in dirs:
        expanded = directory.expanduser()
        if expanded in seen:
            continue
        seen.add(expanded)
        unique_dirs.append(expanded)
    return unique_dirs


def resolve_executable(name: str, env_var: str | None = None) -> Path | None:
    if env_var:
        configured = os.getenv(env_var)
        if configured:
            candidate = Path(configured).expanduser()
            if _is_executable(candidate):
                return candidate.resolve()

    resolved = shutil.which(name)
    if resolved:
        return Path(resolved).resolve()

    for directory in _candidate_executable_dirs():
        candidate = directory / name
        if _is_executable(candidate):
            return candidate.resolve()

    return None


def provider_dependency_status(
    *,
    provider_name: str,
    model_name: str,
    ready: bool,
    error: Exception | None = None,
) -> dict[str, object]:
    if error is not None:
        detail = f"{provider_name} failed to initialize: {error}"
    elif ready:
        detail = f"{provider_name} engine ready"
        if model_name:
            detail += f" ({model_name})"
    else:
        detail = f"{provider_name} engine is installed but not ready yet"

    return {
        "name": provider_name,
        "available": error is None and ready,
        "required": True,
        "detail": detail,
        "location": None,
    }


def ffmpeg_dependency_status() -> dict[str, object]:
    ffmpeg = resolve_executable("ffmpeg", env_var="LV_FFMPEG_PATH")
    if ffmpeg is not None:
        return {
            "name": "ffmpeg",
            "available": True,
            "required": True,
            "detail": f"MP3 support ready ({ffmpeg})",
            "location": str(ffmpeg),
        }

    return {
        "name": "ffmpeg",
        "available": False,
        "required": True,
        "detail": (
            "ffmpeg is required for MP3 synthesis and export. "
            "Checked PATH plus common Homebrew locations. "
            "Install it with brew install ffmpeg. "
            "If the desktop app still cannot find it, set a custom ffmpeg path in app settings. "
            "Standalone service runs can also use LV_FFMPEG_PATH."
        ),
        "location": None,
    }


def runtime_dependencies(
    *,
    provider_name: str,
    model_name: str,
    provider_ready: bool,
    provider_error: Exception | None = None,
) -> list[dict[str, object]]:
    return [
        provider_dependency_status(
            provider_name=provider_name,
            model_name=model_name,
            ready=provider_ready,
            error=provider_error,
        ),
        ffmpeg_dependency_status(),
    ]
