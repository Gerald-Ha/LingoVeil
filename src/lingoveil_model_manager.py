from __future__ import annotations
import shutil
import threading
import time

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from lingoveil_paths import (
    bergamot_sidecar_dir,
    is_dev_mode,
    languagetool_local_dir,
    licenses_data_dir,
    models_data_dir,
    project_root,
    seamless_model_dir,
)

SEAMLESS_MODEL_ID = "facebook/seamless-m4t-v2-large"
SEAMLESS_MODEL_REVISION = "5f8cc790b19fc3f67a61c105133b20b34e3dcb76"
SEAMLESS_MODEL_LICENSE = "CC-BY-NC-4.0"
SEAMLESS_MODEL_SIZE_GIB = 8.7
BERGAMOT_MODEL_LICENSE_STATUS = "Lizenzprüfung ausstehend"
LANGUAGETOOL_LICENSE = "LGPL-2.1"
SEAMLESS_REQUIRED_FILES = (
    "config.json",
    "model-00001-of-00002.safetensors",
    "model-00002-of-00002.safetensors",
    "tokenizer_config.json",
)

@dataclass
class ModelComponent:
    component_id: str
    display_name: str
    description: str
    component_type: str  
    license_label: str
    license_path: str
    source_url: str
    expected_size_label: str
    revision: str = ""
    local_path: Path = field(default_factory=Path)

    installed: bool = False
    download_status: str = "idle"
    error: str = ""
def validate_seamless_model_dir(path: Path) -> tuple[bool, str]:
    if not path.is_dir():
        return False, f"Modellordner fehlt: {path}"
    missing = [name for name in SEAMLESS_REQUIRED_FILES if not (path / name).is_file()]
    if missing:
        return False, f"Fehlende Dateien: {', '.join(missing)}"
    return True, "OK"
