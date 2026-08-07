from __future__ import annotations
import hashlib
import json
import os
import re
import unicodedata

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
TRANSLATION_PROMPT_VERSION = "v3"
TRANSLATION_ENGINE_LM_STUDIO = "lm_studio"
TRANSLATION_ENGINE_BERGAMOT = "bergamot"
TRANSLATION_ENGINE_SEAMLESS_M4T = "seamless_m4t"
ENGINE_DISPLAY_NAMES: dict[str, str] = {
    TRANSLATION_ENGINE_BERGAMOT: "Bergamot",
    TRANSLATION_ENGINE_SEAMLESS_M4T: "SeamlessM4T",
    TRANSLATION_ENGINE_LM_STUDIO: "LM Studio",
}

CACHE_SOURCE_NEW_TRANSLATION = "new_translation"
CACHE_SOURCE_PERSISTENT_CACHE = "persistent_cache"
CACHE_SOURCE_SESSION_CACHE = "session_cache"
CACHE_SOURCE_IN_FLIGHT = "in_flight"
SOURCE_LANG = "en"
TARGET_LANG = "de"
MAX_CACHE_ENTRIES = 2000
CACHE_FILE_VERSION = 1
_APOSTROPHE_MAP = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u2032": "'",
    "`": "'",
})

_QUOTE_MAP = str.maketrans({
    "\u201c": '"',
    "\u201d": '"',
    "\u00ab": '"',
    "\u00bb": '"',
})

_DASH_MAP = str.maketrans({
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
})

def engine_display_name(engine: str) -> str:
    pass
    return ENGINE_DISPLAY_NAMES.get(engine.strip().lower(), engine)

def cache_source_from_detail(detail: str) -> str:
    pass
    lowered = detail.strip().lower()

    if "persist" in lowered:
        return CACHE_SOURCE_PERSISTENT_CACHE
    if lowered in {"arbeitsspeicher", "session"}:
        return CACHE_SOURCE_SESSION_CACHE
    if "bearbeitung" in lowered or "in flight" in lowered:
        return CACHE_SOURCE_IN_FLIGHT
    if "neu" in lowered:
        return CACHE_SOURCE_NEW_TRANSLATION
    return detail or CACHE_SOURCE_NEW_TRANSLATION
def normalize_source_text(text: str) -> str:
    pass
    text = unicodedata.normalize("NFKC", text)

    text = text.translate(_APOSTROPHE_MAP).translate(_QUOTE_MAP).translate(_DASH_MAP)

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    text = re.sub(r"\s+", " ", text.replace("\n", " "))

    text = text.strip().lower()

    return text
def build_cache_key(
    text: str,
    source_lang: str,
    target_lang: str,
    model: str,
    prompt_version: str,
    translation_engine: str | None = None,
) -> str:
    normalized = normalize_source_text(text)

    if translation_engine is None:
        payload: dict[str, str] = {
            "source_lang": source_lang,
            "target_lang": target_lang,
            "model": model,
            "prompt_version": prompt_version,
            "normalized_source_text": normalized,
        }

    else:
        payload = {
            "translation_engine": translation_engine,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "engine_model_or_variant": model,
            "prompt_or_engine_version": prompt_version,
            "normalized_source_text": normalized,
        }

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def cache_lookup_keys(
    text: str,
    source_lang: str,
    target_lang: str,
    model: str,
    prompt_version: str,
    translation_engine: str | None,
) -> list[str]:
    pass
    keys: list[str] = []
    if translation_engine is not None:
        keys.append(
            build_cache_key(
                text,
                source_lang,
                target_lang,
                model,
                prompt_version,
                translation_engine=translation_engine,
            )

        )

    if translation_engine in (None, TRANSLATION_ENGINE_LM_STUDIO):
        legacy = build_cache_key(
            text, source_lang, target_lang, model, prompt_version, translation_engine=None
        )

        if legacy not in keys:
            keys.append(legacy)

    return keys
def lookup_cached_entry(
    cache: TranslationCache,
    text: str,
    *,
    source_lang: str,
    target_lang: str,
    model: str,
    prompt_version: str,
    translation_engine: str | None,
) -> tuple[str | None, CacheEntryData | None]:
    for key in cache_lookup_keys(
        text, source_lang, target_lang, model, prompt_version, translation_engine
    ):
        entry = get_cached_translation(cache, key)

        if entry is not None:
            return key, entry
    return None, None
def cache_key_short(cache_key: str, length: int = 12) -> str:
    return cache_key[:length]
def compute_stable_set_signature(cache_keys: list[str]) -> str:
    unique = sorted(set(cache_keys))

    return hashlib.sha256("|".join(unique).encode("utf-8")).hexdigest()

