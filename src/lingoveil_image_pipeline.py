from __future__ import annotations
import ipaddress
import os
import re
import socket
import tempfile

from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
import httpx

from PIL import Image
ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

ALLOWED_IMAGE_MIME = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
}

MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_PDF_BYTES = 100 * 1024 * 1024
MAX_PDF_PAGES = 500
URL_TIMEOUT_SEC = 20.0
URL_MAX_REDIRECTS = 5
BLOCKED_SCHEMES = {"file", "ftp", "data", "javascript", "mailto", "blob"}

IMAGE_URL_RE = re.compile(r"\.(png|jpe?g|webp)(\?|$)", re.IGNORECASE)

GIF_URL_RE = re.compile(r"\.gif(?:$|[?#])", re.IGNORECASE)

PDF_URL_RE = re.compile(r"\.pdf(\?|$)", re.IGNORECASE)

class UrlSecurityError(ValueError):
    pass
class SizeLimitError(ValueError):
    pass
class GifNotAllowedError(ValueError):
    pass
def is_gif_bytes(data: bytes) -> bool:
    return data.startswith((b"GIF87a", b"GIF89a"))

def is_gif_url(url: str) -> bool:
    return bool(GIF_URL_RE.search(url.strip()))

def is_social_preview_url(url: str) -> bool:
    name = Path(urlparse(url).path).stem.lower().replace("_", "-")

    return name in {
        "fbshare",
        "facebook-share",
        "social-share",
        "og-image",
        "twitter-card",
    }

def _log(msg: str, log_fn: Any = None) -> None:
    if log_fn:
        log_fn(msg)

    else:
        print(f"[Browser-Pipeline] {msg}")

def _hostname_blocked(hostname: str) -> str | None:
    host = (hostname or "").strip().lower().rstrip(".")

    if not host:
        return "Leerer Hostname"
    if host in {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}:
        return "localhost ist blockiert"
    if host.endswith(".local") or host.endswith(".internal"):
        return f"Interner Hostname blockiert: {host}"
    try:
        if ":" in host and not host.startswith("["):
            addr = ipaddress.ip_address(host)

        else:
            literal = host.strip("[]")

            addr = ipaddress.ip_address(literal)

    except ValueError:
        return None
    if addr.is_loopback:
        return "Loopback-Adresse blockiert"
    if addr.is_private:
        return "Private IP-Adresse blockiert"
    if addr.is_link_local:
        return "Link-Local-Adresse blockiert"
    if addr.is_multicast:
        return "Multicast-Adresse blockiert"
    if addr.is_reserved:
        return "Reservierte IP-Adresse blockiert"
    if str(addr) == "169.254.169.254":
        return "Metadata-IP blockiert"
    return None
def validate_remote_url(url: str) -> str:
    parsed = urlparse(url.strip())

    scheme = (parsed.scheme or "").lower()

    if scheme not in {"http", "https"}:
        raise UrlSecurityError(
            f"Nur http/https erlaubt. Blockiertes Schema: {scheme or '(leer)'}"
        )

    if scheme in BLOCKED_SCHEMES:
        raise UrlSecurityError(f"Schema blockiert: {scheme}")

    host = parsed.hostname
    if not host:
        raise UrlSecurityError("URL ohne Hostname")

    blocked = _hostname_blocked(host)

    if blocked:
        raise UrlSecurityError(blocked)

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if scheme == "https" else 80))

    except socket.gaierror as exc:
        raise UrlSecurityError(f"Hostname nicht auflösbar: {host}") from exc
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        blocked_ip = _hostname_blocked(ip_str)

        if blocked_ip:
            raise UrlSecurityError(f"{blocked_ip} ({ip_str})")

    return url.strip()

def classify_remote_url(url: str) -> str:
    pass
    validated = validate_remote_url(url)

    parsed = urlparse(validated)

    path_lower = (parsed.path or "").lower()

    if path_lower.endswith(".pdf") or PDF_URL_RE.search(validated):
        return "pdf"
    if any(path_lower.endswith(ext) for ext in ALLOWED_IMAGE_SUFFIXES):
        return "image"
    if IMAGE_URL_RE.search(validated):
        return "image"
    return "page"
def sniff_download_kind(data: bytes) -> str | None:
    if is_pdf_bytes(data):
        return "application/pdf"
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()

        return "image"
    except Exception:
        return None
def _content_type_matches_allowed(
    content_type: str,
    data: bytes,
    allowed_content_types: set[str],
) -> bool:
    normalized = (content_type or "").split(";")[0].strip().lower()

    if normalized in allowed_content_types:
        return True
    if normalized in {"", "application/octet-stream"} and "application/octet-stream" in allowed_content_types:
        return True
    sniffed = sniff_download_kind(data)

    if sniffed == "image" and allowed_content_types & ALLOWED_IMAGE_MIME:
        return True
    if sniffed == "application/pdf" and "application/pdf" in allowed_content_types:
        return True
    return False
def _read_limited_response(
    response: httpx.Response,
    *,
    max_bytes: int,
) -> bytes:
    total = 0
    chunks: list[bytes] = []
    for chunk in response.iter_bytes(chunk_size=65536):
        total += len(chunk)

        if total > max_bytes:
            raise SizeLimitError(
                f"Download überschreitet {max_bytes // (1024 * 1024)} MB"
            )

        chunks.append(chunk)

    return b"".join(chunks)

