from __future__ import annotations
import json
import os
import secrets
import signal
import shutil
import subprocess
import sys
import tempfile
import threading

from datetime import datetime
from pathlib import Path
from typing import Any
import uvicorn

from fastapi import Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, HttpUrl
from core.app_paths import AppPaths
from core.model_manager import AppModelManager, ModelManagerError
from lingoveil_browser_pipeline import BrowserTranslationPipeline
from lingoveil_browser_server import create_app
from lingoveil_bookmarks import DatabaseMangaBookmarkStore
from lingoveil_config import LlmSettings, SUPPORTED_TRANSLATION_ENGINES
from lingoveil_database import AuthService, Database, UserDataStore
from lingoveil_history import DatabaseLiveHistoryStore
from lingoveil_jobs import FairTranslationQueue
from lingoveil_model_manager import (
    SEAMLESS_MODEL_LICENSE,
    SEAMLESS_MODEL_SIZE_GIB,
)

from lingoveil_notifications import ChapterNotificationMailer
from lingoveil_translation_cache import engine_display_name
from lingoveil_llm import LlmTranslator
from lingoveil_ollama import (
    OllamaSettings,
    OllamaTranslationError,
    OllamaTranslator,
    ollama_model_capabilities,
    ollama_supported_lingoveil_languages,
)

from lingoveil_update import APP_VERSION, UpdateChecker
VERSION = APP_VERSION
DATA_DIR = Path(os.environ.get("LINGOVEIL_LIVE_DATA_DIR", "/app/data")).resolve()

MODELS_DIR = Path(os.environ.get("LINGOVEIL_LIVE_MODELS_DIR", "/app/modelle")).resolve()

CACHE_DIR = Path(os.environ.get("LINGOVEIL_LIVE_CACHE_DIR", "/app/cache")).resolve()

SETTINGS_FILE = DATA_DIR / "settings.json"
MODEL_UPLOAD_LIMIT = 12 * 1024**3
DEFAULTS: dict[str, Any] = {
    "theme": "dark",
    "interface_language": "en",
    "chapter_email_notifications": False,
    "engine": "bergamot",
    "source_language": "eng",
    "target_language": "deu",
    "prefetch_count": 10,
    "history_limit": 10,
    "bookmark_chapter_cache_limit": 10,
    "browser_cache_ttl_sec": 300,
    "ocr_min_image_width": 150,
    "ocr_min_image_height": 150,
    "default_view": "translated",
    "lm_studio_base_url": "",
    "lm_studio_model": "",
    "lm_studio_timeout_sec": 120,
    "ollama_base_url": "http://host.docker.internal:11435",
    "ollama_model": "translategemma:4b",
    "ollama_timeout_sec": 120,
    "ollama_keep_alive": "2m",
    "ollama_status": "NOT_TESTED",
    "ollama_last_error": "",
    "seamless_device": "auto",
    "seamless_license_accepted": False,
    "overlay_mode": "exact_group_bbox",
    "show_overflow": True,
    "show_debug_areas": False,
}

SEAMLESS_TARGET_LANGUAGES = {
    "afr", "amh", "arb", "ary", "arz", "asm", "azj", "bel", "ben", "bos",
    "bul", "cat", "ceb", "ces", "ckb", "cmn", "cmn_Hant", "cym", "dan",
    "deu", "ell", "eng", "est", "eus", "fin", "fra", "fuv", "gaz", "gle",
    "glg", "guj", "heb", "hin", "hrv", "hun", "hye", "ibo", "ind", "isl",
    "ita", "jav", "jpn", "kan", "kat", "kaz", "khk", "khm", "kir", "kor",
    "lao", "lit", "lug", "luo", "lvs", "mai", "mal", "mar", "mkd", "mlt",
    "mni", "mya", "nld", "nno", "nob", "npi", "nya", "ory", "pan", "pbt",
    "pes", "pol", "por", "ron", "rus", "sat", "slk", "slv", "sna", "snd",
    "som", "spa", "srp", "swe", "swh", "tam", "tel", "tgk", "tgl", "tha",
    "tur", "ukr", "urd", "uzn", "vie", "yor", "yue", "zlm", "zul",
}

BERGAMOT_TARGET_LANGUAGES = {
    "bul", "ces", "deu", "spa", "est", "fra", "ita", "por", "rus", "ukr",
}

OLLAMA_STATUSES = {"NOT_CONFIGURED", "NOT_TESTED", "AVAILABLE", "UNAVAILABLE"}

def _paths() -> AppPaths:
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
        settings_file=SETTINGS_FILE,
        logs_dir=DATA_DIR / "logs",
        desktop_entry_dir=DATA_DIR / "unused-desktop",
    )

def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)

            handle.write("\n")

            handle.flush()

            os.fsync(handle.fileno())

        os.replace(name, path)

    finally:
        Path(name).unlink(missing_ok=True)

def load_settings() -> tuple[dict[str, Any], str | None]:
    if not SETTINGS_FILE.is_file():
        return dict(DEFAULTS), None
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))

        merged = {**DEFAULTS, **raw}

        if (
            os.environ.get("LINGOVEIL_OLLAMA_BRIDGE_TOKEN", "").strip()

            and merged.get("ollama_base_url") == "http://host.docker.internal:11434"
        ):
            merged["ollama_base_url"] = "http://host.docker.internal:11435"
            merged["ollama_status"] = "NOT_TESTED"
            merged["ollama_last_error"] = ""
        return validate_settings(merged), None
    except Exception as exc:
        return dict(DEFAULTS), f"Beschädigte Konfiguration; sichere Standardwerte aktiv: {exc}"
