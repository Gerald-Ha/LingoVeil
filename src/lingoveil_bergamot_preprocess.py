from __future__ import annotations
import hashlib
import json
import re
import time

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from lingoveil_config import (
    TRANSLATION_ENGINE_BERGAMOT,
    TRANSLATION_ENGINE_SEAMLESS_M4T,
    BergamotPreprocessSettings,
    SEAMLESS_DEFAULT_MODEL_ID,
    SEAMLESS_DEFAULT_MODEL_REVISION,
)

from lingoveil_languagetool import (
    LANGUAGETOOL_SAFE_RULES_VERSION,
    LanguageToolError,
    LocalLanguageToolClient,
)

MIN_TOKEN_LEN_SYMSPELL = 4
MIN_TOKEN_LEN_EDIT2 = 8
MIN_FREQUENCY_RATIO_EDIT2 = 4.0
_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")

_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?;]\s*$")

BERGAMOT_FUNCTION_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "to", "of", "in", "on", "at", "by",
    "for", "with", "from", "as", "is", "am", "are", "was", "were", "be", "been",
    "will", "would", "shall", "should", "can", "could", "may", "might", "must",
    "do", "does", "did", "have", "has", "had", "not", "no", "yes", "so", "than",
    "that", "this", "these", "those", "it", "its", "we", "you", "they", "he",
    "she", "me", "him", "her", "us", "them", "my", "your", "our", "their",
    "into", "onto", "up", "down", "out", "off", "over", "under", "about",
    "when", "where", "while", "because", "then", "there", "here", "all", "some",
    "any", "each", "every", "both", "either", "neither", "too", "very", "just",
    "only", "also", "even", "still", "already", "yet", "now", "how", "what",
    "who", "whom", "which", "why", "go", "going", "been", "being",
})

_SYMSPELL_BUNDLE: tuple[Any, Any] | None = None
_SYMSPELL_DICT_PATH: Path | None = None
_SYMSPELL_INIT_MS: float = 0.0
def get_symspell_init_ms() -> float:
    return _SYMSPELL_INIT_MS
def reset_symspell_singleton() -> None:
    global _SYMSPELL_BUNDLE, _SYMSPELL_DICT_PATH, _SYMSPELL_INIT_MS
    _SYMSPELL_BUNDLE = None
    _SYMSPELL_DICT_PATH = None
    _SYMSPELL_INIT_MS = 0.0
def _load_symspell_singleton(
    dict_path: Path,
    log_fn: Callable[[str], None] | None = None,
) -> tuple[Any, Any]:
    global _SYMSPELL_BUNDLE, _SYMSPELL_DICT_PATH, _SYMSPELL_INIT_MS
    if _SYMSPELL_BUNDLE is not None and _SYMSPELL_DICT_PATH == dict_path:
        return _SYMSPELL_BUNDLE
    from symspellpy import SymSpell, Verbosity
    t0 = time.monotonic()

    sym = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)

    if not dict_path.exists():
        raise FileNotFoundError(f"SymSpell-Wörterbuch fehlt: {dict_path}")

    sym.load_dictionary(str(dict_path), term_index=0, count_index=1)

    _SYMSPELL_BUNDLE = (sym, Verbosity)

    _SYMSPELL_DICT_PATH = dict_path
    _SYMSPELL_INIT_MS = (time.monotonic() - t0) * 1000
    if log_fn:
        log_fn(f"SymSpell-Wörterbuch geladen ({_SYMSPELL_INIT_MS:.0f} ms)")

    return _SYMSPELL_BUNDLE
@dataclass
class OcrGlossary:
    version: int = 1
    protected_terms: list[str] = field(default_factory=list)

    corrections: dict[str, str] = field(default_factory=dict)

    @property
    def protected_set(self) -> set[str]:
        return set(self.protected_terms)

    @property
    def fingerprint(self) -> str:
        payload = {
            "version": self.version,
            "protected_terms": sorted(self.protected_terms),
            "corrections": {
                k.lower(): v for k, v in sorted(self.corrections.items())
            },
        }

        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)

        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
