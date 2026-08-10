from __future__ import annotations
import json
import re
import threading
import time

from dataclasses import dataclass
from typing import Any, Callable
import httpx

OLLAMA_PROMPT_VERSION = "ollama-translategemma-v1"
OLLAMA_MAX_BLOCKS = 10
OLLAMA_MAX_INPUT_CHARS = 1500
TRANSLATEGEMMA_LANGUAGES: tuple[str, ...] = (
    "ar-EG", "ar-SA", "bg-BG", "bn-IN", "ca-ES", "cs-CZ", "da-DK",
    "de-DE", "el-GR", "en", "es-MX", "et-EE", "fa-IR", "fi-FI",
    "fil-PH", "fr-CA", "fr-FR", "gu-IN", "he-IL", "hi-IN", "hr-HR",
    "hu-HU", "id-ID", "is-IS", "it-IT", "ja-JP", "kn-IN", "ko-KR",
    "lt-LT", "lv-LV", "ml-IN", "mr-IN", "nl-NL", "no-NO", "pa-IN",
    "pl-PL", "pt-BR", "pt-PT", "ro-RO", "ru-RU", "sk-SK", "sl-SI",
    "sr-RS", "sv-SE", "sw-KE", "sw-TZ", "ta-IN", "te-IN", "th-TH",
    "tr-TR", "uk-UA", "ur-PK", "vi-VN", "zh-CN", "zh-TW", "zu-ZA",
)

KNOWN_OLLAMA_MODEL_CAPABILITIES: dict[str, dict[str, Any]] = {
    "translategemma:4b": {
        "supported_languages": TRANSLATEGEMMA_LANGUAGES,
        "officially_supported": True,
        "tested": True,
    },
    "translategemma:12b": {
        "supported_languages": TRANSLATEGEMMA_LANGUAGES,
        "officially_supported": True,
        "tested": False,
    },
    "translategemma:27b": {
        "supported_languages": TRANSLATEGEMMA_LANGUAGES,
        "officially_supported": True,
        "tested": False,
    },
}

LINGOVEIL_TO_TRANSLATEGEMMA: dict[str, str] = {
    "arb": "ar-SA", "bul": "bg-BG", "ben": "bn-IN", "cat": "ca-ES",
    "ces": "cs-CZ", "dan": "da-DK", "deu": "de-DE", "ell": "el-GR",
    "eng": "en", "spa": "es-MX", "est": "et-EE", "pes": "fa-IR",
    "fin": "fi-FI", "tgl": "fil-PH", "fra": "fr-FR", "guj": "gu-IN",
    "heb": "he-IL", "hin": "hi-IN", "hrv": "hr-HR", "hun": "hu-HU",
    "ind": "id-ID", "isl": "is-IS", "ita": "it-IT", "jpn": "ja-JP",
    "kan": "kn-IN", "kor": "ko-KR", "lit": "lt-LT", "lvs": "lv-LV",
    "mal": "ml-IN", "mar": "mr-IN", "nld": "nl-NL", "nob": "no-NO",
    "pan": "pa-IN", "pol": "pl-PL", "por": "pt-PT", "ron": "ro-RO",
    "rus": "ru-RU", "slk": "sk-SK", "slv": "sl-SI", "srp": "sr-RS",
    "swe": "sv-SE", "swh": "sw-KE", "tam": "ta-IN", "tel": "te-IN",
    "tha": "th-TH", "tur": "tr-TR", "ukr": "uk-UA", "urd": "ur-PK",
    "vie": "vi-VN", "cmn": "zh-CN", "cmn_Hant": "zh-TW", "zul": "zu-ZA",
}

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "pt": "Portuguese",
    "ru": "Russian", "ar": "Arabic", "it": "Italian", "uk": "Ukrainian",
}

def normalize_ollama_model_name(name: str) -> str:
    return name.strip().lower()

