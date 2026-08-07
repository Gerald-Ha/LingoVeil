from __future__ import annotations
import gc
import resource
import threading
import time

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from lingoveil_config import (
    DEFAULT_TRANSLATION_ENGINE,
    SEAMLESS_DEFAULT_MODEL_ID,
    SEAMLESS_DEFAULT_MODEL_REVISION,
    SUPPORTED_TRANSLATION_ENGINES,
    TRANSLATION_ENGINE_BERGAMOT,
    TRANSLATION_ENGINE_LM_STUDIO,
    TRANSLATION_ENGINE_SEAMLESS_M4T,
    BergamotPreprocessSettings,
    BergamotSettings,
    LlmSettings,
    TranslationSettings,
    validate_translation_engine,
)

from lingoveil_bergamot import BergamotError, BergamotTranslatorClient
from lingoveil_bergamot_preprocess import (
    BergamotPreprocessor,
    PreprocessResult,
    bergamot_passthrough_retry_text,
    build_bergamot_preprocess_cache_key,
    build_seamless_m4t_preprocess_cache_key,
    get_symspell_init_ms,
    should_run_local_preprocess,
)

from lingoveil_llm import LlmTranslationError, LlmTranslator
from lingoveil_model_manager import validate_seamless_model_dir
from lingoveil_paths import seamless_model_dir
from lingoveil_seamless_m4t import SeamlessM4TError, SeamlessM4TTextTranslator
from lingoveil_translation_cache import (
    SOURCE_LANG,
    TARGET_LANG,
    TRANSLATION_PROMPT_VERSION,
    build_cache_key,
    looks_like_untranslated,
)

BERGAMOT_MODEL_VARIANT = "bergamot-en-de"
BERGAMOT_PROMPT_VERSION = "bergamot-v1"
SEAMLESS_M4T_MODEL_VARIANT = SEAMLESS_DEFAULT_MODEL_ID
SEAMLESS_M4T_PROMPT_VERSION = SEAMLESS_DEFAULT_MODEL_REVISION
@dataclass
class TranslationBlockResult:
    block_id: str
    translation: str
    corrected_source: str = ""
    engine: str = ""
    duration_sec: float = 0.0
    bergamot_input: str = ""
    preprocess: PreprocessResult | None = None
    error: str = ""
@dataclass
class EngineStats:
    bergamot_requests: int = 0
    seamless_m4t_requests: int = 0
    lm_studio_requests: int = 0
    engine_switches: int = 0
    ignored_stale_responses: int = 0
    bergamot_status: str = "nicht gestartet"
    seamless_m4t_status: str = "nicht gestartet"
    last_error: str = ""
    preprocess_calls: int = 0
    symspell_calls: int = 0
    languagetool_starts: int = 0
@dataclass
class PreparedBlock:
    ocr_text: str
    cache_key: str
    engine_text: str
    preprocess: PreprocessResult | None = None
