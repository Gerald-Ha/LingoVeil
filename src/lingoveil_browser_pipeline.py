from __future__ import annotations
import ctypes
import gc
import json
import os
import re
import shutil
import threading
import uuid

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from statistics import median
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from PIL import Image
from lingoveil_config import (
    TRANSLATION_ENGINE_BERGAMOT,
    TRANSLATION_ENGINE_LM_STUDIO,
    TRANSLATION_ENGINE_OLLAMA,
    TRANSLATION_ENGINE_SEAMLESS_M4T,
    load_translation_settings,
    validate_translation_engine,
)

from lingoveil_image_pipeline import (
    ALLOWED_IMAGE_MIME,
    MAX_IMAGE_BYTES,
    MAX_PDF_BYTES,
    download_url_bytes,
    extract_page_images,
    fetch_page_html,
    is_pdf_bytes,
    is_gif_url,
    is_social_preview_url,
    load_image_bytes,
    load_image_file,
    pdf_page_count,
    render_pdf_page,
    save_image_copy,
    validate_remote_url,
)

from lingoveil_fetch_strategies import FetchStrategyStore
from lingoveil_history import LiveHistoryStore
from lingoveil_bookmarks import MangaBookmarkStore
from lingoveil_mangadex import mangadex_chapter_id, resolve_mangadex_chapter
from lingoveil_manga_catalog import is_supported_manga_url, resolve_manga_catalog
from lingoveil_mangatown import mangatown_chapter, resolve_mangatown_chapter
from lingoveil_model_manager import ModelManager, validate_seamless_model_dir
from lingoveil_paths import (
    browser_artifacts_dir,
    clear_browser_artifacts,
    browser_session_dir,
    env_file_path,
    translation_cache_path,
)

from lingoveil_translation_cache import (
    CACHE_SOURCE_PERSISTENT_CACHE,
    clear_translation_cache,
    engine_display_name,
    load_cache,
    normalize_source_text,
    plan_translation_batch,
    save_cache_atomic,
    set_cached_translation,
)

from lingoveil_translation_engine import (
    SOURCE_LANG,
    TARGET_LANG,
    TranslationEngineManager,
    engine_cache_model,
    engine_cache_prompt_version,
)

from lingoveil_ocr_grouping import (
    GroupedTextBlock,
    group_english_lines,
    process_ocr_raw,
)