def ollama_model_capabilities(name: str) -> dict[str, Any]:
    normalized = normalize_ollama_model_name(name)

    known = KNOWN_OLLAMA_MODEL_CAPABILITIES.get(normalized)

    if known is None:
        return {
            "model": normalized,
            "supported_languages": (),
            "officially_supported": False,
            "tested": False,
            "capabilities_known": False,
        }

    return {"model": normalized, "capabilities_known": True, **known}

def ollama_supported_lingoveil_languages(name: str) -> list[str]:
    caps = ollama_model_capabilities(name)

    supported = set(caps["supported_languages"])

    return [code for code, translated in LINGOVEIL_TO_TRANSLATEGEMMA.items() if translated in supported]
def to_translategemma_language(code: str) -> str:
    value = code.strip()

    return LINGOVEIL_TO_TRANSLATEGEMMA.get(value, value.replace("_", "-"))

class OllamaTranslationError(Exception):
    pass
class OllamaStructuredOutputError(OllamaTranslationError):
    pass
@dataclass(frozen=True)

class OllamaSettings:
    base_url: str = "http://host.docker.internal:11435"
    model: str = "translategemma:4b"
    timeout_sec: float = 120.0
    keep_alive: str = "2m"
    bridge_token: str = ""
@dataclass(frozen=True)

class OllamaTranslationItem:
    block_id: str
    translation: str
@dataclass(frozen=True)

class OllamaTranslationResponse:
    items: list[OllamaTranslationItem]
    duration_sec: float
    metrics: dict[str, int | float]
