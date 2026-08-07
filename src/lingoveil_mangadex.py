from __future__ import annotations
import re

from pathlib import PurePosixPath
from typing import Any, Callable
from urllib.parse import urlparse
import httpx

from lingoveil_image_pipeline import validate_remote_url
MANGADEX_API_ROOT = "https://api.mangadex.org"
MANGADEX_CHAPTER_RE = re.compile(
    r"^/chapter/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)

def mangadex_chapter_id(url: str) -> str | None:
    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if (parsed.hostname or "").lower().rstrip(".") not in {
        "mangadex.org",
        "www.mangadex.org",
    }:
        return None
    match = MANGADEX_CHAPTER_RE.match(parsed.path)

    return match.group(1).lower() if match else None
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
def resolve_mangadex_chapter(
    url: str,
    *,
    fetch_json: Callable[[str], dict[str, Any]] | None = None,
    validate_url: Callable[[str], str] = validate_remote_url,
) -> list[dict[str, str]]:
    pass
    validate_url(url)

    chapter_id = mangadex_chapter_id(url)

    if chapter_id is None:
        raise ValueError("Keine gültige MangaDex-Chapter-URL")

    fetch = fetch_json or _fetch_json
    endpoint = f"{MANGADEX_API_ROOT}/at-home/server/{chapter_id}"
    payload = fetch(endpoint)

    if payload.get("result") != "ok":
        raise ValueError("MangaDex konnte den Chapter nicht bereitstellen")

    base_url = str(payload.get("baseUrl", "")).rstrip("/")

    chapter = payload.get("chapter")

    if not base_url or not isinstance(chapter, dict):
        raise ValueError("MangaDex-Antwort enthält keinen Bildserver")

    validate_url(base_url)

    chapter_hash = str(chapter.get("hash", "")).strip()

    filenames = chapter.get("data")

    if not chapter_hash or not isinstance(filenames, list):
        raise ValueError("MangaDex-Antwort enthält keine Chapter-Seiten")

    images: list[dict[str, str]] = []
    for index, raw_name in enumerate(filenames, start=1):
        filename = str(raw_name).strip()

        if (
            not filename
            or PurePosixPath(filename).name != filename
            or filename.lower().endswith(".gif")

        ):
            continue
        image_url = f"{base_url}/data/{chapter_hash}/{filename}"
        validate_url(image_url)

        images.append(
            {
                "id": f"mangadex_{index}",
                "url": image_url,
                "key": f"mangadex-{chapter_id}-{chapter_hash}-{filename}",
            }

        )

    if not images:
        raise ValueError("MangaDex-Chapter enthält keine unterstützten Bilder")

    return images
