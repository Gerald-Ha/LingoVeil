from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from core.app_paths import AppPaths
from lingoveil_model_manager import SEAMLESS_MODEL_REVISION, SEAMLESS_REQUIRED_FILES
@dataclass(frozen=True)

class ModelManifestEntry:
    id: str
    name: str
    component: str
    version: str
    description: str
    optional: bool
    install_subdir: str
    estimated_size_bytes: int
    source_url: str
    archive_type: str | None = None
    download_url: str | None = None
    sha256: str | None = None
    required_files: tuple[str, ...] = ()

    required_python_modules: tuple[str, ...] = ()

    notes: str = ""
    metadata_todo: tuple[str, ...] = field(default_factory=tuple)

    def install_path(self, paths: AppPaths) -> Path:
        return paths.models_dir / self.install_subdir
def default_manifest(paths: AppPaths) -> list[ModelManifestEntry]:
    return [
        ModelManifestEntry(
            id="ocr-easyocr-en",
            name="EasyOCR (Englisch)",
            component="ocr",
            version="runtime-managed",
            description="Python-Paket und die von EasyOCR selbst verwalteten OCR-Dateien.",
            optional=False,
            install_subdir="ocr/easyocr",
            estimated_size_bytes=250_000_000,
            source_url="https://github.com/JaidedAI/EasyOCR",
            required_python_modules=("easyocr",),
            notes=(
                "Die eigentlichen OCR-Modelle werden heute von EasyOCR beim ersten Lauf "
                "selbst geladen. Ein zentraler, verifizierter Downloadpfad fuer AppImage "
                "ist vorbereitet, aber noch nicht final definiert."
            ),
            metadata_todo=("download_url", "sha256"),
        ),
        ModelManifestEntry(
            id="bergamot-sidecar",
            name="Bergamot EN→DE",
            component="bergamot",
            version="registry-managed",
            description="Node.js-Sidecar fuer die lokale Bergamot-Übersetzung.",
            optional=False,
            install_subdir="bergamot/sidecar",
            estimated_size_bytes=150_000_000,
            source_url="https://github.com/browsermt/bergamot-translator",
            notes=(
                "Im Dev-Modus liegt der Sidecar bereits im Repository. "
                "Fuer spaetere AppImage-Releases muss entschieden werden, "
                "ob die Sidecar-Runtime eingebettet oder ueber ein separates Bundle "
                "ausgeliefert wird."
            ),
            metadata_todo=("download_url", "sha256", "archive_type"),
        ),
        ModelManifestEntry(
            id="seamless-m4t-v2-large",
            name="SeamlessM4T v2 Large",
            component="seamless_m4t",
            version=SEAMLESS_MODEL_REVISION,
            description="Optionales lokales Offline-Modell fuer spaetere Sprach- und Audiofunktionen.",
            optional=True,
            install_subdir="seamless_m4t_v2_large",
            estimated_size_bytes=9_340_000_000,
            source_url="https://huggingface.co/facebook/seamless-m4t-v2-large",
            archive_type="directory-or-archive",
            required_files=SEAMLESS_REQUIRED_FILES,
            notes=(
                "Echte, versionierte Download-URLs und SHA-256-Werte werden bewusst "
                "noch nicht erfunden. Die GUI ist fuer spaetere Remote-Downloads vorbereitet."
            ),
            metadata_todo=("download_url", "sha256"),
        ),
        ModelManifestEntry(
            id="languagetool-local",
            name="LanguageTool (lokal)",
            component="languagetool",
            version="6.6",
            description="Optionales Grammatik-Tool fuer OCR-Nachbearbeitung.",
            optional=True,
            install_subdir="tools/languagetool",
            estimated_size_bytes=251_998_221,
            source_url="https://languagetool.org/download/LanguageTool-6.6.zip",
            archive_type="zip",
            download_url="https://languagetool.org/download/LanguageTool-6.6.zip",
            sha256="53600506b399bb5ffe1e4c8dec794fd378212f14aaf38ccef9b6f89314d11631",
            required_files=("languagetool-server.jar",),
            notes="LanguageTool 6.6 (LGPL-2.1-or-later), lokal und optional.",
        ),
    ]