@dataclass
class CacheEntryData:
    source_lang: str
    target_lang: str
    model: str
    prompt_version: str
    normalized_source_text: str
    original_ocr_text: str
    corrected_source: str
    translated_text: str
    created_at: str
    updated_at: str
    hit_count: int = 0
    translation_engine: str = ""
@dataclass
class TranslationCache:
    version: int = CACHE_FILE_VERSION
    entries: dict[str, CacheEntryData] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.entries)

def _infer_translation_engine(item: dict[str, Any]) -> str | None:
    explicit = str(item.get("translation_engine", "")).strip().lower()

    if explicit in (
        TRANSLATION_ENGINE_LM_STUDIO,
        TRANSLATION_ENGINE_BERGAMOT,
        TRANSLATION_ENGINE_SEAMLESS_M4T,
    ):
        return explicit
    if explicit:
        return None
    model = str(item.get("model", ""))

    prompt = str(item.get("prompt_version", ""))

    if prompt == TRANSLATION_PROMPT_VERSION and model and "bergamot" not in model.lower():
        return TRANSLATION_ENGINE_LM_STUDIO
    return None
def load_cache(path: Path, log_fn=None) -> TranslationCache:
    if not path.exists():
        return TranslationCache()

    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)

    except (json.JSONDecodeError, OSError) as exc:
        if log_fn:
            log_fn(f"Cache-Datei ungültig ({exc}) – starte mit leerem Cache")

        return TranslationCache()

    if raw.get("version") != CACHE_FILE_VERSION:
        if log_fn:
            log_fn(f"Cache-Version {raw.get('version')} unbekannt – leerer Cache")

        return TranslationCache()

    entries: dict[str, CacheEntryData] = {}

    migrated = 0
    for key, item in raw.get("entries", {}).items():
        if not isinstance(item, dict):
            continue
        try:
            inferred = _infer_translation_engine(item)

            if inferred is None and not item.get("translation_engine"):
                if log_fn:
                    log_fn(
                        f"Cache-Eintrag {key[:12]}… übersprungen "
                        f"(Engine nicht eindeutig)"
                    )

                continue
            engine = str(item.get("translation_engine") or inferred or "")

            entries[key] = CacheEntryData(
                source_lang=str(item["source_lang"]),
                target_lang=str(item["target_lang"]),
                model=str(item["model"]),
                prompt_version=str(item["prompt_version"]),
                normalized_source_text=str(item["normalized_source_text"]),
                original_ocr_text=str(item.get("original_ocr_text", "")),
                corrected_source=str(item.get("corrected_source", "")),
                translated_text=str(item.get("translated_text", "")),
                created_at=str(item.get("created_at", "")),
                updated_at=str(item.get("updated_at", "")),
                hit_count=int(item.get("hit_count", 0)),
                translation_engine=engine,
            )

            if not item.get("translation_engine") and inferred == TRANSLATION_ENGINE_LM_STUDIO:
                migrated += 1
        except (KeyError, TypeError, ValueError):
            continue
    if migrated and log_fn:
        log_fn(f"Cache-Migration: {migrated} LM-Studio-Einträge ohne Engine-Feld erkannt")

    return TranslationCache(entries=entries)

def save_cache_atomic(path: Path, cache: TranslationCache) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(path.suffix + ".tmp")

    payload = {
        "version": cache.version,
        "entries": {
            key: {
                "source_lang": e.source_lang,
                "target_lang": e.target_lang,
                "model": e.model,
                "prompt_version": e.prompt_version,
                "normalized_source_text": e.normalized_source_text,
                "original_ocr_text": e.original_ocr_text,
                "corrected_source": e.corrected_source,
                "translated_text": e.translated_text,
                "created_at": e.created_at,
                "updated_at": e.updated_at,
                "hit_count": e.hit_count,
                "translation_engine": e.translation_engine,
            }

            for key, e in cache.entries.items()
        },
    }

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

        f.flush()

        os.fsync(f.fileno())

    os.replace(tmp_path, path)

def _evict_if_needed(cache: TranslationCache) -> None:
    if len(cache.entries) <= MAX_CACHE_ENTRIES:
        return
    sorted_keys = sorted(
        cache.entries.keys(),
        key=lambda k: (cache.entries[k].updated_at, cache.entries[k].hit_count),
    )

    remove_count = len(cache.entries) - MAX_CACHE_ENTRIES
    for key in sorted_keys[:remove_count]:
        del cache.entries[key]
def get_cached_translation(
    cache: TranslationCache,
    cache_key: str,
) -> CacheEntryData | None:
    entry = cache.entries.get(cache_key)

    if entry is None:
        return None
    entry.hit_count += 1
    entry.updated_at = datetime.now(timezone.utc).isoformat()

    return entry
