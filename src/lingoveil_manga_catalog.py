from __future__ import annotations
import re

from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
import httpx

from bs4 import BeautifulSoup
from lingoveil_image_pipeline import fetch_page_html, validate_remote_url
from lingoveil_mangatown import mangatown_chapter
MANGADEX_TITLE_RE = re.compile(
    r"^/title/(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})(?:/[^/]+)?/?$",
    re.IGNORECASE,
)

MANGAREAD_TITLE_RE = re.compile(r"^/manga/[^/]+/?$", re.IGNORECASE)

MANGATOWN_TITLE_RE = re.compile(r"^/manga/[^/]+/?$", re.IGNORECASE)

def _site_and_id(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url.strip())

    host = (parsed.hostname or "").lower().rstrip(".")

    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if host in {"mangaread.org", "www.mangaread.org"}:
        return ("mangaread", "") if MANGAREAD_TITLE_RE.match(parsed.path) else None
    if host in {"mangatown.com", "www.mangatown.com"}:
        return ("mangatown", "") if MANGATOWN_TITLE_RE.match(parsed.path) else None
    if host in {"mangadex.org", "www.mangadex.org"}:
        match = MANGADEX_TITLE_RE.match(parsed.path)

        return ("mangadex", match.group("id").lower()) if match else None
    return None
def is_supported_manga_url(url: str) -> bool:
    return _site_and_id(url) is not None
def _chapter_number(value: str) -> tuple:
    parts = re.findall(r"\d+(?:\.\d+)?|[a-z]+", value.lower())

    return tuple(
        (0, float(part)) if re.fullmatch(r"\d+(?:\.\d+)?", part) else (1, part)

        for part in parts
    )

def _html_catalog(
    url: str,
    *,
    site: str,
    fetch_html: Callable[..., str],
    log_fn=None,
) -> dict[str, Any]:
    html = fetch_html(url, log_fn=log_fn)

    soup = BeautifulSoup(html, "html.parser")

    heading = soup.find("h1")

    title = heading.get_text(" ", strip=True) if heading else urlparse(url).path
    canonical_host = (
        "www.mangaread.org" if site == "mangaread" else "www.mangatown.com"
    )

    canonical_root = f"https://{canonical_host}{urlparse(url).path.rstrip('/')}/"
    chapters: dict[str, dict[str, Any]] = {}

    for anchor in soup.find_all("a", href=True):
        candidate = urljoin(canonical_root, str(anchor["href"]).strip())

        parsed = urlparse(candidate)

        if (parsed.hostname or "").lower() != canonical_host:
            continue
        text = anchor.get_text(" ", strip=True)

        if site == "mangaread":
            if not parsed.path.startswith(urlparse(canonical_root).path):
                continue
            match = re.search(r"/chapter-([^/]+)/?$", parsed.path, re.IGNORECASE)

            if not match:
                continue
            chapter = match.group(1).replace("-", ".")

            label = text if text.lower().startswith("chapter") else f"Chapter {chapter}"
            volume = ""
        else:
            if not urlparse(str(anchor["href"]).strip()).path.endswith("/"):
                continue
            parsed_chapter = mangatown_chapter(candidate)

            if parsed_chapter is None:
                continue
            candidate = parsed_chapter[0]
            if not urlparse(candidate).path.startswith(urlparse(canonical_root).path):
                continue
            path = urlparse(candidate).path
            chapter_match = re.search(r"/c([^/]+)/?$", path, re.IGNORECASE)

            volume_match = re.search(r"/v([^/]+)/", path, re.IGNORECASE)

            if not chapter_match:
                continue
            chapter = chapter_match.group(1).lstrip("0") or "0"
            volume = (volume_match.group(1).lstrip("0") or "0") if volume_match else ""
            label = f"Chapter {chapter}"
            if volume:
                label += f" · Vol. {volume}"
        chapters[candidate] = {
            "label": label,
            "url": candidate,
            "volume": volume,
            "chapter": chapter,
            "language": "",
        }

    ordered = sorted(
        chapters.values(),
        key=lambda item: (
            _chapter_number(item["chapter"]),
            _chapter_number(item["volume"]),
        ),
        reverse=True,
    )

    if not ordered:
        raise ValueError("Auf der Manga-Seite wurden keine Chapter gefunden")

    return {
        "is_catalog": True,
        "site": site,
        "title": title,
        "url": canonical_root,
        "groups": [{"label": "Chapter", "chapters": ordered}],
    }

