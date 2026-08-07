from __future__ import annotations
import gc
import resource
import time

from pathlib import Path
from typing import Any, Callable
import torch

from transformers import SeamlessM4Tv2ForTextToText
from transformers.models.seamless_m4t.feature_extraction_seamless_m4t import (
    SeamlessM4TFeatureExtractor,
)

from transformers.models.seamless_m4t.processing_seamless_m4t import (
    SeamlessM4TProcessor,
)

from transformers.models.seamless_m4t.tokenization_seamless_m4t_fast import (
    SeamlessM4TTokenizerFast,
)

LOG_PREFIX = "[SeamlessM4T]"
DEFAULT_SOURCE_MODEL = "facebook/seamless-m4t-v2-large"
DEFAULT_MODEL_LICENSE = "CC-BY-NC-4.0 (Modellgewichte, nur nichtkommerzielle Nutzung)"
_MIN_TOKENIZER_JSON_BYTES = 1_000_000
class SeamlessM4TError(Exception):
    pass
class SeamlessM4TTextTranslator:
    pass
    def __init__(
        self,
        model_dir: Path,
        device_preference: str = "auto",
        source_lang: str = "eng",
        target_lang: str = "deu",
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        self.model_dir = Path(model_dir)

        self.device_preference = device_preference
        self.default_source_lang = source_lang
        self.default_target_lang = target_lang
        self._log = log_fn or (lambda msg: print(f"{LOG_PREFIX} {msg}", flush=True))

        self._processor: Any = None
        self._model: SeamlessM4Tv2ForTextToText | None = None
        self._started = False
        self._ready = False
        self._closed = False
        self.load_duration_sec = 0.0
        self.inference_count = 0
        self.total_inference_sec = 0.0
        self.device_mode = "unknown"
        self.torch_dtype: str = "unknown"
        self.device_map: str | dict[str, int] | None = None
        self.ram_rss_mb_before = 0.0
        self.ram_rss_mb_after_load = 0.0
        self.vram_mb_before = 0.0
        self.vram_mb_after_load = 0.0
        self.cuda_attempted = False
        self.cuda_success = False
        self.cuda_oom_error = ""
        self.load_attempts: list[dict[str, Any]] = []
    @staticmethod
    def _rss_mb() -> float:
        usage = resource.getrusage(resource.RUSAGE_SELF)

        return usage.ru_maxrss / 1024.0
    @staticmethod
    def _vram_mb() -> float:
        if not torch.cuda.is_available():
            return 0.0
        return torch.cuda.memory_allocated() / (1024.0 * 1024.0)

    def _log_device_map(self) -> None:
        if self._model is None:
            return
        if hasattr(self._model, "hf_device_map"):
            self.device_map = dict(self._model.hf_device_map)

            self._log(f"hf_device_map: {self.device_map}")

        else:
            device = next(self._model.parameters()).device
            self.device_map = str(device)

            self._log(f"Modell-Device: {device}")

    def _release_model(self) -> int:
        self._model = None
        self._processor = None
        self.device_map = None
        self._ready = False
        collected = gc.collect()

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return collected
    def _tokenizer_json_path(self) -> Path:
        return self.model_dir / "tokenizer.json"
    def _remove_invalid_tokenizer_json(self) -> None:
        pass
        tokenizer_json = self._tokenizer_json_path()

        if not tokenizer_json.is_file():
            return
        if tokenizer_json.stat().st_size >= _MIN_TOKENIZER_JSON_BYTES:
            return
        try:
            tokenizer_json.unlink()

        except OSError as exc:
            raise SeamlessM4TError(
                f"Defekte tokenizer.json konnte nicht entfernt werden: {exc}"
            ) from exc
        self._log("Defekte tokenizer.json entfernt (zu klein / veraltet)")

    def _ensure_tokenizer_json(self) -> None:
        pass
        self._remove_invalid_tokenizer_json()

        tokenizer_json = self._tokenizer_json_path()

        if tokenizer_json.is_file():
            return
        self._log("Erzeuge tokenizer.json für Offline-Ladepfad (einmalig) …")

        try:
            tokenizer = SeamlessM4TTokenizerFast.from_pretrained(
                str(self.model_dir),
                local_files_only=True,
                src_lang=self.default_source_lang,
                tgt_lang=self.default_target_lang,
            )

            tokenizer.save_pretrained(str(self.model_dir))

        except Exception as exc:
            raise SeamlessM4TError(
                f"tokenizer.json konnte nicht erzeugt werden: {exc}"
            ) from exc
        size_mb = tokenizer_json.stat().st_size / (1024.0 * 1024.0)

        self._log(f"tokenizer.json erzeugt ({size_mb:.1f} MB)")

    def _load_tokenizer(self) -> SeamlessM4TTokenizerFast:
        self._ensure_tokenizer_json()

        try:
            return SeamlessM4TTokenizerFast.from_pretrained(
                str(self.model_dir),
                local_files_only=True,
                src_lang=self.default_source_lang,
                tgt_lang=self.default_target_lang,
            )

        except Exception as exc:
            raise SeamlessM4TError(
                f"Seamless-Tokenizer konnte nicht geladen werden: {exc}"
            ) from exc
    def _load_processor(self) -> None:
        self._log(f"Lade Prozessor aus {self.model_dir} (offline)")

        tokenizer = self._load_tokenizer()

        feature_extractor = SeamlessM4TFeatureExtractor.from_pretrained(
            str(self.model_dir),
            local_files_only=True,
        )

        self._processor = SeamlessM4TProcessor(
            feature_extractor=feature_extractor,
            tokenizer=tokenizer,
        )

    def _try_load_model(
        self,
        *,
        device: str,
        torch_dtype: torch.dtype,
        device_map: str | None,
    ) -> None:
        attempt: dict[str, Any] = {
            "device": device,
            "torch_dtype": str(torch_dtype).replace("torch.", ""),
            "device_map": device_map,
            "success": False,
            "error": "",
            "duration_sec": 0.0,
            "vram_mb_after": 0.0,
        }

        label = f"device={device}, dtype={attempt['torch_dtype']}, device_map={device_map}"
        self._log(f"Lade T2TT-Modell ({label})")

        t0 = time.monotonic()

        try:
            kwargs: dict[str, Any] = {
                "local_files_only": True,
                "torch_dtype": torch_dtype,
            }

            if device_map is not None:
                kwargs["device_map"] = device_map
            self._model = SeamlessM4Tv2ForTextToText.from_pretrained(
                str(self.model_dir),
                **kwargs,
            )

            if device_map is None:
                self._model = self._model.to(device)

            self._model.eval()

            attempt["success"] = True
            attempt["duration_sec"] = time.monotonic() - t0
            attempt["vram_mb_after"] = self._vram_mb()

            self.load_attempts.append(attempt)

            self._log(
                f"Modell geladen ({attempt['duration_sec']:.2f} s, "
                f"VRAM {attempt['vram_mb_after']:.1f} MB)"
            )

            self._log_device_map()

        except Exception as exc:
            attempt["duration_sec"] = time.monotonic() - t0
            attempt["error"] = str(exc)

            self.load_attempts.append(attempt)

            self._log(f"Laden fehlgeschlagen ({label}): {exc}")

            self._release_model()

            raise
    def start(self) -> None:
        if self._started:
            return
        if self._closed:
            raise SeamlessM4TError("SeamlessM4T-Translator bereits geschlossen")

        if not self.model_dir.is_dir():
            raise SeamlessM4TError(f"Modellordner fehlt: {self.model_dir}")

        config_file = self.model_dir / "config.json"
        if not config_file.is_file():
            raise SeamlessM4TError(
                f"config.json fehlt in {self.model_dir}. Bitte Modell zuerst herunterladen."
            )

        self.ram_rss_mb_before = self._rss_mb()

        self.vram_mb_before = self._vram_mb()

        self._log(
            f"RAM (max RSS) vor Start: {self.ram_rss_mb_before:.1f} MB, "
            f"VRAM: {self.vram_mb_before:.1f} MB"
        )

        t0 = time.monotonic()

        self._load_processor()

        cuda_available = torch.cuda.is_available()

        want_cuda = self.device_preference in {"auto", "cuda", "gpu"}

        if want_cuda and cuda_available:
            self.cuda_attempted = True
            try:
                self._try_load_model(
                    device="cuda",
                    torch_dtype=torch.float16,
                    device_map="auto",
                )

                self.device_mode = "cuda"
                self.torch_dtype = "float16"
                self.cuda_success = True
            except RuntimeError as exc:
                if "out of memory" in str(exc).lower():
                    self.cuda_oom_error = str(exc)

                    self._log("CUDA OOM – wechsle kontrolliert auf CPU-Fallback")

                else:
                    raise SeamlessM4TError(f"CUDA-Laden fehlgeschlagen: {exc}") from exc
            except Exception as exc:
                if "out of memory" in str(exc).lower():
                    self.cuda_oom_error = str(exc)

                    self._log("CUDA OOM – wechsle kontrolliert auf CPU-Fallback")

                else:
                    raise SeamlessM4TError(f"CUDA-Laden fehlgeschlagen: {exc}") from exc
        if not self.cuda_success:
            self._try_load_model(
                device="cpu",
                torch_dtype=torch.float32,
                device_map=None,
            )

            self.device_mode = "cpu"
            self.torch_dtype = "float32"
        self.load_duration_sec = time.monotonic() - t0
        self.ram_rss_mb_after_load = self._rss_mb()

        self.vram_mb_after_load = self._vram_mb()

        self._started = True
        self._ready = True
        self._log(
            f"Bereit ({self.load_duration_sec:.2f} s, Modus={self.device_mode}, "
            f"dtype={self.torch_dtype}, RAM {self.ram_rss_mb_after_load:.1f} MB, "
            f"VRAM {self.vram_mb_after_load:.1f} MB)"
        )

    def _move_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if self._model is None:
            raise SeamlessM4TError("Modell nicht geladen")

        device = next(self._model.parameters()).device
        moved: dict[str, Any] = {}

        for key, value in inputs.items():
            if isinstance(value, torch.Tensor):
                moved[key] = value.to(device)

            else:
                moved[key] = value
        return moved
    def translate_blocks(
        self,
        blocks: list[dict[str, str]],
        source_lang: str = "eng",
        target_lang: str = "deu",
    ) -> list[dict[str, str]]:
        if not blocks:
            return []
        if not self._started:
            self.start()

        if self._processor is None or self._model is None:
            raise SeamlessM4TError("Engine nicht initialisiert")

        id_order: list[str] = []
        texts: list[str] = []
        for block in blocks:
            id_order.append(block["id"])

            texts.append(block.get("text", ""))

        t0 = time.monotonic()

        try:
            text_inputs = self._processor(
                text=texts,
                src_lang=source_lang or self.default_source_lang,
                return_tensors="pt",
                padding=True,
                truncation=True,
            )

            text_inputs = self._move_inputs(text_inputs)

            with torch.inference_mode():
                output_tokens = self._model.generate(
                    **text_inputs,
                    tgt_lang=target_lang or self.default_target_lang,
                )

        except RuntimeError as exc:
            if "out of memory" in str(exc).lower() and self.device_mode == "cuda":
                raise SeamlessM4TError(
                    f"CUDA-Inferenz OOM (kein automatischer Wechsel während Lauf): {exc}"
                ) from exc
            raise SeamlessM4TError(f"generate fehlgeschlagen: {exc}") from exc
        except Exception as exc:
            raise SeamlessM4TError(f"Übersetzung fehlgeschlagen: {exc}") from exc
        duration = time.monotonic() - t0
        self.inference_count += 1
        self.total_inference_sec += duration
        if output_tokens.dim() == 1:
            output_tokens = output_tokens.unsqueeze(0)

        results: list[dict[str, str]] = []
        for block_id, token_row in zip(id_order, output_tokens, strict=True):
            decoded = self._processor.decode(
                token_row.tolist(),
                skip_special_tokens=True,
            )

            results.append({"id": block_id, "translation": decoded})

        self._log(
            f"Batch: {len(blocks)} Text(e), {duration:.3f} s "
            f"(IDs: {', '.join(id_order)})"
        )

        return results
    def close(self) -> None:
        if self._closed:
            return
        ram_before = self._rss_mb()

        vram_before = self._vram_mb()

        self._log("Unload gestartet")

        self._log(f"RAM RSS vor close(): {ram_before:.1f} MB")

        self._log(f"VRAM vor close(): {vram_before:.1f} MB")

        collected = self._release_model()

        self._log("Modellreferenzen gelöscht")

        self._log(f"gc.collect(): {collected} Objekte")

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

            self._log("torch.cuda.empty_cache(): ausgeführt")

        ram_after = self._rss_mb()

        vram_after = self._vram_mb()

        self._log(f"RAM RSS nach Unload: {ram_after:.1f} MB")

        self._log(f"VRAM nach Unload: {vram_after:.1f} MB")

        self._log(
            "Hinweis: RSS kann durch Python-/PyTorch-Allocator reserviert bleiben"
        )

        self._started = False
        self._closed = True
        self._log("Engine geschlossen")