from lingoveil_ocr_worker import EasyOcrWorker
from lingoveil_overlay_worker import OverlayWorker
from lingoveil_group_ids import group_id_str
LogFn = Callable[[str], None]
class BrowserTranslationPipeline:
    pass
    def __init__(self, *, log_fn: LogFn | None = None) -> None:
        self._log_fn = log_fn or (lambda msg: print(msg))

        self.session_id = uuid.uuid4().hex[:12]
        self.session_dir = browser_session_dir(self.session_id)

        self.artifacts_dir = browser_artifacts_dir()

        self.settings = load_translation_settings(env_file_path())

        self.ollama_unavailable_callback: Callable[[str], None] | None = None
        self.ollama_available = False
        self.engine_manager = TranslationEngineManager(
            self.settings, self._log, self._on_ollama_unavailable
        )

        self.persistent_cache = load_cache(translation_cache_path())

        self._clear_persistent_cache_on_startup()

        self.session_resolved: dict[str, Any] = {}

        self.ocr_engine: EasyOcrWorker | None = None
        self.overlay_worker: OverlayWorker | None = None
        self._ocr_idle_timeout_sec = TranslationEngineManager._read_idle_timeout()

        self._ocr_idle_timer: threading.Timer | None = None
        self._ocr_lock = threading.RLock()

        self._stored_images: dict[str, Path] = {}

        self._stored_pdfs: dict[str, Path] = {}

        self._page_image_urls: dict[str, str] = {}

        self._page_image_sources: dict[str, str] = {}

        self._page_image_preview_cache: dict[str, tuple[bytes, str]] = {}

        self._page_image_preview_cache_limit = 8
        self._page_image_history: dict[str, tuple[str, str]] = {}

        self._catalog_chapter_metadata: dict[str, dict[str, str]] = {}

        self._pdf_preview_cache: dict[tuple[str, int], bytes] = {}

        self._pdf_preview_cache_limit = 48
        self._closed = False
        data_dir = Path(os.environ.get("LINGOVEIL_LIVE_DATA_DIR", "/app/data"))

        self._default_bookmarks = MangaBookmarkStore(data_dir)

        self._bookmark_context: ContextVar[MangaBookmarkStore | None] = ContextVar(
            "lingoveil_bookmark_store", default=None
        )

        self._bookmark_check_lock = threading.Lock()

        self._progress_backup_lock = threading.RLock()

        self.bookmark_chapter_cache_limit = 10
        self._default_history = LiveHistoryStore(
            data_dir,
            Path(os.environ.get("LINGOVEIL_LIVE_CACHE_DIR", "/app/cache")),
            limit=10,
            protected_manga_urls=self.bookmarks.urls,
        )

        self._history_context: ContextVar[LiveHistoryStore | None] = ContextVar(
            "lingoveil_history_store", default=None
        )

        self.fetch_strategies = FetchStrategyStore(
            Path(os.environ.get("LINGOVEIL_LIVE_DATA_DIR", "/app/data"))

            / "fetch_strategies.json",
            log_fn=self._log,
        )

    @property
    def bookmarks(self) -> MangaBookmarkStore:
        return self._bookmark_context.get() or self._default_bookmarks
    @property
    def history(self) -> LiveHistoryStore:
        return self._history_context.get() or self._default_history
    @contextmanager
    def bind_user_stores(
        self,
        bookmarks: MangaBookmarkStore,
        history: LiveHistoryStore,
    ):
        bookmark_token = self._bookmark_context.set(bookmarks)

        history_token = self._history_context.set(history)

        try:
            yield
        finally:
            self._history_context.reset(history_token)

            self._bookmark_context.reset(bookmark_token)

    @staticmethod
    def _backup_text(value: Any, limit: int = 2000) -> str:
        return str(value or "")[:limit]
    def export_progress(self) -> dict[str, Any]:
        pass
        with self._progress_backup_lock:
            history = self.history._load()

            bookmarks = self.bookmarks._load()

            entries = []
            for entry in history.get("entries", []):
                images = [
                    {
                        "key": self._backup_text(image.get("key"), 100),
                        "url": self._backup_text(image.get("url")),
                        "source_url": self._backup_text(image.get("source_url")),
                        "translations": {},
                        "original_file": "",
                    }

                    for image in entry.get("images", [])

                    if isinstance(image, dict) and image.get("url")

                ]
                entries.append({
                    "id": self.history._entry_id(self._backup_text(entry.get("url"))),
                    "url": self._backup_text(entry.get("url")),
                    "kind": self._backup_text(entry.get("kind"), 50),
                    "created_at": self._backup_text(entry.get("created_at"), 100),
                    "updated_at": self._backup_text(entry.get("updated_at"), 100),
                    "images": images,
                    "metadata": {
                        self._backup_text(key, 100): self._backup_text(value, 1000)

                        for key, value in entry.get("metadata", {}).items()
                    },
                })

            return {
                "format": "lingoveil-live-progress",
                "version": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "history": {"version": 1, "entries": entries},
                "bookmarks": json.loads(json.dumps(bookmarks)),
            }

    def restore_progress(self, payload: dict[str, Any]) -> dict[str, int]:
        if payload.get("format") != "lingoveil-live-progress":
            raise ValueError("Keine gültige LingoVeil-Fortschrittsdatei")

        if payload.get("version") != 1:
            raise ValueError("Diese Backup-Version wird nicht unterstützt")

        history = payload.get("history")

        bookmarks = payload.get("bookmarks")

        if not isinstance(history, dict) or not isinstance(history.get("entries"), list):
            raise ValueError("Backup enthält keine gültige History")

        if not isinstance(bookmarks, dict) or not isinstance(bookmarks.get("bookmarks"), list):
            raise ValueError("Backup enthält keine gültigen Bookmarks")

        if len(history["entries"]) > 5000 or len(bookmarks["bookmarks"]) > 5000:
            raise ValueError("Backup enthält zu viele Einträge")

        clean_entries = []
        image_count = 0
        for entry in history["entries"]:
            if not isinstance(entry, dict):
                raise ValueError("Ungültiger History-Eintrag")

            url = self._backup_text(entry.get("url"))

            if not url.startswith(("http://", "https://")):
                raise ValueError("History enthält eine ungültige URL")

            metadata = entry.get("metadata", {})

            if not isinstance(metadata, dict):
                raise ValueError("Ungültige History-Metadaten")

            clean_images = []
            for image in entry.get("images", []):
                if not isinstance(image, dict):
                    raise ValueError("Ungültiger Bild-Eintrag")

                image_url = self._backup_text(image.get("url"))

                if not image_url.startswith(("http://", "https://")):
                    continue
                image_count += 1
                if image_count > 100000:
                    raise ValueError("Backup enthält zu viele Bilder")

                clean_images.append({
                    "key": self.history._image_key(image_url),
                    "url": image_url,
                    "source_url": self._backup_text(image.get("source_url")) or url,
                    "translations": {},
                    "original_file": "",
                })

            clean_entries.append({
                "id": self.history._entry_id(url),
                "url": url,
                "kind": self._backup_text(entry.get("kind"), 50) or "page",
                "created_at": self._backup_text(entry.get("created_at"), 100),
                "updated_at": self._backup_text(entry.get("updated_at"), 100),
                "images": clean_images,
                "metadata": {
                    self._backup_text(key, 100): self._backup_text(value, 1000)

                    for key, value in metadata.items()
                },
            })

        clean_bookmarks = json.loads(json.dumps(bookmarks))

        for bookmark in clean_bookmarks["bookmarks"]:
            if not isinstance(bookmark, dict):
                raise ValueError("Ungültiger Bookmark-Eintrag")

            url = bookmark.get("url")

            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                raise ValueError("Bookmark enthält eine ungültige URL")

        with self._progress_backup_lock, self.history._lock, self.bookmarks._lock:
            previous_history = self.history._load()

            previous_bookmarks = self.bookmarks._load()

            try:
                self.bookmarks._save(clean_bookmarks)

                restored_history = {"version": 1, "entries": clean_entries}

                self.history._prune(restored_history)

                self.history._save(restored_history)

            except Exception:
                self.bookmarks._save(previous_bookmarks)

                self.history._save(previous_history)

                raise
            shutil.rmtree(self.history.assets_dir, ignore_errors=True)

            self.history.assets_dir.mkdir(parents=True, exist_ok=True)

            self._page_image_urls.clear()

            self._page_image_sources.clear()

            self._page_image_preview_cache.clear()

            self._page_image_history.clear()

            self._catalog_chapter_metadata.clear()

        return {
            "history_entries": len(self.history.list_entries()),
            "bookmarks": len(self.bookmarks.list()),
        }

    def _log(self, msg: str) -> None:
        self._log_fn(f"[Browser-Pipeline] {msg}")

    def _clear_persistent_cache_on_startup(self) -> None:
        pass
        artifact_count = clear_browser_artifacts()

        if artifact_count > 0:
            self._log(f"Browser-Artefakte beim Start geleert ({artifact_count} Datei(en))")

        count = clear_translation_cache(self.persistent_cache)

        if count <= 0:
            return
        try:
            save_cache_atomic(translation_cache_path(), self.persistent_cache)

        except OSError as exc:
            self._log(f"Cache-Leeren beim Start fehlgeschlagen: {exc}")

        else:
            self._log(f"Persistenter Cache beim Start geleert ({count} alte Einträge)")

    def _ensure_engine(self, engine_name: str) -> None:
        engine = validate_translation_engine(engine_name)

        if self.engine_manager.active_engine != engine:
            self.engine_manager.set_engine(engine)

        else:
            self.engine_manager.update_settings(self.settings)

        self.engine_manager.ensure_ready()

    def apply_live_settings(self, live_settings: dict[str, Any]) -> None:
        pass
        target = str(live_settings.get("target_language", "deu")).strip()

        self.ollama_available = live_settings.get("ollama_status") == "AVAILABLE"
        bergamot_codes = {
            "bul": "bg", "ces": "cs", "deu": "de", "spa": "es", "est": "et",
            "fra": "fr", "ita": "it", "por": "pt", "rus": "ru", "ukr": "uk",
        }

        bergamot_target = bergamot_codes.get(target, self.settings.bergamot.target_lang)

        seamless_target = target
        self.settings = replace(
            self.settings,
            translation_engine=str(live_settings["engine"]),
            llm=replace(
                self.settings.llm,
                base_url=str(live_settings["lm_studio_base_url"]),
                model=str(live_settings["lm_studio_model"]),
                timeout_sec=float(live_settings["lm_studio_timeout_sec"]),
            ),
            ollama=replace(
                self.settings.ollama,
                base_url=str(live_settings["ollama_base_url"]),
                model=str(live_settings["ollama_model"]),
                timeout_sec=float(live_settings["ollama_timeout_sec"]),
                keep_alive=str(live_settings["ollama_keep_alive"]),
            ),
            bergamot=replace(
                self.settings.bergamot,
                target_lang=bergamot_target,
            ),
            seamless=replace(
                self.settings.seamless,
                target_lang=seamless_target,
                device=str(live_settings["seamless_device"]),
                license_accepted=bool(
                    live_settings.get("seamless_license_accepted", False)

                ),
            ),
        )

        self.engine_manager.update_settings(self.settings)

        self.engine_manager.set_engine(self.settings.translation_engine)

        self.history.set_limit(int(live_settings.get("history_limit", 10)))

        self.bookmark_chapter_cache_limit = max(
            0,
            int(live_settings.get("bookmark_chapter_cache_limit", 10)),
        )

        self._enforce_all_bookmark_cache_limits()

        self._log(
            f"Live-Einstellungen aktiv: Engine {self.settings.translation_engine}, "
            f"Zielsprache {target}"
        )

    def _cache_model(self, engine_name: str) -> str:
        return engine_cache_model(
            engine_name, self.settings.llm.model, self.settings.ollama.model
        )

    def _cache_prompt_version(self, engine_name: str) -> str:
        return engine_cache_prompt_version(engine_name)

    def _seamless_ready(self) -> bool:
        manager = ModelManager(
            seamless_model_dir_override=self.settings.seamless.model_dir,
            log_fn=self._log,
        )

        ok, _msg = validate_seamless_model_dir(manager.seamless_path())

        return ok
    def _touch_ocr_activity(self) -> None:
        if self._ocr_idle_timeout_sec <= 0 or self._closed:
            return
        if self._ocr_idle_timer is not None:
            self._ocr_idle_timer.cancel()

        self._ocr_idle_timer = threading.Timer(
            self._ocr_idle_timeout_sec,
            self._idle_unload_ocr,
        )

        self._ocr_idle_timer.name = "lingoveil-ocr-idle"
        self._ocr_idle_timer.daemon = True
        self._ocr_idle_timer.start()

    def _idle_unload_ocr(self) -> None:
        with self._ocr_lock:
            self._ocr_idle_timer = None
            if self._closed or (self.ocr_engine is None and self.overlay_worker is None):
                return
            if (
                (self.ocr_engine is not None and self.ocr_engine.busy)

                or (self.overlay_worker is not None and self.overlay_worker.busy)

            ):
                self._touch_ocr_activity()

                return
            self._log(f"Bildpipeline-Idle-Limit erreicht ({self._ocr_idle_timeout_sec / 60:g} min)")

            if self.ocr_engine is not None:
                self.ocr_engine.close()

                self.ocr_engine = None
            if self.overlay_worker is not None:
                self.overlay_worker.close()

                self.overlay_worker = None
            self._release_idle_memory()

    @staticmethod
    def _current_rss_mb() -> float:
        try:
            fields = Path("/proc/self/statm").read_text(encoding="ascii").split()

            return int(fields[1]) * os.sysconf("SC_PAGE_SIZE") / (1024.0 * 1024.0)

        except (OSError, ValueError, IndexError):
            return 0.0
    def _release_idle_memory(self) -> None:
        rss_before = self._current_rss_mb()

        preview_count = len(self._page_image_preview_cache)

        pdf_count = len(self._pdf_preview_cache)

        self._page_image_preview_cache.clear()

        self._pdf_preview_cache.clear()

        collected = gc.collect()

        trimmed = False
        try:
            libc = ctypes.CDLL("libc.so.6")

            malloc_trim = libc.malloc_trim
            malloc_trim.argtypes = [ctypes.c_size_t]
            malloc_trim.restype = ctypes.c_int
            trimmed = bool(malloc_trim(0))

        except (AttributeError, OSError):
            pass
        rss_after = self._current_rss_mb()

        self._log(
            "Idle-Speicherbereinigung: "
            f"Preview-Cache {preview_count}, PDF-Cache {pdf_count}, "
            f"GC {collected}, malloc_trim={'ja' if trimmed else 'nein'}, "
            f"RSS {rss_before:.1f}→{rss_after:.1f} MB"
        )

    def _ensure_ocr_engine(self) -> EasyOcrWorker:
        with self._ocr_lock:
            if self.ocr_engine is None:
                self.ocr_engine = EasyOcrWorker(self._log)

        return self.ocr_engine
    def _ensure_overlay_worker(self) -> OverlayWorker:
        with self._ocr_lock:
            if self.overlay_worker is None:
                self.overlay_worker = OverlayWorker(self._log)

            return self.overlay_worker
    def _wait_for_ocr(self, timeout: float = 180.0) -> EasyOcrWorker:
        engine = self._ensure_ocr_engine()

        if not engine.ready.wait(timeout=timeout):
            raise RuntimeError("OCR-Engine nicht bereit")

        if engine.error:
            raise RuntimeError(f"OCR-Initialisierung fehlgeschlagen: {engine.error}")

        with self._ocr_lock:
            self._touch_ocr_activity()

        return engine
    def _run_ocr(self, image: Image.Image) -> tuple[list, list]:
        engine = self._wait_for_ocr()

        with self._ocr_lock:
            raw = self._run_ocr_preserving_detail(engine, image)

            self._touch_ocr_activity()

        run_no = 1
        timestamp = datetime.now(timezone.utc).isoformat()

        _, accepted, rejected = process_ocr_raw(
            raw, image.width, image.height, run_no, timestamp
        )

        groups = self._split_distant_ocr_groups(
            group_english_lines(accepted, run_no),
            run_no,
        )

        self._log(
            f"OCR: {len(accepted)} akzeptiert, {len(rejected)} verworfen, "
            f"{len(groups)} Gruppen"
        )

        return groups, rejected
    def _split_distant_ocr_groups(
        self,
        groups: list[GroupedTextBlock],
        run_no: int,
    ) -> list[GroupedTextBlock]:
        pass
        split_groups: list[GroupedTextBlock] = []
        for group in groups:
            lines = sorted(group.lines, key=lambda line: (line.rect[1], line.center_x))

            if len(lines) < 3:
                split_groups.append(group)

                continue
            typical_height = max(1.0, median(line.height for line in lines))

            dialog_lines = []
            for line in lines:
                latin = "".join(
                    char for char in line.normalized_text if char.isalpha()

                )

                is_oversized_short_effect = (
                    len(latin) <= 4
                    and line.height > typical_height * 2
                    and line.confidence < 0.70
                )

                if not is_oversized_short_effect:
                    dialog_lines.append(line)

            if not dialog_lines:
                continue
            lines = dialog_lines
            segments: list[list] = [[lines[0]]]
            for line in lines[1:]:
                previous = segments[-1][-1]
                vertical_gap = line.rect[1] - previous.rect[3]
                if vertical_gap > max(24.0, typical_height * 1.75):
                    segments.append([])

                segments[-1].append(line)

            if len(segments) == 1:
                split_groups.append(group)

                continue
            for segment in segments:
                rects = [line.rect for line in segment]
                texts = [line.normalized_text for line in segment if line.normalized_text]
                confidences = [line.confidence for line in segment]
                split_groups.append(
                    GroupedTextBlock(
                        id=0,
                        bbox=(
                            min(rect[0] for rect in rects),
                            min(rect[1] for rect in rects),
                            max(rect[2] for rect in rects),
                            max(rect[3] for rect in rects),
                        ),
                        text=" ".join(texts),
                        lines=segment,
                        average_confidence=sum(confidences) / len(confidences),
                        min_confidence=min(confidences),
                        ocr_run=run_no,
                    )

                )

        split_groups.sort(key=lambda item: (item.bbox[1], item.bbox[0]))

        for index, group in enumerate(split_groups, start=1):
            group.id = index
        if len(split_groups) != len(groups):
            self._log(
                f"OCR-Gruppentrennung: {len(groups)} → {len(split_groups)} Gruppen"
            )

        return split_groups
    def _run_ocr_preserving_detail(self, engine: Any, image: Image.Image) -> list:
        pass
        tile_height = 2400
        overlap = 240
        if image.height <= tile_height:
            return engine.run_ocr(image)

        raw: list = []
        step = tile_height - overlap
        starts = list(range(0, image.height, step))

        if starts and starts[-1] + tile_height >= image.height:
            starts[-1] = max(0, image.height - tile_height)

        starts = list(dict.fromkeys(starts))

        for tile_index, top in enumerate(starts):
            bottom = min(image.height, top + tile_height)

            tile = image.crop((0, top, image.width, bottom))

            tile_raw = engine.run_ocr(tile)

            previous_bottom = (
                min(image.height, starts[tile_index - 1] + tile_height)

                if tile_index > 0
                else top
            )

            keep_from = (
                top
                if tile_index == 0
                else (top + previous_bottom) / 2
            )

            next_top = (
                starts[tile_index + 1]
                if tile_index < len(starts) - 1
                else bottom
            )

            keep_until = (
                bottom
                if tile_index == len(starts) - 1
                else (bottom + next_top) / 2
            )

            for bbox, text, confidence in tile_raw:
                translated_bbox = [
                    [float(point[0]), float(point[1]) + top]
                    for point in bbox
                ]
                center_y = sum(point[1] for point in translated_bbox) / len(translated_bbox)

                if keep_from <= center_y < keep_until:
                    raw.append((translated_bbox, text, confidence))

        self._log(
            f"OCR-Kachelung: {len(starts)} Abschnitte für "
            f"{image.width}×{image.height}px"
        )

        return raw
    def _translate_groups(self, groups: list, engine_name: str) -> dict[str, dict[str, str]]:
        if not groups:
            return {}

        if engine_name == TRANSLATION_ENGINE_OLLAMA and not self.ollama_available:
            raise RuntimeError(
                "Ollama ist nicht verfügbar. Bitte den Verbindungstest unter "
                "Optionen → Modelle erneut ausführen."
            )

        self._ensure_engine(engine_name)

        if engine_name == TRANSLATION_ENGINE_SEAMLESS_M4T and not self._seamless_ready():
            raise RuntimeError(
                "SeamlessM4T-Modell fehlt. Bitte über „Modelle“ herunterladen."
            )

        group_pairs = [(group_id_str(g.id), g.text) for g in groups]
        plan = plan_translation_batch(
            group_pairs,
            cache=self.persistent_cache,
            model=self._cache_model(engine_name),
            prompt_version=self._cache_prompt_version(engine_name),
            source_lang=self._source_language(engine_name),
            target_lang=self._target_language(engine_name),
            translation_engine=engine_name,
            inflight_keys=set(),
            skip_cache=False,
            session_hits=self.session_resolved,
        )

        translations: dict[str, dict[str, str]] = {}

        for gid, entry in plan.already_cached_group_ids.items():
            translations[gid] = {
                "german": entry.translated_text,
                "cache_source": CACHE_SOURCE_PERSISTENT_CACHE,
                "status": "übersetzt",
            }

        if plan.blocks_to_send:
            engine_blocks = [{"id": b["id"], "text": b["text"]} for b in plan.blocks_to_send]
            results = self.engine_manager.translate_blocks(
                engine_blocks,
                request_generation=self.engine_manager.generation,
            )

            for item in results:
                block = next(
                    (b for b in plan.blocks_to_send if b["id"] == item.block_id),
                    None,
                )

                if block is None:
                    continue
                cache_key = block["_cache_key"]
                ocr_text = block["text"]
                set_cached_translation(
                    self.persistent_cache,
                    cache_key,
                    source_lang=self._source_language(engine_name),
                    target_lang=self._target_language(engine_name),
                    model=self._cache_model(engine_name),
                    prompt_version=self._cache_prompt_version(engine_name),
                    normalized_source_text=normalize_source_text(ocr_text),
                    original_ocr_text=ocr_text,
                    corrected_source=item.corrected_source,
                    translated_text=item.translation,
                    translation_engine=engine_name,
                )

                self.session_resolved[cache_key] = self.persistent_cache.entries[cache_key]
                status = "übersetzt"
                if item.error:
                    status = "Fallback: OCR-Text"
                    self._log(
                        f"Bergamot lieferte keine Übersetzung für {item.block_id}; "
                        "verwende OCR-Text als Fallback"
                    )

                for resolved_id in plan.key_to_group_ids.get(
                    cache_key, [item.block_id]
                ):
                    translations[resolved_id] = {
                        "german": item.translation,
                        "cache_source": "new_translation",
                        "status": status,
                    }

            save_cache_atomic(translation_cache_path(), self.persistent_cache)

        return translations
    def _source_language(self, engine_name: str) -> str:
        if engine_name in (TRANSLATION_ENGINE_SEAMLESS_M4T, TRANSLATION_ENGINE_OLLAMA):
            return self.settings.seamless.source_lang
        return self.settings.bergamot.source_lang
    def _target_language(self, engine_name: str) -> str:
        if engine_name in (TRANSLATION_ENGINE_SEAMLESS_M4T, TRANSLATION_ENGINE_OLLAMA):
            return self.settings.seamless.target_lang
        return self.settings.bergamot.target_lang
    def _on_ollama_unavailable(self, reason: str) -> None:
        self.ollama_available = False
        self._log(f"Ollama wurde als nicht verfügbar markiert: {reason}")

        if self.ollama_unavailable_callback is not None:
            self.ollama_unavailable_callback(reason)

    def _render_exact_overlay(
        self,
        image: Image.Image,
        groups: list,
        translations: dict[str, dict[str, str]],
    ) -> tuple[Path, list[dict[str, Any]]]:
        grouped_input: list[list[Any]] = []
        for group in groups:
            gid = group_id_str(group.id)

            tr = translations.get(gid, {})

            grouped_input.append(
                [
                    gid,
                    list(group.bbox),
                    group.text,
                    tr.get("german", ""),
                    tr.get("status", "übersetzt" if tr.get("german") else "wird übersetzt"),
                    tr.get("cache_source", ""),
                    self.engine_manager.active_engine,
                ]
            )

        request_id = uuid.uuid4().hex
        input_path = self.session_dir / f"overlay-{request_id}-input.png"
        output_path = self.session_dir / f"overlay-{request_id}-rendered.png"
        save_image_copy(image, input_path)

        worker = self._ensure_overlay_worker()

        infos = worker.render(
            input_path=input_path,
            output_path=output_path,
            grouped=grouped_input,
        )

        input_path.unlink(missing_ok=True)

        with self._ocr_lock:
            self._touch_ocr_activity()

        return output_path, infos
    def _save_artifacts(
        self,
        *,
        source_image: Image.Image,
        rendered_image: Path,
        infos: list[dict[str, Any]],
        engine_name: str,
        extra: dict[str, Any] | None = None,
        pdf_page: bool = False,
    ) -> dict[str, str]:
        input_path = self.artifacts_dir / "browser_input_latest.png"
        rendered_path = self.artifacts_dir / "browser_rendered_latest.png"
        json_path = self.artifacts_dir / "browser_latest.json"
        save_image_copy(source_image, input_path)

        shutil.copyfile(rendered_image, rendered_path)

        if pdf_page:
            save_image_copy(source_image, self.artifacts_dir / "browser_pdf_page_latest.png")

        stats = self.engine_manager.stats
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "engine": engine_name,
            "engine_display_name": engine_display_name(engine_name),
            "render_mode": "exact_group_bbox",
            "session_id": self.session_id,
            "groups": infos,
            "request_counters": {
                "bergamot": stats.bergamot_requests,
                "seamless_m4t": stats.seamless_m4t_requests,
                "lm_studio": stats.lm_studio_requests,
                "ollama": stats.ollama_requests,
            },
            "cache_hits": {
                "session": len(self.session_resolved),
                "persistent": sum(
                    1 for g in infos if g.get("cache_source") == "persistent_cache"
                ),
            },
        }

        if extra:
            payload.update(extra)

        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        return {
            "input_image_path": str(input_path),
            "rendered_image_path": str(rendered_path),
            "json_path": str(json_path),
        }

    def process_image(self, image: Image.Image, engine_name: str) -> dict[str, Any]:
        engine_name = validate_translation_engine(engine_name)

        groups, _ = self._run_ocr(image)

        translations = self._translate_groups(groups, engine_name)

        rendered, infos = self._render_exact_overlay(image, groups, translations)

        paths = self._save_artifacts(
            source_image=image,
            rendered_image=rendered,
            infos=infos,
            engine_name=engine_name,
        )

        rendered.unlink(missing_ok=True)

        return {
            "engine": engine_name,
            "target_language": self._target_language(engine_name),
            "engine_display_name": engine_display_name(engine_name),
            "groups": infos,
            "rendered_image_path": paths.get("rendered_image_path", ""),
            "input_image_path": paths.get("input_image_path", ""),
            "json_path": paths.get("json_path", ""),
            "request_counters": {
                "bergamot": self.engine_manager.stats.bergamot_requests,
                "seamless_m4t": self.engine_manager.stats.seamless_m4t_requests,
                "lm_studio": self.engine_manager.stats.lm_studio_requests,
            },
            "cache_hits": len(self.session_resolved),
            "group_count": len(infos),
        }

    def store_uploaded_image(self, data: bytes, filename: str) -> str:
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError("Bilddatei zu groß (max. 25 MB)")

        image_id = uuid.uuid4().hex[:10]
        path = self.session_dir / f"{image_id}_{Path(filename).name}"
        path.write_bytes(data)

        load_image_bytes(data)

        self._stored_images[image_id] = path
        return image_id
    def store_uploaded_pdf(self, data: bytes, filename: str) -> tuple[str, int]:
        if len(data) > MAX_PDF_BYTES:
            raise ValueError("PDF-Datei zu groß (max. 100 MB)")

        if not is_pdf_bytes(data):
            raise ValueError("Keine gültige PDF-Datei")

        pdf_id = uuid.uuid4().hex[:10]
        path = self.session_dir / f"{pdf_id}_{Path(filename).name}"
        path.write_bytes(data)

        pages = pdf_page_count(path)

        self._stored_pdfs[pdf_id] = path
        return pdf_id, pages
    def process_stored_image(self, image_id: str, engine_name: str) -> dict[str, Any]:
        path = self._stored_images.get(image_id)

        if path is None:
            raise ValueError("Unbekannte Bild-ID")

        return self.process_image(load_image_file(path), engine_name)

    def process_pdf_page(
        self,
        pdf_path: Path,
        page_number: int,
        engine_name: str,
    ) -> dict[str, Any]:
        page_image = render_pdf_page(pdf_path, page_number)

        engine_name = validate_translation_engine(engine_name)

        groups, _ = self._run_ocr(page_image)

        translations = self._translate_groups(groups, engine_name)

        rendered, infos = self._render_exact_overlay(page_image, groups, translations)

        paths = self._save_artifacts(
            source_image=page_image,
            rendered_image=rendered,
            infos=infos,
            engine_name=engine_name,
            extra={"pdf_page": page_number},
            pdf_page=True,
        )

        rendered.unlink(missing_ok=True)

        return {
            "engine": engine_name,
            "page_number": page_number,
            "page_count": pdf_page_count(pdf_path),
            "groups": infos,
            "rendered_image_path": paths["rendered_image_path"],
            "input_image_path": paths["input_image_path"],
            "json_path": paths["json_path"],
            "request_counters": {
                "bergamot": self.engine_manager.stats.bergamot_requests,
                "seamless_m4t": self.engine_manager.stats.seamless_m4t_requests,
                "lm_studio": self.engine_manager.stats.lm_studio_requests,
            },
            "cache_hits": len(self.session_resolved),
        }

    def process_stored_pdf_page(
        self,
        pdf_id: str,
        page_number: int,
        engine_name: str,
    ) -> dict[str, Any]:
        path = self._stored_pdfs.get(pdf_id)

        if path is None:
            raise ValueError("Unbekannte PDF-ID")

        return self.process_pdf_page(path, page_number, engine_name)

    def download_image_url(self, url: str) -> str:
        validate_remote_url(url)

        data, _ = download_url_bytes(
            url,
            max_bytes=MAX_IMAGE_BYTES,
            allowed_content_types=ALLOWED_IMAGE_MIME | {"application/octet-stream"},
            log_fn=self._log,
        )

        image_id = self.store_uploaded_image(data, _url_basename(url))

        self._page_image_urls[image_id] = url
        entry = self.history.touch(url, [{"url": url}], kind="image")

        self._page_image_history[image_id] = (
            entry["id"],
            entry["images"][0]["key"],
        )

        return image_id
    def download_pdf_url(self, url: str) -> tuple[str, int]:
        validate_remote_url(url)

        data, content_type = download_url_bytes(
            url,
            max_bytes=MAX_PDF_BYTES,
            allowed_content_types={"application/pdf", "application/octet-stream"},
            log_fn=self._log,
        )

        if not is_pdf_bytes(data):
            raise ValueError("URL lieferte keine PDF-Datei")

        return self.store_uploaded_pdf(data, _url_basename(url))

    def pdf_page_preview_png(self, pdf_id: str, page_number: int) -> bytes:
        cache_key = (pdf_id, page_number)

        cached = self._pdf_preview_cache.get(cache_key)

        if cached is not None:
            return cached
        path = self._stored_pdfs.get(pdf_id)

        if path is None:
            raise ValueError("Unbekannte PDF-ID")

        image = render_pdf_page(path, page_number)

        buffer = BytesIO()

        image.save(buffer, format="PNG")

        png = buffer.getvalue()

        if len(self._pdf_preview_cache) >= self._pdf_preview_cache_limit:
            oldest = next(iter(self._pdf_preview_cache))

            self._pdf_preview_cache.pop(oldest, None)

        self._pdf_preview_cache[cache_key] = png
        return png
    def analyze_page_images(self, url: str) -> dict[str, Any]:
        validate_remote_url(url)

        metadata = self._catalog_chapter_metadata.get(url, {})

        if mangadex_chapter_id(url):
            images = resolve_mangadex_chapter(url)

            self._log(f"MangaDex-API: {len(images)} Chapter-Seiten erkannt")

            history_entry = self.history.touch(
                url,
                images,
                kind="mangadex",
                metadata=metadata,
            )

            self._record_bookmark_read(history_entry)

            return self._register_history_entry(history_entry)

        if mangatown_chapter(url):
            canonical_url, images = resolve_mangatown_chapter(
                url,
                log_fn=self._log,
            )

            self._log(f"MangaTown: {len(images)} Chapter-Seiten erkannt")

            history_entry = self.history.touch(
                canonical_url,
                images,
                kind="mangatown",
                metadata=metadata,
            )

            self._record_bookmark_read(history_entry)

            return self._register_history_entry(history_entry)

        html = fetch_page_html(url, log_fn=self._log)

        images = extract_page_images(html, url)

        history_entry = self.history.touch(
            url,
            images,
            kind="page",
            metadata=metadata,
        )

        self._record_bookmark_read(history_entry)

        return self._register_history_entry(history_entry)

    def analyze_manga_catalog(self, url: str) -> dict[str, Any]:
        catalog = resolve_manga_catalog(url, log_fn=self._log)

        if not catalog.get("is_catalog"):
            return catalog
        bookmark = self.bookmarks.get_by_url(str(catalog.get("url", "")))

        catalog["bookmarked"] = bookmark is not None
        catalog["last_read_url"] = (bookmark or {}).get("last_read_url", "")

        catalog["last_read_at"] = (bookmark or {}).get("last_read_at", "")

        catalog["read_chapters"] = (bookmark or {}).get("chapters", {})

        catalog["new_chapters"] = (bookmark or {}).get("new_chapters", [])

        catalog["last_checked_at"] = (bookmark or {}).get("last_checked_at", "")

        for group in catalog.get("groups", []):
            for chapter in group.get("chapters", []):
                chapter_url = str(chapter.get("url", ""))

                if chapter_url:
                    self._catalog_chapter_metadata[chapter_url] = {
                        "manga_title": str(catalog.get("title", "")),
                        "site": str(catalog.get("site", "")),
                        "volume": str(chapter.get("volume", "")),
                        "chapter": str(chapter.get("chapter", "")),
                        "chapter_label": str(chapter.get("label", "")),
                        "manga_url": str(catalog.get("url", "")),
                    }

        return catalog
    def list_bookmarks(self) -> list[dict[str, Any]]:
        return self.bookmarks.list()

    def add_bookmark(self, *, url: str, title: str, site: str) -> dict[str, Any]:
        if not is_supported_manga_url(url):
            raise ValueError(
                "Bookmarks werden derzeit nur für MangaRead, MangaTown "
                "und MangaDex unterstützt"
            )

        catalog = resolve_manga_catalog(url, log_fn=self._log)

        chapters = self._catalog_chapter_snapshot(catalog)

        return self.bookmarks.add(
            url=url,
            title=title,
            site=site,
            catalog_chapters=chapters,
        )

    def remove_bookmark(self, url: str, *, delete_reading_data: bool) -> None:
        self.bookmarks.remove(url, delete_reading_data=delete_reading_data)

        self.history.set_limit(self.history.limit)

    @staticmethod
    def _catalog_chapter_snapshot(
        catalog: dict[str, Any],
    ) -> list[dict[str, str]]:
        chapters = [
            {
                "url": str(chapter.get("url", "")),
                "volume": str(chapter.get("volume", "")),
                "chapter": str(chapter.get("chapter", "")),
                "label": str(chapter.get("label", "")),
                "language": str(chapter.get("language", "")),
            }

            for group in catalog.get("groups", [])

            for chapter in group.get("chapters", [])

            if chapter.get("url")

        ]
        def numeric(value: str) -> tuple:
            return tuple(
                float(part) if re.fullmatch(r"\d+(?:\.\d+)?", part) else -1.0
                for part in re.findall(r"\d+(?:\.\d+)?", value)

            ) or (-1.0,)

        chapters.sort(
            key=lambda item: (
                numeric(item["volume"]),
                numeric(item["chapter"]),
            ),
            reverse=True,
        )

        return chapters
    def check_bookmark_updates(self, *, force: bool) -> dict[str, Any]:
        if not self._bookmark_check_lock.acquire(blocking=False):
            return {
                "status": "running",
                "checked": 0,
                "new_chapters": 0,
                "errors": [],
            }

        try:
            now = datetime.now(timezone.utc)

            checked = 0
            new_count = 0
            errors: list[str] = []
            discoveries: list[dict[str, Any]] = []
            for bookmark in self.bookmarks.list():
                last_checked = str(bookmark.get("last_checked_at", ""))

                if not force and last_checked:
                    try:
                        age = (now - datetime.fromisoformat(last_checked)).total_seconds()

                        if age < 12 * 60 * 60:
                            continue
                    except ValueError:
                        pass
                try:
                    catalog = resolve_manga_catalog(
                        str(bookmark["url"]),
                        log_fn=self._log,
                    )

                    before = {
                        str(item.get("url", ""))

                        for item in bookmark.get("new_chapters", [])
                    }

                    updated = self.bookmarks.update_catalog_snapshot(
                        str(bookmark["url"]),
                        self._catalog_chapter_snapshot(catalog),
                    )

                    after = {
                        str(item.get("url", ""))

                        for item in (updated or {}).get("new_chapters", [])
                    }

                    new_count += len(after - before)

                    newly_found = [
                        item
                        for item in (updated or {}).get("new_chapters", [])

                        if str(item.get("url", "")) in after - before
                    ]
                    if newly_found:
                        discoveries.append({
                            "bookmark_id": str(bookmark.get("id", "")),
                            "title": str(bookmark.get("title", "")),
                            "manga_url": str(bookmark.get("url", "")),
                            "chapters": newly_found,
                        })

                    checked += 1
                except Exception as exc:
                    errors.append(f"{bookmark.get('title', bookmark['url'])}: {exc}")

            return {
                "status": "completed",
                "checked": checked,
                "new_chapters": new_count,
                "errors": errors,
                "discoveries": discoveries,
            }

        finally:
            self._bookmark_check_lock.release()

    def _record_bookmark_read(self, entry: dict[str, Any]) -> None:
        metadata = entry.get("metadata", {})

        manga_url = str(metadata.get("manga_url", ""))

        if not manga_url:
            return
        bookmark = self.bookmarks.mark_read(
            manga_url=manga_url,
            chapter_url=str(entry.get("url", "")),
            volume=str(metadata.get("volume", "")),
            chapter=str(metadata.get("chapter", "")),
            label=str(metadata.get("chapter_label", "")),
        )

        if bookmark is not None:
            self._enforce_bookmark_cache_limit(manga_url)

    def _enforce_bookmark_cache_limit(self, manga_url: str) -> None:
        limit = self.bookmark_chapter_cache_limit
        if limit == 0:
            return
        keep = self.bookmarks.recent_chapter_urls(manga_url, limit)

        removed = self.history.prune_bookmark_assets(manga_url, keep)

        if removed:
            self._log(
                f"Bookmark-Cachelimit: {removed} alte Bildartefakt(e) freigegeben"
            )

    def _enforce_all_bookmark_cache_limits(self) -> None:
        if self.bookmark_chapter_cache_limit == 0:
            return
        for bookmark in self.bookmarks.list():
            self._enforce_bookmark_cache_limit(str(bookmark.get("url", "")))

    def _register_history_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        stored: list[dict[str, str]] = []
        chapter_navigation = self.bookmarks.chapter_navigation(entry["url"])

        if chapter_navigation["enabled"]:
            metadata = entry.get("metadata", {})

            chapter = str(
                metadata.get("chapter", "")

                or chapter_navigation.get("chapter", "")

            )

            chapter_navigation["chapter"] = chapter
            chapter_navigation["chapter_label"] = str(
                metadata.get("chapter_label", "")

                or chapter_navigation.get("chapter_label", "")

                or (f"Chapter {chapter}" if chapter else "Chapter")

            )

        social_urls = {
            item["url"]
            for item in entry.get("images", [])

            if is_social_preview_url(item["url"])
        }

        if social_urls:
            self.history.remove_image_urls(entry["id"], social_urls)

            entry = {
                **entry,
                "images": [
                    item for item in entry.get("images", [])

                    if item["url"] not in social_urls
                ],
            }

            self._log(
                f"{len(social_urls)} Social-Preview-Bild(er) aus History entfernt"
            )

        for item in entry.get("images", []):
            if is_gif_url(item["url"]):
                continue
            image_id = uuid.uuid4().hex[:10]
            image_url = item["url"]
            self._page_image_urls[image_id] = image_url
            self._page_image_sources[image_id] = (
                item.get("source_url") or entry["url"]
            )

            self._page_image_history[image_id] = (entry["id"], item["key"])

            preview_url = f"/api/page-image-preview/{image_id}"
            if item.get("original_file"):
                try:
                    self.history.asset_path(str(item["original_file"]))

                except (ValueError, FileNotFoundError):
                    pass
                else:
                    preview_url = f"/api/history/assets/{item['original_file']}"
            cached_translations = {}

            translated_engines: set[str] = set()

            for stored_key, files in item.get("translations", {}).items():
                rendered_file = str(files.get("rendered_file", ""))

                result_file = str(files.get("result_file", ""))

                try:
                    self.history.asset_path(rendered_file)

                    self.history.asset_path(result_file)

                except (ValueError, FileNotFoundError):
                    continue
                try:
                    cached_result = json.loads(
                        self.history.asset_path(result_file).read_text(encoding="utf-8")

                    )

                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                engine = str(cached_result.get("engine") or stored_key.split(":", 1)[0])

                legacy_target = (
                    "deu" if engine in (
                        TRANSLATION_ENGINE_SEAMLESS_M4T, TRANSLATION_ENGINE_OLLAMA
                    ) else "de"
                )

                target_language = str(cached_result.get("target_language", legacy_target))

                variant_key = f"{engine}:{target_language}"
                cached_translations[variant_key] = {
                    "rendered_url": f"/api/history/assets/{rendered_file}",
                    "result_url": f"/api/history/assets/{result_file}",
                    "engine": engine,
                    "target_language": target_language,
                }

                translated_engines.add(engine)

            stored.append(
                {
                    "id": image_id,
                    "history_id": entry["id"],
                    "url": image_url,
                    "preview_url": preview_url,
                    "translated_engines": sorted(translated_engines),
                    "translated_variants": sorted(cached_translations.keys()),
                    "cached_translations": cached_translations,
                }

            )

        if not stored:
            return {
                "images": [],
                "chapter_navigation": chapter_navigation,
                "message": (
                    "Auf dieser Webseite konnten keine direkt ladbaren Bilder "
                    "erkannt werden. Nutze alternativ den Desktop-Modus."
                ),
            }

        return {
            "history_id": entry["id"],
            "url": entry["url"],
            "images": stored,
            "chapter_navigation": chapter_navigation,
            "message": "",
        }

    def open_history(self, entry_id: str) -> dict[str, Any]:
        entry = self.history.get(entry_id)

        if entry is None:
            raise ValueError("History-Eintrag nicht gefunden")

        images = entry.get("images", [])

        missing_assets = not images or any(
            not str(image.get("original_file", "")).strip()

            for image in images
        )

        for image in images:
            referenced_files = [str(image.get("original_file", ""))]
            for files in image.get("translations", {}).values():
                referenced_files.extend(
                    [str(files.get("rendered_file", "")), str(files.get("result_file", ""))]
                )

            for relative_path in filter(None, referenced_files):
                try:
                    self.history.asset_path(relative_path)

                except (ValueError, FileNotFoundError):
                    missing_assets = True
                    break
            if missing_assets:
                break
        if entry.get("needs_refresh") or missing_assets:
            self._log(f"Unvollständige History wird vollständig neu geladen: {entry['url']}")

            return self.analyze_page_images(entry["url"])

        if entry.get("kind") == "mangadex" or mangadex_chapter_id(entry["url"]):
            images = resolve_mangadex_chapter(entry["url"])

            entry = self.history.touch(entry["url"], images, kind="mangadex")

            self._log(
                f"MangaDex-History aktualisiert: {len(images)} Chapter-Seiten"
            )

        elif entry.get("kind") == "mangatown" or mangatown_chapter(entry["url"]):
            canonical_url, images = resolve_mangatown_chapter(
                entry["url"],
                log_fn=self._log,
            )

            entry = self.history.touch(
                canonical_url,
                images,
                kind="mangatown",
            )

            self._log(
                f"MangaTown-History aktualisiert: {len(images)} Chapter-Seiten"
            )

        self._record_bookmark_read(entry)

        return self._register_history_entry(entry)

    def page_image_preview(self, image_id: str) -> tuple[bytes, str]:
        cached = self._page_image_preview_cache.get(image_id)

        if cached is not None:
            return cached
        url = self._page_image_urls.get(image_id)

        if not url:
            raise ValueError("Unbekannte Bild-ID")

        source_url = self._page_image_sources.get(image_id, url)

        data, content_type = self.fetch_strategies.download(
            url,
            source_url=source_url,
            max_bytes=MAX_IMAGE_BYTES,
            allowed_content_types=ALLOWED_IMAGE_MIME | {"application/octet-stream"},
        )

        load_image_bytes(data)

        return self._remember_page_image_preview(image_id, data, content_type)

    def _remember_page_image_preview(
        self,
        image_id: str,
        data: bytes,
        content_type: str,
    ) -> tuple[bytes, str]:
        if len(self._page_image_preview_cache) >= self._page_image_preview_cache_limit:
            oldest = next(iter(self._page_image_preview_cache))

            self._page_image_preview_cache.pop(oldest, None)

        cached = (data, content_type or "image/jpeg")

        self._page_image_preview_cache[image_id] = cached
        return cached
    def process_page_image(
        self, image_id: str, engine_name: str, *, force: bool = False
    ) -> dict[str, Any]:
        url = self._page_image_urls.get(image_id)

        if not url:
            path = self._stored_images.get(image_id)

            if path is not None:
                return self.process_stored_image(image_id, engine_name)

            raise ValueError("Unbekannte Bild-ID")

        history_ref = self._page_image_history.get(image_id)

        if history_ref and not force:
            cached = self.history.cached_translation(
                *history_ref, engine_name, self._target_language(engine_name)

            )

            if cached is not None:
                result, rendered, original = cached
                current_target = self._target_language(engine_name)

                legacy_target = "deu" if engine_name in (
                    TRANSLATION_ENGINE_SEAMLESS_M4T, TRANSLATION_ENGINE_OLLAMA
                ) else "de"
                cached_target = str(result.get("target_language", legacy_target))

                if cached_target != current_target:
                    self._log(
                        "History-Cache wegen geänderter Zielsprache verworfen: "
                        f"{cached_target} -> {current_target}"
                    )

                    cached = None
            if cached is not None:
                result, rendered, original = cached
                shutil.copyfile(
                    rendered,
                    self.artifacts_dir / "browser_rendered_latest.png",
                )

                shutil.copyfile(
                    original,
                    self.artifacts_dir / "browser_input_latest.png",
                )

                result = dict(result)

                result["history_cache_hit"] = True
                result["rendered_url"] = (
                    "/api/history/assets/"
                    f"{rendered.relative_to(self.history.assets_dir)}"
                )

                result["translation_variant"] = (
                    f"{engine_name}:{cached_target}"
                )

                self._log(f"History-Cache verwendet: {history_ref[0]} / {image_id}")

                return result
        preview = self._page_image_preview_cache.get(image_id)

        if preview is not None:
            data = preview[0]
        else:
            source_url = self._page_image_sources.get(image_id, url)

            data, content_type = self.fetch_strategies.download(
                url,
                source_url=source_url,
                max_bytes=MAX_IMAGE_BYTES,
                allowed_content_types=ALLOWED_IMAGE_MIME | {"application/octet-stream"},
            )

            self._remember_page_image_preview(image_id, data, content_type)

        result = self.process_image(load_image_bytes(data), engine_name)

        if history_ref:
            saved_variant = self.history.save_translation(
                entry_id=history_ref[0],
                image_key=history_ref[1],
                engine=engine_name,
                original=data,
                rendered_path=Path(result["rendered_image_path"]),
                result=result,
            )

            if saved_variant:
                result["rendered_url"] = (
                    f"/api/history/assets/{saved_variant['rendered_file']}"
                )

                result["translation_variant"] = saved_variant["variant_key"]
        return result
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with self._ocr_lock:
            if self._ocr_idle_timer is not None:
                self._ocr_idle_timer.cancel()

                self._ocr_idle_timer = None
            if self.ocr_engine is not None:
                self.ocr_engine.close()

                self.ocr_engine = None
            if self.overlay_worker is not None:
                self.overlay_worker.close()

                self.overlay_worker = None
        try:
            self.engine_manager.close()

        except Exception as exc:
            self._log(f"Engine-Shutdown-Fehler: {exc}")

        try:
            save_cache_atomic(translation_cache_path(), self.persistent_cache)

        except Exception as exc:
            self._log(f"Cache-Speichern fehlgeschlagen: {exc}")

        try:
            if self.session_dir.exists():
                shutil.rmtree(self.session_dir, ignore_errors=True)

        except Exception as exc:
            self._log(f"Session-Bereinigung fehlgeschlagen: {exc}")

        self._log("Pipeline geschlossen")

def _url_basename(url: str) -> str:
    path = urlparse(url).path
    name = Path(path).name
    return name or "download.bin"