def download_url_bytes(
    url: str,
    *,
    max_bytes: int,
    allowed_content_types: set[str] | None = None,
    request_headers: dict[str, str] | None = None,
    log_fn: Any = None,
) -> tuple[bytes, str]:
    validated = validate_remote_url(url)

    if is_gif_url(validated):
        raise GifNotAllowedError("GIF-Bilder sind deaktiviert")

    current = validated
    with httpx.Client(
        follow_redirects=False,
        timeout=URL_TIMEOUT_SEC,
        headers={
            "User-Agent": "LingoVeil-Browser/1.0",
            **(request_headers or {}),
        },
    ) as client:
        for _ in range(URL_MAX_REDIRECTS + 1):
            validate_remote_url(current)

            response = client.get(current)

            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")

                if not location:
                    raise UrlSecurityError("Redirect ohne Ziel-URL")

                current = urljoin(current, location)

                continue
            response.raise_for_status()

            content_type = (
                response.headers.get("content-type", "").split(";")[0].strip().lower()

            )

            data = _read_limited_response(response, max_bytes=max_bytes)

            if content_type == "image/gif" or is_gif_bytes(data):
                raise GifNotAllowedError("GIF-Bilder sind deaktiviert")

            if allowed_content_types and not _content_type_matches_allowed(
                content_type,
                data,
                allowed_content_types,
            ):
                raise ValueError(
                    f"Unerwarteter Content-Type: {content_type or 'unbekannt'}"
                )

            if not content_type:
                sniffed = sniff_download_kind(data)

                if sniffed == "image":
                    content_type = "image/jpeg"
                elif sniffed == "application/pdf":
                    content_type = "application/pdf"
            _log(f"Download OK ({len(data)} Bytes): {current}", log_fn)

            return data, content_type
    raise UrlSecurityError("Zu viele Redirects")

def load_image_bytes(data: bytes) -> Image.Image:
    if len(data) > MAX_IMAGE_BYTES:
        raise SizeLimitError("Bilddatei zu groß")

    if is_gif_bytes(data):
        raise GifNotAllowedError("GIF-Bilder sind deaktiviert")

    image = Image.open(BytesIO(data))

    image.load()

    return image.convert("RGB")

def load_image_file(path: Path) -> Image.Image:
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise SizeLimitError("Bilddatei zu groß")

    suffix = path.suffix.lower()

    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise ValueError(f"Nicht unterstütztes Bildformat: {suffix}")

    image = Image.open(path)

    image.load()

    return image.convert("RGB")

def save_image_copy(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}-",
        suffix=path.suffix or ".png",
        dir=path.parent,
        delete=False,
    ) as handle:
        tmp_path = Path(handle.name)

    try:
        image.save(tmp_path, format="PNG")

        os.replace(tmp_path, path)

    finally:
        tmp_path.unlink(missing_ok=True)

def is_pdf_bytes(data: bytes) -> bool:
    return data[:4] == b"%PDF"
def render_pdf_page(pdf_path: Path, page_number: int) -> Image.Image:
    import fitz

    if pdf_path.stat().st_size > MAX_PDF_BYTES:
        raise SizeLimitError("PDF-Datei zu groß")

    doc = fitz.open(pdf_path)

    try:
        if doc.page_count > MAX_PDF_PAGES:
            raise ValueError(f"PDF hat mehr als {MAX_PDF_PAGES} Seiten")

        if page_number < 0 or page_number >= doc.page_count:
            raise ValueError("Ungültige Seitennummer")

        page = doc.load_page(page_number)

        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)

        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    finally:
        doc.close()

def pdf_page_count(pdf_path: Path) -> int:
    import fitz

    if pdf_path.stat().st_size > MAX_PDF_BYTES:
        raise SizeLimitError("PDF-Datei zu groß")

    doc = fitz.open(pdf_path)

    try:
        count = doc.page_count
        if count > MAX_PDF_PAGES:
            raise ValueError(f"PDF hat mehr als {MAX_PDF_PAGES} Seiten")

        return count
    finally:
        doc.close()

def extract_page_images(html: str, base_url: str) -> list[dict[str, str]]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    found: list[str] = []
    seen: set[str] = set()

    def add_candidate(raw: str) -> None:
        if not raw:
            return
        absolute = urljoin(base_url, raw.strip())

        if is_gif_url(absolute):
            return
        if absolute in seen:
            return
        seen.add(absolute)

        found.append(absolute)

    for img in soup.find_all("img"):
        add_candidate(img.get("src", ""))

        srcset = img.get("srcset", "")

        for part in srcset.split(","):
            token = part.strip().split(" ")[0]
            add_candidate(token)

    for source in soup.find_all("source"):
        add_candidate(source.get("src", ""))

        srcset = source.get("srcset", "")

        for part in srcset.split(","):
            token = part.strip().split(" ")[0]
            add_candidate(token)

    if not found:
        for meta in soup.find_all("meta"):
            if (meta.get("property") or "").lower() == "og:image":
                add_candidate(meta.get("content", ""))

    results: list[dict[str, str]] = []
    for idx, url in enumerate(found, start=1):
        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"}:
            continue
        if is_social_preview_url(url):
            continue
        lower = url.lower()

        if any(lower.endswith(ext) for ext in ALLOWED_IMAGE_SUFFIXES):
            results.append({"id": f"img_{idx}", "url": url})

        elif re.search(r"\.(png|jpe?g|webp)(\?|$)", lower):
            results.append({"id": f"img_{idx}", "url": url})

    return results
def fetch_page_html(url: str, *, log_fn: Any = None) -> str:
    data, content_type = download_url_bytes(
        url,
        max_bytes=2 * 1024 * 1024,
        allowed_content_types={"text/html", "application/xhtml+xml"},
        log_fn=log_fn,
    )

    if content_type and "html" not in content_type and "xhtml" not in content_type:
        raise ValueError("URL lieferte kein HTML")

    return data.decode("utf-8", errors="replace")