def set_cached_translation(
    cache: TranslationCache,
    cache_key: str,
    *,
    source_lang: str,
    target_lang: str,
    model: str,
    prompt_version: str,
    normalized_source_text: str,
    original_ocr_text: str,
    corrected_source: str,
    translated_text: str,
    translation_engine: str = "",
) -> None:
    now = datetime.now(timezone.utc).isoformat()

    existing = cache.entries.get(cache_key)

    if existing is not None:
        existing.corrected_source = corrected_source
        existing.translated_text = translated_text
        existing.original_ocr_text = original_ocr_text
        existing.translation_engine = translation_engine or existing.translation_engine
        existing.updated_at = now
        existing.hit_count += 1
    else:
        cache.entries[cache_key] = CacheEntryData(
            source_lang=source_lang,
            target_lang=target_lang,
            model=model,
            prompt_version=prompt_version,
            normalized_source_text=normalized_source_text,
            original_ocr_text=original_ocr_text,
            corrected_source=corrected_source,
            translated_text=translated_text,
            created_at=now,
            updated_at=now,
            hit_count=1,
            translation_engine=translation_engine,
        )

    _evict_if_needed(cache)

def remove_cached_translation(cache: TranslationCache, cache_key: str) -> None:
    cache.entries.pop(cache_key, None)

def clear_translation_cache(cache: TranslationCache) -> int:
    pass
    count = len(cache.entries)

    cache.entries.clear()

    return count
def looks_like_untranslated(source: str, translation: str) -> bool:
    pass
    src = normalize_source_text(source)

    trg = normalize_source_text(translation)

    return bool(src) and src == trg
@dataclass
class GroupCacheInfo:
    group_id: str
    ocr_text: str
    normalized_text: str
    cache_key: str
@dataclass
class BatchPlanResult:
    groups: list[GroupCacheInfo]
    blocks_to_send: list[dict[str, str]]
    key_to_group_ids: dict[str, list[str]]
    cache_hits_persistent: int = 0
    cache_hits_session: int = 0
    batch_duplicates_skipped: int = 0
    inflight_skipped: int = 0
    already_cached_group_ids: dict[str, CacheEntryData] = field(default_factory=dict)

def plan_translation_batch(
    groups: list[tuple[str, str]],
    *,
    cache: TranslationCache,
    model: str,
    prompt_version: str = TRANSLATION_PROMPT_VERSION,
    source_lang: str = SOURCE_LANG,
    target_lang: str = TARGET_LANG,
    translation_engine: str | None = None,
    inflight_keys: set[str],
    skip_cache: bool = False,
    session_hits: dict[str, CacheEntryData] | None = None,
    custom_cache_keys: dict[str, str] | None = None,
    engine_texts: dict[str, str] | None = None,
) -> BatchPlanResult:
    pass
    result = BatchPlanResult(groups=[], blocks_to_send=[], key_to_group_ids={})

    seen_send_keys: set[str] = set()

    for group_id, ocr_text in groups:
        normalized = normalize_source_text(ocr_text)

        if custom_cache_keys and group_id in custom_cache_keys:
            key = custom_cache_keys[group_id]
            lookup_keys = [key]
        else:
            lookup_keys = cache_lookup_keys(
                ocr_text, source_lang, target_lang, model, prompt_version, translation_engine
            )

            key = lookup_keys[0]
        info = GroupCacheInfo(
            group_id=group_id,
            ocr_text=ocr_text,
            normalized_text=normalized,
            cache_key=key,
        )

        result.groups.append(info)

        result.key_to_group_ids.setdefault(key, []).append(group_id)

        if not skip_cache:
            hit_key: str | None = None
            hit_entry: CacheEntryData | None = None
            for candidate in lookup_keys:
                entry = get_cached_translation(cache, candidate)

                if entry is not None:
                    hit_key = candidate
                    hit_entry = entry
                    break
            if hit_entry is not None:
                result.cache_hits_persistent += 1
                result.already_cached_group_ids[group_id] = hit_entry
                if hit_key and hit_key != key:
                    info.cache_key = hit_key
                continue
            if session_hits:
                for candidate in lookup_keys:
                    if candidate in session_hits:
                        result.cache_hits_session += 1
                        result.already_cached_group_ids[group_id] = session_hits[candidate]
                        if candidate != key:
                            info.cache_key = candidate
                        break
                if group_id in result.already_cached_group_ids:
                    continue
        inflight_hit = any(k in inflight_keys for k in lookup_keys)

        if inflight_hit:
            result.inflight_skipped += 1
            continue
        if key in seen_send_keys:
            result.batch_duplicates_skipped += 1
            continue
        seen_send_keys.add(key)

        send_text = (
            engine_texts[group_id]
            if engine_texts and group_id in engine_texts
            else ocr_text
        )

        result.blocks_to_send.append({
            "id": group_id,
            "text": send_text,
            "_cache_key": key,
            "_ocr_text": ocr_text,
        })

    return result
