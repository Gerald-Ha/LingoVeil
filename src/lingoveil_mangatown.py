from __future__ import annotations
import re
import hashlib

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from lingoveil_image_pipeline import (
    ALLOWED_IMAGE_SUFFIXES,
    fetch_page_html,
    is_gif_url,
    validate_remote_url,
)

MANGATOWN_CHAPTER_RE = re.compile(
    r"^(?P<root>/manga/[^/]+/(?:[^/]+/)*c[0-9][^/]*/?)"
    r"(?:(?P<page>[1-9][0-9]*)\.html)?$",
    re.IGNORECASE,
)

def mangatown_chapter(url: str) -> tuple[str, int] | None:
    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if (parsed.hostname or "").lower().rstrip(".") not in {
        "mangatown.com",
        "www.mangatown.com",
    }:
        return None
    match = MANGATOWN_CHAPTER_RE.match(parsed.path)

    if not match:
        return None
    canonical = f"https://www.mangatown.com{match.group('root').rstrip('/')}/"
    return canonical, int(match.group("page") or 1)

def _page_number(url: str, canonical_url: str) -> int | None:
    parsed = mangatown_chapter(url)

    if parsed is None or parsed[0] != canonical_url:
        return None
    return parsed[1]
def _extract_page_image(
    html: str,
    page_url: str,
    validate_url: Callable[[str], str],
) -> str:
    soup = BeautifulSoup(html, "html.parser")

    image = soup.find("img", id="image")

    raw_url = str(image.get("src", "")).strip() if image else ""
    image_url = urljoin(page_url, raw_url)

    suffix = Path(urlparse(image_url).path).suffix.lower()

    if (
        not raw_url
        or suffix not in ALLOWED_IMAGE_SUFFIXES
        or is_gif_url(image_url)

    ):
        raise ValueError("MangaTown-Seite enthält kein unterstütztes Manga-Bild")

    validate_url(image_url)

    return image_url
def resolve_mangatown_chapter(
    url: str,
    *,
    fetch_html: Callable[..., str] = fetch_page_html,
    validate_url: Callable[[str], str] = validate_remote_url,
    log_fn=None,
) -> tuple[str, list[dict[str, str]]]:
    pass
    validate_url(url)

    parsed = mangatown_chapter(url)

    if parsed is None:
        raise ValueError("Keine gültige MangaTown-Chapter-URL")

    canonical_url, requested_page = parsed
    requested_html = fetch_html(url, log_fn=log_fn)

    soup = BeautifulSoup(requested_html, "html.parser")

    page_urls: dict[int, str] = {requested_page: url}

    for element in soup.find_all(["a", "option"]):
        raw_url = element.get("href") or element.get("value") or ""
        candidate = urljoin(url, str(raw_url).strip())

        page = _page_number(candidate, canonical_url)

        if page is not None:
            page_urls[page] = canonical_url if page == 1 else candidate
    page_urls[1] = canonical_url
    ordered = sorted(page_urls.items())

    if not ordered:
        raise ValueError("MangaTown-Chapter enthält keine lesbaren Seiten")

    def resolve_page(item: tuple[int, str]) -> tuple[int, str, str]:
        page, page_url = item
        html = requested_html if page == requested_page else fetch_html(
            page_url,
            log_fn=log_fn,
        )

        return page, page_url, _extract_page_image(
            html,
            page_url,
            validate_url,
        )

    with ThreadPoolExecutor(max_workers=min(6, len(ordered))) as executor:
        resolved = list(executor.map(resolve_page, ordered))

    images = [
        {
            "id": f"mangatown_{page}",
            "url": image_url,
            "source_url": page_url,
            "key": "mangatown-" + hashlib.sha256(
                f"{canonical_url}#{page}".encode("utf-8")

            ).hexdigest()[:24],
        }

        for page, page_url, image_url in resolved
    ]
    return canonical_url, images