def validate_settings(raw: dict[str, Any]) -> dict[str, Any]:
    value = dict(DEFAULTS)

    value.update(raw)

    if value["engine"] not in SUPPORTED_TRANSLATION_ENGINES:
        raise ValueError("Unbekannte Engine")

    if value["theme"] not in {"dark", "light"}:
        raise ValueError("Theme muss dark oder light sein")

    if value["interface_language"] not in {"de", "en"}:
        raise ValueError("Oberflächensprache muss de oder en sein")

    if value["target_language"] not in SEAMLESS_TARGET_LANGUAGES:
        raise ValueError("Diese Zielsprache wird von SeamlessM4T nicht unterstützt")

    if value["engine"] == "bergamot" and value["target_language"] not in BERGAMOT_TARGET_LANGUAGES:
        raise ValueError(
            "Diese Zielsprache wird von Bergamot nicht unterstützt. "
            "Bitte zuerst SeamlessM4T auswählen."
        )

    if value["engine"] == "lm_studio" and value["target_language"] != "deu":
        raise ValueError("LM Studio ist derzeit nur für die Zielsprache Deutsch konfiguriert")

    ollama_languages = set(ollama_supported_lingoveil_languages(str(value["ollama_model"])))

    if value["engine"] == "ollama" and ollama_languages and value["target_language"] not in ollama_languages:
        raise ValueError("Diese Zielsprache wird vom ausgewählten Ollama-Modell nicht unterstützt")

    value["prefetch_count"] = int(value["prefetch_count"])

    if not 0 <= value["prefetch_count"] <= 100:
        raise ValueError("prefetch_count muss zwischen 0 und 100 liegen")

    value["history_limit"] = int(value["history_limit"])

    if not 1 <= value["history_limit"] <= 100:
        raise ValueError("history_limit muss zwischen 1 und 100 liegen")

    value["bookmark_chapter_cache_limit"] = int(
        value["bookmark_chapter_cache_limit"]
    )

    if value["bookmark_chapter_cache_limit"] < 0:
        raise ValueError("bookmark_chapter_cache_limit darf nicht negativ sein")

    value["browser_cache_ttl_sec"] = int(value["browser_cache_ttl_sec"])

    if not 30 <= value["browser_cache_ttl_sec"] <= 3600:
        raise ValueError("browser_cache_ttl_sec muss zwischen 30 und 3600 liegen")

    value["ocr_min_image_width"] = int(value["ocr_min_image_width"])
    value["ocr_min_image_height"] = int(value["ocr_min_image_height"])

    if not 0 <= value["ocr_min_image_width"] <= 10000:
        raise ValueError("Die OCR-Mindestbreite muss zwischen 0 und 10000 Pixel liegen")

    if not 0 <= value["ocr_min_image_height"] <= 10000:
        raise ValueError("Die OCR-Mindesthöhe muss zwischen 0 und 10000 Pixel liegen")

    value["lm_studio_timeout_sec"] = float(value["lm_studio_timeout_sec"])

    if not 1 <= value["lm_studio_timeout_sec"] <= 600:
        raise ValueError("LM-Studio-Timeout muss zwischen 1 und 600 Sekunden liegen")

    value["ollama_timeout_sec"] = float(value["ollama_timeout_sec"])

    if not 1 <= value["ollama_timeout_sec"] <= 600:
        raise ValueError("Ollama-Timeout muss zwischen 1 und 600 Sekunden liegen")

    if value["seamless_device"] not in {"auto", "cpu", "cuda"}:
        raise ValueError("Gerät muss auto, cpu oder cuda sein")

    if value["overlay_mode"] != "exact_group_bbox":
        raise ValueError("Produktiv unterstützt wird derzeit nur exact_group_bbox")

    if value["default_view"] not in {"translated", "original"}:
        raise ValueError("default_view muss translated oder original sein")

    for key in (
        "show_overflow", "show_debug_areas", "seamless_license_accepted",
        "chapter_email_notifications",
    ):
        value[key] = bool(value[key])

    for key in ("source_language", "target_language"):
        value[key] = str(value[key]).strip()

        if not value[key]:
            raise ValueError(f"{key} darf nicht leer sein")

    value["lm_studio_model"] = str(value["lm_studio_model"]).strip()

    value["lm_studio_base_url"] = str(value["lm_studio_base_url"]).strip().rstrip("/")

    value["ollama_base_url"] = str(value["ollama_base_url"]).strip().rstrip("/")

    value["ollama_model"] = str(value["ollama_model"]).strip()

    value["ollama_keep_alive"] = str(value["ollama_keep_alive"]).strip()

    value["ollama_last_error"] = str(value.get("ollama_last_error", ""))[:1000]
    value["ollama_status"] = str(value.get("ollama_status", "NOT_TESTED"))

    if value["ollama_status"] not in OLLAMA_STATUSES:
        value["ollama_status"] = "NOT_TESTED"
    ollama_configured = bool(value["ollama_base_url"] and value["ollama_model"])

    if not ollama_configured:
        value["ollama_status"] = "NOT_CONFIGURED"
    elif not value["ollama_base_url"].startswith(("http://", "https://")):
        raise ValueError("Ollama-Basis-URL muss http/https verwenden")

    if not value["ollama_keep_alive"]:
        raise ValueError("Ollama Keep-Alive darf nicht leer sein")

    lm_studio_partially_configured = bool(
        value["lm_studio_base_url"] or value["lm_studio_model"]
    )

    if lm_studio_partially_configured:
        if not value["lm_studio_base_url"].startswith(("http://", "https://")):
            raise ValueError("LM-Studio-Basis-URL muss http/https verwenden")

        if not value["lm_studio_model"]:
            raise ValueError("Für LM Studio muss ein Modell eingetragen werden")

    if value["engine"] == "lm_studio" and not (
        value["lm_studio_base_url"] and value["lm_studio_model"]
    ):
        raise ValueError("LM Studio ist noch nicht vollständig konfiguriert")

    return value
