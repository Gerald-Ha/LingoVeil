from __future__ import annotations
import os
import sys

from dataclasses import dataclass
from pathlib import Path
APP_DIR_NAME = "lingoveil"
APP_DISPLAY_NAME = "LingoVeil"
def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]
def is_frozen() -> bool:
    return getattr(sys, "frozen", False) is True
def is_dev_mode() -> bool:
    env = os.environ.get("LINGOVEIL_DEV_MODE", "").strip().lower()

    if env in {"1", "true", "yes", "on"}:
        return True
    root = _project_root()

    return (root / "src" / "lingoveil_config.py").is_file() and (root / "config").is_dir()

def _xdg_dir(env_name: str, default: Path) -> Path:
    value = os.environ.get(env_name, "").strip()

    return Path(value).expanduser() if value else default
@dataclass(frozen=True)

class AppPaths:
    project_root: Path
    runtime_root: Path
    config_dir: Path
    data_dir: Path
    cache_dir: Path
    models_dir: Path
    resources_dir: Path
    downloads_dir: Path
    tmp_dir: Path
    settings_file: Path
    logs_dir: Path
    desktop_entry_dir: Path
    def ensure_dirs(self) -> None:
        for path in (
            self.config_dir,
            self.data_dir,
            self.cache_dir,
            self.models_dir,
            self.resources_dir,
            self.downloads_dir,
            self.tmp_dir,
            self.logs_dir,
            self.desktop_entry_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

def build_app_paths() -> AppPaths:
    project_root = _project_root()

    runtime_root = Path(getattr(sys, "_MEIPASS", project_root)).resolve() if is_frozen() else project_root
    config_home = _xdg_dir("XDG_CONFIG_HOME", Path.home() / ".config")

    data_home = _xdg_dir("XDG_DATA_HOME", Path.home() / ".local" / "share")

    cache_home = _xdg_dir("XDG_CACHE_HOME", Path.home() / ".cache")

    state_home = _xdg_dir("XDG_STATE_HOME", Path.home() / ".local" / "state")

    if is_dev_mode():
        config_dir = project_root / "config"
        data_dir = project_root
        cache_dir = project_root / "artifacts"
        models_dir = project_root / "models"
        resources_dir = project_root / "resources"
        downloads_dir = cache_dir / "downloads"
        tmp_dir = cache_dir / "tmp"
        logs_dir = cache_dir / "logs"
        desktop_entry_dir = project_root / "packaging"
    else:
        config_dir = config_home / APP_DIR_NAME
        data_dir = data_home / APP_DIR_NAME
        cache_dir = cache_home / APP_DIR_NAME
        models_dir = data_dir / "models"
        resources_dir = data_dir / "resources"
        downloads_dir = cache_dir / "downloads"
        tmp_dir = cache_dir / "tmp"
        logs_dir = state_home / APP_DIR_NAME / "logs"
        desktop_entry_dir = data_dir / "desktop"
    return AppPaths(
        project_root=project_root,
        runtime_root=runtime_root,
        config_dir=config_dir,
        data_dir=data_dir,
        cache_dir=cache_dir,
        models_dir=models_dir,
        resources_dir=resources_dir,
        downloads_dir=downloads_dir,
        tmp_dir=tmp_dir,
        settings_file=config_dir / "settings.json",
        logs_dir=logs_dir,
        desktop_entry_dir=desktop_entry_dir,
    )

def diagnostics() -> dict[str, str]:
    paths = build_app_paths()

    return {
        "project_root": str(paths.project_root),
        "runtime_root": str(paths.runtime_root),
        "config_dir": str(paths.config_dir),
        "data_dir": str(paths.data_dir),
        "cache_dir": str(paths.cache_dir),
        "models_dir": str(paths.models_dir),
        "resources_dir": str(paths.resources_dir),
        "downloads_dir": str(paths.downloads_dir),
        "tmp_dir": str(paths.tmp_dir),
        "logs_dir": str(paths.logs_dir),
        "settings_file": str(paths.settings_file),
        "dev_mode": str(is_dev_mode()),
        "frozen": str(is_frozen()),
    }
