from __future__ import annotations
import json
import subprocess
import sys
import threading
import uuid

from pathlib import Path
from typing import Any, Callable
class OverlayWorker:
    def __init__(self, log_fn: Callable[[str], None]) -> None:
        self._log = log_fn
        self._proc: subprocess.Popen[str] | None = None
        self._request_lock = threading.Lock()

        self._stderr_thread: threading.Thread | None = None
        self._closed = False
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
                self._log(message.removeprefix("[Overlay] "))

    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        if self._closed:
            raise RuntimeError("Overlay-Worker wurde bereits geschlossen")

        script = Path(__file__).with_name("lingoveil_overlay_worker_main.py")

        self._proc = subprocess.Popen(
            [sys.executable, str(script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            name="overlay-stderr",
            daemon=True,
        )

        self._stderr_thread.start()

        self._request({"type": "start"})

        self._log("Overlay-Worker bereit.")

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        proc = self._proc
        if proc is None or proc.poll() is not None or proc.stdin is None or proc.stdout is None:
            raise RuntimeError("Overlay-Worker ist nicht aktiv")

        payload["request_id"] = uuid.uuid4().hex
        with self._request_lock:
            proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")

            proc.stdin.flush()

            line = proc.stdout.readline()

        if not line:
            raise RuntimeError(f"Overlay-Worker wurde unerwartet beendet (Code {proc.poll()})")

        response = json.loads(line)

        if response.get("type") == "error":
            raise RuntimeError(str(response.get("message", "Unbekannter Overlay-Fehler")))

        return response
    def render(
        self,
        *,
        input_path: Path,
        output_path: Path,
        grouped: list[list[Any]],
    ) -> list[dict[str, Any]]:
        self.start()

        response = self._request(
            {
                "type": "render",
                "input_path": str(input_path),
                "output_path": str(output_path),
                "grouped": grouped,
            }

        )

        return list(response.get("groups", []))

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

            except Exception as exc:
                self._log(f"Overlay-Worker-Shutdown erzwungen: {exc}")

                proc.kill()

                proc.wait(timeout=5.0)

        self._proc = None