def run_self_test() -> int:
    pass
    errors: list[str] = []
    tmp = Path("/tmp/lingoveil_cache_selftest.json")

    def check(name: str, cond: bool, msg: str = "") -> None:
        if not cond:
            errors.append(f"{name}: {msg}")

    n1 = normalize_source_text("  WELCOME   BACK ULTIMATE MAGICIANS!! ")

    check("norm1", n1 == "welcome back ultimate magicians!!", n1)

    n2 = normalize_source_text("YAYI\nThey've Returnedii")

    check("norm2", n2 == "yayi they've returnedii", n2)

    check("norm3", normalize_source_text("NO!") != normalize_source_text("NO?"))

    model = "test-model"
    key_wb = build_cache_key("Welcome back!", model=model, source_lang="en", target_lang="de", prompt_version="v3")

    key_wb2 = build_cache_key("Welcome back?", model=model, source_lang="en", target_lang="de", prompt_version="v3")

    check("key_diff", key_wb != key_wb2)

    cache = TranslationCache()

    inflight: set[str] = set()

    groups_a = [("G01", "Welcome back!"), ("G02", "Welcome back!"), ("G03", "Congratulations!")]
    plan_a = plan_translation_batch(
        groups_a, cache=cache, model=model, inflight_keys=inflight,
    )

    check("A_groups", len(plan_a.groups) == 3)

    check("A_send", len(plan_a.blocks_to_send) == 2, f"got {len(plan_a.blocks_to_send)}")

    check("A_dup", plan_a.batch_duplicates_skipped == 1, str(plan_a.batch_duplicates_skipped))

    for block in plan_a.blocks_to_send:
        key = block["_cache_key"]
        set_cached_translation(
            cache, key,
            source_lang="en", target_lang="de", model=model, prompt_version="v3",
            normalized_source_text=normalize_source_text(block["text"]),
            original_ocr_text=block["text"],
            corrected_source=block["text"].upper(),
            translated_text=f"DE:{block['text']}",
        )

    plan_b = plan_translation_batch(
        groups_a, cache=cache, model=model, inflight_keys=inflight,
    )

    check("B_send", len(plan_b.blocks_to_send) == 0)

    check("B_hits", plan_b.cache_hits_persistent == 3, str(plan_b.cache_hits_persistent))

    groups_c = [("G99", "Welcome back!"), ("G100", "Congratulations!")]
    plan_c = plan_translation_batch(
        groups_c, cache=cache, model=model, inflight_keys=inflight,
    )

    check("C_send", len(plan_c.blocks_to_send) == 0)

    check("C_hits", plan_c.cache_hits_persistent == 2)

    plan_d = plan_translation_batch(
        [("G01", "Welcome back?")], cache=cache, model=model, inflight_keys=inflight,
    )

    check("D_send", len(plan_d.blocks_to_send) == 1)

    key_e = build_cache_key("In flight text", model=model, source_lang="en", target_lang="de", prompt_version="v3")

    inflight.add(key_e)

    plan_e = plan_translation_batch(
        [("G01", "In flight text"), ("G02", "In flight text")],
        cache=cache, model=model, inflight_keys=inflight, skip_cache=True,
    )

    check("E_send", len(plan_e.blocks_to_send) == 0)

    check("E_inflight", plan_e.inflight_skipped == 2, str(plan_e.inflight_skipped))

    inflight.discard(key_e)

    save_cache_atomic(tmp, cache)

    reloaded = load_cache(tmp)

    plan_f = plan_translation_batch(
        [("G01", "Welcome back!")], cache=reloaded, model=model, inflight_keys=set(),
    )

    check("F_hits", plan_f.cache_hits_persistent == 1)

    check("F_send", len(plan_f.blocks_to_send) == 0)

    keys = [build_cache_key(t, model=model, source_lang="en", target_lang="de", prompt_version="v3") for t in ["A", "B"]]
    sig1 = compute_stable_set_signature(keys)

    sig2 = compute_stable_set_signature(list(reversed(keys)))

    check("sig", sig1 == sig2)

    tmp.unlink(missing_ok=True)

    if errors:
        print("SELF-TEST FEHLGESCHLAGEN:")

        for e in errors:
            print(f"  - {e}")

        return 1
    print("SELF-TEST OK (Fälle A–F)")

    return 0
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        raise SystemExit(run_self_test())

    print("Verwendung: python lingoveil_translation_cache.py --self-test")