class SettingsBody(BaseModel):
    theme: str
    interface_language: str = Field(pattern="^(de|en)$")

    chapter_email_notifications: bool = False
    engine: str
    source_language: str = Field(min_length=2, max_length=16)

    target_language: str = Field(min_length=2, max_length=16)

    prefetch_count: int = Field(ge=0, le=100)

    history_limit: int = Field(ge=1, le=100)

    bookmark_chapter_cache_limit: int = Field(ge=0)

    browser_cache_ttl_sec: int = Field(ge=30, le=3600)

    ocr_min_image_width: int = Field(ge=0, le=10000)

    ocr_min_image_height: int = Field(ge=0, le=10000)

    default_view: str
    lm_studio_base_url: str = Field(max_length=500)

    lm_studio_model: str = Field(max_length=200)

    lm_studio_timeout_sec: float = Field(ge=1, le=600)

    ollama_base_url: str = Field(max_length=500)

    ollama_model: str = Field(max_length=200)

    ollama_timeout_sec: float = Field(ge=1, le=600)

    ollama_keep_alive: str = Field(min_length=1, max_length=50)

    ollama_status: str = "NOT_TESTED"
    ollama_last_error: str = ""
    seamless_device: str
    seamless_license_accepted: bool
    overlay_mode: str
    show_overflow: bool
    show_debug_areas: bool
class EngineSelectionBody(BaseModel):
    engine: str
class LlmConnectionTestBody(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)

    model: str = Field(min_length=1, max_length=200)

    timeout_sec: float = Field(ge=1, le=600)

class OllamaConnectionBody(LlmConnectionTestBody):
    keep_alive: str = Field(min_length=1, max_length=50)

class AccountUpdateBody(BaseModel):
    username: str = Field(min_length=3, max_length=64)

    email: str = Field(min_length=3, max_length=320)

    current_password: str = Field(min_length=1, max_length=1024)

    new_password: str = Field(default="", max_length=1024)

class SeamlessDownloadBody(BaseModel):
    accept_license: bool
class BookmarkBody(BaseModel):
    url: str = Field(min_length=1, max_length=2000)

    title: str = Field(min_length=1, max_length=500)

    site: str = Field(min_length=1, max_length=50)

class BookmarkRemoveBody(BaseModel):
    url: str = Field(min_length=1, max_length=2000)

    delete_reading_data: bool = False
class RegistrationSettingBody(BaseModel):
    enabled: bool
class PasswordResetRequestBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)

class PasswordResetConfirmBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    code: str = Field(min_length=6, max_length=6)

    new_password: str = Field(min_length=8, max_length=1024)

