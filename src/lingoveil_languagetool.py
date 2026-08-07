from __future__ import annotations
import json
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
LOG_PREFIX = "[LanguageTool]"
LANGUAGETOOL_SAFE_RULES_VERSION = "lt-safe-v2"
AUTO_APPLY_CATEGORIES = {
    "TYPOS",
    "CASING",
    "PUNCTUATION",
    "COMPOUNDING",
    "CONFUSED_WORDS",
    "MISSING_PUNCTUATION",
}

AUTO_APPLY_BLOCKED_RULE_IDS = {
    "PLURAL_VERB_AFTER_THIS",
    "THIS_NNS",
    "AGREEMENT_SENT_START",
    "SUBJECT_VERB_AGREEMENT",
}

AUTO_APPLY_RULE_IDS_PREFIXES = (
    "EN_A_VS_AN",
    "UPPERCASE_SENTENCE_START",
    "COMMA_PARENTHESIS_WHITESPACE",
    "WHITESPACE_RULE",
)

class LanguageToolError(Exception):
    pass
@dataclass
class LanguageToolSettings:
    java_bin: str = "java"
    timeout_sec: float = 5.0
    language: str = "en-US"
    lt_home: Path | None = None
    config_path: Path | None = None
    host: str = "127.0.0.1"
def _find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))

        return int(sock.getsockname()[1])

def default_languagetool_home(project_root: Path | None = None) -> Path:
    root = project_root or Path(__file__).resolve().parent.parent
    lt_dir = root / "tools" / "languagetool"
    for candidate in sorted(lt_dir.glob("LanguageTool-*")):
        jar = candidate / "languagetool-server.jar"
        if jar.exists():
            return candidate
    raise LanguageToolError(f"LanguageTool nicht gefunden unter {lt_dir}")

