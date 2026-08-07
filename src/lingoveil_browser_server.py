from __future__ import annotations
import ipaddress
import secrets
import socket
import sys
import threading
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import uvicorn

from fastapi import Cookie, Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from lingoveil_browser_pipeline import BrowserTranslationPipeline
from lingoveil_config import (
    DEFAULT_BROWSER_PORT,
    TRANSLATION_ENGINE_BERGAMOT,
    TRANSLATION_ENGINE_LM_STUDIO,
    TRANSLATION_ENGINE_SEAMLESS_M4T,
    validate_translation_engine,
)

from lingoveil_image_pipeline import SizeLimitError, UrlSecurityError
from lingoveil_seamless_worker import SeamlessM4TError
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"
DEFAULT_PORT = DEFAULT_BROWSER_PORT
BIND_HOST = "0.0.0.0"
LOCAL_HOST = "127.0.0.1"
def _log(msg: str) -> None:
    line = f"[Browser-Server] {msg}"
    try:
        print(line, file=sys.stderr, flush=True)

    except (ValueError, OSError):
        pass
def _local_lan_addresses() -> list[str]:
    pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 1))

            ip = sock.getsockname()[0]
    except OSError:
        return []
    if ip.startswith("127."):
        return []
    try:
        addr = ipaddress.ip_address(ip)

    except ValueError:
        return []
    if addr.is_private or addr.is_link_local:
        return [ip]
    return []
def _warn_if_firewall_blocks(port: int) -> str | None:
    import shutil
    import subprocess

    if not shutil.which("firewall-cmd"):
        return None
    try:
        subprocess.run(
            ["firewall-cmd", "--state"],
            capture_output=True,
            check=True,
            timeout=3,
        )

    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    try:
        result = subprocess.run(
            ["firewall-cmd", "--query-port", f"{port}/tcp"],
            capture_output=True,
            check=False,
            timeout=3,
        )

        if result.returncode == 0:
            return None
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (
        f"Port {port}/tcp ist in firewalld nicht freigegeben. "
        "Tablet-/LAN-Zugriff wird blockiert, bis der Port freigegeben wird."
    )

def _normalize_access_code(code: str) -> str:
    digits = "".join(ch for ch in code.strip() if ch.isdigit())

    if len(digits) != 4:
        raise ValueError("Browser-Code muss aus genau 4 Ziffern bestehen")

    return digits
def _generate_access_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(4))

def _session_url(host: str, port: int, access_code: str) -> str:
    return f"http://{host}:{port}/?code={access_code}"
def _host_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/"
def session_urls(port: int, access_code: str) -> list[str]:
    urls = [_session_url(LOCAL_HOST, port, access_code)]
    for ip in _local_lan_addresses():
        urls.append(_session_url(ip, port, access_code))

    return urls
def _find_free_port(start: int = DEFAULT_PORT, attempts: int = 20) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            try:
                sock.bind((BIND_HOST, port))

                return port
            except OSError:
                continue
    raise RuntimeError("Kein freier lokaler Port gefunden")

def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            sock.bind((BIND_HOST, port))

            return True
        except OSError:
            return False
@dataclass(frozen=True)

class BrowserLaunchInfo:
    port: int
    access_code: str
    local_url: str
    lan_urls: list[str]
    warning: str | None = None
    @property
    def browser_url(self) -> str:
        return self.local_url
    @property
    def display_urls(self) -> list[str]:
        return [self.local_url, *self.lan_urls]
class ProcessImageRequest(BaseModel):
    image_id: str
    engine: str = TRANSLATION_ENGINE_BERGAMOT
class ProcessPdfPageRequest(BaseModel):
    pdf_id: str
    page_number: int = 0
    engine: str = TRANSLATION_ENGINE_BERGAMOT
class UrlRequest(BaseModel):
    url: str
    engine: str = TRANSLATION_ENGINE_BERGAMOT
class PageImageRequest(BaseModel):
    image_id: str
    engine: str = TRANSLATION_ENGINE_BERGAMOT
    force: bool = False
