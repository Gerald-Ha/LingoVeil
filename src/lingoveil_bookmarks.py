from __future__ import annotations
import hashlib
import json
import os
import tempfile
import threading

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
class MangaBookmarkStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "bookmarks.json"
        self._lock = threading.RLock()

        if not self.path.is_file():
            self._save({"version": 1, "bookmarks": []})

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _id(url: str) -> str:
        return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:20]
    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))

            if not isinstance(value.get("bookmarks"), list):
                raise ValueError("bookmarks fehlt")

            return value
        except (OSError, ValueError, json.JSONDecodeError):
            return {"version": 1, "bookmarks": []}

    def _save(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        fd, name = tempfile.mkstemp(
            prefix=".bookmarks-",
            suffix=".json",
            dir=self.path.parent,
        )

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)

                handle.write("\n")

                handle.flush()

                os.fsync(handle.fileno())

            os.replace(name, self.path)

        finally:
            Path(name).unlink(missing_ok=True)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            bookmarks = [self._normalized(item) for item in self._load()["bookmarks"]]
            most_recent_read = max(
                (str(item.get("last_read_at", "")) for item in bookmarks),
                default="",
            )

            return sorted(
                bookmarks,
                key=lambda item: (
                    bool(
                        most_recent_read
                        and item.get("last_read_at") == most_recent_read
                    ),
                    bool(item.get("new_chapters")),
                    str(item.get("new_chapter_detected_at", "")),
                    str(item.get("last_read_at", "")),
                    str(item.get("updated_at", "")),
                ),
                reverse=True,
            )

    @staticmethod
    def _normalized(item: dict[str, Any]) -> dict[str, Any]:
        return {
            **item,
            "chapters": item.get("chapters", {}),
            "cached_chapters": item.get("cached_chapters", {}),
            "chapter_count": int(item.get("chapter_count", 0) or 0),
            "known_chapter_urls": list(item.get("known_chapter_urls", [])),
            "known_chapters": list(item.get("known_chapters", [])),
            "latest_chapter": item.get("latest_chapter", {}),
            "new_chapters": list(item.get("new_chapters", [])),
            "last_checked_at": str(item.get("last_checked_at", "")),
            "new_chapter_detected_at": str(
                item.get("new_chapter_detected_at", "")

            ),
        }

    def urls(self) -> set[str]:
        return {
            str(item.get("url", ""))

            for item in self.list()

            if item.get("url")
        }

    def chapter_navigation(self, chapter_url: str) -> dict[str, Any]:
        pass
        normalized = chapter_url.strip()

        for bookmark in self.list():
            chapter_urls = [
                str(url) for url in bookmark.get("known_chapter_urls", []) if url
            ]
            try:
                index = chapter_urls.index(normalized)

            except ValueError:
                continue
            known_chapters = {
                str(item.get("url", "")): item
                for item in bookmark.get("known_chapters", [])

                if item.get("url")
            }

            current = known_chapters.get(normalized, {})

            return {
                "enabled": True,
                "manga_url": str(bookmark.get("url", "")),
                "manga_title": str(bookmark.get("title", "")),
                "previous_url": (
                    chapter_urls[index + 1] if index + 1 < len(chapter_urls) else ""
                ),
                "next_url": chapter_urls[index - 1] if index > 0 else "",
                "chapter": str(current.get("chapter", "")),
                "chapter_label": str(current.get("label", "")),
            }

        return {
            "enabled": False,
            "manga_url": "",
            "manga_title": "",
            "previous_url": "",
            "next_url": "",
            "chapter": "",
            "chapter_label": "",
        }

    def get_by_url(self, url: str) -> dict[str, Any] | None:
        normalized = url.strip()

        return next(
            (item for item in self.list() if item.get("url") == normalized),
            None,
        )

    def add(
        self,
        *,
        url: str,
        title: str,
        site: str,
        catalog_chapters: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            data = self._load()

            normalized = url.strip()

            previous = next(
                (item for item in data["bookmarks"] if item.get("url") == normalized),
                None,
            )

            if previous is None:
                previous = data.get("removed", {}).pop(normalized, None)

            now = self._now()

            snapshot = catalog_chapters or []
            bookmark = {
                "id": self._id(normalized),
                "url": normalized,
                "title": title.strip()[:500],
                "site": site.strip()[:50],
                "created_at": (previous or {}).get("created_at", now),
                "updated_at": now,
                "last_read_url": (previous or {}).get("last_read_url", ""),
                "last_read_at": (previous or {}).get("last_read_at", ""),
                "chapters": (previous or {}).get("chapters", {}),
                "cached_chapters": (previous or {}).get("cached_chapters", {}),
                "chapter_count": (
                    len(snapshot)

                    if snapshot
                    else int((previous or {}).get("chapter_count", 0) or 0)

                ),
                "known_chapter_urls": (
                    [str(item.get("url", "")) for item in snapshot if item.get("url")]
                    if snapshot
                    else list((previous or {}).get("known_chapter_urls", []))

                ),
                "known_chapters": (
                    [dict(item) for item in snapshot]
                    if snapshot
                    else list((previous or {}).get("known_chapters", []))

                ),
                "latest_chapter": (
                    dict(snapshot[0])

                    if snapshot
                    else dict((previous or {}).get("latest_chapter", {}))

                ),
                "new_chapters": list((previous or {}).get("new_chapters", [])),
                "last_checked_at": now if snapshot else str(
                    (previous or {}).get("last_checked_at", "")

                ),
                "new_chapter_detected_at": str(
                    (previous or {}).get("new_chapter_detected_at", "")

                ),
            }

            data["bookmarks"] = [
                bookmark,
                *[
                    item for item in data["bookmarks"]
                    if item.get("url") != normalized
                ],
            ]
            self._save(data)

            return bookmark
    def mark_cached(
        self,
        *,
        manga_url: str,
        chapter_url: str,
        volume: str,
        chapter: str,
        label: str,
        total_pages: int = 0,
    ) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()
            bookmark = next(
                (
                    item for item in data["bookmarks"]
                    if item.get("url") == manga_url.strip()
                ),
                None,
            )
            if bookmark is None:
                return None

            now = self._now()
            bookmark.setdefault("cached_chapters", {})[chapter_url] = {
                "url": chapter_url,
                "volume": volume,
                "chapter": chapter,
                "label": label,
                "cached_at": now,
                "status": "queued",
                "total_pages": max(0, int(total_pages)),
                "completed_page_keys": [],
            }
            bookmark["updated_at"] = now
            data["bookmarks"] = [
                bookmark,
                *[
                    item for item in data["bookmarks"]
                    if item.get("url") != manga_url.strip()
                ],
            ]
            self._save(data)
            return self._normalized(bookmark)
    def record_cached_page(
        self,
        *,
        chapter_url: str,
        page_key: str,
        total_pages: int,
    ) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()
            bookmark = next(
                (
                    item for item in data["bookmarks"]
                    if chapter_url in item.get("cached_chapters", {})
                ),
                None,
            )
            if bookmark is None:
                return None

            cached = bookmark.setdefault("cached_chapters", {})[chapter_url]
            completed = set(cached.get("completed_page_keys", []))
            if page_key:
                completed.add(page_key)
            expected = max(0, int(total_pages or cached.get("total_pages", 0)))
            cached["total_pages"] = expected
            cached["completed_page_keys"] = sorted(completed)
            cached["completed_pages"] = len(completed)
            cached["status"] = (
                "complete" if expected > 0 and len(completed) >= expected else "queued"
            )
            cached["updated_at"] = self._now()
            bookmark["updated_at"] = cached["updated_at"]
            self._save(data)
            return self._normalized(bookmark)
    def remove(self, url: str, *, delete_reading_data: bool) -> None:
        with self._lock:
            data = self._load()

            normalized = url.strip()

            bookmark = next(
                (item for item in data["bookmarks"] if item.get("url") == normalized),
                None,
            )

            if bookmark is None:
                return
            if delete_reading_data:
                data["bookmarks"] = [
                    item for item in data["bookmarks"]
                    if item.get("url") != normalized
                ]
            else:
                data.setdefault("removed", {})[normalized] = {
                    **bookmark,
                    "removed_at": self._now(),
                }

                data["bookmarks"] = [
                    item for item in data["bookmarks"]
                    if item.get("url") != normalized
                ]
            self._save(data)

    def mark_read(
        self,
        *,
        manga_url: str,
        chapter_url: str,
        volume: str,
        chapter: str,
        label: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()

            bookmark = next(
                (
                    item for item in data["bookmarks"]
                    if item.get("url") == manga_url.strip()

                ),
                None,
            )

            if bookmark is None:
                return None
            now = self._now()

            bookmark.setdefault("chapters", {})[chapter_url] = {
                "url": chapter_url,
                "volume": volume,
                "chapter": chapter,
                "label": label,
                "read_at": now,
            }
            cached = bookmark.setdefault("cached_chapters", {}).setdefault(
                chapter_url,
                {"url": chapter_url, "cached_at": now},
            )
            cached.update({
                "volume": volume,
                "chapter": chapter,
                "label": label,
            })

            bookmark["last_read_url"] = chapter_url
            bookmark["last_read_at"] = now
            bookmark["new_chapters"] = [
                item for item in bookmark.get("new_chapters", [])

                if item.get("url") != chapter_url
            ]
            if not bookmark["new_chapters"]:
                bookmark["new_chapter_detected_at"] = ""
            bookmark["updated_at"] = now
            data["bookmarks"] = [
                bookmark,
                *[
                    item for item in data["bookmarks"]
                    if item.get("url") != manga_url.strip()

                ],
            ]
            self._save(data)

            return bookmark
    def update_catalog_snapshot(
        self,
        manga_url: str,
        catalog_chapters: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()

            bookmark = next(
                (
                    item for item in data["bookmarks"]
                    if item.get("url") == manga_url.strip()

                ),
                None,
            )

            if bookmark is None:
                return None
            now = self._now()

            known = set(bookmark.get("known_chapter_urls", []))

            existing_new = {
                str(item.get("url", "")): item
                for item in bookmark.get("new_chapters", [])

                if item.get("url")
            }

            for chapter in catalog_chapters:
                chapter_url = str(chapter.get("url", ""))

                if chapter_url and known and chapter_url not in known:
                    existing_new[chapter_url] = dict(chapter)

            newly_detected = bool(
                set(existing_new) - {
                    str(item.get("url", ""))

                    for item in bookmark.get("new_chapters", [])
                }

            )

            bookmark["chapter_count"] = len(catalog_chapters)

            bookmark["known_chapter_urls"] = [
                str(item.get("url", ""))

                for item in catalog_chapters
                if item.get("url")

            ]
            bookmark["known_chapters"] = [
                dict(item) for item in catalog_chapters if item.get("url")

            ]
            bookmark["latest_chapter"] = (
                dict(catalog_chapters[0]) if catalog_chapters else {}

            )

            bookmark["new_chapters"] = [
                existing_new[str(item.get("url"))]
                for item in catalog_chapters
                if str(item.get("url", "")) in existing_new
            ]
            bookmark["last_checked_at"] = now
            bookmark["updated_at"] = now
            if newly_detected:
                bookmark["new_chapter_detected_at"] = now
            data["bookmarks"] = [
                bookmark,
                *[
                    item for item in data["bookmarks"]
                    if item.get("url") != manga_url.strip()

                ],
            ]
            self._save(data)

            return self._normalized(bookmark)

    def recent_chapter_urls(self, manga_url: str, limit: int) -> set[str]:
        bookmark = self.get_by_url(manga_url)

        if bookmark is None or limit == 0:
            return set()

        chapters = sorted(
            bookmark.get("cached_chapters", {}).values(),
            key=lambda item: str(item.get("cached_at", "")),
            reverse=True,
        )

        return {
            str(item.get("url", ""))

            for item in chapters[:limit]
            if item.get("url")
        }

class DatabaseMangaBookmarkStore(MangaBookmarkStore):
    pass
    _user_locks_guard = threading.Lock()
    _user_locks: dict[str, threading.RLock] = {}

    def __init__(self, user_data: Any, user_id: str) -> None:
        self.user_data = user_data
        self.user_id = user_id
        self.path = Path(f"postgresql-bookmarks-{user_id}")

        with self._user_locks_guard:
            self._lock = self._user_locks.setdefault(user_id, threading.RLock())

    def _load(self) -> dict[str, Any]:
        items = self.user_data.load_bookmarks(self.user_id, include_removed=True)

        active = [
            {key: value for key, value in item.items() if key != "active"}

            for item in items
            if item.get("active", True)

        ]
        removed = {
            str(item.get("url", "")): {
                key: value for key, value in item.items() if key != "active"
            }

            for item in items
            if not item.get("active", True) and item.get("url")
        }

        return {"version": 2, "bookmarks": active, "removed": removed}

    def _save(self, value: dict[str, Any]) -> None:
        active = [{**item, "active": True} for item in value.get("bookmarks", [])]
        removed = [
            {**item, "url": url, "active": False}

            for url, item in value.get("removed", {}).items()

        ]
        self.user_data.replace_bookmarks(self.user_id, [*active, *removed])
