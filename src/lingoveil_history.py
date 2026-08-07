from __future__ import annotations
import hashlib
import json
import os
import shutil
import tempfile
import threading

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
class LiveHistoryStore:
    def __init__(
        self,
        data_dir: Path,
        cache_dir: Path,
        *,
        limit: int = 10,
        protected_manga_urls: Callable[[], set[str]] | None = None,
    ) -> None:
        self.index_path = data_dir / "history.json"
        self.assets_dir = cache_dir / "history"
        self.limit = max(1, min(100, int(limit)))

        self._protected_manga_urls = protected_manga_urls or (lambda: set())

        self._lock = threading.RLock()

        self.assets_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _entry_id(url: str) -> str:
        return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:20]
    @staticmethod
    def _image_key(url: str) -> str:
        return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:20]
    def _load(self) -> dict[str, Any]:
        if not self.index_path.is_file():
            return {"version": 1, "entries": []}

        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))

            if not isinstance(raw.get("entries"), list):
                raise ValueError("entries fehlt")

            return raw
        except (OSError, ValueError, json.JSONDecodeError):
            return {"version": 1, "entries": []}

    def _save(self, value: dict[str, Any]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

        fd, name = tempfile.mkstemp(
            prefix=".history-",
            suffix=".json",
            dir=self.index_path.parent,
        )

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)

                handle.write("\n")

                handle.flush()

                os.fsync(handle.fileno())

            os.replace(name, self.index_path)

        finally:
            Path(name).unlink(missing_ok=True)

    def set_limit(self, limit: int) -> None:
        with self._lock:
            self.limit = max(1, min(100, int(limit)))

            data = self._load()

            self._prune(data)

            self._save(data)

    def _prune(self, data: dict[str, Any]) -> None:
        entries = data["entries"]
        protected = self._protected_manga_urls()

        kept: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        regular_count = 0
        for entry in entries:
            manga_url = str(entry.get("metadata", {}).get("manga_url", ""))

            if manga_url and manga_url in protected:
                kept.append(entry)

            elif regular_count < self.limit:
                kept.append(entry)

                regular_count += 1
            else:
                removed.append(entry)

        data["entries"] = kept
        for entry in removed:
            shutil.rmtree(self.assets_dir / str(entry.get("id", "")), ignore_errors=True)

    def touch(
        self,
        url: str,
        images: list[dict[str, str]],
        *,
        kind: str = "page",
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            data = self._load()

            entry_id = self._entry_id(url)

            previous = next(
                (entry for entry in data["entries"] if entry.get("id") == entry_id),
                None,
            )

            previous_images = {
                item.get("key"): item
                for item in (previous or {}).get("images", [])

                if item.get("key")
            }

            normalized_images = []
            for item in images:
                image_url = str(item["url"])

                key = str(item.get("key") or self._image_key(image_url))

                old = previous_images.get(key, {})

                original_file = str(old.get("original_file", ""))

                try:
                    if original_file:
                        self.asset_path(original_file)

                except (ValueError, FileNotFoundError):
                    original_file = ""
                translations = {}

                if original_file:
                    for engine, files in old.get("translations", {}).items():
                        rendered_file = str(files.get("rendered_file", ""))

                        result_file = str(files.get("result_file", ""))

                        try:
                            self.asset_path(rendered_file)

                            self.asset_path(result_file)

                        except (ValueError, FileNotFoundError):
                            continue
                        translations[str(engine)] = {
                            "rendered_file": rendered_file,
                            "result_file": result_file,
                        }

                normalized_images.append(
                    {
                        "key": key,
                        "url": image_url,
                        "source_url": str(item.get("source_url") or url),
                        "translations": translations,
                        "original_file": original_file,
                    }

                )

            now = self._now()

            entry = {
                "id": entry_id,
                "url": url,
                "kind": kind,
                "created_at": (previous or {}).get("created_at", now),
                "updated_at": now,
                "images": normalized_images,
                "metadata": {
                    **(previous or {}).get("metadata", {}),
                    **(metadata or {}),
                },
            }

            data["entries"] = [
                entry,
                *[item for item in data["entries"] if item.get("id") != entry_id],
            ]
            self._prune(data)

            self._save(data)

            return entry
    def list_entries(self) -> list[dict[str, Any]]:
        with self._lock:
            entries = self._load()["entries"]
            return [
                {
                    "id": entry["id"],
                    "url": entry["url"],
                    "kind": entry.get("kind", "page"),
                    "updated_at": entry.get("updated_at", ""),
                    "image_count": len(entry.get("images", [])),
                    "translated_count": sum(
                        1 for image in entry.get("images", [])

                        if image.get("translations")

                    ),
                    "metadata": entry.get("metadata", {}),
                }

                for entry in entries
            ]
    def prune_bookmark_assets(
        self,
        manga_url: str,
        keep_chapter_urls: set[str],
    ) -> int:
        pass
        with self._lock:
            data = self._load()

            changed = 0
            for entry in data["entries"]:
                metadata = entry.get("metadata", {})

                if metadata.get("manga_url") != manga_url:
                    continue
                if entry.get("url") in keep_chapter_urls:
                    continue
                entry_id = str(entry.get("id", ""))

                if entry_id:
                    shutil.rmtree(self.assets_dir / entry_id, ignore_errors=True)

                for image in entry.get("images", []):
                    if image.get("translations") or image.get("original_file"):
                        changed += 1
                    image["translations"] = {}

                    image["original_file"] = ""
            if changed:
                self._save(data)

            return changed
    def get(self, entry_id: str) -> dict[str, Any] | None:
        with self._lock:
            return next(
                (
                    entry
                    for entry in self._load()["entries"]
                    if entry.get("id") == entry_id
                ),
                None,
            )

    def remove_image_urls(self, entry_id: str, urls: set[str]) -> None:
        if not urls:
            return
        with self._lock:
            data = self._load()

            entry = next(
                (item for item in data["entries"] if item.get("id") == entry_id),
                None,
            )

            if entry is None:
                return
            removed = [
                image for image in entry.get("images", [])

                if image.get("url") in urls
            ]
            entry["images"] = [
                image for image in entry.get("images", [])

                if image.get("url") not in urls
            ]
            for image in removed:
                image_key = str(image.get("key", ""))

                if image_key:
                    shutil.rmtree(
                        self.assets_dir / entry_id / image_key,
                        ignore_errors=True,
                    )

            entry["updated_at"] = self._now()

            self._save(data)

    def save_translation(
        self,
        *,
        entry_id: str,
        image_key: str,
        engine: str,
        original: bytes,
        rendered_path: Path,
        result: dict[str, Any],
    ) -> dict[str, str] | None:
        with self._lock:
            data = self._load()

            entry = next(
                (item for item in data["entries"] if item.get("id") == entry_id),
                None,
            )

            if entry is None:
                return
            image = next(
                (item for item in entry.get("images", []) if item.get("key") == image_key),
                None,
            )

            if image is None:
                return
            target_language = str(result.get("target_language", "unknown"))

            variant_key = f"{engine}:{target_language}"
            target_dir = self.assets_dir / entry_id / image_key / variant_key
            target_dir.mkdir(parents=True, exist_ok=True)

            if original.startswith(b"\x89PNG\r\n\x1a\n"):
                original_suffix = ".png"
            elif original.startswith(b"\xff\xd8\xff"):
                original_suffix = ".jpg"
            elif original.startswith(b"RIFF") and original[8:12] == b"WEBP":
                original_suffix = ".webp"
            else:
                original_suffix = ".img"
            original_path = target_dir.parent / f"original{original_suffix}"
            rendered_target = target_dir / "rendered.png"
            result_target = target_dir / "result.json"
            original_path.write_bytes(original)

            shutil.copyfile(rendered_path, rendered_target)

            result_target.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            image["original_file"] = str(original_path.relative_to(self.assets_dir))

            image.setdefault("translations", {})[variant_key] = {
                "rendered_file": str(rendered_target.relative_to(self.assets_dir)),
                "result_file": str(result_target.relative_to(self.assets_dir)),
                "engine": engine,
                "target_language": target_language,
            }

            entry["updated_at"] = self._now()

            data["entries"] = [
                entry,
                *[item for item in data["entries"] if item.get("id") != entry_id],
            ]
            self._prune(data)

            self._save(data)

            return {
                "rendered_file": str(rendered_target.relative_to(self.assets_dir)),
                "result_file": str(result_target.relative_to(self.assets_dir)),
                "original_file": str(original_path.relative_to(self.assets_dir)),
                "variant_key": variant_key,
            }

    def cached_translation(
        self, entry_id: str, image_key: str, engine: str, target_language: str | None = None
    ) -> tuple[dict[str, Any], Path, Path] | None:
        with self._lock:
            entry = self.get(entry_id)

            if entry is None:
                return None
            image = next(
                (item for item in entry.get("images", []) if item.get("key") == image_key),
                None,
            )

            if image is None:
                return None
            translations = image.get("translations", {})

            cached = translations.get(f"{engine}:{target_language}") if target_language else None
            if cached is None and target_language is None:
                cached = next(
                    (
                        value for key, value in translations.items()

                        if str(key).startswith(f"{engine}:")

                    ),
                    None,
                )

            if cached is None:
                cached = translations.get(engine)

            if not cached:
                return None
            rendered = (self.assets_dir / cached["rendered_file"]).resolve()

            result_file = (self.assets_dir / cached["result_file"]).resolve()

            original = (self.assets_dir / image["original_file"]).resolve()

            if not all(path.is_file() for path in (rendered, result_file, original)):
                return None
            return json.loads(result_file.read_text(encoding="utf-8")), rendered, original
    def asset_path(self, relative: str) -> Path:
        candidate = (self.assets_dir / relative).resolve()

        root = self.assets_dir.resolve()

        if candidate != root and root not in candidate.parents:
            raise ValueError("Ungültiger History-Pfad")

        if not candidate.is_file():
            raise FileNotFoundError(relative)

        return candidate
    def clear(self) -> None:
        with self._lock:
            shutil.rmtree(self.assets_dir, ignore_errors=True)

            self.assets_dir.mkdir(parents=True, exist_ok=True)

            self._save({"version": 1, "entries": []})

class DatabaseLiveHistoryStore(LiveHistoryStore):
    pass
    def __init__(
        self,
        user_data: Any,
        user_id: str,
        cache_dir: Path,
        *,
        limit: int,
        protected_manga_urls: Callable[[], set[str]],
    ) -> None:
        self.user_data = user_data
        self.user_id = user_id
        self.index_path = Path(f"postgresql-history-{user_id}")

        self.assets_dir = cache_dir / "history" / user_id
        self.limit = max(1, min(100, int(limit)))

        self._protected_manga_urls = protected_manga_urls
        self._lock = threading.RLock()

        self.assets_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        return {"version": 2, "entries": self.user_data.load_history(self.user_id)}

    def _save(self, value: dict[str, Any]) -> None:
        self.user_data.replace_history(self.user_id, list(value.get("entries", [])))