class LoginRequest(BaseModel):
    username: str = Field(default="", max_length=64)

    password: str = Field(default="", max_length=1024)

    code: str = Field(default="", max_length=256)

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)

    email: str = Field(min_length=3, max_length=320)

    password: str = Field(min_length=8, max_length=1024)

def create_app(
    *,
    session_token: str,
    access_code: str,
    pipeline: BrowserTranslationPipeline,
    port: int = DEFAULT_PORT,
    auth_service: Any | None = None,
    session_cookie_secure: bool = False,
    job_queue: Any | None = None,
    user_settings_provider: Callable[[str], dict[str, Any]] | None = None,
) -> FastAPI:
    app = FastAPI(title="LingoVeil Live", docs_url=None, redoc_url=None)

    def apply_user_translation_settings(user: dict[str, Any] | None) -> dict[str, Any]:
        if user_settings_provider is None or user is None:
            return {}

        settings = user_settings_provider(str(user["id"]))

        pipeline.apply_live_settings(settings)

        return settings
    def is_authorized(
        *,
        token: str | None = None,
        code: str | None = None,
    ) -> bool:
        supplied_token = token or ""
        supplied_code = code or ""
        if auth_service is not None:
            return auth_service.authenticate(supplied_token or supplied_code) is not None
        if supplied_token and supplied_token == session_token:
            return True
        if supplied_code and supplied_code == access_code:
            return True
        return False
    def require_token(
        x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
        x_session_code: str | None = Header(default=None, alias="X-Session-Code"),
        token: str | None = Query(default=None),
        code: str | None = Query(default=None),
        lingoveil_session: str | None = Cookie(default=None),
    ) -> None:
        supplied_token = x_session_token or token
        supplied_code = x_session_code or code or lingoveil_session
        if is_authorized(token=supplied_token, code=supplied_code):
            return
        if supplied_code:
            raise HTTPException(status_code=401, detail="Ungültiger Zugangscode")

        if supplied_token:
            raise HTTPException(status_code=401, detail="Ungültiges Sitzungstoken")

        raise HTTPException(status_code=401, detail="Authentifizierung erforderlich")

    @app.post("/api/login")

    def api_login(body: LoginRequest) -> JSONResponse:
        if auth_service is not None:
            try:
                opaque_token, user = auth_service.login(body.username, body.password)

            except ValueError as exc:
                return JSONResponse(status_code=401, content={"error": str(exc)})

            response = JSONResponse(content={"status": "authenticated", "user": user})

            response.set_cookie(
                key="lingoveil_session",
                value=opaque_token,
                httponly=True,
                samesite="strict",
                secure=session_cookie_secure,
                path="/",
                max_age=auth_service.session_hours * 60 * 60,
            )

            return response
        if not is_authorized(token=body.code, code=body.code):
            return JSONResponse(
                status_code=401,
                content={"error": "Ungültiger Zugangscode"},
            )

        response = JSONResponse(content={"status": "authenticated"})

        response.set_cookie(
            key="lingoveil_session",
            value=session_token,
            httponly=True,
            samesite="strict",
            secure=False,
            path="/",
            max_age=12 * 60 * 60,
        )

        return response
    @app.post("/api/register", status_code=201)

    def api_register(body: RegisterRequest) -> JSONResponse:
        if auth_service is None:
            return JSONResponse(status_code=404, content={"error": "Registrierung ist nicht verfügbar"})

        try:
            user = auth_service.register(body.username, body.email, body.password)

            opaque_token, user = auth_service.login(body.username, body.password)

        except ValueError as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})

        response = JSONResponse(status_code=201, content={"status": "registered", "user": user})

        response.set_cookie(
            key="lingoveil_session",
            value=opaque_token,
            httponly=True,
            samesite="strict",
            secure=session_cookie_secure,
            path="/",
            max_age=auth_service.session_hours * 60 * 60,
        )

        return response
    @app.get("/api/me")

    def api_me(lingoveil_session: str | None = Cookie(default=None)) -> dict[str, Any]:
        if auth_service is None:
            return {"username": "local", "email": "", "role": "admin", "is_admin": True}

        user = auth_service.authenticate(lingoveil_session)

        if user is None:
            raise HTTPException(status_code=401, detail="Authentifizierung erforderlich")

        return user
    @app.post("/api/logout")

    def api_logout(lingoveil_session: str | None = Cookie(default=None)) -> JSONResponse:
        if auth_service is not None:
            auth_service.logout(lingoveil_session)

        response = JSONResponse(content={"status": "logged_out"})

        response.delete_cookie("lingoveil_session", path="/")

        return response
    def _api_error(exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            raise exc
        if isinstance(exc, (UrlSecurityError, SizeLimitError, ValueError)):
            return JSONResponse(status_code=400, content={"error": str(exc)})

        if isinstance(exc, (RuntimeError, SeamlessM4TError)):
            return JSONResponse(status_code=409, content={"error": str(exc)})

        _log(f"API-Fehler: {exc}")

        return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/status")

    def api_status(_: None = Depends(require_token)) -> dict[str, Any]:
        stats = pipeline.engine_manager.stats
        return {
            "status": "ok",
            "bind_host": BIND_HOST,
            "local_url": _host_url(LOCAL_HOST, port),
            "lan_urls": [_host_url(ip, port) for ip in _local_lan_addresses()],
            "browser_url": _session_url(LOCAL_HOST, port, access_code),
            "access_code": access_code,
            "session_id": pipeline.session_id,
            "active_engine": pipeline.engine_manager.active_engine,
            "engines": [
                TRANSLATION_ENGINE_BERGAMOT,
                TRANSLATION_ENGINE_SEAMLESS_M4T,
                TRANSLATION_ENGINE_LM_STUDIO,
            ],
            "request_counters": {
                "bergamot": stats.bergamot_requests,
                "seamless_m4t": stats.seamless_m4t_requests,
                "lm_studio": stats.lm_studio_requests,
            },
            "render_mode": "exact_group_bbox",
        }

    @app.post("/api/upload/image")

    async def upload_image(
        file: UploadFile = File(...),
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        data = await file.read()

        image_id = pipeline.store_uploaded_image(data, file.filename or "upload.png")

        return {"image_id": image_id, "filename": file.filename}

    @app.post("/api/upload/pdf")

    async def upload_pdf(
        file: UploadFile = File(...),
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        data = await file.read()

        pdf_id, pages = pipeline.store_uploaded_pdf(data, file.filename or "upload.pdf")

        return {"pdf_id": pdf_id, "page_count": pages, "filename": file.filename}

    @app.post("/api/url/image")

    def url_image(body: UrlRequest, _: None = Depends(require_token)):
        try:
            image_id = pipeline.download_image_url(body.url)

            return {"image_id": image_id, "url": body.url}

        except Exception as exc:
            return _api_error(exc)

    @app.post("/api/url/pdf")

    def url_pdf(body: UrlRequest, _: None = Depends(require_token)):
        try:
            pdf_id, pages = pipeline.download_pdf_url(body.url)

            return {"pdf_id": pdf_id, "page_count": pages, "url": body.url}

        except Exception as exc:
            return _api_error(exc)

    @app.post("/api/url/page-images")

    def url_page_images(body: UrlRequest, _: None = Depends(require_token)):
        try:
            return pipeline.analyze_page_images(body.url)

        except Exception as exc:
            return _api_error(exc)

    @app.post("/api/url/manga-catalog")

    def url_manga_catalog(body: UrlRequest, _: None = Depends(require_token)):
        try:
            return pipeline.analyze_manga_catalog(body.url)

        except Exception as exc:
            return _api_error(exc)

    @app.get("/api/pdf-preview/{pdf_id}/{page_number}")

    def pdf_page_preview(
        pdf_id: str,
        page_number: int,
        _: None = Depends(require_token),
    ) -> Response:
        try:
            png = pipeline.pdf_page_preview_png(pdf_id, page_number)

            return Response(content=png, media_type="image/png")

        except Exception as exc:
            return _api_error(exc)

    @app.get("/api/page-image-preview/{image_id}")

    def page_image_preview(
        image_id: str,
        _: None = Depends(require_token),
    ) -> Response:
        try:
            data, content_type = pipeline.page_image_preview(image_id)

            return Response(content=data, media_type=content_type)

        except Exception as exc:
            return _api_error(exc)

    @app.post("/api/process/image")

    def process_image(
        body: ProcessImageRequest,
        request: Request,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            engine = validate_translation_engine(body.engine)

            user = getattr(request.state, "user", None)

            if engine == TRANSLATION_ENGINE_LM_STUDIO and user and not user["is_admin"]:
                raise HTTPException(status_code=403, detail="LM Studio ist nur für Administratoren verfügbar")

            bookmarks, history = pipeline.bookmarks, pipeline.history
            def task():
                with pipeline.bind_user_stores(bookmarks, history):
                    apply_user_translation_settings(user)

                    return pipeline.process_stored_image(body.image_id, engine)

            if job_queue is None:
                return task()

            return job_queue.submit(
                user["id"], f"image:{body.image_id}:{engine}",
                {"kind": "image", "image_id": body.image_id, "engine": engine}, task,
            )

        except Exception as exc:
            return _api_error(exc)

    @app.post("/api/process/pdf-page")

    def process_pdf_page(
        body: ProcessPdfPageRequest,
        request: Request,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            engine = validate_translation_engine(body.engine)

            user = getattr(request.state, "user", None)

            if engine == TRANSLATION_ENGINE_LM_STUDIO and user and not user["is_admin"]:
                raise HTTPException(status_code=403, detail="LM Studio ist nur für Administratoren verfügbar")

            bookmarks, history = pipeline.bookmarks, pipeline.history
            def task():
                with pipeline.bind_user_stores(bookmarks, history):
                    apply_user_translation_settings(user)

                    return pipeline.process_stored_pdf_page(body.pdf_id, body.page_number, engine)

            if job_queue is None:
                return task()

            return job_queue.submit(
                user["id"], f"pdf:{body.pdf_id}:{body.page_number}:{engine}",
                {"kind": "pdf", "pdf_id": body.pdf_id, "page": body.page_number, "engine": engine}, task,
            )

        except Exception as exc:
            return _api_error(exc)

    @app.post("/api/process/page-image")

    def process_page_image(
        body: PageImageRequest,
        request: Request,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            engine = validate_translation_engine(body.engine)

            user = getattr(request.state, "user", None)

            if engine == TRANSLATION_ENGINE_LM_STUDIO and user and not user["is_admin"]:
                raise HTTPException(status_code=403, detail="LM Studio ist nur für Administratoren verfügbar")

            bookmarks, history = pipeline.bookmarks, pipeline.history
            job_settings = (
                user_settings_provider(str(user["id"]))

                if user_settings_provider is not None and user is not None else {}

            )

            target_language = str(job_settings.get("target_language", "deu"))

            def task():
                with pipeline.bind_user_stores(bookmarks, history):
                    if job_settings:
                        pipeline.apply_live_settings(job_settings)

                    return pipeline.process_page_image(body.image_id, engine, force=body.force)

            if job_queue is None:
                return task()

            return job_queue.submit(
                user["id"],
                f"page-image:{body.image_id}:{engine}:{target_language}:{body.force}",
                {
                    "kind": "page-image", "image_id": body.image_id,
                    "engine": engine, "target_language": target_language,
                    "force": body.force,
                }, task,
            )

        except Exception as exc:
            return _api_error(exc)

    @app.post("/api/translation-jobs/page-image")

    def enqueue_page_image(
        body: PageImageRequest,
        request: Request,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            if job_queue is None:
                raise HTTPException(status_code=503, detail="Hintergrundaufträge sind nicht verfügbar")

            engine = validate_translation_engine(body.engine)

            user = getattr(request.state, "user", None)

            if engine == TRANSLATION_ENGINE_LM_STUDIO and user and not user["is_admin"]:
                raise HTTPException(status_code=403, detail="LM Studio ist nur für Administratoren verfügbar")

            bookmarks, history = pipeline.bookmarks, pipeline.history
            job_settings = (
                user_settings_provider(str(user["id"]))

                if user_settings_provider is not None and user is not None else {}

            )

            target_language = str(job_settings.get("target_language", "deu"))

            def task():
                with pipeline.bind_user_stores(bookmarks, history):
                    if job_settings:
                        pipeline.apply_live_settings(job_settings)

                    return pipeline.process_page_image(body.image_id, engine, force=body.force)

            work = job_queue.enqueue(
                user["id"],
                f"page-image:{body.image_id}:{engine}:{target_language}:{body.force}",
                {
                    "kind": "page-image", "image_id": body.image_id,
                    "engine": engine, "target_language": target_language,
                    "force": body.force,
                },
                task,
            )

            return {"job_id": work.job_id, "status": "queued"}

        except Exception as exc:
            return _api_error(exc)

    @app.post("/api/translation-jobs/pdf-page")

    def enqueue_pdf_page(
        body: ProcessPdfPageRequest,
        request: Request,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            if job_queue is None:
                raise HTTPException(status_code=503, detail="Hintergrundaufträge sind nicht verfügbar")

            engine = validate_translation_engine(body.engine)

            user = getattr(request.state, "user", None)

            if engine == TRANSLATION_ENGINE_LM_STUDIO and user and not user["is_admin"]:
                raise HTTPException(status_code=403, detail="LM Studio ist nur für Administratoren verfügbar")

            bookmarks, history = pipeline.bookmarks, pipeline.history
            job_settings = (
                user_settings_provider(str(user["id"]))

                if user_settings_provider is not None and user is not None else {}

            )

            target_language = str(job_settings.get("target_language", "deu"))

            def task():
                with pipeline.bind_user_stores(bookmarks, history):
                    if job_settings:
                        pipeline.apply_live_settings(job_settings)

                    return pipeline.process_stored_pdf_page(
                        body.pdf_id, body.page_number, engine
                    )

            work = job_queue.enqueue(
                user["id"],
                f"pdf:{body.pdf_id}:{body.page_number}:{engine}:{target_language}",
                {
                    "kind": "pdf", "pdf_id": body.pdf_id,
                    "page": body.page_number, "engine": engine,
                    "target_language": target_language,
                },
                task,
            )

            return {"job_id": work.job_id, "status": "queued"}

        except Exception as exc:
            return _api_error(exc)

    @app.get("/api/translation-jobs/{job_id}")

    def translation_job_status(
        job_id: str,
        request: Request,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        user = getattr(request.state, "user", None)

        try:
            result = job_queue.status(str(user["id"]), job_id) if job_queue else None
        except Exception as exc:
            return _api_error(exc)

        if result is None:
            raise HTTPException(status_code=404, detail="Übersetzungsauftrag nicht gefunden")

        return result
    @app.get("/api/rendered")

    def get_rendered(_: None = Depends(require_token)) -> FileResponse:
        path = pipeline.artifacts_dir / "browser_rendered_latest.png"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Noch kein gerendertes Bild")

        return FileResponse(path, media_type="image/png")

    @app.get("/api/input")

    def get_input(_: None = Depends(require_token)) -> FileResponse:
        path = pipeline.artifacts_dir / "browser_input_latest.png"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Noch kein Eingabebild")

        return FileResponse(path, media_type="image/png")

    @app.post("/api/shutdown")

    def api_shutdown(_: None = Depends(require_token)) -> dict[str, str]:
        threading.Thread(target=BrowserServerManager.instance().stop, daemon=True).start()

        return {"status": "shutting_down"}

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/login.html")

    def login_page():
        login_path = WEB_DIR / "login.html"
        if not login_path.is_file():
            raise HTTPException(status_code=404, detail="Login-Oberfläche fehlt")

        return FileResponse(login_path)

    @app.get("/")

    def index(
        token: str | None = Query(default=None),
        code: str | None = Query(default=None),
        lingoveil_session: str | None = Cookie(default=None),
    ):
        if not is_authorized(token=token, code=code or lingoveil_session):
            query = ""
            if code:
                query = f"?error=invalid&code={code}"
            elif token:
                query = "?error=invalid"
            return RedirectResponse(url=f"/login.html{query}", status_code=302)

        index_path = WEB_DIR / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=404, detail="Web-Oberfläche fehlt")

        return FileResponse(index_path)

    return app
class BrowserServerManager:
    _singleton: BrowserServerManager | None = None
    def __init__(self) -> None:
        self.session_token = secrets.token_urlsafe(24)

        self.pipeline = BrowserTranslationPipeline(log_fn=_log)

        self.port = self.pipeline.settings.browser.port or DEFAULT_PORT
        self.access_code = self.pipeline.settings.browser.access_code or _generate_access_code()

        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None
        self._started = False
        self._last_warning: str | None = None
    @classmethod
    def instance(cls) -> BrowserServerManager:
        if cls._singleton is None:
            cls._singleton = cls()

        return cls._singleton
    @property
    def url(self) -> str:
        return _session_url(LOCAL_HOST, self.port, self.access_code)

    @property
    def urls(self) -> list[str]:
        return session_urls(self.port, self.access_code)

    @property
    def warning(self) -> str | None:
        return self._last_warning
    def launch_info(self) -> BrowserLaunchInfo:
        return BrowserLaunchInfo(
            port=self.port,
            access_code=self.access_code,
            local_url=_session_url(LOCAL_HOST, self.port, self.access_code),
            lan_urls=[
                _session_url(ip, self.port, self.access_code)

                for ip in _local_lan_addresses()

            ],
            warning=self._last_warning,
        )

    def ensure_started(
        self,
        *,
        preferred_port: int | None = None,
        access_code: str | None = None,
        strict_port: bool = False,
    ) -> BrowserLaunchInfo:
        if getattr(self.pipeline, "_closed", False):
            self.pipeline = BrowserTranslationPipeline(log_fn=_log)

        desired_port = preferred_port or self.pipeline.settings.browser.port or DEFAULT_PORT
        desired_code = access_code or self.pipeline.settings.browser.access_code or ""
        desired_code = (
            _normalize_access_code(desired_code) if desired_code else _generate_access_code()

        )

        if self._started and self._thread and self._thread.is_alive():
            if self.port == desired_port and self.access_code == desired_code:
                return self.launch_info()

            self.stop()

        if strict_port:
            if not _port_available(desired_port):
                raise RuntimeError(
                    f"Port {desired_port} ist bereits belegt. Bitte in den Optionen einen anderen Port wählen."
                )

            self.port = desired_port
        else:
            self.port = desired_port if _port_available(desired_port) else _find_free_port(desired_port)

        self.access_code = desired_code
        if self._started and self._thread and self._thread.is_alive():
            return self.launch_info()

        app = create_app(
            session_token=self.session_token,
            access_code=self.access_code,
            pipeline=self.pipeline,
            port=self.port,
        )

        config = uvicorn.Config(
            app,
            host=BIND_HOST,
            port=self.port,
            log_level="warning",
            access_log=False,
        )

        self._server = uvicorn.Server(config)

        def _run() -> None:
            _log(f"Starte auf {LOCAL_HOST}:{self.port} und LAN ({BIND_HOST}:{self.port})")

            self._server.run()

        self._thread = threading.Thread(target=_run, name="lingoveil-browser-server", daemon=False)

        self._thread.start()

        self._started = True
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self._thread.is_alive():
                time.sleep(0.05)

                break
        self._last_warning = _warn_if_firewall_blocks(self.port)

        if self._last_warning:
            _log(f"WARNUNG: {self._last_warning}")

            _log(
                f"Freigabe: sudo firewall-cmd --add-port={self.port}/tcp --permanent "
                "&& sudo firewall-cmd --reload"
            )

        for entry_url in self.urls:
            _log(f"URL: {entry_url}")

        _log(f"Code: {self.access_code}")

        return self.launch_info()

    def stop(self) -> None:
        if not self._started:
            return
        _log("Shutdown …")

        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=8.0)

        self.pipeline.close()

        self._started = False
        self._server = None
        self._thread = None
        self._last_warning = None
        _log("Beendet")

def main() -> int:
    manager = BrowserServerManager.instance()

    info = manager.ensure_started(strict_port=True)

    for entry_url in info.display_urls:
        print(entry_url)

    print(f"Code: {info.access_code}")

    try:
        while manager._thread and manager._thread.is_alive():
            time.sleep(0.5)

    except KeyboardInterrupt:
        manager.stop()

    return 0
if __name__ == "__main__":
    raise SystemExit(main())
