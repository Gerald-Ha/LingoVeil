from __future__ import annotations
import hashlib
import importlib.util
import os
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from core.app_paths import AppPaths
from core.model_manifest import ModelManifestEntry, default_manifest
from lingoveil_model_manager import validate_seamless_model_dir
from lingoveil_paths import bergamot_sidecar_dir, languagetool_local_dir
ProgressFn = Callable[[int, int, str], None]
class ModelManagerError(RuntimeError):
    pass
@dataclass(frozen=True)

class ComponentStatus:
    manifest: ModelManifestEntry
    status: str
    install_path: Path
    installed_version: str | None
    available_version: str | None
    size_label: str
    error: str = ""
    can_download: bool = False
class AppModelManager:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.manifest = default_manifest(paths)

    def list_components(self) -> list[ComponentStatus]:
        components: list[ComponentStatus] = []
        for item in self.manifest:
            try:
                components.append(self.inspect_component(item.id))

            except Exception as exc:
                install_path = item.install_path(self.paths)

                components.append(
                    ComponentStatus(
                        manifest=item,
                        status="Fehler",
                        install_path=install_path,
                        installed_version=None,
                        available_version=item.version,
                        size_label=self._format_bytes(item.estimated_size_bytes),
                        error=str(exc),
                        can_download=bool(item.download_url),
                    )

                )

        return components
    def get_manifest_entry(self, component_id: str) -> ModelManifestEntry:
        for item in self.manifest:
            if item.id == component_id:
                return item
        raise KeyError(component_id)

    def inspect_component(self, component_id: str) -> ComponentStatus:
        item = self.get_manifest_entry(component_id)

        install_path = item.install_path(self.paths)

        status = "nicht installiert"
        error = ""
        installed_version: str | None = None
        if item.component == "ocr":
            if all(importlib.util.find_spec(mod) is not None for mod in item.required_python_modules):
                status = "installiert"
                installed_version = item.version
            else:
                error = "Python-Modul EasyOCR fehlt."
        elif item.component == "bergamot":
            sidecar = bergamot_sidecar_dir()

            translator_dir = sidecar / "node_modules" / "@browsermt" / "bergamot-translator"
            install_path = sidecar
            if translator_dir.is_dir():
                status = "installiert"
                installed_version = item.version
            elif sidecar.exists():
                status = "beschädigt"
                error = "Sidecar-Verzeichnis vorhanden, aber node_modules fehlen."
        elif item.component == "seamless_m4t":
            ok, msg = validate_seamless_model_dir(install_path)

            if ok:
                status = "installiert"
                installed_version = item.version
            elif install_path.exists():
                status = "beschädigt"
                error = msg
            else:
                error = msg
        elif item.component == "languagetool":
            lt_dir = item.install_path(self.paths)

            install_path = lt_dir
            if any(lt_dir.glob("**/languagetool-server.jar")):
                status = "installiert"
                installed_version = item.version
            elif lt_dir.exists():
                status = "beschädigt"
                error = "Ordner vorhanden, aber kein LanguageTool-Server-JAR gefunden."
        else:
            if install_path.exists():
                status = "installiert"
                installed_version = item.version
        size_label = self._format_bytes(item.estimated_size_bytes)

        return ComponentStatus(
            manifest=item,
            status=status,
            install_path=install_path,
            installed_version=installed_version,
            available_version=item.version,
            size_label=size_label,
            error=error,
            can_download=bool(item.download_url),
        )

    @staticmethod
    def _format_bytes(size: int) -> str:
        if size >= 1024**3:
            return f"{size / (1024**3):.1f} GiB"
        if size >= 1024**2:
            return f"{size / (1024**2):.1f} MiB"
        if size >= 1024:
            return f"{size / 1024:.1f} KiB"
        return f"{size} B"
    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)

        return digest.hexdigest()

    def ensure_space(self, required_bytes: int) -> None:
        usage = shutil.disk_usage(self.paths.downloads_dir if self.paths.downloads_dir.exists() else self.paths.cache_dir)

        if usage.free < required_bytes:
            raise ModelManagerError(
                f"Nicht genug freier Speicherplatz: benötigt {self._format_bytes(required_bytes)}, "
                f"verfügbar {self._format_bytes(usage.free)}."
            )

    def remove_component(self, component_id: str) -> None:
        status = self.inspect_component(component_id)

        target = status.install_path
        if not target.exists():
            return
        if status.manifest.component == "bergamot":
            raise ModelManagerError("Der Bergamot-Sidecar wird im Dev-Modus aus dem Repository verwendet und wird hier nicht entfernt.")

        shutil.rmtree(target)

    def install_from_archive(
        self,
        component_id: str,
        archive_path: Path,
        *,
        progress: ProgressFn | None = None,
    ) -> Path:
        item = self.get_manifest_entry(component_id)

        archive_path = archive_path.expanduser().resolve()

        if not archive_path.is_file():
            raise ModelManagerError(f"Archiv nicht gefunden: {archive_path}")

        if item.sha256:
            actual = self.sha256_file(archive_path)

            if actual.lower() != item.sha256.lower():
                raise ModelManagerError("SHA-256 stimmt nicht mit dem Manifest überein.")

        self.paths.ensure_dirs()

        target = item.install_path(self.paths)

        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="lingoveil-install-", dir=str(self.paths.tmp_dir)) as tmp_dir:
            tmp_root = Path(tmp_dir)

            extract_dir = tmp_root / "extract"
            extract_dir.mkdir(parents=True, exist_ok=True)

            self._extract_archive_safe(archive_path, extract_dir)

            install_source = self._resolve_install_source(item, extract_dir)

            self._validate_install_source(item, install_source)

            tmp_target = parent / f".{target.name}.partial"
            if tmp_target.exists():
                shutil.rmtree(tmp_target, ignore_errors=True)

            shutil.copytree(install_source, tmp_target)

            if item.component == "languagetool":
                self._remove_languagetool_test_artifacts(tmp_target)

            if target.exists():
                shutil.rmtree(target)

            tmp_target.replace(target)

            if progress:
                progress(1, 1, "Installiert")

        return target
    @staticmethod
    def _remove_languagetool_test_artifacts(root: Path) -> None:
        pass
        relative_paths = (
            "testrules.sh",
            "testrules.bat",
            "libs/languagetool-core-tests.jar",
            "org/languagetool/resource/es/test.txt",
            "org/languagetool/resource/es/test-tagged.txt",
            "org/languagetool/resource/ro/test_diacritics.dict",
            "org/languagetool/resource/ro/test_diacritics.info",
        )

        for relative_path in relative_paths:
            (root / relative_path).unlink(missing_ok=True)

    def download_and_install(
        self,
        component_id: str,
        *,
        progress: ProgressFn | None = None,
    ) -> Path:
        item = self.get_manifest_entry(component_id)

        if not item.download_url:
            raise ModelManagerError(
                "Für diese Komponente ist noch keine verifizierte Download-URL hinterlegt."
            )

        if not item.sha256:
            raise ModelManagerError(
                "Für diese Komponente ist noch kein verifizierter SHA-256-Wert hinterlegt."
            )

        self.paths.ensure_dirs()

        self.ensure_space(max(item.estimated_size_bytes, 1))

        suffix = Path(item.download_url).suffix or ".bin"
        with tempfile.NamedTemporaryFile(
            prefix=f"{component_id}-",
            suffix=suffix,
            dir=self.paths.downloads_dir,
            delete=False,
        ) as handle:
            tmp_file = Path(handle.name)

            try:
                self._download_file(item.download_url, tmp_file, progress)

                return self.install_from_archive(component_id, tmp_file, progress=progress)

            finally:
                if tmp_file.exists():
                    tmp_file.unlink()

    def _download_file(self, url: str, destination: Path, progress: ProgressFn | None) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": "LingoVeil/Qt"})

        with urllib.request.urlopen(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length", "0"))

            downloaded = 0
            with destination.open("wb") as out:
                while True:
                    chunk = response.read(1024 * 256)

                    if not chunk:
                        break
                    out.write(chunk)

                    downloaded += len(chunk)

                    if progress:
                        progress(downloaded, total, "Download läuft")

    def _resolve_install_source(self, item: ModelManifestEntry, extract_dir: Path) -> Path:
        required = set(item.required_files)

        if required and required.issubset({child.name for child in extract_dir.iterdir()}):
            return extract_dir
        for child in extract_dir.iterdir():
            if child.is_dir():
                names = {entry.name for entry in child.iterdir()}

                if required and required.issubset(names):
                    return child
        return extract_dir
    def _validate_install_source(self, item: ModelManifestEntry, install_source: Path) -> None:
        if item.component == "seamless_m4t":
            ok, msg = validate_seamless_model_dir(install_source)

            if not ok:
                raise ModelManagerError(msg)

            return
        for required in item.required_files:
            if not (install_source / required).exists():
                raise ModelManagerError(f"Pflichtdatei fehlt nach der Installation: {required}")

        for mod in item.required_python_modules:
            if importlib.util.find_spec(mod) is None:
                raise ModelManagerError(f"Pflichtmodul fehlt in der aktuellen Umgebung: {mod}")

    def _extract_archive_safe(self, archive_path: Path, destination: Path) -> None:
        suffixes = "".join(archive_path.suffixes).lower()

        if suffixes.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as archive:
                for member in archive.infolist():
                    self._ensure_safe_member_path(destination, member.filename)

                archive.extractall(destination)

            return
        if suffixes.endswith(".tar.gz") or suffixes.endswith(".tgz") or suffixes.endswith(".tar"):
            with tarfile.open(archive_path) as archive:
                for member in archive.getmembers():
                    self._ensure_safe_member_path(destination, member.name)

                archive.extractall(destination)

            return
        raise ModelManagerError(f"Nicht unterstütztes Archivformat: {archive_path.name}")

    @staticmethod
    def _ensure_safe_member_path(destination: Path, member_name: str) -> None:
        member_path = destination / member_name
        resolved = member_path.resolve()

        destination_resolved = destination.resolve()

        if os.path.commonpath([str(destination_resolved), str(resolved)]) != str(destination_resolved):
            raise ModelManagerError(f"Unsicherer Archivpfad erkannt: {member_name}")
