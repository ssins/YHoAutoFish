import shutil
import sys
from pathlib import Path


def _is_frozen_app():
    return bool(getattr(sys, "frozen", False) or "__compiled__" in globals())


def app_base_dir():
    if _is_frozen_app():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_path(*parts):
    bundle_dir = getattr(sys, "_MEIPASS", None)
    base = Path(bundle_dir).resolve() if bundle_dir else app_base_dir()
    return str(base.joinpath(*parts))


def writable_path(*parts):
    return str(app_base_dir().joinpath(*parts))


def ensure_writable_file(filename):
    target = Path(writable_path(filename))
    source = Path(resource_path(filename))
    if not target.exists() and source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
    return str(target)
