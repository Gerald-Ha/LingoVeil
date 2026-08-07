from __future__ import annotations
import base64
import json
import subprocess
import sys
import threading
import uuid

from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from PIL import Image
class EasyOcrWorker:
    pass
    def __init__(self, log_fn: Callable[[str], None]) -> None:
        self.log = log_fn
        self.error: Exception | None = None
        self.ready = threading.Event()

        self._proc: subprocess.Popen[str] | None = None
        self._request_lock = threading.Lock()

        self._stderr_thread: threading.Thread | None = None
        self._closed = False
        self._init_thread = threading.Thread(
            target=self._start,
            name="easyocr-worker-start",
            daemon=True,
        )

        self._init_thread.start()

    @property
    def busy(self) -> bool:
        return self._request_lock.locked()

    @staticmethod
    def _worker_path() -> Path:
        return Path(__file__).with_name("lingoveil_ocr_worker_main.py")

    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            message = line.rstrip()

            if message:
                self.log(message.removeprefix("[EasyOCR] "))

    def _start(self) -> None:
        try:
            self.log("EasyOCR-Worker wird gestartet (gpu=False, Sprache: en) …")

            self._proc = subprocess.Popen(
                [sys.executable, str(self._worker_path())],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            self._stderr_thread = threading.Thread(
                target=self._read_stderr,
                name="easyocr-stderr",
                daemon=True,
            )

            self._stderr_thread.start()

            self._request({"type": "start"})

            self.log("EasyOCR-Worker bereit.")

        except Exception as exc:
            self.error = exc
            self.log(f"EasyOCR-Worker konnte nicht starten: {exc}")

            self._terminate()

        finally:
            self.ready.set()

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        proc = self._proc
        if proc is None or proc.poll() is not None or proc.stdin is None or proc.stdout is None:
            raise RuntimeError("EasyOCR-Worker ist nicht aktiv")

        payload["request_id"] = uuid.uuid4().hex
        with self._request_lock:
            proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")

            proc.stdin.flush()

            line = proc.stdout.readline()

        if not line:
            raise RuntimeError(f"EasyOCR-Worker wurde unerwartet beendet (Code {proc.poll()})")

        response = json.loads(line)

        if response.get("type") == "error":
            raise RuntimeError(str(response.get("message", "Unbekannter OCR-Fehler")))

        return response
    def run_ocr(self, image: Image.Image) -> list[tuple[Any, str, float]]:
        if not self.ready.is_set() or self.error is not None:
            raise RuntimeError("EasyOCR-Worker ist nicht bereit")

        buffer = BytesIO()

        image.convert("RGB").save(buffer, format="PNG")

        response = self._request(
            {
                "type": "ocr",
                "image": base64.b64encode(buffer.getvalue()).decode("ascii"),
            }

        )

        return list(response.get("results", []))

    def _terminate(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.kill()

            proc.wait(timeout=5.0)

        self._proc = None
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.ready.wait(timeout=300.0)

        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            try:
                self._request({"type": "shutdown"})

                proc.wait(timeout=10.0)

            except Exception as exc:
                self.log(f"EasyOCR-Worker-Shutdown erzwungen: {exc}")

                self._terminate()

        self._proc = None