def _fetch_json(url: str) -> dict[str, Any]:
    response = httpx.get(
        url,
        headers={"User-Agent": "LingoVeil-Live/1.0"},
        follow_redirects=True,
        timeout=20.0,
    )

    response.raise_for_status()

    value = response.json()

    if not isinstance(value, dict):
        raise ValueError("MangaDex-API lieferte keine gültige Antwort")

    return value
def _localized_title(attributes: dict[str, Any]) -> str:
    titles = attributes.get("title") or {}

    for language in ("de", "en", "ja-ro"):
        if titles.get(language):
            return str(titles[language])

    return str(next(iter(titles.values()), "MangaDex Manga"))

def _with_query(url: str, values: dict[str, str]) -> str:
    parsed = urlparse(url)

    query = dict(parse_qsl(parsed.query))

    query.update(values)

    return urlunparse(parsed._replace(query=urlencode(query)))

def _mangadex_catalog(
    url: str,
    manga_id: str,
    *,
    fetch_json: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    title_payload = fetch_json(f"https://api.mangadex.org/manga/{manga_id}")

    attributes = (title_payload.get("data") or {}).get("attributes") or {}

    title = _localized_title(attributes)

    feed_root = f"https://api.mangadex.org/manga/{manga_id}/feed"
    chapters: list[dict[str, Any]] = []
    offset = 0
    while True:
        endpoint = _with_query(
            feed_root,
            {
                "limit": "100",
                "offset": str(offset),
                "order[volume]": "asc",
                "order[chapter]": "asc",
            },
        )

        payload = fetch_json(endpoint)

        batch = payload.get("data") or []
        for item in batch:
            attrs = item.get("attributes") or {}

            chapter_id = str(item.get("id", ""))

            if not chapter_id:
                continue
            volume = str(attrs.get("volume") or "")

            chapter = str(attrs.get("chapter") or "?")

            language = str(attrs.get("translatedLanguage") or "")

            label = f"Chapter {chapter}"
            if language:
                label += f" · {language.upper()}"
            chapters.append(
                {
                    "label": label,
                    "url": f"https://mangadex.org/chapter/{chapter_id}",
                    "volume": volume,
                    "chapter": chapter,
                    "language": language,
                }

            )

        offset += len(batch)

        if not batch or offset >= int(payload.get("total", offset)):
            break
    groups: dict[str, list[dict[str, Any]]] = {}

    for chapter in chapters:
        volume = chapter["volume"]
        groups.setdefault(volume, []).append(chapter)

    result_groups = [
        {
            "label": f"Volume {volume}" if volume else "Ohne Volume",
            "volume": volume,
            "chapters": items,
        }

        for volume, items in groups.items()

    ]
    if not result_groups:
        raise ValueError("MangaDex meldet keine verfügbaren Chapter")

    return {
        "is_catalog": True,
        "site": "mangadex",
        "title": title,
        "url": url,
        "groups": result_groups,
    }

def resolve_manga_catalog(
    url: str,
    *,
    fetch_html: Callable[..., str] = fetch_page_html,
    fetch_json: Callable[[str], dict[str, Any]] = _fetch_json,
    log_fn=None,
) -> dict[str, Any]:
    validate_remote_url(url)

    detected = _site_and_id(url)

    if detected is None:
        return {"is_catalog": False}

    site, manga_id = detected
    if site == "mangadex":
        return _mangadex_catalog(url, manga_id, fetch_json=fetch_json)

    return _html_catalog(url, site=site, fetch_html=fetch_html, log_fn=log_fn)