class TranslationEngineManager:
    pass
    def __init__(
        self,
        settings: TranslationSettings,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self._log = log_fn or (lambda msg: print(msg, flush=True))

        self._engine = settings.translation_engine
        self._generation = 1
        self._lock = threading.Lock()

        self._bergamot: BergamotTranslatorClient | None = None
        self._seamless: SeamlessM4TTextTranslator | None = None
        self._llm = LlmTranslator(settings.llm, self._log)

        self._preprocessor: BergamotPreprocessor | None = None
        self._stats = EngineStats()

        self._closed = False
    @property
    def active_engine(self) -> str:
        return self._engine
    @property
    def generation(self) -> int:
        return self._generation
    @property
    def stats(self) -> EngineStats:
        return self._stats
    @property
    def preprocessor(self) -> BergamotPreprocessor | None:
        return self._preprocessor
    def _bergamot_client(self) -> BergamotTranslatorClient:
        if self._bergamot is None:
            from lingoveil_bergamot import BergamotSettings as SidecarSettings
            sidecar = SidecarSettings(
                node_bin=self.settings.bergamot.node_bin,
                timeout_sec=self.settings.bergamot.timeout_sec,
                source_lang=self.settings.bergamot.source_lang,
                target_lang=self.settings.bergamot.target_lang,
            )

            self._bergamot = BergamotTranslatorClient(sidecar, self._log)

        return self._bergamot
    def _ensure_preprocessor(self) -> BergamotPreprocessor:
        if self._preprocessor is None:
            self._preprocessor = BergamotPreprocessor(
                self.settings.preprocess,
                log_fn=self._log,
            )

        return self._preprocessor
    def _close_bergamot(self) -> None:
        if self._bergamot is not None:
            self._bergamot.close()

            self._bergamot = None
        self._stats.bergamot_status = "nicht gestartet"
    @staticmethod
    def _rss_mb() -> float:
        usage = resource.getrusage(resource.RUSAGE_SELF)

        return usage.ru_maxrss / 1024.0
    @staticmethod
    def _vram_mb() -> float:
        try:
            import torch

            if torch.cuda.is_available():
                return torch.cuda.memory_allocated() / (1024.0 * 1024.0)

        except Exception:
            pass
        return 0.0
    def _seamless_model_path(self) -> Path:
        return seamless_model_dir(self.settings.seamless.model_dir)

    def _close_seamless_m4t(self) -> None:
        if self._seamless is not None:
            ram_before = self._rss_mb()

            vram_before = self._vram_mb()

            self._log("[SeamlessM4T] Unload gestartet")

            self._log(f"[SeamlessM4T] RAM RSS vor close(): {ram_before:.1f} MB")

            self._log(f"[SeamlessM4T] VRAM vor close(): {vram_before:.1f} MB")

            self._seamless.close()

            self._seamless = None
            self._log("[SeamlessM4T] Manager-Referenz gelöscht")

            collected = gc.collect()

            self._log(f"[SeamlessM4T] gc.collect(): {collected} Objekte")

            cuda_cleared = False
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                    cuda_cleared = True
            except Exception:
                pass
            if cuda_cleared:
                self._log("[SeamlessM4T] torch.cuda.empty_cache(): ausgeführt")

            ram_after = self._rss_mb()

            vram_after = self._vram_mb()

            self._log(f"[SeamlessM4T] RAM RSS nach Unload: {ram_after:.1f} MB")

            self._log(f"[SeamlessM4T] VRAM nach Unload: {vram_after:.1f} MB")

            self._log(
                "[SeamlessM4T] Hinweis: RSS kann durch Python-/PyTorch-Allocator "
                "reserviert bleiben"
            )

            self._log(
                f"SeamlessM4T freigegeben – RAM {ram_before:.0f}→{ram_after:.0f} MB, "
                f"VRAM {vram_before:.0f}→{vram_after:.0f} MB"
            )

        self._stats.seamless_m4t_status = "nicht gestartet"
    def _validate_seamless_ready(self) -> Path:
        if not self.settings.seamless.license_accepted:
            raise SeamlessM4TError(
                "SeamlessM4T-Lizenz nicht akzeptiert. "
                "Bitte über „Modelle“ bestätigen und das Modell herunterladen."
            )

        model_path = self._seamless_model_path()

        ok, msg = validate_seamless_model_dir(model_path)

        if not ok:
            raise SeamlessM4TError(
                f"SeamlessM4T-Modell fehlt oder unvollständig: {msg}. "
                "Bitte über „Modelle“ herunterladen."
            )

        return model_path
    def _start_seamless_m4t(self) -> None:
        model_path = self._validate_seamless_ready()

        self._stats.seamless_m4t_status = "wird geladen"
        self._log(f"SeamlessM4T lazy load: {model_path}")

        self._seamless = SeamlessM4TTextTranslator(
            model_path,
            device_preference=self.settings.seamless.device,
            source_lang=self.settings.seamless.source_lang,
            target_lang=self.settings.seamless.target_lang,
            log_fn=self._log,
        )

        self._seamless.start()

        self._stats.seamless_m4t_status = (
            f"bereit ({self._seamless.device_mode}, {self._seamless.torch_dtype})"
        )

    def _shutdown_preprocess_languagetool(self) -> None:
        if self._preprocessor is not None:
            self._preprocessor.shutdown_languagetool()

    def _start_bergamot(self) -> None:
        self._stats.bergamot_status = "wird geladen"
        client = self._bergamot_client()

        client.start()

        client.ping(timeout_sec=min(30.0, self.settings.bergamot.timeout_sec))

        self._stats.bergamot_status = "bereit"
    def reload_glossary(self) -> str:
        prep = self._ensure_preprocessor()

        return prep.reload_glossary()

    def preprocess_enabled(self) -> bool:
        return should_run_local_preprocess(self._engine, self.settings.preprocess)

    def prepare_block(self, ocr_text: str) -> PreparedBlock:
        pass
        if self._engine == TRANSLATION_ENGINE_LM_STUDIO:
            key = build_cache_key(
                ocr_text,
                SOURCE_LANG,
                TARGET_LANG,
                self.settings.llm.model,
                TRANSLATION_PROMPT_VERSION,
                translation_engine=TRANSLATION_ENGINE_LM_STUDIO,
            )

            return PreparedBlock(
                ocr_text=ocr_text,
                cache_key=key,
                engine_text=ocr_text,
                preprocess=None,
            )

        if self.preprocess_enabled():
            prep = self._ensure_preprocessor()

            result = prep.preprocess(ocr_text)

            self._stats.preprocess_calls += 1
            self._stats.symspell_calls = prep.symspell_calls
            if prep.languagetool_running:
                self._stats.languagetool_starts = 1
            if self._engine == TRANSLATION_ENGINE_SEAMLESS_M4T:
                key = build_seamless_m4t_preprocess_cache_key(
                    result.final_text,
                    settings=self.settings.preprocess,
                    glossary_fingerprint=prep.glossary.fingerprint,
                    source_lang=self.settings.seamless.source_lang,
                    target_lang=self.settings.seamless.target_lang,
                    model_id=self.settings.seamless.model_id,
                    model_revision=self.settings.seamless.model_revision,
                )

            else:
                key = build_bergamot_preprocess_cache_key(
                    result.final_text,
                    settings=self.settings.preprocess,
                    glossary_fingerprint=prep.glossary.fingerprint,
                    source_lang=self.settings.bergamot.source_lang,
                    target_lang=self.settings.bergamot.target_lang,
                    bergamot_model_or_variant=BERGAMOT_MODEL_VARIANT,
                )

            return PreparedBlock(
                ocr_text=ocr_text,
                cache_key=key,
                engine_text=result.final_text,
                preprocess=result,
            )

        if self._engine == TRANSLATION_ENGINE_SEAMLESS_M4T:
            key = build_cache_key(
                ocr_text,
                self.settings.seamless.source_lang,
                self.settings.seamless.target_lang,
                SEAMLESS_M4T_MODEL_VARIANT,
                SEAMLESS_M4T_PROMPT_VERSION,
                translation_engine=TRANSLATION_ENGINE_SEAMLESS_M4T,
            )

            return PreparedBlock(
                ocr_text=ocr_text,
                cache_key=key,
                engine_text=ocr_text,
                preprocess=None,
            )

        key = build_cache_key(
            ocr_text,
            SOURCE_LANG,
            TARGET_LANG,
            BERGAMOT_MODEL_VARIANT,
            BERGAMOT_PROMPT_VERSION,
            translation_engine=TRANSLATION_ENGINE_BERGAMOT,
        )

        return PreparedBlock(
            ocr_text=ocr_text,
            cache_key=key,
            engine_text=ocr_text,
            preprocess=None,
        )

    def set_engine(self, engine_name: str) -> None:
        engine = validate_translation_engine(engine_name)

        with self._lock:
            if engine == self._engine:
                return
            old_engine = self._engine
            self._engine = engine
            self._generation += 1
            self._stats.engine_switches += 1
            self._log(
                f"Engine-Wechsel: {old_engine} → {engine} "
                f"(Generation {self._generation})"
            )

            if old_engine == TRANSLATION_ENGINE_BERGAMOT:
                self._close_bergamot()

            if old_engine == TRANSLATION_ENGINE_SEAMLESS_M4T:
                self._close_seamless_m4t()

            if engine == TRANSLATION_ENGINE_LM_STUDIO:
                self._shutdown_preprocess_languagetool()

            if engine == TRANSLATION_ENGINE_BERGAMOT:
                if self._stats.bergamot_status != "bereit":
                    try:
                        self._start_bergamot()

                    except BergamotError as exc:
                        self._stats.bergamot_status = "Fehler"
                        self._stats.last_error = str(exc)

                        raise
            if engine == TRANSLATION_ENGINE_SEAMLESS_M4T:
                self._stats.seamless_m4t_status = "bereit (lazy)"
            if engine == TRANSLATION_ENGINE_LM_STUDIO:
                self._llm = LlmTranslator(self.settings.llm, self._log)

    def ensure_ready(self) -> None:
        with self._lock:
            if self._engine == TRANSLATION_ENGINE_BERGAMOT:
                if self._stats.bergamot_status != "bereit":
                    self._start_bergamot()

            elif self._engine == TRANSLATION_ENGINE_SEAMLESS_M4T:
                if self._seamless is None:
                    self._start_seamless_m4t()

    def translate_blocks(
        self,
        blocks: list[dict[str, str]],
        *,
        request_generation: int | None = None,
        max_chars: int = 4000,
        max_blocks: int = 20,
        prepared: dict[str, PreparedBlock] | None = None,
    ) -> list[TranslationBlockResult]:
        if not blocks:
            return []
        gen_at_start = request_generation if request_generation is not None else self._generation
        if request_generation is not None and gen_at_start != self._generation:
            self._stats.ignored_stale_responses += 1
            self._log(
                f"Veraltete Übersetzungsanfrage ignoriert "
                f"(Generation {gen_at_start} → {self._generation})"
            )

            return []
        engine = self._engine
        if engine == TRANSLATION_ENGINE_BERGAMOT:
            self.ensure_ready()

            self._stats.bergamot_requests += 1
            bergamot_blocks: list[dict[str, str]] = []
            prep_by_id: dict[str, PreprocessResult | None] = {}

            for block in blocks:
                bid = block["id"]
                if prepared and bid in prepared:
                    pb = prepared[bid]
                    bergamot_blocks.append({"id": bid, "text": pb.engine_text})

                    prep_by_id[bid] = pb.preprocess
                elif self.preprocess_enabled():
                    pb = self.prepare_block(block["text"])

                    bergamot_blocks.append({"id": bid, "text": pb.engine_text})

                    prep_by_id[bid] = pb.preprocess
                else:
                    bergamot_blocks.append(block)

                    prep_by_id[bid] = None
            t0 = time.monotonic()

            try:
                raw = self._bergamot_client().translate_blocks(
                    bergamot_blocks,
                    source_lang=self.settings.bergamot.source_lang,
                    target_lang=self.settings.bergamot.target_lang,
                    timeout_sec=self.settings.bergamot.timeout_sec,
                )

            except BergamotError as exc:
                self._stats.bergamot_status = "Fehler"
                self._stats.last_error = str(exc)

                raise
            duration = time.monotonic() - t0
            if gen_at_start != self._generation:
                self._stats.ignored_stale_responses += 1
                self._log(
                    f"Verspätete Bergamot-Antwort ignoriert "
                    f"(Generation {gen_at_start} → {self._generation})"
                )

                return []
            raw_by_id = {item["id"]: item for item in raw}

            retry_blocks: list[dict[str, str]] = []
            retry_source: dict[str, str] = {}

            for block in bergamot_blocks:
                bid = block["id"]
                item = raw_by_id.get(bid)

                if item is None:
                    continue
                engine_text = block["text"]
                if looks_like_untranslated(engine_text, item["translation"]):
                    retry_text = bergamot_passthrough_retry_text(engine_text)

                    if retry_text != engine_text:
                        retry_blocks.append({"id": bid, "text": retry_text})

                        retry_source[bid] = engine_text
            if retry_blocks:
                self._stats.bergamot_requests += 1
                self._log(
                    f"Bergamot-Passthrough-Retry für {len(retry_blocks)} Text(e)"
                )

                try:
                    raw_retry = self._bergamot_client().translate_blocks(
                        retry_blocks,
                        source_lang=self.settings.bergamot.source_lang,
                        target_lang=self.settings.bergamot.target_lang,
                        timeout_sec=self.settings.bergamot.timeout_sec,
                    )

                except BergamotError as exc:
                    self._stats.bergamot_status = "Fehler"
                    self._stats.last_error = str(exc)

                    raise
                duration = time.monotonic() - t0
                if gen_at_start != self._generation:
                    self._stats.ignored_stale_responses += 1
                    self._log(
                        f"Verspätete Bergamot-Antwort ignoriert "
                        f"(Generation {gen_at_start} → {self._generation})"
                    )

                    return []
                for item in raw_retry:
                    bid = item["id"]
                    if not looks_like_untranslated(
                        retry_source.get(bid, ""), item["translation"]
                    ):
                        raw_by_id[bid] = item
            results: list[TranslationBlockResult] = []
            for item in raw_by_id.values():
                bid = item["id"]
                prep = prep_by_id.get(bid)

                engine_text = ""
                if prepared and bid in prepared:
                    engine_text = prepared[bid].engine_text
                elif prep is not None:
                    engine_text = prep.final_text
                else:
                    for b in blocks:
                        if b["id"] == bid:
                            engine_text = b["text"]
                            break
                results.append(
                    TranslationBlockResult(
                        block_id=bid,
                        translation=item["translation"] or engine_text,
                        corrected_source=engine_text,
                        engine=TRANSLATION_ENGINE_BERGAMOT,
                        duration_sec=duration,
                        bergamot_input=engine_text,
                        preprocess=prep,
                        error=str(item.get("error", "")),
                    )

                )

            return results
        if engine == TRANSLATION_ENGINE_SEAMLESS_M4T:
            self.ensure_ready()

            self._stats.seamless_m4t_requests += 1
            seamless_blocks: list[dict[str, str]] = []
            prep_by_id: dict[str, PreprocessResult | None] = {}

            for block in blocks:
                bid = block["id"]
                if prepared and bid in prepared:
                    pb = prepared[bid]
                    seamless_blocks.append({"id": bid, "text": pb.engine_text})

                    prep_by_id[bid] = pb.preprocess
                elif self.preprocess_enabled():
                    pb = self.prepare_block(block["text"])

                    seamless_blocks.append({"id": bid, "text": pb.engine_text})

                    prep_by_id[bid] = pb.preprocess
                else:
                    seamless_blocks.append(block)

                    prep_by_id[bid] = None
            text_to_ids: dict[str, list[str]] = {}

            unique_send: list[dict[str, str]] = []
            for sb in seamless_blocks:
                text = sb["text"]
                text_to_ids.setdefault(text, []).append(sb["id"])

            for text, ids in text_to_ids.items():
                unique_send.append({"id": ids[0], "text": text})

            t0 = time.monotonic()

            try:
                if self._seamless is None:
                    raise SeamlessM4TError("SeamlessM4T nicht initialisiert")

                raw_unique = self._seamless.translate_blocks(
                    unique_send,
                    source_lang=self.settings.seamless.source_lang,
                    target_lang=self.settings.seamless.target_lang,
                )

            except SeamlessM4TError as exc:
                self._stats.seamless_m4t_status = "Fehler"
                self._stats.last_error = str(exc)

                raise
            duration = time.monotonic() - t0
            if gen_at_start != self._generation:
                self._stats.ignored_stale_responses += 1
                self._log(
                    f"Verspätete SeamlessM4T-Antwort ignoriert "
                    f"(Generation {gen_at_start} → {self._generation})"
                )

                return []
            trans_by_text: dict[str, str] = {}

            for item in raw_unique:
                for sb in seamless_blocks:
                    if sb["id"] == item["id"]:
                        trans_by_text[sb["text"]] = item["translation"]
                        break
            results: list[TranslationBlockResult] = []
            for sb in seamless_blocks:
                bid = sb["id"]
                prep = prep_by_id.get(bid)

                engine_text = sb["text"]
                translation = trans_by_text.get(engine_text, "")

                results.append(
                    TranslationBlockResult(
                        block_id=bid,
                        translation=translation,
                        corrected_source=engine_text,
                        engine=TRANSLATION_ENGINE_SEAMLESS_M4T,
                        duration_sec=duration,
                        bergamot_input=engine_text,
                        preprocess=prep,
                    )

                )

            return results
        if engine == TRANSLATION_ENGINE_LM_STUDIO:
            self._stats.lm_studio_requests += 1
            try:
                response = self._llm.translate_blocks(
                    blocks,
                    max_chars=max_chars,
                    max_blocks=max_blocks,
                )

            except LlmTranslationError as exc:
                self._stats.last_error = str(exc)

                raise
            if gen_at_start != self._generation:
                self._stats.ignored_stale_responses += 1
                self._log(
                    f"Verspätete LM-Studio-Antwort ignoriert "
                    f"(Generation {gen_at_start} → {self._generation})"
                )

                return []
            return [
                TranslationBlockResult(
                    block_id=item.block_id,
                    translation=item.german,
                    corrected_source=item.corrected_source,
                    engine=TRANSLATION_ENGINE_LM_STUDIO,
                    duration_sec=response.duration_sec,
                )

                for item in response.items
            ]
        raise ValueError(f"Unbekannte Engine: {engine}")

    def update_settings(self, settings: TranslationSettings) -> None:
        old_bergamot = self.settings.bergamot
        old_seamless = self.settings.seamless
        old_preprocess = self.settings.preprocess
        self.settings = settings
        self._llm.settings = settings.llm
        if old_bergamot != settings.bergamot:
            self._close_bergamot()

        if old_seamless != settings.seamless:
            self._close_seamless_m4t()

        if self._preprocessor is not None:
            self._preprocessor.settings = settings.preprocess
        if (
            old_preprocess.languagetool_enabled
            and not settings.preprocess.languagetool_enabled
        ):
            self._shutdown_preprocess_languagetool()

        if self._engine == TRANSLATION_ENGINE_LM_STUDIO:
            self._shutdown_preprocess_languagetool()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_bergamot()

        self._close_seamless_m4t()

        if self._preprocessor is not None:
            if hasattr(self._preprocessor, "close"):
                self._preprocessor.close()

            self._preprocessor = None
def engine_cache_model(engine: str, llm_model: str) -> str:
    if engine == TRANSLATION_ENGINE_BERGAMOT:
        return BERGAMOT_MODEL_VARIANT
    if engine == TRANSLATION_ENGINE_SEAMLESS_M4T:
        return SEAMLESS_M4T_MODEL_VARIANT
    return llm_model
def engine_cache_prompt_version(engine: str) -> str:
    if engine == TRANSLATION_ENGINE_BERGAMOT:
        return BERGAMOT_PROMPT_VERSION
    if engine == TRANSLATION_ENGINE_SEAMLESS_M4T:
        return SEAMLESS_M4T_PROMPT_VERSION
    return TRANSLATION_PROMPT_VERSION
def run_self_test() -> int:
    pass
    from dataclasses import replace
    from lingoveil_config import SeamlessM4TSettings
    from lingoveil_translation_cache import (
        TRANSLATION_ENGINE_SEAMLESS_M4T as CACHE_SEAMLESS,
        plan_translation_batch,
        TranslationCache,
    )

    errors: list[str] = []
    def check(name: str, cond: bool, msg: str = "") -> None:
        if not cond:
            errors.append(f"{name}: {msg}")

    bergamot_calls: list[Any] = []
    seamless_calls: list[Any] = []
    lm_calls: list[Any] = []
    class MockBergamot:
        def start(self) -> None:
            pass
        def ping(self, timeout_sec: float = 10.0) -> dict:
            return {"type": "pong", "ready": True}

        def translate_blocks(self, blocks, **kwargs) -> list[dict]:
            bergamot_calls.append(blocks)

            return [{"id": b["id"], "translation": f"DE:{b['text']}"} for b in blocks]
        def close(self) -> None:
            pass
    class MockSeamless:
        load_duration_sec = 0.01
        device_mode = "mock"
        torch_dtype = "float16"
        def start(self) -> None:
            pass
        def translate_blocks(self, blocks, **kwargs) -> list[dict]:
            seamless_calls.append(blocks)

            return [
                {"id": b["id"], "translation": f"SEAM:{b['text']}"}

                for b in blocks
            ]
        def close(self) -> None:
            pass
    class MockLlm:
        def translate_blocks(self, blocks, **kwargs):
            from lingoveil_llm import TranslationItem, TranslationResponse
            lm_calls.append(blocks)

            items = [
                TranslationItem(
                    block_id=b["id"],
                    corrected_source=b["text"].upper(),
                    german=f"DE-LLM:{b['text']}",
                )

                for b in blocks
            ]
            return TranslationResponse(items=items, raw_content="{}", duration_sec=0.1)

    base = _base_test_settings()

    blocks = [{"id": "G01", "text": "Hello"}]
    check("S1_default", base.translation_engine == TRANSLATION_ENGINE_BERGAMOT)

    bergamot_calls.clear()

    seamless_calls.clear()

    lm_calls.clear()

    mgr2 = TranslationEngineManager(base)

    mgr2._bergamot = MockBergamot()  

    mgr2._stats.bergamot_status = "bereit"
    mgr2._llm = MockLlm()  

    mgr2.translate_blocks(blocks, request_generation=mgr2.generation)

    check("S2_bergamot", len(bergamot_calls) == 1)

    check("S2_seamless", len(seamless_calls) == 0)

    check("S2_lm", len(lm_calls) == 0)

    mgr2.close()

    seamless_calls.clear()

    bergamot_calls.clear()

    lm_calls.clear()

    seam_settings = replace(
        base,
        translation_engine=TRANSLATION_ENGINE_SEAMLESS_M4T,
        seamless=replace(base.seamless, license_accepted=True),
    )

    mgr3 = TranslationEngineManager(seam_settings)

    mgr3._seamless = MockSeamless()  

    mgr3._stats.seamless_m4t_status = "bereit"
    mgr3._llm = MockLlm()  

    mgr3._bergamot = MockBergamot()  

    mgr3.translate_blocks(blocks, request_generation=mgr3.generation)

    check("S3_seamless", len(seamless_calls) == 1)

    check("S3_bergamot", len(bergamot_calls) == 0)

    check("S3_lm", len(lm_calls) == 0)

    mgr3.close()

    class PrepSpy:
        calls = 0
        def preprocess(self, *a, **k):
            PrepSpy.calls += 1
            raise AssertionError("preprocess bei lm_studio")

    lm_calls.clear()

    bergamot_calls.clear()

    seamless_calls.clear()

    PrepSpy.calls = 0
    mgr4 = TranslationEngineManager(
        replace(base, translation_engine=TRANSLATION_ENGINE_LM_STUDIO)

    )

    mgr4._preprocessor = PrepSpy()  

    mgr4._llm = MockLlm()  

    pb = mgr4.prepare_block("Hello OCR")

    mgr4.translate_blocks(blocks, request_generation=mgr4.generation)

    check("S4_lm", len(lm_calls) == 1)

    check("S4_no_berg", len(bergamot_calls) == 0)

    check("S4_no_seam", len(seamless_calls) == 0)

    check("S4_no_prep", PrepSpy.calls == 0 and pb.engine_text == "Hello OCR")

    mgr4.close()

    key_b = build_cache_key(
        "same ocr", "en", "de", BERGAMOT_MODEL_VARIANT, BERGAMOT_PROMPT_VERSION,
        translation_engine=TRANSLATION_ENGINE_BERGAMOT,
    )

    key_s = build_cache_key(
        "same ocr", "eng", "deu", SEAMLESS_M4T_MODEL_VARIANT,
        SEAMLESS_M4T_PROMPT_VERSION, translation_engine=TRANSLATION_ENGINE_SEAMLESS_M4T,
    )

    key_l = build_cache_key(
        "same ocr", "en", "de", "mock-model", TRANSLATION_PROMPT_VERSION,
        translation_engine=TRANSLATION_ENGINE_LM_STUDIO,
    )

    check("S5_sep", key_b != key_s and key_s != key_l and key_b != key_l)

    missing_mgr = TranslationEngineManager(
        replace(
            base,
            translation_engine=TRANSLATION_ENGINE_SEAMLESS_M4T,
            seamless=replace(
                base.seamless,
                license_accepted=True,
                model_dir="/nonexistent/seamless_test_missing",
            ),
        )

    )

    s6_err = False
    try:
        missing_mgr.ensure_ready()

    except SeamlessM4TError:
        s6_err = True
    check("S6_error", s6_err)

    check("S6_no_berg", len(bergamot_calls) == 0)

    check("S6_no_counter", missing_mgr.stats.seamless_m4t_requests == 0)

    missing_mgr.close()

    seamless_calls.clear()

    bergamot_calls.clear()

    mgr7 = TranslationEngineManager(seam_settings)

    mgr7._seamless = MockSeamless()  

    mgr7._stats.seamless_m4t_status = "bereit"
    old_gen = mgr7.generation
    mgr7.set_engine(TRANSLATION_ENGINE_BERGAMOT)

    mgr7._bergamot = MockBergamot()  

    mgr7._stats.bergamot_status = "bereit"
    check("S7_unloaded", mgr7._seamless is None)

    stale7 = mgr7.translate_blocks(blocks, request_generation=old_gen)

    mgr7.translate_blocks(blocks, request_generation=mgr7.generation)

    check("S7_stale", len(stale7) == 0)

    check("S7_berg", len(bergamot_calls) == 1)

    mgr7.close()

    bergamot_calls.clear()

    seamless_calls.clear()

    mgr8 = TranslationEngineManager(base)

    mgr8._bergamot = MockBergamot()  

    mgr8._stats.bergamot_status = "bereit"
    mgr8.set_engine(TRANSLATION_ENGINE_SEAMLESS_M4T)

    mgr8._seamless = MockSeamless()  

    check("S8_berg_closed", mgr8._bergamot is None)

    mgr8.translate_blocks(blocks, request_generation=mgr8.generation)

    check("S8_seam", len(seamless_calls) == 1)

    mgr8.close()

    seamless_calls.clear()

    lm_calls.clear()

    mgr9 = TranslationEngineManager(seam_settings)

    mgr9._seamless = MockSeamless()  

    mgr9._stats.seamless_m4t_status = "bereit"
    mgr9.set_engine(TRANSLATION_ENGINE_LM_STUDIO)

    mgr9._llm = MockLlm()  

    check("S9_unloaded", mgr9._seamless is None)

    pb9 = mgr9.prepare_block("raw ocr")

    mgr9.translate_blocks(blocks, request_generation=mgr9.generation)

    check("S9_lm", len(lm_calls) == 1)

    check("S9_raw", pb9.engine_text == "raw ocr")

    mgr9.close()

    seamless_calls.clear()

    mgr10 = TranslationEngineManager(seam_settings)

    mgr10._seamless = MockSeamless()  

    mgr10._stats.seamless_m4t_status = "bereit"
    dup_blocks = [{"id": "G01", "text": "Same"}, {"id": "G02", "text": "Same"}]
    res10 = mgr10.translate_blocks(dup_blocks, request_generation=mgr10.generation)

    check("S10_one_call", len(seamless_calls) == 1 and len(seamless_calls[0]) == 1)

    check("S10_two_out", len(res10) == 2 and res10[0].translation == res10[1].translation)

    mgr10.close()

    lic_mgr = TranslationEngineManager(
        replace(
            base,
            translation_engine=TRANSLATION_ENGINE_SEAMLESS_M4T,
            seamless=replace(base.seamless, license_accepted=False),
        )

    )

    s11_err = False
    try:
        lic_mgr.ensure_ready()

    except SeamlessM4TError as exc:
        s11_err = "Lizenz" in str(exc)

    check("S11_license", s11_err)

    lic_mgr.close()

    from lingoveil_paths import is_dev_mode, path_diagnostics, project_root
    diag = path_diagnostics()

    check("S12_dev", is_dev_mode())

    check("S12_proj", (project_root() / "src").is_dir())

    check("S12_diag", "config_dir" in diag and "seamless_model_default" in diag)

    if errors:
        print("SELF-TEST FEHLGESCHLAGEN:")

        for err in errors:
            print(f"  - {err}")

        return 1
    print("SELF-TEST OK (S1–S12)")

    return 0
def _default_seamless_settings(**overrides: Any) -> SeamlessM4TSettings:
    from lingoveil_config import SeamlessM4TSettings
    defaults = dict(
        model_id=SEAMLESS_DEFAULT_MODEL_ID,
        model_revision=SEAMLESS_DEFAULT_MODEL_REVISION,
        model_dir="",
        source_lang="eng",
        target_lang="deu",
        device="auto",
        license_accepted=False,
    )

    defaults.update(overrides)

    return SeamlessM4TSettings(**defaults)

def _base_test_settings() -> TranslationSettings:
    from lingoveil_config import BrowserSettings
    return TranslationSettings(
        translation_engine=TRANSLATION_ENGINE_BERGAMOT,
        llm=LlmSettings("http://127.0.0.1:1234", "mock-model", 30.0),
        bergamot=BergamotSettings("node", 30.0, "en", "de"),
        seamless=_default_seamless_settings(),
        preprocess=_default_preprocess_settings(enabled=False),
        browser=BrowserSettings(port=8765, access_code=""),
    )

def _default_preprocess_settings(*, enabled: bool = True) -> BergamotPreprocessSettings:
    root = Path(__file__).resolve().parent.parent
    return BergamotPreprocessSettings(
        enabled=enabled,
        mode="standard",
        normalization_enabled=True,
        glossary_enabled=True,
        symspell_enabled=True,
        languagetool_enabled=False,
        languagetool_timeout_sec=5.0,
        preprocess_version="preprocess-v1",
        glossary_path=root / "config" / "ocr_glossary.json",
        symspell_dict_path=root / "resources" / "symspell" / "frequency_dictionary_en_82_765.txt",
    )

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        raise SystemExit(run_self_test())

    print("Verwendung: python lingoveil_translation_engine.py --self-test")