@dataclass
class LocalLanguageToolClient:
    settings: LanguageToolSettings
    log_fn: Callable[[str], None] | None = None
    _proc: subprocess.Popen[str] | None = field(default=None, init=False, repr=False)

    _stderr_thread: threading.Thread | None = field(default=None, init=False, repr=False)

    _port: int | None = field(default=None, init=False, repr=False)

    _closed: bool = field(default=False, init=False, repr=False)

    def _log(self, message: str) -> None:
        if self.log_fn:
            self.log_fn(f"{LOG_PREFIX} {message}")

        else:
            print(f"{LOG_PREFIX} {message}", flush=True)

    @property
    def base_url(self) -> str:
        if self._port is None:
            raise LanguageToolError("LanguageTool-Server nicht gestartet")

        return f"http://{self.settings.host}:{self._port}"
    def _lt_home(self) -> Path:
        if self.settings.lt_home is not None:
            return self.settings.lt_home
        return default_languagetool_home()

    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        if self._closed:
            raise LanguageToolError("LanguageTool-Client bereits geschlossen")

        lt_home = self._lt_home()

        jar_path = lt_home / "languagetool-server.jar"
        if not jar_path.exists():
            raise LanguageToolError(f"languagetool-server.jar fehlt: {jar_path}")

        self._port = _find_free_port(self.settings.host)

        cmd = [
            self.settings.java_bin,
            "-cp",
            str(jar_path),
            "org.languagetool.server.HTTPServer",
            "--port",
            str(self._port),
        ]
        config = self.settings.config_path
        if config is not None and config.exists() and config.stat().st_size > 0:
            if "languageModel=" not in config.read_text(encoding="utf-8"):
                cmd.extend(["--config", str(config)])

        self._log(f"Starte Server auf {self.settings.host}:{self._port}")

        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(lt_home),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        except OSError as exc:
            raise LanguageToolError(f"LanguageTool konnte nicht gestartet werden: {exc}") from exc
        self._stderr_thread = threading.Thread(
            target=self._read_stderr, name="languagetool-stderr", daemon=True
        )

        self._stderr_thread.start()

        self._wait_ready()

    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            text = line.rstrip()

            if text:
                self._log(text)

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + max(30.0, self.settings.timeout_sec * 3)

        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise LanguageToolError("LanguageTool-Prozess vor Bereitschaft beendet")

            try:
                self.check("This is a test.", timeout_sec=3.0)

                self._log("Server bereit")

                return
            except LanguageToolError:
                time.sleep(0.5)

        raise LanguageToolError("LanguageTool-Start-Timeout")

    def check(self, text: str, *, timeout_sec: float | None = None) -> dict[str, Any]:
        if not text.strip():
            return {"matches": []}

        effective_timeout = (
            timeout_sec if timeout_sec is not None else self.settings.timeout_sec
        )

        if self._proc is None or self._port is None:
            raise LanguageToolError("LanguageTool-Server nicht gestartet")

        data = urllib.parse.urlencode({
            "language": self.settings.language,
            "text": text,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/v2/check",
            data=data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        try:
            with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))

        except urllib.error.URLError as exc:
            raise LanguageToolError(f"LanguageTool-Anfrage fehlgeschlagen: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LanguageToolError(f"Ungültige LanguageTool-Antwort: {exc}") from exc
        return payload
    def apply_safe_corrections(
        self,
        text: str,
        matches: list[dict[str, Any]],
        *,
        protected_terms: set[str] | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        protected = {p.upper() for p in (protected_terms or set())}

        applied: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        sorted_matches = sorted(
            matches,
            key=lambda m: int(m.get("offset", 0)),
            reverse=True,
        )

        result = text
        for match in sorted_matches:
            replacements = match.get("replacements") or []
            rule = match.get("rule") or {}

            category = (rule.get("category") or {}).get("id", "")

            rule_id = rule.get("id", "")

            offset = int(match.get("offset", 0))

            length = int(match.get("length", 0))

            original_slice = result[offset : offset + length]
            decision = self._evaluate_match(
                match,
                original_slice,
                replacements,
                category,
                rule_id,
                protected,
            )

            if not decision["applied"]:
                rejected.append(decision)

                continue
            replacement = decision["replacement"]
            result = result[:offset] + replacement + result[offset + length :]
            applied.append(decision)

        return result, applied + [
            {**r, "applied": False} for r in rejected if "applied" not in r
        ]
    def _evaluate_match(
        self,
        match: dict[str, Any],
        original_slice: str,
        replacements: list[dict[str, Any]],
        category: str,
        rule_id: str,
        protected: set[str],
    ) -> dict[str, Any]:
        base = {
            "rule_id": rule_id,
            "category": category,
            "message": match.get("message", ""),
            "context": (match.get("context") or {}).get("text", ""),
            "original": original_slice,
            "suggestions": [r.get("value", "") for r in replacements],
            "applied": False,
            "reason": "",
        }

        if not replacements:
            base["reason"] = "keine Vorschläge"
            return base
        if len(replacements) != 1:
            base["reason"] = "mehrere konkurrierende Vorschläge"
            return base
        replacement = str(replacements[0].get("value", "")).strip()

        if not replacement:
            base["reason"] = "leerer Ersatz"
            return base
        if len(original_slice) > 80 or len(replacement) > 80:
            base["reason"] = "zu lange Änderung"
            return base
        if self._touches_protected(original_slice, replacement, protected):
            base["reason"] = "geschützter Begriff betroffen"
            return base
        if rule_id in AUTO_APPLY_BLOCKED_RULE_IDS:
            base["reason"] = f"Regel blockiert ({rule_id})"
            return base
        category_ok = category in AUTO_APPLY_CATEGORIES
        rule_ok = any(rule_id.startswith(p) for p in AUTO_APPLY_RULE_IDS_PREFIXES)

        if not category_ok and not rule_ok:
            base["reason"] = f"Kategorie/Regel nicht freigegeben ({category})"
            return base
        base["applied"] = True
        base["replacement"] = replacement
        base["reason"] = "sichere lokale Korrektur"
        return base
    @staticmethod
    def _touches_protected(
        original: str,
        replacement: str,
        protected: set[str],
    ) -> bool:
        import re

        orig_tokens = {t.upper() for t in re.findall(r"[A-Za-z']+", original)}

        repl_tokens = {t.upper() for t in re.findall(r"[A-Za-z']+", replacement)}

        for term in protected:
            if term in orig_tokens and term not in repl_tokens:
                return True
        return False
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()

            try:
                self._proc.wait(timeout=8.0)

            except subprocess.TimeoutExpired:
                self._proc.kill()

                self._proc.wait(timeout=3.0)

        self._proc = None
        self._log("Server beendet")