class OllamaTranslator:
    def __init__(
        self,
        settings: OllamaSettings,
        log_fn: Callable[[str], None] | None = None,
        unavailable_fn: Callable[[str], None] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.log = log_fn or (lambda message: None)

        self.unavailable_fn = unavailable_fn
        self._client = httpx.Client(transport=transport)

        self._request_lock = threading.Lock()

        self._closed = False
    def update_settings(self, settings: OllamaSettings) -> None:
        self.settings = settings
    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._client.close()

    def _url(self, path: str) -> str:
        return f"{self.settings.base_url.rstrip('/')}{path}"
    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._closed:
            raise OllamaTranslationError("Ollama-Client wurde geschlossen")

        try:
            headers = dict(kwargs.pop("headers", {}))

            if self.settings.bridge_token:
                headers["Authorization"] = f"Bearer {self.settings.bridge_token}"
            connect_timeout = min(5.0, self.settings.timeout_sec)

            response = self._client.request(
                method, self._url(path), timeout=httpx.Timeout(
                    self.settings.timeout_sec, connect=connect_timeout
                ),
                headers=headers, **kwargs
            )

            response.raise_for_status()

            return response
        except httpx.ConnectTimeout as exc:
            message = f"Ollama-Verbindungsaufbau nach {connect_timeout:g}s abgebrochen"
            self._mark_unavailable(message)

            raise OllamaTranslationError(message) from exc
        except httpx.TimeoutException as exc:
            self._mark_unavailable(f"Ollama-Timeout nach {self.settings.timeout_sec:g}s")

            raise OllamaTranslationError(
                f"Ollama-Timeout nach {self.settings.timeout_sec:g}s"
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            messages = {
                401: "Bridge-Authentifizierung fehlgeschlagen",
                403: "Ollama-Endpunkt wurde von der Bridge abgelehnt",
                502: "Bridge erreichbar, aber Ollama nicht verfügbar",
            }

            message = messages.get(
                exc.response.status_code,
                f"Ollama HTTP {exc.response.status_code}: {detail}",
            )

            self._mark_unavailable(message)

            raise OllamaTranslationError(message) from exc
        except httpx.HTTPError as exc:
            self._mark_unavailable(f"Ollama-Verbindung fehlgeschlagen: {exc}")

            raise OllamaTranslationError(f"Ollama-Verbindung fehlgeschlagen: {exc}") from exc
    def _mark_unavailable(self, reason: str) -> None:
        if self.unavailable_fn is not None:
            self.unavailable_fn(reason)

    def list_models(self) -> list[dict[str, Any]]:
        try:
            data = self._request("GET", "/api/tags").json()

        except (json.JSONDecodeError, ValueError) as exc:
            raise OllamaTranslationError("Ollama /api/tags lieferte kein gültiges JSON") from exc
        models = data.get("models")

        if not isinstance(models, list):
            raise OllamaTranslationError("Ollama /api/tags enthält keine Modellliste")

        result = []
        for entry in models:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or entry.get("model") or "").strip()

            if not name:
                continue
            result.append({**entry, **ollama_model_capabilities(name)})

        return result
    def show_model(self, model: str | None = None) -> dict[str, Any]:
        try:
            return self._request(
                "POST", "/api/show", json={"model": model or self.settings.model}

            ).json()

        except (json.JSONDecodeError, ValueError) as exc:
            raise OllamaTranslationError("Ollama /api/show lieferte kein gültiges JSON") from exc
    @staticmethod
    def _schema(ids: list[str]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "translations": {
                    "type": "object",
                    "properties": {
                        block_id: {"type": "string", "minLength": 1}

                        for block_id in ids
                    },
                    "required": ids,
                    "additionalProperties": False,
                }
            },
            "required": ["translations"],
            "additionalProperties": False,
        }

    @staticmethod
    def _language_name(code: str) -> str:
        base = code.split("-", 1)[0].lower()

        return LANGUAGE_NAMES.get(base, code)

    def _prompt(
        self, blocks: list[dict[str, str]], source_lang: str, target_lang: str
    ) -> str:
        source = to_translategemma_language(source_lang)

        target = to_translategemma_language(target_lang)

        dialogue = [{"id": str(b["id"]), "text": str(b["text"])} for b in blocks]
        return (
            f"You are a professional {self._language_name(source)} ({source}) to "
            f"{self._language_name(target)} ({target}) translator. Translate the following "
            "manga or comic dialogue accurately. Preserve the original meaning, natural "
            "conversational language, names, jokes, emotional tone, punctuation, and "
            "intensity. Translate every speech bubble separately and never merge speech "
            "bubbles. Do not explain or provide alternatives. Return only the JSON object "
            "required by the response schema.\n\n"
            + json.dumps({"dialogue": dialogue}, ensure_ascii=False, separators=(",", ":"))

        )

    @staticmethod
    def _parse_content(content: str, expected_ids: set[str]) -> tuple[dict[str, str], set[str]]:
        try:
            data = json.loads(content)

        except json.JSONDecodeError as exc:
            raise OllamaStructuredOutputError(f"Ungültiges Ollama-JSON: {exc}") from exc
        translations = data.get("translations") if isinstance(data, dict) else None
        if not isinstance(translations, dict):
            raise OllamaStructuredOutputError("Ollama-Antwort enthält kein translations-Objekt")

        valid: dict[str, str] = {}

        returned = {str(key) for key in translations}

        for block_id in expected_ids & returned:
            value = translations.get(block_id)

            if isinstance(value, str) and value.strip():
                valid[block_id] = value.strip()

        invalid_ids = (expected_ids - set(valid)) | (returned - expected_ids)

        return valid, invalid_ids
    def _translate_once(
        self,
        blocks: list[dict[str, str]],
        source_lang: str,
        target_lang: str,
    ) -> tuple[dict[str, str], set[str], float, dict[str, int | float]]:
        ids = [str(block["id"]) for block in blocks]
        body = {
            "model": self.settings.model,
            "stream": False,
            "keep_alive": self.settings.keep_alive,
            "options": {"temperature": 0},
            "messages": [{
                "role": "user",
                "content": self._prompt(blocks, source_lang, target_lang),
            }],
            "format": self._schema(ids),
        }

        started = time.monotonic()

        response = self._request("POST", "/api/chat", json=body)

        duration = time.monotonic() - started
        try:
            payload = response.json()

        except json.JSONDecodeError as exc:
            raise OllamaTranslationError("Ollama /api/chat lieferte kein gültiges JSON") from exc
        content = str(payload.get("message", {}).get("content", ""))

        valid, invalid = self._parse_content(content, set(ids))

        metrics = {
            key: payload[key]
            for key in ("load_duration", "prompt_eval_duration", "eval_duration")

            if isinstance(payload.get(key), (int, float))
        }

        self.log(
            "Ollama antwortete in " + f"{duration:.2f}s; "
            + ", ".join(f"{key}={value}" for key, value in metrics.items())

        )

        return valid, invalid, duration, metrics
    def translate_blocks(
        self,
        blocks: list[dict[str, str]],
        *,
        source_lang: str,
        target_lang: str,
        max_chars: int = OLLAMA_MAX_INPUT_CHARS,
        max_blocks: int = OLLAMA_MAX_BLOCKS,
    ) -> OllamaTranslationResponse:
        if not blocks:
            return OllamaTranslationResponse([], 0.0, {})

        if len(blocks) > max_blocks:
            raise OllamaTranslationError(f"Zu viele Ollama-Blöcke ({len(blocks)} > {max_blocks})")

        if sum(len(str(block["text"])) for block in blocks) > max_chars:
            raise OllamaTranslationError("Ollama-Batch überschreitet das Zeichenlimit")

        ids = [str(block["id"]) for block in blocks]
        if len(ids) != len(set(ids)) or any(not re.fullmatch(r"[A-Za-z0-9_-]+", i) for i in ids):
            raise OllamaTranslationError("Ungültige oder doppelte Block-ID")

        by_id = {str(block["id"]): block for block in blocks}

        with self._request_lock:
            try:
                valid, invalid, duration, metrics = self._translate_once(
                    blocks, source_lang, target_lang
                )

                missing = set(ids) - set(valid)

                retry_ids = set(missing)

                if invalid - set(ids):
                    retry_ids = set(ids)

                    valid.clear()

            except OllamaStructuredOutputError:
                valid, duration, metrics = {}, 0.0, {}

                retry_ids = set(ids)

            for block_id in ids:
                if block_id not in retry_ids:
                    continue
                retry_valid, retry_invalid, retry_duration, retry_metrics = self._translate_once(
                    [by_id[block_id]], source_lang, target_lang
                )

                duration += retry_duration
                metrics.update(retry_metrics)

                if retry_invalid or set(retry_valid) != {block_id}:
                    continue
                valid.update(retry_valid)

            if set(valid) != set(ids):
                missing_text = ", ".join(sorted(set(ids) - set(valid))) or "keine"
                raise OllamaTranslationError(
                    f"Ollama-Antwort unvollständig oder ungültig; fehlend: {missing_text}"
                )

        return OllamaTranslationResponse(
            [OllamaTranslationItem(block_id=i, translation=valid[i]) for i in ids],
            duration,
            metrics,
        )

    def test_connection(self) -> dict[str, Any]:
        models = self.list_models()

        names = {str(entry["model"]) for entry in models}

        normalized = normalize_ollama_model_name(self.settings.model)

        if normalized not in names:
            raise OllamaTranslationError(
                f"Ollama-Modell '{self.settings.model}' ist nicht installiert"
            )

        self.show_model(self.settings.model)

        probe = self.translate_blocks(
            [{"id": "TEST", "text": "Hello!"}],
            source_lang="eng",
            target_lang="deu",
            max_blocks=1,
            max_chars=100,
        )

        return {
            "available": True,
            "model": self.settings.model,
            "translation": probe.items[0].translation,
            "duration_sec": probe.duration_sec,
            "metrics": probe.metrics,
        }
