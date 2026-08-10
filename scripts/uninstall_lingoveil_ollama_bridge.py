#!/usr/bin/env python3
"""Remove only files and configuration managed by the bridge installer."""

from __future__ import annotations

import os
import platform
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

from install_lingoveil_ollama_bridge import (
    BRIDGE_PORT, CONFIG_DIR, ENV_BEGIN, ENV_END, INSTALL_DIR, RUNTIME_ADDRESS,
    SERVICE, SERVICE_USER, UNIT_FILE, USER_MARKER, managed_env,
    wait_for_port_available,
)
from discover_lingoveil_ollama_bridge_address import discover_address


def stop_installed_service(loaded: str) -> None:
    if loaded and loaded != "not-found":
        stopped = subprocess.run(
            ["systemctl", "stop", SERVICE], capture_output=True, text=True, check=False,
        )
        if stopped.returncode:
            raise RuntimeError(
                f"Could not stop {SERVICE}: "
                f"{stopped.stderr.strip() or stopped.stdout.strip()}"
            )

    if RUNTIME_ADDRESS.exists():
        address = RUNTIME_ADDRESS.read_text(encoding="ascii").strip()
    else:
        address = discover_address()
    try:
        wait_for_port_available(address, BRIDGE_PORT, attempts=40)
    except RuntimeError as exc:
        raise RuntimeError(
            f"{SERVICE} was stopped, but {address}:{BRIDGE_PORT} is still occupied. "
            "The installation was kept so the listener can be investigated with: "
            f"sudo ss -ltnp 'sport = :{BRIDGE_PORT}'"
        ) from exc
    if loaded and loaded != "not-found":
        subprocess.run(["systemctl", "disable", SERVICE], check=False)


def main() -> int:
    if os.geteuid() != 0:
        print("Run this uninstaller as root (sudo python3 ...).", file=sys.stderr)
        return 1
    if platform.system() != "Linux":
        print("This uninstaller supports Linux only.", file=sys.stderr)
        return 1
    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / ".env"
    created_user = USER_MARKER.exists()
    loaded = subprocess.run(
        ["systemctl", "show", SERVICE, "--property=LoadState", "--value"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    try:
        stop_installed_service(loaded)
    except (OSError, RuntimeError) as exc:
        print(f"Uninstallation failed: {exc}", file=sys.stderr)
        return 1
    UNIT_FILE.unlink(missing_ok=True)
    subprocess.run(["systemctl", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "reset-failed", SERVICE], check=False)
    shutil.rmtree(INSTALL_DIR, ignore_errors=True)
    shutil.rmtree(Path("/run/lingoveil-ollama-bridge"), ignore_errors=True)
    shutil.rmtree(CONFIG_DIR, ignore_errors=True)
    if env_path.exists():
        env_path.write_text(managed_env(env_path.read_text(encoding="utf-8"), None), encoding="utf-8")
    if created_user:
        try:
            pwd.getpwnam(SERVICE_USER)
        except KeyError:
            pass
        else:
            subprocess.run(["userdel", SERVICE_USER], check=False)
    print("LingoVeil Ollama Bridge removed. Ollama, Docker, models and LingoVeil were untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
