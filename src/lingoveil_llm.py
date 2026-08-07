from __future__ import annotations
import json
import re

from dataclasses import dataclass
from typing import Any
import httpx

from lingoveil_config import LlmSettings
SYSTEM_PROMPT = """You translate English manga and comic dialogue into natural German.
Input contains OCR text from speech bubbles. It may contain minor OCR mistakes,
incorrect capitalization, duplicated letters, missing letters, merged words, or broken words.
For each input block:
1. Carefully reconstruct the likely intended English text.
2. Translate it naturally into German.
3. Preserve the meaning, tone, punctuation, capitalization, and intensity.
4. Do not invent missing story details.
5. Do not add explanations.
6. Do not translate Japanese, Chinese, Korean, sound effects, or non-English noise.
OCR correction rules:
- Prefer plausible common English words over invented proper names when OCR output
  contains duplicated letters, missing letters, incorrect capitalization, or merged words.
- Do not interpret heavily damaged words as fantasy personal names unless clearly justified.
- Keep plausible proper names only when they are clearly recognizable as names.
Examples:
- "MACICIANSI!" is likely "MAGICIANS!!", not a fictional personal name.
- "Returnedii" is likely "RETURNED!!"
- "Devilsll" is likely "DEVILS!!"
German translation rules:
- Translate naturally into German. Prefer contextually natural German phrasing over
  literal word-for-word translation.
- Use idiomatic German for manga battle scenes and crowd reactions.
- Examples:
  - "Congratulations on repelling the devils!!"
    → "Glückwunsch zur erfolgreichen Vertreibung der Teufel!!"
  - "Welcome back, ultimate magicians!!"
    → "Willkommen zurück, ultimative Magier!!"
- In corrected_source, preserve comic-style ALL CAPS when the original bubble uses it.
Return strict JSON only. No markdown code blocks. No extra fields. No explanations.
Expected JSON format:
{
  "translations": [
    {
      "id": "G01",
      "corrected_source": "YAY! THEY'VE RETURNED!!",
      "german": "JAAA! SIE SIND ZURÜCK!!"
    }

  ]
}"""
@dataclass
class TranslationItem:
    block_id: str
    corrected_source: str
    german: str
@dataclass
class TranslationResponse:
    items: list[TranslationItem]
    raw_content: str
    duration_sec: float
class LlmTranslationError(Exception):
    pass
def _strip_markdown_json(content: str) -> str:
    text = content.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)

        text = re.sub(r"\s*```$", "", text)

    return text.strip()

def parse_translation_json(content: str) -> list[TranslationItem]:
    cleaned = _strip_markdown_json(content)

    if not cleaned:
        raise LlmTranslationError("Leere LLM-Antwort")

    try:
        data = json.loads(cleaned)

    except json.JSONDecodeError as exc:
        raise LlmTranslationError(f"Ungültiges JSON: {exc}") from exc
    entries = data.get("translations")

    if not isinstance(entries, list):
        raise LlmTranslationError("Feld 'translations' fehlt oder ist kein Array")

    items: list[TranslationItem] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        block_id = str(entry.get("id", "")).strip()

        corrected = str(entry.get("corrected_source", "")).strip()

        german = str(entry.get("german", "")).strip()

        if not block_id:
            continue
        items.append(
            TranslationItem(
                block_id=block_id,
                corrected_source=corrected,
                german=german,
            )

        )

    return items
DEFAULT_LLM_TIMEOUT_SEC = 120.0
class LlmTranslator:
    def __init__(self, settings: LlmSettings, log_fn) -> None:
        self.settings = settings
        self.log = log_fn
    def _translate_once(
        self,
        request_body: dict[str, Any],
        timeout_sec: float,
        attempt_label: str,
    ) -> TranslationResponse:
        import time

        self.log(
            f"Sende Anfrage an LM Studio ({attempt_label}, "
            f"Timeout {timeout_sec:.0f}s) …"
        )

        start = time.monotonic()

        try:
            with httpx.Client(timeout=timeout_sec) as client:
                response = client.post(
                    self.settings.chat_completions_url,
                    json=request_body,
                )

        except httpx.TimeoutException as exc:
            raise LlmTranslationError(
                f"Timeout nach {timeout_sec:.0f}s ({attempt_label})"
            ) from exc
        except httpx.ConnectError as exc:
            raise LlmTranslationError(f"Verbindung fehlgeschlagen: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LlmTranslationError(f"HTTP-Fehler: {exc}") from exc
        duration = time.monotonic() - start
        if response.status_code != 200:
            body = response.text[:500]
            raise LlmTranslationError(
                f"HTTP {response.status_code}: {body}"
            )

        try:
            data = response.json()

        except json.JSONDecodeError as exc:
            raise LlmTranslationError(f"Antwort ist kein JSON: {exc}") from exc
        choices = data.get("choices")

        if not choices:
            raise LlmTranslationError("Keine choices in LLM-Antwort")

        content = choices[0].get("message", {}).get("content", "")

        if not str(content).strip():
            raise LlmTranslationError("Leerer message.content in LLM-Antwort")

        items = parse_translation_json(str(content))

        self.log(f"LM Studio antwortete ({attempt_label}, {duration:.2f}s)")

        return TranslationResponse(items=items, raw_content=str(content), duration_sec=duration)

    def translate_blocks(
        self,
        blocks: list[dict[str, str]],
        *,
        max_chars: int,
        max_blocks: int,
    ) -> TranslationResponse:
        if not blocks:
            raise LlmTranslationError("Keine Blöcke zum Übersetzen")

        if len(blocks) > max_blocks:
            raise LlmTranslationError(f"Zu viele Blöcke ({len(blocks)} > {max_blocks})")

        payload_blocks = [{"id": b["id"], "text": b["text"]} for b in blocks]
        block_sections = [
            f"[{block['id']}]\n{block['text']}" for block in payload_blocks
        ]
        user_content = (
            "Translate the following OCR blocks from English to German. "
            "Return strict JSON only.\n\n" + "\n\n".join(block_sections)

        )

        if len(user_content) > max_chars:
            raise LlmTranslationError(
                f"Anfrage zu lang ({len(user_content)} Zeichen > {max_chars})"
            )

        self.log(
            "Prompt-Format: ein Batch mit "
            f"{len(payload_blocks)} Blöcken ([Gxx] + Text je Block)"
        )

        request_body: dict[str, Any] = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
        }

        timeout_sec = float(self.settings.timeout_sec)

        return self._translate_once(request_body, timeout_sec, "Anfrage")
