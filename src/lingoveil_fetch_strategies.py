from __future__ import annotations
import json
import os
import tempfile
import threading

from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from lingoveil_image_pipeline import (
    GifNotAllowedError,
    SizeLimitError,
    UrlSecurityError,
    download_url_bytes,
)

FetchFn = Callable[..., tuple[bytes, str]]
def source_origin(url: str) -> str:
    parsed = urlparse(url.strip())

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Quellseite besitzt keine gültige HTTP-Origin")

    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}/"
class FetchStrategyStore:
    pass
    STRATEGIES = ("standard", "source_referer")

    def __init__(
        self,
        path: Path,
        *,
        log_fn: Callable[[str], None] | None = None,
        fetch_fn: FetchFn = download_url_bytes,
    ) -> None:
        self.path = path
        self._log = log_fn or (lambda _message: None)

        self._fetch = fetch_fn
        self._lock = threading.RLock()

    def _load(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))

            methods = raw.get("origins", {})

            if not isinstance(methods, dict):
                return {}

            return {
                str(origin): str(method)

                for origin, method in methods.items()

                if method in self.STRATEGIES
            }

        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _save(self, methods: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        fd, name = tempfile.mkstemp(prefix=".fetch-strategies-", dir=self.path.parent)

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {"version": 1, "origins": methods},
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )

                handle.write("\n")

                handle.flush()

                os.fsync(handle.fileno())

            os.replace(name, self.path)

        finally:
            Path(name).unlink(missing_ok=True)

    def _remember(self, origin: str, strategy: str) -> None:
        with self._lock:
            methods = self._load()

            if methods.get(origin) == strategy:
                return
            methods[origin] = strategy
            self._save(methods)

        self._log(f"Abrufstrategie gespeichert: {origin} → {strategy}")

    def preferred(self, source_url: str) -> str | None:
        with self._lock:
            return self._load().get(source_origin(source_url))

    def download(
        self,
        url: str,
        *,
        source_url: str,
        max_bytes: int,
        allowed_content_types: set[str],
    ) -> tuple[bytes, str]:
        origin = source_origin(source_url)

        preferred = self.preferred(source_url)

        ordered = [
            *([preferred] if preferred in self.STRATEGIES else []),
            *[method for method in self.STRATEGIES if method != preferred],
        ]
        failures: list[tuple[str, Exception]] = []
        for strategy in ordered:
            headers: dict[str, str] = {}

            if strategy == "source_referer":
                headers["Referer"] = source_url
            try:
                result = self._fetch(
                    url,
                    max_bytes=max_bytes,
                    allowed_content_types=allowed_content_types,
                    request_headers=headers,
                    log_fn=self._log,
                )

                self._remember(origin, strategy)

                return result
            except (UrlSecurityError, SizeLimitError, GifNotAllowedError):
                raise
            except Exception as exc:
                failures.append((strategy, exc))

                self._log(
                    f"Abrufstrategie {strategy} fehlgeschlagen für {origin}: {exc}"
                )

        attempted = ", ".join(method for method, _exc in failures)

        last_error = failures[-1][1]
        raise RuntimeError(
            f"Keine Abrufstrategie erfolgreich ({attempted}): {last_error}"
        ) from last_error