def load_ocr_glossary(path: Path, log_fn: Callable[[str], None] | None = None) -> OcrGlossary:
    if not path.exists():
        if log_fn:
            log_fn(f"Glossar fehlt ({path}) – leeres Glossar")

        return OcrGlossary()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))

    except json.JSONDecodeError as exc:
        if log_fn:
            log_fn(f"Glossar ungültig ({exc}) – leeres Glossar")

        return OcrGlossary()

    if not isinstance(raw, dict):
        return OcrGlossary()

    protected = raw.get("protected_terms") or []
    corrections = raw.get("corrections") or {}

    return OcrGlossary(
        version=int(raw.get("version", 1)),
        protected_terms=[str(x) for x in protected],
        corrections={str(k): str(v) for k, v in corrections.items()},
    )

def ensure_glossary_file(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)

    template = {
        "version": 1,
        "protected_terms": [],
        "corrections": {},
    }

    path.write_text(json.dumps(template, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

@dataclass
class PreprocessResult:
    original_text: str
    normalized_text: str
    glossary_text: str
    symspell_text: str
    languagetool_text: str
    final_text: str
    applied_changes: list[dict[str, Any]] = field(default_factory=list)

    warnings: list[str] = field(default_factory=list)

    stage_durations_ms: dict[str, float] = field(default_factory=dict)

def should_run_bergamot_preprocess(
    active_engine: str,
    settings: BergamotPreprocessSettings,
) -> bool:
    pass
    return (
        active_engine == TRANSLATION_ENGINE_BERGAMOT
        and settings.enabled
    )

def should_run_local_preprocess(
    active_engine: str,
    settings: BergamotPreprocessSettings,
) -> bool:
    pass
    return (
        active_engine in (TRANSLATION_ENGINE_BERGAMOT, TRANSLATION_ENGINE_SEAMLESS_M4T)

        and settings.enabled
    )

def build_bergamot_preprocess_cache_key(
    final_preprocessed_text: str,
    *,
    settings: BergamotPreprocessSettings,
    glossary_fingerprint: str,
    source_lang: str = "en",
    target_lang: str = "de",
    bergamot_model_or_variant: str = "bergamot-en-de",
) -> str:
    normalized = final_preprocessed_text.strip().lower()

    payload = {
        "translation_engine": TRANSLATION_ENGINE_BERGAMOT,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "bergamot_model_or_variant": bergamot_model_or_variant,
        "preprocess_enabled": settings.enabled,
        "preprocess_mode": settings.mode,
        "preprocess_version": settings.preprocess_version,
        "normalization_enabled": settings.normalization_enabled,
        "glossary_enabled": settings.glossary_enabled,
        "glossary_fingerprint": glossary_fingerprint,
        "symspell_enabled": settings.symspell_enabled,
        "languagetool_enabled": settings.languagetool_enabled,
        "languagetool_safe_rules_version": LANGUAGETOOL_SAFE_RULES_VERSION,
        "final_preprocessed_text": normalized,
    }

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def build_seamless_m4t_preprocess_cache_key(
    final_preprocessed_text: str,
    *,
    settings: BergamotPreprocessSettings,
    glossary_fingerprint: str,
    source_lang: str = "eng",
    target_lang: str = "deu",
    model_id: str = SEAMLESS_DEFAULT_MODEL_ID,
    model_revision: str = SEAMLESS_DEFAULT_MODEL_REVISION,
) -> str:
    normalized = final_preprocessed_text.strip().lower()

    payload = {
        "translation_engine": TRANSLATION_ENGINE_SEAMLESS_M4T,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "model": model_id,
        "revision": model_revision,
        "preprocess_enabled": settings.enabled,
        "preprocess_mode": settings.mode,
        "preprocess_version": settings.preprocess_version,
        "normalization_enabled": settings.normalization_enabled,
        "glossary_enabled": settings.glossary_enabled,
        "glossary_fingerprint": glossary_fingerprint,
        "symspell_enabled": settings.symspell_enabled,
        "languagetool_enabled": settings.languagetool_enabled,
        "languagetool_safe_rules_version": LANGUAGETOOL_SAFE_RULES_VERSION,
        "final_preprocessed_text": normalized,
    }

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

class BergamotPreprocessor:
    pass
    def __init__(
        self,
        settings: BergamotPreprocessSettings,
        *,
        glossary: OcrGlossary | None = None,
        glossary_path: Path | None = None,
        symspell_dict_path: Path | None = None,
        languagetool_client: LocalLanguageToolClient | None = None,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.log_fn = log_fn
        self._glossary_path = glossary_path or settings.glossary_path
        self.glossary = glossary or load_ocr_glossary(self._glossary_path, log_fn)

        self._symspell_dict_path = symspell_dict_path or settings.symspell_dict_path
        self._lt_client = languagetool_client
        self._lt_owned = languagetool_client is None
        self._symspell_calls = 0
    def _log(self, message: str) -> None:
        if self.log_fn:
            self.log_fn(message)

    @property
    def symspell_calls(self) -> int:
        return self._symspell_calls
    def reload_glossary(self) -> str:
        pass
        previous = self.glossary
        loaded = load_ocr_glossary(self._glossary_path, self.log_fn)

        if not self._glossary_path.exists():
            self._log("Glossar neu laden: Datei fehlt – bisheriges Glossar behalten")

            return previous.fingerprint
        try:
            json.loads(self._glossary_path.read_text(encoding="utf-8"))

        except json.JSONDecodeError as exc:
            self._log(f"Glossar neu laden: ungültiges JSON ({exc}) – bisheriges Glossar behalten")

            return previous.fingerprint
        self.glossary = loaded
        self._log(f"Glossar neu geladen (Fingerprint: {loaded.fingerprint})")

        return loaded.fingerprint
    def _ensure_symspell(self):
        bundle = _load_symspell_singleton(self._symspell_dict_path, self.log_fn)

        self._symspell_calls += 1
        return bundle
    def _ensure_languagetool(self) -> LocalLanguageToolClient:
        if self._lt_client is None:
            from lingoveil_languagetool import LanguageToolSettings
            self._lt_client = LocalLanguageToolClient(
                LanguageToolSettings(timeout_sec=self.settings.languagetool_timeout_sec),
                log_fn=self.log_fn,
            )

            self._lt_client.start()

        return self._lt_client
    @property
    def languagetool_running(self) -> bool:
        return (
            self._lt_client is not None
            and self._lt_client._proc is not None
            and self._lt_client._proc.poll() is None
        )

    def shutdown_languagetool(self) -> None:
        if self._lt_client is not None and self._lt_owned:
            self._lt_client.close()

            self._lt_client = None
    def preprocess(
        self,
        text: str,
        *,
        use_symspell: bool | None = None,
        use_languagetool: bool | None = None,
    ) -> PreprocessResult:
        result = PreprocessResult(
            original_text=text,
            normalized_text=text,
            glossary_text=text,
            symspell_text=text,
            languagetool_text=text,
            final_text=text,
        )

        working = text
        if self.settings.normalization_enabled:
            t0 = time.monotonic()

            result.normalized_text, changes = normalize_manga_casing(
                working, self.glossary.protected_set
            )

            result.applied_changes.extend(changes)

            fw_text, fw_changes = lowercase_function_words_mid_sentence(
                result.normalized_text,
                self.glossary.protected_set,
            )

            result.applied_changes.extend(fw_changes)

            result.normalized_text = fw_text
            result.stage_durations_ms["normalization"] = (time.monotonic() - t0) * 1000
            working = result.normalized_text
        else:
            result.normalized_text = working
        if self.settings.glossary_enabled:
            t1 = time.monotonic()

            result.glossary_text, g_changes = apply_glossary_corrections(
                working, self.glossary
            )

            result.applied_changes.extend(g_changes)

            result.stage_durations_ms["glossary"] = (time.monotonic() - t1) * 1000
            working = result.glossary_text
        else:
            result.glossary_text = working
        symspell_on = (
            self.settings.symspell_enabled if use_symspell is None else use_symspell
        )

        t2 = time.monotonic()

        if symspell_on:
            try:
                result.symspell_text, s_changes, s_diag = apply_symspell_tokens(
                    working,
                    self.glossary.protected_set,
                    self._ensure_symspell(),
                )

                result.applied_changes.extend(s_changes)

                result.applied_changes.extend(s_diag)

                working = result.symspell_text
            except Exception as exc:
                result.warnings.append(f"SymSpell: {exc}")

                result.symspell_text = working
        else:
            result.symspell_text = working
        result.stage_durations_ms["symspell"] = (time.monotonic() - t2) * 1000
        lt_on = (
            self.settings.languagetool_enabled
            if use_languagetool is None
            else use_languagetool
        )

        t3 = time.monotonic()

        if lt_on:
            try:
                lt = self._ensure_languagetool()

                payload = lt.check(working)

                corrected, lt_changes = lt.apply_safe_corrections(
                    working,
                    payload.get("matches", []),
                    protected_terms=self.glossary.protected_set,
                )

                result.languagetool_text = corrected
                for change in lt_changes:
                    entry = dict(change)

                    entry["stage"] = "languagetool"
                    result.applied_changes.append(entry)

                for match in payload.get("matches", []):
                    rule_id = (match.get("rule") or {}).get("id", "")

                    if not any(
                        c.get("rule_id") == rule_id and c.get("applied")

                        for c in lt_changes
                    ):
                        result.applied_changes.append({
                            "stage": "languagetool",
                            "rule_id": rule_id,
                            "category": (match.get("rule") or {}).get("category", {}),
                            "message": match.get("message", ""),
                            "original": (match.get("context") or {}).get("text", ""),
                            "suggestions": [
                                r.get("value", "")

                                for r in (match.get("replacements") or [])

                            ],
                            "applied": False,
                            "reason": "nicht automatisch angewendet",
                        })

                working = result.languagetool_text
            except (LanguageToolError, TimeoutError, OSError) as exc:
                result.warnings.append(f"LanguageTool: {exc}")

                result.languagetool_text = working
        else:
            result.languagetool_text = working
        result.stage_durations_ms["languagetool"] = (time.monotonic() - t3) * 1000
        result.final_text = working
        return result
    def close(self) -> None:
        self.shutdown_languagetool()

def lowercase_function_words_mid_sentence(
    text: str,
    protected: set[str],
) -> tuple[str, list[dict[str, Any]]]:
    pass
    protected_upper = {p.upper() for p in protected}

    changes: list[dict[str, Any]] = []
    parts: list[str] = []
    last = 0
    for match in _TOKEN_RE.finditer(text):
        gap = text[last : match.start()]
        parts.append(gap)

        token = match.group(0)

        alpha = "".join(c for c in token if c.isalpha())

        is_sentence_start = last == 0 or bool(_SENTENCE_BOUNDARY_RE.search(gap))

        if (
            alpha
            and not is_sentence_start
            and alpha.upper() not in protected_upper
            and alpha.lower() in BERGAMOT_FUNCTION_WORDS
            and any(c.isupper() for c in alpha)

        ):
            new_token = "".join(c.lower() if c.isalpha() else c for c in token)

            if new_token != token:
                changes.append({
                    "stage": "normalization",
                    "rule": "function_word_mid_sentence",
                    "before": token,
                    "after": new_token,
                    "applied": True,
                })

            token = new_token
        parts.append(token)

        last = match.end()

    parts.append(text[last:])

    return "".join(parts), changes
def bergamot_passthrough_retry_text(text: str) -> str:
    pass
    return text.strip().lower()

def normalize_manga_casing(
    text: str,
    protected: set[str],
) -> tuple[str, list[dict[str, Any]]]:
    pass
    protected_map = {p.upper(): p for p in protected}

    changes: list[dict[str, Any]] = []
    def transform_token(token: str) -> str:
        if token.upper() in protected_map:
            return protected_map[token.upper()]
        alpha = [c for c in token if c.isalpha()]
        if not alpha:
            return token
        upper_count = sum(1 for c in alpha if c.isupper())

        if upper_count == len(alpha) and len(alpha) > 1:
            new = token.lower()

            if new != token:
                changes.append({
                    "stage": "normalization",
                    "rule": "all_caps_to_lower",
                    "before": token,
                    "after": new,
                    "applied": True,
                })

            return new
        if _is_mixed_ocr_caps(token):
            new = token.lower()

            if new != token:
                changes.append({
                    "stage": "normalization",
                    "rule": "mixed_ocr_caps_to_lower",
                    "before": token,
                    "after": new,
                    "applied": True,
                })

            return new
        return token
    parts: list[str] = []
    last = 0
    for match in _TOKEN_RE.finditer(text):
        parts.append(text[last : match.start()])

        parts.append(transform_token(match.group(0)))

        last = match.end()

    parts.append(text[last:])

    normalized = "".join(parts)

    normalized = re.sub(r"[ \t]+", " ", normalized)

    normalized = re.sub(r"\n{3,}", "\n\n", normalized)

    return normalized.strip(), changes
def _is_mixed_ocr_caps(token: str) -> bool:
    alpha = [c for c in token if c.isalpha()]
    if len(alpha) < 2:
        return False
    upper_positions = [i for i, c in enumerate(alpha) if c.isupper()]
    if len(upper_positions) == len(alpha):
        return False
    if len(upper_positions) >= 2:
        return True
    if len(upper_positions) == 1 and upper_positions[0] > 0:
        return True
    return False
def apply_glossary_corrections(
    text: str,
    glossary: OcrGlossary,
) -> tuple[str, list[dict[str, Any]]]:
    changes: list[dict[str, Any]] = []
    result = text
    corrections_ci = {
        k.upper(): (k, v) for k, v in glossary.corrections.items()
    }

    for _key_upper, (orig_key, replacement) in sorted(
        corrections_ci.items(), key=lambda item: -len(item[0])

    ):
        pattern = re.compile(re.escape(orig_key), re.IGNORECASE)

        if not pattern.search(result):
            continue
        def repl(match: re.Match[str], rep: str = replacement) -> str:
            changes.append({
                "stage": "glossary",
                "rule": "correction",
                "before": match.group(0),
                "after": rep,
                "applied": True,
            })

            return rep
        result = pattern.sub(repl, result)

    return result, changes
def apply_symspell_tokens(
    text: str,
    protected: set[str],
    symspell_bundle: tuple[Any, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    sym, Verbosity = symspell_bundle
    protected_upper = {p.upper() for p in protected}

    applied: list[dict[str, Any]] = []
    diagnostic: list[dict[str, Any]] = []
    def transform_token(token: str) -> str:
        if token.upper() in protected_upper:
            return token
        if len(token) < MIN_TOKEN_LEN_SYMSPELL and token.isalpha():
            diagnostic.append({
                "stage": "symspell",
                "rule": "short_token_skipped",
                "before": token,
                "applied": False,
                "reason": "kurzes Wort",
            })

            return token
        suggestions = sym.lookup(
            token.lower(),
            Verbosity.CLOSEST,
            max_edit_distance=1,
        )

        if not suggestions:
            if len(token) >= MIN_TOKEN_LEN_EDIT2:
                suggestions2 = sym.lookup(
                    token.lower(),
                    Verbosity.CLOSEST,
                    max_edit_distance=2,
                )

                if suggestions2:
                    best = suggestions2[0]
                    exact = sym.lookup(
                        token.lower(), Verbosity.CLOSEST, max_edit_distance=0
                    )

                    original_freq = exact[0].count if exact else 0
                    if (
                        best.count >= max(original_freq, 1) * MIN_FREQUENCY_RATIO_EDIT2
                        and best.term != token.lower()

                    ):
                        suggestions = [best]
                    else:
                        diagnostic.append({
                            "stage": "symspell",
                            "rule": "edit_distance_2_rejected",
                            "before": token,
                            "suggestion": best.term,
                            "applied": False,
                            "reason": "unsichere ED2-Korrektur",
                        })

            return token
        best = suggestions[0]
        if best.term == token.lower():
            return token
        new_token = _preserve_token_casing(token, best.term)

        if "'" in token and "'" not in new_token:
            diagnostic.append({
                "stage": "symspell",
                "rule": "apostrophe_preserved",
                "before": token,
                "suggestion": new_token,
                "applied": False,
                "reason": "Apostroph würde entfernt",
            })

            return token
        applied.append({
            "stage": "symspell",
            "rule": "token_correction",
            "before": token,
            "after": new_token,
            "distance": best.distance,
            "frequency": best.count,
            "applied": True,
        })

        return new_token
    parts: list[str] = []
    last = 0
    for match in _TOKEN_RE.finditer(text):
        parts.append(text[last : match.start()])

        parts.append(transform_token(match.group(0)))

        last = match.end()

    parts.append(text[last:])

    return "".join(parts), applied, diagnostic
def _preserve_token_casing(original: str, corrected: str) -> str:
    if original.isupper():
        return corrected.upper()

    if original[0].isupper():
        return corrected.capitalize()

    return corrected
