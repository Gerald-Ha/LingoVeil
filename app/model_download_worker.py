from __future__ import annotations
import os
import sys
import threading

from pathlib import Path
from core.app_paths import AppPaths
from core.model_manager import AppModelManager
from lingoveil_model_manager import ModelManager
DATA_DIR = Path(os.environ.get("LINGOVEIL_LIVE_DATA_DIR", "/app/data")).resolve()

MODELS_DIR = Path(os.environ.get("LINGOVEIL_LIVE_MODELS_DIR", "/app/modelle")).resolve()

CACHE_DIR = Path(os.environ.get("LINGOVEIL_LIVE_CACHE_DIR", "/app/cache")).resolve()

def paths() -> AppPaths:
    return AppPaths(
        project_root=Path("/app"),
        runtime_root=Path("/app"),
        config_dir=DATA_DIR,
        data_dir=DATA_DIR,
        cache_dir=CACHE_DIR,
        models_dir=MODELS_DIR,
        resources_dir=Path("/app/resources"),
        downloads_dir=CACHE_DIR / "downloads",
        tmp_dir=CACHE_DIR / "tmp",
        settings_file=DATA_DIR / "settings.json",
        logs_dir=DATA_DIR / "logs",
        desktop_entry_dir=DATA_DIR / "unused-desktop",
    )

def download_seamless() -> int:
    done = threading.Event()

    successful = False
    def finished(ok: bool, message: str) -> None:
        nonlocal successful
        successful = ok
        print(f"[LingoVeil Live] [Modelle] {message}", flush=True)

        done.set()

    manager = ModelManager(
        seamless_model_dir_override=str(MODELS_DIR / "seamless_m4t_v2_large"),
        log_fn=lambda message: print(
            f"[LingoVeil Live] [Modelle] {message}", flush=True
        ),
    )

    manager.download_seamless(on_done=finished)

    done.wait()

    return 0 if successful else 1
def main() -> int:
    component_id = sys.argv[1] if len(sys.argv) > 1 else ""
    app_paths = paths()

    app_paths.ensure_dirs()

    if component_id == "seamless-m4t-v2-large":
        return download_seamless()

    if component_id == "languagetool-local":
        AppModelManager(app_paths).download_and_install(component_id)

        return 0
    print(f"Unbekannte Download-Komponente: {component_id}", file=sys.stderr)

    return 2
if __name__ == "__main__":
    raise SystemExit(main())