def build_app():
    paths = _paths()

    paths.ensure_dirs()

    glossary_source = Path("/app/resources/ocr_glossary.json")

    glossary_target = DATA_DIR / "lingoveil" / "ocr_glossary.json"
    if glossary_source.is_file() and not glossary_target.is_file():
        glossary_target.parent.mkdir(parents=True, exist_ok=True)

        shutil.copyfile(glossary_source, glossary_target)

    settings, settings_warning = load_settings()

    pipeline = BrowserTranslationPipeline(log_fn=lambda m: print(f"[LingoVeil Live] {m}", flush=True))

    def mark_ollama_unavailable(reason: str) -> None:
        current, _warning = load_settings()

        current["ollama_status"] = "UNAVAILABLE"
        current["ollama_last_error"] = reason
        _atomic_json(SETTINGS_FILE, validate_settings(current))

    pipeline.ollama_unavailable_callback = mark_ollama_unavailable
    pipeline.apply_live_settings(settings)

    database = Database(os.environ.get("LINGOVEIL_DATABASE_URL", ""))

    database.initialize()

    auth = AuthService(
        database,
        session_hours=int(os.environ.get("LINGOVEIL_SESSION_HOURS", "72")),
    )

    user_data = UserDataStore(database)

    job_queue = FairTranslationQueue(database)

    def effective_user_settings(user_id: str) -> dict[str, Any]:
        system, _warning = load_settings()

        system.update(user_data.load_settings(user_id))

        return validate_settings(system)

    session_cookie_secure = os.environ.get(
        "LINGOVEIL_SESSION_COOKIE_SECURE", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}

    port = int(os.environ.get("LINGOVEIL_LIVE_PORT", "8765"))

    app = create_app(
        session_token="",
        access_code="",
        pipeline=pipeline,
        port=port,
        auth_service=auth,
        session_cookie_secure=session_cookie_secure,
        job_queue=job_queue,
        user_settings_provider=effective_user_settings,
    )

    app.title = "LingoVeil Live"
    app.state.pipeline = pipeline
    app.state.settings_warning = settings_warning
    app.state.database = database
    app.state.auth = auth
    app.state.user_data = user_data
    update_checker = UpdateChecker(data_dir=DATA_DIR)

    mailer = ChapterNotificationMailer(database)

    bookmark_update_stop = threading.Event()

    update_check_stop = threading.Event()

    bookmark_update_thread: threading.Thread | None = None
    update_thread: threading.Thread | None = None
    def check_bookmarks_periodically() -> None:
        while not bookmark_update_stop.is_set():
            for user in user_data.users():
                bookmark_store = DatabaseMangaBookmarkStore(user_data, user["id"])

                personal = user_data.load_settings(user["id"])

                history_store = DatabaseLiveHistoryStore(
                    user_data,
                    user["id"],
                    CACHE_DIR,
                    limit=int(personal.get("history_limit", DEFAULTS["history_limit"])),
                    protected_manga_urls=bookmark_store.urls,
                )

                with pipeline.bind_user_stores(bookmark_store, history_store):
                    result = pipeline.check_bookmark_updates(force=False)

                if bool(personal.get("chapter_email_notifications", False)):
                    user_data.enqueue_chapter_notifications(
                        user["id"], result.get("discoveries", [])

                    )

                if result["checked"] or result["errors"]:
                    print(
                        f"[LingoVeil Live] [Bookmarks] {user['username']}: "
                        f"{result['checked']} geprüft, "
                        f"{result['new_chapters']} neue Chapter, "
                        f"{len(result['errors'])} Fehler",
                        flush=True,
                    )

            mailer.deliver_pending()

            bookmark_update_stop.wait(12 * 60 * 60)

    def check_updates_periodically() -> None:
        while not update_check_stop.is_set():
            result = update_checker.check(force=False)

            print(
                "[LingoVeil Live] [Update] "
                f"{result['status']} (installiert: {result['installed_version']}, "
                f"aktuell: {result.get('latest_version') or 'unbekannt'})",
                flush=True,
            )

            retry_seconds = 60 if result["status"] == "error" else 6 * 60 * 60
            update_check_stop.wait(retry_seconds)

    @app.on_event("startup")

    def start_bookmark_updates() -> None:
        nonlocal bookmark_update_thread, update_thread
        bookmark_update_thread = threading.Thread(
            target=check_bookmarks_periodically,
            name="lingoveil-bookmark-updates",
            daemon=True,
        )

        bookmark_update_thread.start()

        if update_checker.automatic_enabled:
            update_thread = threading.Thread(
                target=check_updates_periodically,
                name="lingoveil-update-check",
                daemon=True,
            )

            update_thread.start()

        else:
            print(
                "[LingoVeil Live] [Update] Automatische Prüfung deaktiviert "
                "(manueller Check bleibt verfügbar).",
                flush=True,
            )

    @app.on_event("shutdown")

    def close_pipeline() -> None:
        bookmark_update_stop.set()

        update_check_stop.set()

        if bookmark_update_thread is not None:
            bookmark_update_thread.join(timeout=2)

        if update_thread is not None:
            update_thread.join(timeout=2)

        job_queue.stop()

        pipeline.close()

    @app.middleware("http")

    async def live_access_control(request, call_next):
        if request.url.path in {
            "/api/health", "/api/login", "/api/register", "/api/auth/config",
            "/api/password-reset/request", "/api/password-reset/confirm",
        } or not request.url.path.startswith("/api/"):
            return await call_next(request)

        user = auth.authenticate(request.cookies.get("lingoveil_session"))

        if user is None:
            return JSONResponse(status_code=401, content={"error": "Authentifizierung erforderlich"})

        request.state.user = user
        if user["is_admin"]:
            user_data.migrate_legacy_files(user["id"], DATA_DIR)

        bookmark_store = DatabaseMangaBookmarkStore(user_data, user["id"])

        personal = user_data.load_settings(user["id"])

        history_store = DatabaseLiveHistoryStore(
            user_data,
            user["id"],
            CACHE_DIR,
            limit=int(personal.get("history_limit", DEFAULTS["history_limit"])),
            protected_manga_urls=bookmark_store.urls,
        )

        with pipeline.bind_user_stores(bookmark_store, history_store):
            return await call_next(request)

    def current_user(request: Request) -> dict[str, Any]:
        user = getattr(request.state, "user", None)

        if user is None:
            raise HTTPException(status_code=401, detail="Authentifizierung erforderlich")

        return user
    def require_admin(request: Request) -> dict[str, Any]:
        user = current_user(request)

        if not user["is_admin"]:
            raise HTTPException(status_code=403, detail="Administratorrechte erforderlich")

        return user
    app.router.routes[:] = [
        route for route in app.router.routes
        if getattr(route, "path", None) != "/api/shutdown"
    ]
    @app.get("/api/health")

    def health() -> dict[str, Any]:
        checks: dict[str, bool] = {}

        for name, directory in (("data", DATA_DIR), ("models", MODELS_DIR), ("cache", CACHE_DIR)):
            try:
                directory.mkdir(parents=True, exist_ok=True)

                probe = directory / ".healthcheck"
                probe.write_text("ok", encoding="ascii")

                probe.unlink()

                checks[name] = True
            except OSError:
                checks[name] = False
        database_ok = database.healthy()

        healthy = all(checks.values()) and database_ok and settings_warning is None
        return {
            "status": "ok" if healthy else "degraded",
            "service": "LingoVeil Live",
            "version": VERSION,
            "checks": checks,
            "configuration_warning": settings_warning,
            "authentication_configured": True,
            "database": database_ok,
            "active_engine": pipeline.engine_manager.active_engine,
        }

    @app.get("/api/auth/config")

    def auth_config() -> dict[str, Any]:
        return {**user_data.registration_config(), "password_reset_available": mailer.configured}

    @app.post("/api/password-reset/request")

    def request_password_reset(body: PasswordResetRequestBody) -> dict[str, str]:
        if not mailer.configured:
            raise HTTPException(
                status_code=503,
                detail="Passwort-Wiederherstellung ist nicht verfügbar, weil SMTP nicht konfiguriert ist",
            )

        try:
            reset = auth.create_password_reset(body.email)

            try:
                mailer.send_password_reset(
                    email=reset["email"], username=reset["username"],
                    code=reset["code"], language=reset["language"],
                )

            except Exception as exc:
                auth.revoke_password_reset(reset["user_id"])

                raise HTTPException(
                    status_code=502, detail="Die Wiederherstellungs-E-Mail konnte nicht gesendet werden"
                ) from exc
            return {"status": "sent"}

        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    @app.post("/api/password-reset/confirm")

    def confirm_password_reset(body: PasswordResetConfirmBody) -> dict[str, str]:
        try:
            auth.reset_password(body.email, body.code, body.new_password)

            return {"status": "password_reset"}

        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    @app.get("/api/admin/users")

    def admin_users(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        config = user_data.registration_config()

        return {
            "registration_enabled": config["registration_configured_enabled"],
            "users": user_data.users(),
        }

    @app.put("/api/admin/registration")

    def admin_registration(
        body: RegistrationSettingBody,
        _: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        user_data.set_registration_enabled(body.enabled)

        return {"status": "saved", "registration_enabled": body.enabled}

    @app.delete("/api/admin/users/{user_id}")

    def admin_delete_user(
        user_id: str,
        admin: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        if user_id == admin["id"]:
            raise HTTPException(status_code=422, detail="Das Administratorkonto kann nicht gelöscht werden")

        try:
            deleted = user_data.delete_user(user_id)

        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        shutil.rmtree(CACHE_DIR / "history" / user_id, ignore_errors=True)

        return {"status": "deleted", "user": deleted}

    @app.get("/api/settings")

    def get_settings(request: Request) -> dict[str, Any]:
        current, warning = load_settings()

        user = current_user(request)

        current.update(user_data.load_settings(user["id"]))

        if not user["is_admin"]:
            current["lm_studio_base_url"] = ""
            current["lm_studio_model"] = ""
            current["ollama_base_url"] = ""
        if not mailer.configured:
            current["chapter_email_notifications"] = False
        return {
            "settings": current,
            "warning": warning,
            "user": user,
            "capabilities": {
                "smtp_configured": mailer.configured,
                "translation_engines": {
                    "bergamot": sorted(BERGAMOT_TARGET_LANGUAGES),
                    "seamless_m4t": sorted(SEAMLESS_TARGET_LANGUAGES),
                    "lm_studio": ["deu"],
                    "ollama": ollama_supported_lingoveil_languages(
                        current["ollama_model"]
                    ),
                },
                "ollama_model": ollama_model_capabilities(current["ollama_model"]),
            },
        }

    @app.get("/api/app-update")

    def app_update(force: bool = False) -> dict[str, Any]:
        return update_checker.check(force=force)

    @app.post("/api/lm-studio/test")

    def test_lm_studio(
        body: LlmConnectionTestBody,
        _: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        translator = LlmTranslator(
            LlmSettings(
                base_url=body.base_url.strip().rstrip("/"),
                model=body.model.strip(),
                timeout_sec=body.timeout_sec,
            ),
            lambda message: print(f"[LM Studio Test] {message}", flush=True),
        )

        try:
            result = translator.translate_blocks(
                [{"id": "TEST", "text": "Hello!"}], max_chars=100, max_blocks=1
            )

            return {
                "available": True,
                "translation": result.items[0].german if result.items else "",
                "duration_sec": result.duration_sec,
            }

        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    @app.get("/api/ollama/models")

    def ollama_models(
        base_url: str,
        timeout_sec: float = 120,
        _: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        client = OllamaTranslator(
            OllamaSettings(
                base_url=base_url.strip().rstrip("/"),
                model="translategemma:4b",
                timeout_sec=timeout_sec,
                keep_alive="2m",
                bridge_token=os.environ.get("LINGOVEIL_OLLAMA_BRIDGE_TOKEN", ""),
            )

        )

        try:
            return {"models": client.list_models()}

        except OllamaTranslationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        finally:
            client.close()

    @app.post("/api/ollama/test")

    def test_ollama(
        body: OllamaConnectionBody,
        _: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        settings = OllamaSettings(
            base_url=body.base_url.strip().rstrip("/"),
            model=body.model.strip(),
            timeout_sec=body.timeout_sec,
            keep_alive=body.keep_alive.strip(),
            bridge_token=os.environ.get("LINGOVEIL_OLLAMA_BRIDGE_TOKEN", ""),
        )

        client = OllamaTranslator(
            settings,
            lambda message: print(f"[Ollama Test] {message}", flush=True),
        )

        try:
            result = client.test_connection()

        except OllamaTranslationError as exc:
            current, _warning = load_settings()

            current.update({
                "ollama_base_url": settings.base_url,
                "ollama_model": settings.model,
                "ollama_timeout_sec": settings.timeout_sec,
                "ollama_keep_alive": settings.keep_alive,
                "ollama_status": "UNAVAILABLE",
                "ollama_last_error": str(exc),
            })

            _atomic_json(SETTINGS_FILE, validate_settings(current))

            pipeline.apply_live_settings(current)

            raise HTTPException(status_code=503, detail=str(exc)) from exc
        finally:
            client.close()

        current, _warning = load_settings()

        current.update({
            "ollama_base_url": settings.base_url,
            "ollama_model": settings.model,
            "ollama_timeout_sec": settings.timeout_sec,
            "ollama_keep_alive": settings.keep_alive,
            "ollama_status": "AVAILABLE",
            "ollama_last_error": "",
        })

        current = validate_settings(current)

        _atomic_json(SETTINGS_FILE, current)

        pipeline.apply_live_settings(current)

        return {
            **result,
            "status": "AVAILABLE",
            "model_capabilities": ollama_model_capabilities(settings.model),
        }

    @app.put("/api/account")

    def update_account(body: AccountUpdateBody, request: Request) -> dict[str, Any]:
        user = current_user(request)

        try:
            updated = auth.update_account(
                user["id"],
                username=body.username,
                email=body.email,
                current_password=body.current_password,
                new_password=body.new_password,
                current_token=request.cookies.get("lingoveil_session"),
            )

            request.state.user = updated
            return {"status": "saved", "user": updated}

        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    @app.put("/api/settings")

    def put_settings(body: SettingsBody, request: Request) -> dict[str, Any]:
        try:
            user = current_user(request)

            incoming = body.model_dump()

            if incoming["chapter_email_notifications"] and not mailer.configured:
                raise ValueError(
                    "E-Mail-Benachrichtigungen sind nicht verfügbar, weil SMTP "
                    "noch nicht vom Administrator konfiguriert wurde."
                )

            if user["is_admin"]:
                previous, _warning = load_settings()

                config_changed = any(
                    incoming[key] != previous[key]
                    for key in (
                        "ollama_base_url", "ollama_model", "ollama_timeout_sec",
                        "ollama_keep_alive",
                    )

                )

                incoming["ollama_status"] = (
                    "NOT_TESTED" if config_changed else previous["ollama_status"]
                )

                incoming["ollama_last_error"] = (
                    "" if config_changed else previous["ollama_last_error"]
                )

                current = validate_settings(incoming)

                _atomic_json(SETTINGS_FILE, current)

            else:
                system, _warning = load_settings()

                for key in (
                    "lm_studio_base_url", "lm_studio_model", "lm_studio_timeout_sec",
                    "seamless_device", "seamless_license_accepted",
                    "ollama_base_url", "ollama_model", "ollama_timeout_sec",
                    "ollama_keep_alive", "ollama_status", "ollama_last_error",
                ):
                    incoming[key] = system[key]
                current = validate_settings(incoming)

            personal_keys = {
                "theme", "interface_language", "chapter_email_notifications",
                "engine", "source_language", "target_language",
                "prefetch_count", "history_limit", "bookmark_chapter_cache_limit",
                "default_view", "show_overflow", "show_debug_areas",
                "ocr_min_image_width", "ocr_min_image_height",
            }

            user_data.save_settings(
                user["id"], {key: current[key] for key in personal_keys}

            )

            return {"status": "saved", "settings": current}

        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    @app.put("/api/settings/engine")

    def put_selected_engine(body: EngineSelectionBody, request: Request) -> dict[str, Any]:
        user = current_user(request)

        if body.engine == "lm_studio" and not user["is_admin"]:
            raise HTTPException(status_code=403, detail="LM Studio ist nur für Administratoren verfügbar")

        current, _warning = load_settings()

        if body.engine == "ollama" and current["ollama_status"] != "AVAILABLE":
            raise HTTPException(
                status_code=409,
                detail="Ollama muss zuerst unter Optionen → Modelle erfolgreich getestet werden",
            )

        current["engine"] = body.engine
        try:
            current = validate_settings(current)

            if user["is_admin"]:
                _atomic_json(SETTINGS_FILE, current)

            personal = user_data.load_settings(user["id"])

            personal["engine"] = current["engine"]
            user_data.save_settings(user["id"], personal)

            return {"status": "saved", "engine": current["engine"]}

        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    @app.post("/api/settings/reset")

    def reset_settings(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        _atomic_json(SETTINGS_FILE, dict(DEFAULTS))

        return {"status": "reset", "settings": dict(DEFAULTS)}

    @app.get("/api/history")

    def list_history() -> dict[str, Any]:
        return {"entries": pipeline.history.list_entries()}

    @app.post("/api/history/{entry_id}/open")

    def open_history(entry_id: str) -> dict[str, Any]:
        try:
            return pipeline.open_history(entry_id)

        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    @app.get("/api/history/assets/{asset_path:path}")

    def history_asset(asset_path: str) -> FileResponse:
        try:
            path = pipeline.history.asset_path(asset_path)

        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail="History-Datei fehlt") from exc
        media_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }

        media_type = media_types.get(path.suffix.lower(), "application/octet-stream")

        return FileResponse(path, media_type=media_type)

    @app.delete("/api/history")

    def clear_history() -> dict[str, str]:
        pipeline.history.clear()

        return {"status": "cleared"}

    @app.get("/api/bookmarks")

    def list_bookmarks() -> dict[str, Any]:
        return {
            "bookmarks": pipeline.list_bookmarks(),
            "backup_file": str(pipeline.bookmarks.path),
        }

    @app.post("/api/bookmarks/check-updates")

    def check_bookmark_updates(request: Request) -> dict[str, Any]:
        result = pipeline.check_bookmark_updates(force=True)

        user = current_user(request)

        personal = user_data.load_settings(user["id"])

        if bool(personal.get("chapter_email_notifications", False)):
            user_data.enqueue_chapter_notifications(
                user["id"], result.get("discoveries", [])

            )

        mailer.deliver_pending()

        return result
    @app.post("/api/bookmarks")

    def add_bookmark(body: BookmarkBody) -> dict[str, Any]:
        return {
            "status": "saved",
            "bookmark": pipeline.add_bookmark(
                url=body.url,
                title=body.title,
                site=body.site,
            ),
        }

    @app.delete("/api/bookmarks")

    def remove_bookmark(body: BookmarkRemoveBody) -> dict[str, str]:
        pipeline.remove_bookmark(
            body.url,
            delete_reading_data=body.delete_reading_data,
        )

        return {"status": "removed"}

    @app.get("/api/progress/backup")

    def download_progress_backup(request: Request) -> JSONResponse:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

        user = current_user(request)

        return JSONResponse(
            user_data.export_user(user["id"]),
            headers={
                "Content-Disposition": (
                    f'attachment; filename="lingoveil-progress-{stamp}.json"'
                ),
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/progress/restore")

    async def restore_progress_backup(
        request: Request,
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        raw = await file.read(10 * 1024 * 1024 + 1)

        if len(raw) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Backup ist größer als 10 MiB")

        try:
            payload = json.loads(raw.decode("utf-8"))

            if not isinstance(payload, dict):
                raise ValueError("Backup-Wurzel muss ein Objekt sein")

            counts = user_data.restore_user(current_user(request)["id"], payload)

        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "restored", **counts}

    manager = AppModelManager(paths)

    download_jobs: dict[str, dict[str, str]] = {}

    download_jobs_lock = threading.Lock()

    def start_model_download(component_id: str) -> dict[str, str]:
        with download_jobs_lock:
            current_job = download_jobs.get(component_id, {})

            if current_job.get("status") == "downloading":
                return current_job
            download_jobs[component_id] = {
                "status": "downloading",
                "message": "Download läuft in einem separaten Hintergrundprozess …",
            }

        try:
            process = subprocess.Popen(
                [sys.executable, "/app/model_download_worker.py", component_id],
                cwd="/app",
            )

        except OSError as exc:
            result = {"status": "error", "message": str(exc)}

            with download_jobs_lock:
                download_jobs[component_id] = result
            return result
        def monitor() -> None:
            return_code = process.wait()

            if return_code == 0:
                result = {
                    "status": "installed",
                    "message": "Download und Installation abgeschlossen.",
                }

            else:
                result = {
                    "status": "error",
                    "message": f"Download-Prozess wurde mit Code {return_code} beendet.",
                }

            with download_jobs_lock:
                download_jobs[component_id] = result
        threading.Thread(
            target=monitor,
            name=f"monitor-download-{component_id}",
            daemon=True,
        ).start()

        return {
            "status": "downloading",
            "message": "Download läuft in einem separaten Hintergrundprozess …",
        }

    @app.get("/api/engines/{engine_name}/availability")

    def engine_availability(engine_name: str, request: Request) -> dict[str, Any]:
        if engine_name not in SUPPORTED_TRANSLATION_ENGINES:
            raise HTTPException(status_code=404, detail="Unbekannte Engine")

        if engine_name == "lm_studio" and not current_user(request)["is_admin"]:
            raise HTTPException(status_code=403, detail="LM Studio ist nur für Administratoren verfügbar")

        if engine_name == "lm_studio":
            current, _warning = load_settings()

            available = bool(
                current["lm_studio_base_url"] and current["lm_studio_model"]
            )

            return {
                "engine": engine_name,
                "available": available,
                "reason": "" if available else "LM Studio ist noch nicht konfiguriert.",
                "fallback": "bergamot",
            }

        if engine_name == "ollama":
            current, _warning = load_settings()

            status = current["ollama_status"]
            return {
                "engine": engine_name,
                "available": status == "AVAILABLE",
                "status": status,
                "reason": current["ollama_last_error"] if status == "UNAVAILABLE" else "",
                "model": current["ollama_model"],
                "model_capabilities": ollama_model_capabilities(current["ollama_model"]),
            }

        if engine_name != "seamless_m4t":
            return {"engine": engine_name, "available": True, "fallback": "bergamot"}

        current, _warning = load_settings()

        component = manager.inspect_component("seamless-m4t-v2-large")

        if not current["seamless_license_accepted"]:
            reason = (
                "SeamlessM4T-Lizenz nicht akzeptiert. Bitte über „Modelle“ "
                "bestätigen und das Modell herunterladen."
            )

        elif component.status != "installiert":
            reason = (
                "SeamlessM4T-Modell ist noch nicht installiert oder der Download "
                "ist noch nicht abgeschlossen. Bitte „Modelle“ öffnen."
            )

        else:
            reason = ""
        return {
            "engine": engine_name,
            "available": not reason,
            "reason": reason,
            "fallback": "bergamot",
            "model_status": component.status,
        }

    @app.get("/api/models")

    def models(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        current_settings, _warning = load_settings()

        with download_jobs_lock:
            jobs = dict(download_jobs)

        return {
            "models": [
                {
                    "id": item.manifest.id,
                    "name": item.manifest.name,
                    "component": item.manifest.component,
                    "optional": item.manifest.optional,
                    "status": item.status,
                    "version": item.available_version,
                    "size": item.size_label,
                    "error": item.error,
                    "download_available": (
                        item.manifest.id == "seamless-m4t-v2-large"
                        or (item.can_download and bool(item.manifest.sha256))

                    ),
                    "download_status": jobs.get(item.manifest.id, {}).get(
                        "status", "idle"
                    ),
                    "download_message": jobs.get(item.manifest.id, {}).get(
                        "message", ""
                    ),
                    "source_url": item.manifest.source_url,
                    "install_path": str(item.install_path),
                    "license": (
                        f"{SEAMLESS_MODEL_LICENSE} (nur nichtkommerziell)"
                        if item.manifest.id == "seamless-m4t-v2-large"
                        else ""
                    ),
                    "license_accepted": bool(
                        current_settings["seamless_license_accepted"]
                    ),
                    "notes": item.manifest.notes,
                }

                for item in manager.list_components()

            ]
        }

    @app.post("/api/models/languagetool-local/download", status_code=202)

    def download_languagetool(
        _: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, str]:
        component_id = "languagetool-local"
        return start_model_download(component_id)

    @app.post("/api/models/seamless-m4t-v2-large/download", status_code=202)

    def download_seamless(
        body: SeamlessDownloadBody,
        _: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        if not body.accept_license:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Die CC-BY-NC-4.0-Lizenz muss vor dem Download ausdrücklich "
                    "akzeptiert werden."
                ),
            )

        with download_jobs_lock:
            current_job = download_jobs.get("seamless-m4t-v2-large", {})

        if current_job.get("status") == "downloading":
            return current_job
        free_bytes = shutil.disk_usage(MODELS_DIR).free
        required_gib = SEAMLESS_MODEL_SIZE_GIB + 1.0
        if free_bytes < int(required_gib * 1024**3):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Nicht genug Speicherplatz. Benötigt werden mindestens "
                    f"{required_gib:.1f} GiB freier Speicher."
                ),
            )

        current, _warning = load_settings()

        current["seamless_license_accepted"] = True
        current = validate_settings(current)

        _atomic_json(SETTINGS_FILE, current)

        pipeline.apply_live_settings(current)

        return start_model_download("seamless-m4t-v2-large")

    @app.post("/api/models/{component_id}/import")

    async def import_model(
        component_id: str,
        file: UploadFile = File(...),
        _: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        if component_id not in {entry.id for entry in manager.manifest}:
            raise HTTPException(status_code=404, detail="Unbekannte Modell-ID")

        suffix = "".join(Path(file.filename or "model.zip").suffixes).lower()

        if suffix not in {".zip", ".tar", ".tar.gz", ".tgz"}:
            raise HTTPException(status_code=415, detail="Nur ZIP/TAR/TAR.GZ/TGZ erlaubt")

        target = paths.tmp_dir / f"upload-{secrets.token_hex(8)}{suffix}"
        size = 0
        try:
            with target.open("wb") as handle:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)

                    if size > MODEL_UPLOAD_LIMIT:
                        raise HTTPException(status_code=413, detail="Modellarchiv ist zu groß")

                    handle.write(chunk)

            manager.install_from_archive(component_id, target)

            return {"status": "installed", "component_id": component_id}

        except ModelManagerError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            target.unlink(missing_ok=True)

    @app.delete("/api/models/{component_id}")

    def delete_model(
        component_id: str,
        _: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        try:
            manager.remove_component(component_id)

            return {"status": "removed", "component_id": component_id}

        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unbekannte Modell-ID") from exc
        except ModelManagerError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return app
APP = build_app()

def main() -> int:
    port = int(os.environ.get("LINGOVEIL_LIVE_PORT", "8765"))

    print(f"[LingoVeil Live] Start auf 0.0.0.0:{port}", flush=True)

    uvicorn.run(APP, host="0.0.0.0", port=port, log_level="info", access_log=True)

    return 0
if __name__ == "__main__":
    raise SystemExit(main())
