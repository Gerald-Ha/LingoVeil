from __future__ import annotations
import json
import subprocess
import sys
import threading
import uuid

from pathlib import Path
from typing import Any, Callable
class SeamlessM4TError(Exception):
    pass
class SeamlessM4TWorkerClient:
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
        self._log = log_fn or (lambda msg: print(f"[SeamlessM4T] {msg}", flush=True))

        self._proc: subprocess.Popen[str] | None = None
        self._stderr_thread: threading.Thread | None = None
        self._request_lock = threading.Lock()

        self._closed = False
        self.device_mode = "unknown"
        self.torch_dtype = "unknown"
        self.load_duration_sec = 0.0
        self.inference_count = 0
        self.total_inference_sec = 0.0
    @staticmethod
    def _worker_path() -> Path:
        return Path(__file__).with_name("lingoveil_seamless_worker_main.py")

    @property
    def busy(self) -> bool:
        return self._request_lock.locked()

    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            message = line.rstrip()

            if message:
                self._log(message.removeprefix("[SeamlessM4T] "))

    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        if self._closed:
            raise SeamlessM4TError("SeamlessM4T-Worker bereits geschlossen")

        cmd = [
            sys.executable,
            str(self._worker_path()),
            str(self.model_dir),
            self.device_preference,
            self.default_source_lang,
            self.default_target_lang,
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

        except OSError as exc:
            raise SeamlessM4TError(f"SeamlessM4T-Worker konnte nicht starten: {exc}") from exc
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            name="seamless-stderr",
            daemon=True,
        )

        self._stderr_thread.start()

        response = self._request({"type": "start"})

        self.device_mode = str(response.get("device_mode", "unknown"))

        self.torch_dtype = str(response.get("torch_dtype", "unknown"))

        self.load_duration_sec = float(response.get("load_duration_sec", 0.0))

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        proc = self._proc
        if proc is None or proc.poll() is not None or proc.stdin is None or proc.stdout is None:
            raise SeamlessM4TError("SeamlessM4T-Worker ist nicht aktiv")

        payload["request_id"] = uuid.uuid4().hex
        with self._request_lock:
            try:
                proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")

                proc.stdin.flush()

                line = proc.stdout.readline()

            except OSError as exc:
                raise SeamlessM4TError(f"Kommunikation mit SeamlessM4T fehlgeschlagen: {exc}") from exc
        if not line:
            raise SeamlessM4TError(
                f"SeamlessM4T-Worker wurde unerwartet beendet (Code {proc.poll()})"
            )

        try:
            response = json.loads(line)

        except json.JSONDecodeError as exc:
            raise SeamlessM4TError("Ungültige Antwort vom SeamlessM4T-Worker") from exc
        if response.get("type") == "error":
            raise SeamlessM4TError(str(response.get("message", "Unbekannter Worker-Fehler")))

        return response
    def translate_blocks(
        self,
        blocks: list[dict[str, str]],
        source_lang: str = "eng",
        target_lang: str = "deu",
    ) -> list[dict[str, str]]:
        if not blocks:
            return []
        self.start()

        response = self._request(
            {
                "type": "translate",
                "blocks": blocks,
                "source_lang": source_lang,
                "target_lang": target_lang,
            }

        )

        self.inference_count += 1
        self.total_inference_sec += float(response.get("duration_sec", 0.0))

        return list(response.get("translations", []))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            try:
                self._request({"type": "shutdown"})

                proc.wait(timeout=10.0)

            except (SeamlessM4TError, subprocess.TimeoutExpired) as exc:
                self._log(f"Worker-Shutdown erzwungen: {exc}")

                proc.kill()

                proc.wait(timeout=5.0)

        self._proc = None