def dir_size_gib(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    return total / (1024**3)

class ModelManager:
    pass
    def __init__(
        self,
        *,
        seamless_model_dir_override: str = "",
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._log = log_fn or (lambda msg: print(f"[ModelManager] {msg}", flush=True))

        self._seamless_dir_override = seamless_model_dir_override.strip()

        self._download_thread: threading.Thread | None = None
        self._download_cancel = threading.Event()

        self._download_progress = 0.0
        self._download_error = ""
    def seamless_path(self) -> Path:
        return seamless_model_dir(self._seamless_dir_override)

    def set_seamless_dir_override(self, path: str) -> None:
        self._seamless_dir_override = path.strip()

    def list_components(self) -> list[ModelComponent]:
        components: list[ModelComponent] = []
        berg_path = bergamot_sidecar_dir()

        berg_installed = (berg_path / "node_modules" / "@browsermt" / "bergamot-translator").is_dir()

        components.append(
            ModelComponent(
                component_id="bergamot_en_de",
                display_name="Bergamot EN→DE",
                description="Lokaler Bergamot-Sidecar (Modelle werden vom Sidecar geladen)",
                component_type="model",
                license_label=BERGAMOT_MODEL_LICENSE_STATUS,
                license_path=str(licenses_data_dir() / "Bergamot-MPL-2.0.txt"),
                source_url="https://github.com/browsermt/bergamot-translator",
                expected_size_label="Sidecar + Registry-Modelle (RAM)",
                local_path=berg_path,
                installed=berg_installed,
            )

        )

        seam_path = self.seamless_path()

        seam_ok, seam_msg = validate_seamless_model_dir(seam_path)

        size = dir_size_gib(seam_path) if seam_path.exists() else 0.0
        components.append(
            ModelComponent(
                component_id="seamless_m4t_v2_large",
                display_name="SeamlessM4T v2 Large (T2TT)",
                description="Optionales lokales Übersetzungsmodell (nur Text-zu-Text)",
                component_type="model",
                license_label=f"{SEAMLESS_MODEL_LICENSE} (nur nichtkommerziell)",
                license_path=str(licenses_data_dir() / "SeamlessM4T-CC-BY-NC-4.0.txt"),
                source_url=f"https://huggingface.co/{SEAMLESS_MODEL_ID}",
                expected_size_label=f"ca. {SEAMLESS_MODEL_SIZE_GIB} GiB",
                revision=SEAMLESS_MODEL_REVISION,
                local_path=seam_path,
                installed=seam_ok,
                error="" if seam_ok else seam_msg,
                download_status=self._current_download_status(),
            )

        )

        if size > 0:
            components[-1].expected_size_label = f"{size:.1f} GiB installiert"
        lt_path = languagetool_local_dir()

        lt_installed = any(lt_path.glob("**/languagetool-server.jar"))

        components.append(
            ModelComponent(
                component_id="languagetool_local",
                display_name="LanguageTool (lokal)",
                description="Optionales lokales Grammatik-Tool für OCR-Nachbearbeitung",
                component_type="tool",
                license_label=LANGUAGETOOL_LICENSE,
                license_path=str(licenses_data_dir() / "LanguageTool-LGPL-2.1.txt"),
                source_url="https://languagetool.org/",
                expected_size_label="ca. 250–400 MB",
                local_path=lt_path,
                installed=lt_installed,
            )

        )

        return components
    def _current_download_status(self) -> str:
        if self._download_thread and self._download_thread.is_alive():
            return f"downloading ({self._download_progress:.0f}%)"
        if self._download_error:
            return "error"
        return "idle"
    def download_seamless(
        self,
        *,
        target_dir: Path | None = None,
        on_progress: Callable[[float, str], None] | None = None,
        on_done: Callable[[bool, str], None] | None = None,
    ) -> None:
        if self._download_thread and self._download_thread.is_alive():
            raise RuntimeError("Download läuft bereits")

        self._download_cancel.clear()

        self._download_error = ""
        dest = target_dir or self.seamless_path()

        def worker() -> None:
            ok = False
            msg = ""
            try:
                from huggingface_hub import snapshot_download
                tmp = dest.parent / f".{dest.name}.download"
                if tmp.exists():
                    shutil.rmtree(tmp)

                tmp.mkdir(parents=True, exist_ok=True)

                allow_patterns = [
                    "config.json",
                    "generation_config.json",
                    "model*.safetensors",
                    "model.safetensors.index.json",
                    "tokenizer*",
                    "sentencepiece.bpe.model",
                    "spm_char_lang38_tc.model",
                    "added_tokens.json",
                    "special_tokens_map.json",
                    "preprocessor_config.json",
                    "README.md",
                ]
                def _progress(total: int, current: int) -> None:
                    if total > 0:
                        self._download_progress = 100.0 * current / total
                        if on_progress:
                            on_progress(self._download_progress, "Download …")

                self._log(
                    f"Starte SeamlessM4T-Download nach {tmp} "
                    f"(Revision {SEAMLESS_MODEL_REVISION})"
                )

                snapshot_download(
                    repo_id=SEAMLESS_MODEL_ID,
                    revision=SEAMLESS_MODEL_REVISION,
                    local_dir=str(tmp),
                    allow_patterns=allow_patterns,
                )

                if self._download_cancel.is_set():
                    shutil.rmtree(tmp, ignore_errors=True)

                    msg = "Download abgebrochen"
                else:
                    valid, vmsg = validate_seamless_model_dir(tmp)

                    if not valid:
                        shutil.rmtree(tmp, ignore_errors=True)

                        msg = vmsg
                    else:
                        if dest.exists():
                            shutil.rmtree(dest)

                        tmp.rename(dest)

                        (dest / ".model_revision").write_text(
                            SEAMLESS_MODEL_REVISION + "\n", encoding="utf-8"
                        )

                        ok = True
                        msg = f"Modell installiert: {dest}"
                        self._log(msg)

            except Exception as exc:
                self._download_error = str(exc)

                msg = str(exc)

                self._log(f"Download-Fehler: {exc}")

            finally:
                self._download_progress = 100.0 if ok else 0.0
                if on_done:
                    on_done(ok, msg)

        self._download_thread = threading.Thread(target=worker, daemon=True)

        self._download_thread.start()

    def cancel_download(self) -> None:
        self._download_cancel.set()

    def remove_seamless(self) -> tuple[bool, str]:
        path = self.seamless_path()

        if not path.exists():
            return True, "Bereits entfernt"
        try:
            shutil.rmtree(path)

            self._log(f"SeamlessM4T-Modell entfernt: {path}")

            return True, f"Entfernt: {path}"
        except OSError as exc:
            return False, str(exc)

    def import_seamless_dir(self, source: Path) -> tuple[bool, str]:
        source = source.expanduser().resolve()

        valid, msg = validate_seamless_model_dir(source)

        if not valid:
            return False, msg
        dest = self.seamless_path()

        try:
            if dest.exists():
                shutil.rmtree(dest)

            shutil.copytree(source, dest)

            (dest / ".model_revision").write_text(
                SEAMLESS_MODEL_REVISION + "\n", encoding="utf-8"
            )

            self._log(f"SeamlessM4T importiert von {source} nach {dest}")

            return True, f"Importiert: {dest}"
        except OSError as exc:
            return False, str(exc)

def open_model_manager_dialog(
    parent: object,
    *,
    manager: ModelManager,
    license_accepted: bool,
    on_license_accept: Callable[[], None] | None = None,
    on_path_selected: Callable[[str], None] | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> None:
    pass
    import tkinter as tk

    from tkinter import filedialog, messagebox
    from lingoveil_roi_selector import safe_modal_grab
    from lingoveil_ui import DARK, apply_dark_theme, center_dialog
    log = log_fn or (lambda m: None)

    dialog = tk.Toplevel(parent)  

    apply_dark_theme(dialog)

    dialog.title("LingoVeil – Modelle verwalten")

    dialog.transient(parent)  

    safe_modal_grab(dialog)

    dialog.resizable(True, True)

    frame = tk.Frame(dialog, padx=12, pady=10)

    frame.pack(fill="both", expand=True)

    status_var = tk.StringVar(value="")

    progress_var = tk.DoubleVar(value=0.0)

    def refresh_list() -> None:
        for child in list_frame.winfo_children():
            child.destroy()

        for comp in manager.list_components():
            row = tk.Frame(list_frame, relief="groove", bd=1, padx=8, pady=6)

            row.pack(fill="x", pady=4)

            inst = "installiert" if comp.installed else "nicht installiert"
            tk.Label(
                row,
                text=f"{comp.display_name} [{inst}]",
                font=("DejaVu Sans", 10, "bold"),
            ).pack(anchor="w")

            tk.Label(row, text=comp.description, wraplength=520, justify="left").pack(
                anchor="w"
            )

            tk.Label(
                row,
                text=(
                    f"Pfad: {comp.local_path}\n"
                    f"Lizenz: {comp.license_label}\n"
                    f"Größe: {comp.expected_size_label}"
                ),
                justify="left",
                fg=DARK["muted"],
            ).pack(anchor="w")

            if comp.error:
                tk.Label(row, text=comp.error, fg=DARK["danger"]).pack(anchor="w")

            if comp.component_id == "seamless_m4t_v2_large":
                btn_row = tk.Frame(row)

                btn_row.pack(anchor="w", pady=(4, 0))

                def _download() -> None:
                    if not license_accepted:
                        if not messagebox.askyesno(
                            "Lizenzbestätigung",
                            (
                                "SeamlessM4T v2 Large ist ein optionales lokales "
                                "Übersetzungsmodell.\n\n"
                                f"Downloadgröße: ca. {SEAMLESS_MODEL_SIZE_GIB} GiB\n"
                                "Lizenz der Modellgewichte: CC-BY-NC-4.0\n"
                                "Nur für nichtkommerzielle Nutzung.\n\n"
                                "Das Modell ist nicht Bestandteil der "
                                "LingoVeil-Standardinstallation.\n\n"
                                "Lizenz akzeptieren und herunterladen?"
                            ),
                            parent=dialog,
                        ):
                            return
                        if on_license_accept:
                            on_license_accept()

                    status_var.set("Download gestartet …")

                    def on_prog(pct: float, _msg: str) -> None:
                        progress_var.set(pct)

                        status_var.set(f"Download … {pct:.0f} %")

                        dialog.update_idletasks()

                    def on_done(ok: bool, msg: str) -> None:
                        status_var.set(msg)

                        progress_var.set(0.0)

                        refresh_list()

                        log(msg)

                    try:
                        manager.download_seamless(
                            on_progress=on_prog, on_done=on_done
                        )

                    except Exception as exc:
                        status_var.set(str(exc))

                def _import_dir() -> None:
                    chosen = filedialog.askdirectory(
                        parent=dialog, title="SeamlessM4T-Modellordner auswählen"
                    )

                    if not chosen:
                        return
                    ok, msg = manager.import_seamless_dir(Path(chosen))

                    status_var.set(msg)

                    if ok and on_path_selected:
                        on_path_selected(str(manager.seamless_path()))

                    refresh_list()

                    log(msg)

                def _remove() -> None:
                    if not messagebox.askyesno(
                        "Modell entfernen",
                        f"SeamlessM4T-Modell wirklich entfernen?\n{manager.seamless_path()}",
                        parent=dialog,
                    ):
                        return
                    ok, msg = manager.remove_seamless()

                    status_var.set(msg)

                    refresh_list()

                    log(msg)

                tk.Button(btn_row, text="Lizenz akzeptieren und herunterladen", command=_download).pack(
                    side="left", padx=(0, 6)

                )

                tk.Button(btn_row, text="Ordner importieren", command=_import_dir).pack(
                    side="left", padx=(0, 6)

                )

                tk.Button(btn_row, text="Entfernen", command=_remove).pack(side="left")

    list_frame = tk.Frame(frame)

    list_frame.pack(fill="both", expand=True)

    tk.Label(frame, textvariable=status_var, fg=DARK["muted"]).pack(anchor="w", pady=(8, 0))

    tk.Scale(
        frame,
        variable=progress_var,
        from_=0,
        to=100,
        orient="horizontal",
        length=400,
        showvalue=True,
    ).pack(fill="x", pady=4)

    tk.Button(frame, text="Schließen", command=dialog.destroy).pack(anchor="e", pady=(8, 0))

    refresh_list()

    center_dialog(parent, dialog)
