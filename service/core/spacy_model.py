"""Activate the consented English spaCy wheel from the per-user model store."""
import importlib
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import zipfile

from . import model_catalog, model_lifecycle
from .config import config

ASSET_ID = "spacy-en-core-web-sm"
_active_path: Path | None = None


def deactivate() -> None:
    """Drop the import path and extracted copy before English is removed."""
    global _active_path
    with model_lifecycle._lock:
        if _active_path is not None:
            sys.path[:] = [path for path in sys.path if path != str(_active_path)]
            _active_path = None
            importlib.invalidate_caches()
        root = config.models_dir / "spacy"
        active = root / ".active"
        if active.is_symlink():
            raise ValueError("English model activation directory is a symlink")
        if active.exists():
            shutil.rmtree(active)


def activate() -> bool:
    """Expose only a hash-verified wheel as an installed Python distribution."""
    global _active_path
    with model_lifecycle._lock:
        from .model_downloads import _safe_path
        root = config.models_dir
        asset = model_catalog.ASSETS.get(ASSET_ID)
        if asset is None or asset.inventory(root)["state"] != "verified":
            deactivate()
            return False
        wheel = _safe_path(root, asset.path)
        if not wheel.is_file():
            deactivate()
            return False
        active = _safe_path(root, "spacy/.active")
        if _active_path is not None and _active_path != active:
            sys.path[:] = [path for path in sys.path if path != str(_active_path)]
            _active_path = None
        if not active.is_dir():
            active.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=".spacy-", dir=active.parent))
            try:
                with zipfile.ZipFile(wheel) as archive:
                    names = archive.namelist()
                    if ("en_core_web_sm/__init__.py" not in names or
                            not any(name.endswith(".dist-info/METADATA") and
                                    name.startswith("en_core_web_sm-3.8.0.dist-info/") for name in names)):
                        raise ValueError("Invalid English spaCy wheel layout")
                    if sum(info.file_size for info in archive.infolist()) > 256 * 1024 * 1024:
                        raise ValueError("English spaCy wheel exceeds extraction limit")
                    for info in archive.infolist():
                        path = PurePosixPath(info.filename)
                        if (path.is_absolute() or ".." in path.parts or
                                not path.parts or path.parts[0] == ".active" or
                                stat.S_ISLNK(info.external_attr >> 16)):
                            raise ValueError("Unsafe English spaCy wheel entry")
                        target = temporary.joinpath(*path.parts)
                        if info.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with archive.open(info) as source, target.open("xb") as output:
                                shutil.copyfileobj(source, output)
                temporary.rename(active)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        if str(active) not in sys.path:
            sys.path.insert(0, str(active))
        _active_path = active
        importlib.invalidate_caches()
        return True
