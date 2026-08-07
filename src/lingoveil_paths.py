from __future__ import annotations
import os
import sys

from pathlib import Path
APP_NAME = "lingoveil"
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent
def is_dev_mode() -> bool:
    pass
    configured = os.environ.get("LINGOVEIL_DEV_MODE", "").strip().lower()

    if configured:
        return configured in ("1", "true", "yes")

    root = project_root()

    marker = root / "src" / "lingoveil_config.py"
    return marker.is_file() and (root / "config").is_dir()

def xdg_config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()

    if base:
        return Path(base).expanduser() / APP_NAME
    return Path.home() / ".config" / APP_NAME
def xdg_data_home() -> Path:
    base = os.environ.get("XDG_DATA_HOME", "").strip()

    if base:
        return Path(base).expanduser() / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME
def xdg_cache_home() -> Path:
    base = os.environ.get("XDG_CACHE_HOME", "").strip()

    if base:
        return Path(base).expanduser() / APP_NAME
    return Path.home() / ".cache" / APP_NAME
def xdg_state_home() -> Path:
    base = os.environ.get("XDG_STATE_HOME", "").strip()

    if base:
        return Path(base).expanduser() / APP_NAME
    return Path.home() / ".local" / "state" / APP_NAME
def config_dir() -> Path:
    if is_dev_mode():
        return project_root() / "config"
    return xdg_config_home()

def data_dir() -> Path:
    if is_dev_mode():
        return project_root()

    return xdg_data_home()

def cache_dir() -> Path:
    if is_dev_mode():
        return project_root() / "artifacts"
    return xdg_cache_home()

def state_dir() -> Path:
    return xdg_state_home()

def models_data_dir() -> Path:
    if is_dev_mode():
        return project_root() / "models"
    return xdg_data_home() / "models"
def tools_data_dir() -> Path:
    if is_dev_mode():
        return project_root() / "tools"
    return xdg_data_home() / "tools"
def licenses_data_dir() -> Path:
    if is_dev_mode():
        return project_root() / "LICENSES"
    return xdg_data_home() / "licenses"
def env_file_path() -> Path:
    if is_dev_mode():
        return project_root() / "config" / "lingoveil.env"
    return xdg_config_home() / "lingoveil.env"
def translation_cache_path() -> Path:
    if is_dev_mode():
        return project_root() / "config" / "translation_cache.json"
    return xdg_cache_home() / "translation_cache.json"
def browser_cache_dir() -> Path:
    base = cache_dir() / "browser"
    base.mkdir(parents=True, exist_ok=True)

    return base
def browser_session_dir(session_id: str) -> Path:
    path = browser_cache_dir() / session_id
    path.mkdir(parents=True, exist_ok=True)

    return path
def browser_artifacts_dir() -> Path:
    path = browser_cache_dir()

    if is_dev_mode():
        path = project_root() / "artifacts" / "browser"
    path.mkdir(parents=True, exist_ok=True)

    return path
BROWSER_ARTIFACT_FILENAMES = (
    "browser_latest.json",
    "browser_rendered_latest.png",
    "browser_input_latest.png",
    "browser_pdf_page_latest.png",
)

def clear_browser_artifacts() -> int:
    pass
    removed = 0
    directory = browser_artifacts_dir()

    for name in BROWSER_ARTIFACT_FILENAMES:
        path = directory / name
        if not path.is_file():
            continue
        try:
            path.unlink()

            removed += 1
        except OSError:
            pass
    return removed
def seamless_model_dir(configured_dir: str = "") -> Path:
    if configured_dir.strip():
        return Path(configured_dir).expanduser().resolve()

    live_models = os.environ.get("LINGOVEIL_LIVE_MODELS_DIR", "").strip()

    if live_models:
        return Path(live_models).expanduser().resolve() / "seamless_m4t_v2_large"
    if is_dev_mode():
        return project_root() / "models" / "seamless_m4t_v2_large"
    return models_data_dir() / "seamless_m4t_v2_large"
def bergamot_sidecar_dir() -> Path:
    return project_root() / "sidecar" / "bergamot"
def languagetool_local_dir() -> Path:
    live_models = os.environ.get("LINGOVEIL_LIVE_MODELS_DIR", "").strip()

    if live_models:
        return Path(live_models).expanduser().resolve() / "tools" / "languagetool"
    if is_dev_mode():
        lt = project_root() / "tools" / "languagetool"
        for child in sorted(lt.glob("LanguageTool-*")):
            if child.is_dir():
                return child
        return lt
    return tools_data_dir() / "languagetool"
def glossary_path() -> Path:
    if is_dev_mode():
        return project_root() / "config" / "ocr_glossary.json"
    return xdg_config_home() / "ocr_glossary.json"
def symspell_dict_path() -> Path:
    if is_dev_mode():
        return (
            project_root()

            / "resources"
            / "symspell"
            / "frequency_dictionary_en_82_765.txt"
        )

    return data_dir() / "resources" / "symspell" / "frequency_dictionary_en_82_765.txt"
def is_frozen_app() -> bool:
    return getattr(sys, "frozen", False) is True
def path_diagnostics() -> dict[str, str]:
    return {
        "dev_mode": str(is_dev_mode()),
        "frozen_app": str(is_frozen_app()),
        "config_dir": str(config_dir()),
        "data_dir": str(data_dir()),
        "cache_dir": str(cache_dir()),
        "state_dir": str(state_dir()),
        "models_dir": str(models_data_dir()),
        "tools_dir": str(tools_data_dir()),
        "licenses_dir": str(licenses_data_dir()),
        "env_file": str(env_file_path()),
        "translation_cache": str(translation_cache_path()),
        "seamless_model_default": str(seamless_model_dir()),
    }
