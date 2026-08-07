from __future__ import annotations
import json
import os
import platform
import re
import threading
import time
import uuid

from pathlib import Path
from typing import Any
import httpx

APP_VERSION = "3.0.0"
UPDATE_API_KEY = "upd_4d5c02e8e4fad4c80f0ddd311e5e83816a4cbdea1b99808877a0a9977f15dc78"
UPDATE_PROJECT_ID = "lingoveil-docker"
UPDATE_SERVER_URL = "https://update.gerald-hasani.com"
UPDATE_CHANNEL = "stable"
DONATION_WALLET_ID = 1
DONATION_WALLET_NETWORK = "ethereum"
def automatic_updates_enabled() -> bool:
    pass
    return os.environ.get("UPDATE_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }

class UpdateChecker:
    pass
    def __init__(self, *, data_dir: Path) -> None:
        self.current_version = APP_VERSION
        self.api_key = UPDATE_API_KEY
        self.project_id = UPDATE_PROJECT_ID
        self.server_url = UPDATE_SERVER_URL.rstrip("/")

        self.channel = UPDATE_CHANNEL
        self.automatic_enabled = automatic_updates_enabled()

        self.instance_file = data_dir / "update-instance-id"
        self.wallet_file = data_dir / "donation-wallet-1.json"
        self.cache_seconds = 24 * 60 * 60
        self._lock = threading.Lock()

        self._cached: dict[str, Any] | None = None
        self._cached_at = 0.0
        self.instance_id = self._load_instance_id()

        self.donation_wallet = self._load_donation_wallet()

    def _load_donation_wallet(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.wallet_file.read_text(encoding="utf-8"))

        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return value if self._valid_wallet(value) else None
    @staticmethod
    def _valid_wallet(value: Any) -> bool:
        return bool(
            isinstance(value, dict)

            and value.get("id") == DONATION_WALLET_ID
            and str(value.get("network", "")).lower() == DONATION_WALLET_NETWORK
            and re.fullmatch(r"0x[0-9a-fA-F]{40}", str(value.get("address", "")))

        )

    def _store_donation_wallet(self, value: dict[str, Any]) -> None:
        wallet = {
            "id": DONATION_WALLET_ID,
            "network": DONATION_WALLET_NETWORK,
            "label": str(value.get("label") or "Ethereum / BNB Smart Chain"),
            "address": str(value["address"]),
            "updated_at": value.get("updated_at"),
        }

        self.wallet_file.parent.mkdir(parents=True, exist_ok=True)

        temporary = self.wallet_file.with_suffix(".tmp")

        temporary.write_text(
            json.dumps(wallet, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        os.replace(temporary, self.wallet_file)

        self.donation_wallet = wallet
    def _load_instance_id(self) -> str:
        try:
            value = self.instance_file.read_text(encoding="ascii").strip()

            return str(uuid.UUID(value))

        except (OSError, ValueError):
            value = str(uuid.uuid4())

            self.instance_file.parent.mkdir(parents=True, exist_ok=True)

            temporary = self.instance_file.with_suffix(".tmp")

            temporary.write_text(f"{value}\n", encoding="ascii")

            os.replace(temporary, self.instance_file)

            return value
    def _result(
        self,
        status: str,
        *,
        latest_version: str | None = None,
        minimum_supported: str | None = None,
        critical: bool = False,
        update_link: str | None = None,
        notes_url: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "installed_version": self.current_version,
            "latest_version": latest_version,
            "minimum_supported": minimum_supported,
            "critical": critical,
            "update_link": update_link,
            "notes_url": notes_url,
            "message": message,
            "automatic_updates": self.automatic_enabled,
            "donation_wallet": self.donation_wallet,
        }

    def check(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()

            if (
                not force
                and self._cached is not None
                and now - self._cached_at < self.cache_seconds
            ):
                return {**self._cached, "cached": True}

            result = self._request()

            if result["status"] != "error":
                self._cached = result
                self._cached_at = time.monotonic()

            return {**result, "cached": False}

    def _request(self) -> dict[str, Any]:
        request_id = str(uuid.uuid4())

        payload = {
            "project": {
                "id": self.project_id,
                "instance_id": self.instance_id,
            },
            "current": {"version": self.current_version},
            "channel": self.channel,
            "platform": {
                "os": platform.system().lower(),
                "distro": platform.platform(),
                "arch": platform.machine(),
                "container": "docker",
            },
            "capabilities": {
                "accept_prerelease": self.channel == "beta",
                "supports_delta": False,
                "wallet_ids": [DONATION_WALLET_ID],
            },
        }

        try:
            response = httpx.post(
                f"{self.server_url}/api/updates/v1/updates/check",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "X-Request-ID": request_id,
                    "User-Agent": f"LingoVeil/{self.current_version}",
                },
                timeout=5.0,
            )

            try:
                data = response.json()

            except json.JSONDecodeError:
                data = {}

            response.raise_for_status()

        except (httpx.HTTPError, ValueError) as exc:
            detail = data.get("message") if "data" in locals() else None
            return self._result("error", message=detail or str(exc))

        update = data.get("update") or {}

        latest = data.get("latest") or {}

        current = data.get("current") or {}

        status = str(data.get("status") or "error")

        for wallet in data.get("donation_wallets") or []:
            if self._valid_wallet(wallet):
                self._store_donation_wallet(wallet)

                break
        return {
            **self._result(
                status,
                latest_version=latest.get("version")

                or update.get("latest_version")

                or current.get("version")

                or self.current_version,
                minimum_supported=update.get("minimum_supported"),
                critical=bool(update.get("critical", False)),
                update_link=update.get("update_link"),
                notes_url=update.get("notes_url"),
                message=data.get("message") or update.get("message"),
            ),
            "checked_at": data.get("server_time"),
        }
