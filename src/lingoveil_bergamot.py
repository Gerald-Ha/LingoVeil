from __future__ import annotations
import json
import subprocess
import threading
import time
import uuid

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
LOG_PREFIX = "[Bergamot-Sidecar]"
class BergamotError(Exception):
    pass
@dataclass
class BergamotSettings:
    node_bin: str = "node"
    timeout_sec: float = 30.0
    source_lang: str = "en"
    target_lang: str = "de"
    sidecar_script: Path | None = None
class BergamotTranslatorClient:
    pass
    def __init__(
        self,
        settings: BergamotSettings,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self._log = log_fn or (lambda msg: print(f"{LOG_PREFIX} {msg}", flush=True))

        self._proc: subprocess.Popen[str] | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._lock = threading.Lock()

        self._pending: dict[str, threading.Event] = {}

        self._responses: dict[str, dict[str, Any]] = {}

        self._active_request_id: str | None = None
        self._queued_request_id: str | None = None
        self._closed = False
        self._request_lock = threading.Lock()

    def _sidecar_path(self) -> Path:
        if self.settings.sidecar_script is not None:
            return self.settings.sidecar_script
        project_root = Path(__file__).resolve().parent.parent
        return project_root / "sidecar" / "bergamot" / "bergamot_sidecar.mjs"
    @property
    def busy(self) -> bool:
        return self._request_lock.locked()

    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        if self._closed:
            raise BergamotError("Bergamot-Client bereits geschlossen")

        script = self._sidecar_path()

        if not script.exists():
            raise BergamotError(f"Sidecar-Skript nicht gefunden: {script}")

        cmd = [self.settings.node_bin, str(script)]
        self._log(f"Starte Sidecar: {' '.join(cmd)}")

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=str(script.parent),
            )

        except OSError as exc:
            raise BergamotError(f"Sidecar konnte nicht gestartet werden: {exc}") from exc
        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            name="bergamot-stdout",
            daemon=True,
        )

        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            name="bergamot-stderr",
            daemon=True,
        )

        self._stdout_thread.start()

        self._stderr_thread.start()

    def _read_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for raw_line in proc.stdout:
            line = raw_line.strip()

            if not line:
                continue
            try:
                msg = json.loads(line)

            except json.JSONDecodeError:
                self._log(f"Ungültige stdout-Zeile ignoriert: {line[:200]}")

                continue
            request_id = msg.get("request_id")

            if request_id:
                with self._lock:
                    self._responses[request_id] = msg
                    event = self._pending.get(request_id)

                    if event is not None:
                        event.set()

    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for raw_line in proc.stderr:
            line = raw_line.rstrip()

            if line:
                self._log(line.removeprefix(LOG_PREFIX).strip() or line)

    def _ensure_running(self) -> None:
        if self._proc is None or self._proc.poll() is not None:
            raise BergamotError("Bergamot-Sidecar-Prozess nicht aktiv")

    def _new_request_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"
    def _send(self, payload: dict[str, Any]) -> None:
        self._ensure_running()

        if self._proc is None or self._proc.stdin is None:
            raise BergamotError("Sidecar-stdin nicht verfügbar")

        line = json.dumps(payload, ensure_ascii=False)

        try:
            self._proc.stdin.write(line + "\n")

            self._proc.stdin.flush()

        except OSError as exc:
            raise BergamotError(f"Schreiben an Sidecar fehlgeschlagen: {exc}") from exc
    def _wait_response(self, request_id: str, timeout_sec: float) -> dict[str, Any]:
        event = threading.Event()

        with self._lock:
            self._pending[request_id] = event
        if not event.wait(timeout=timeout_sec):
            with self._lock:
                self._pending.pop(request_id, None)

            raise BergamotError(f"Timeout nach {timeout_sec:.1f}s (request_id={request_id})")

        with self._lock:
            self._pending.pop(request_id, None)

            msg = self._responses.pop(request_id, None)

        if msg is None:
            raise BergamotError(f"Keine Antwort für request_id={request_id}")

        return msg
    def ping(self, timeout_sec: float = 10.0) -> dict[str, Any]:
        self.start()

        request_id = self._new_request_id("ping")

        self._send({"type": "ping", "request_id": request_id})

        msg = self._wait_response(request_id, timeout_sec)

        if msg.get("type") == "error":
            raise BergamotError(msg.get("message", "Ping fehlgeschlagen"))

        return msg
    def translate_blocks(
        self,
        blocks: list[dict[str, str]],
        source_lang: str | None = None,
        target_lang: str | None = None,
        timeout_sec: float | None = None,
    ) -> list[dict[str, str]]:
        with self._request_lock:
            self.start()

            request_id = self._new_request_id("translate")

            with self._lock:
                if self._active_request_id is not None:
                    self._queued_request_id = request_id
                    self._log(
                        "Neuer Auftrag ersetzt wartenden Auftrag "
                        f"({self._queued_request_id})"
                    )

                else:
                    self._active_request_id = request_id
            payload_blocks = [
                {"id": str(b["id"]), "text": str(b["text"])}

                for b in blocks
            ]
            self._send({
                "type": "translate",
                "request_id": request_id,
                "source_lang": source_lang or self.settings.source_lang,
                "target_lang": target_lang or self.settings.target_lang,
                "blocks": payload_blocks,
            })

            effective_timeout = (
                timeout_sec if timeout_sec is not None else self.settings.timeout_sec
            )

            try:
                msg = self._wait_response(request_id, effective_timeout)

            finally:
                with self._lock:
                    if self._active_request_id == request_id:
                        self._active_request_id = None
                    if self._queued_request_id == request_id:
                        self._queued_request_id = None
        if self._proc is not None and self._proc.poll() is not None:
            raise BergamotError("Sidecar-Prozess während Übersetzung beendet")

        if msg.get("type") == "error":
            raise BergamotError(
                f"{msg.get('error_code', 'error')}: {msg.get('message', '')}"
            )

        if msg.get("type") != "translation_result":
            raise BergamotError(f"Unerwartete Antwort: {msg.get('type')}")

        translations = msg.get("translations")

        if not isinstance(translations, list):
            raise BergamotError("Feld 'translations' fehlt in Antwort")

        results: list[dict[str, str]] = []
        for item in translations:
            if not isinstance(item, dict):
                continue
            block_id = str(item.get("id", ""))

            translation = str(item.get("translation", "")).strip()

            if not block_id:
                continue
            if not translation:
                self._log(f"Leere Übersetzung für Block {block_id} – Fallback erforderlich")

                results.append(
                    {
                        "id": block_id,
                        "translation": "",
                        "error": "empty_translation",
                    }

                )

                continue
            results.append({"id": block_id, "translation": translation, "error": ""})

        return results
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._proc is not None and self._proc.poll() is None:
            try:
                request_id = self._new_request_id("shutdown")

                self._send({"type": "shutdown", "request_id": request_id})

                self._wait_response(request_id, timeout_sec=10.0)

            except BergamotError as exc:
                self._log(f"Shutdown-Warnung: {exc}")

            try:
                self._proc.wait(timeout=5.0)

            except subprocess.TimeoutExpired:
                self._proc.kill()

                self._proc.wait(timeout=2.0)

        self._proc = None
