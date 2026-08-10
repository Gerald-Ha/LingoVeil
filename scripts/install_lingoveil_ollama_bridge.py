#!/usr/bin/env python3
"""Install or update the restricted LingoVeil Ollama Bridge on Linux."""

from __future__ import annotations

import grp
import json
import os
import platform
import pwd
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from discover_lingoveil_ollama_bridge_address import DiscoveryError, discover_address
from lingoveil_ollama_bridge import BRIDGE_PORT

SERVICE = "lingoveil-ollama-bridge.service"
SERVICE_USER = "lingoveil-ollama-bridge"
INSTALL_DIR = Path("/usr/local/libexec/lingoveil-ollama-bridge")
CONFIG_DIR = Path("/etc/lingoveil-ollama-bridge")
TOKEN_FILE = CONFIG_DIR / "token"
USER_MARKER = CONFIG_DIR / "installer-created-user"
UNIT_FILE = Path("/etc/systemd/system") / SERVICE
RUNTIME_ADDRESS = Path("/run/lingoveil-ollama-bridge/bind-address")
ENV_BEGIN = "# BEGIN LingoVeil Ollama Bridge (managed by installer)"
ENV_END = "# END LingoVeil Ollama Bridge (managed by installer)"


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=check)


def managed_env(contents: str, token: str | None) -> str:
    lines = contents.splitlines()
    output: list[str] = []
    inside = False
    for line in lines:
        if line == ENV_BEGIN:
            inside = True
            continue
        if line == ENV_END and inside:
            inside = False
            continue
        if not inside:
            output.append(line)
    while output and not output[-1]:
        output.pop()
    if token is not None:
        output.extend([
            "", ENV_BEGIN,
            "LINGOVEIL_OLLAMA_BASE_URL=http://host.docker.internal:11435",
            f"LINGOVEIL_OLLAMA_BRIDGE_TOKEN={token}", ENV_END,
        ])
    return "\n".join(output) + "\n"


def atomic_write(path: Path, contents: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(contents, encoding="utf-8")
    temporary.chmod(mode)
    os.replace(temporary, path)


def unit_text(python: str) -> str:
    discovery = INSTALL_DIR / "discover_lingoveil_ollama_bridge_address.py"
    bridge = INSTALL_DIR / "lingoveil_ollama_bridge.py"
    return f"""[Unit]
Description=LingoVeil restricted Ollama bridge
Wants=network-online.target docker.service ollama.service
After=network-online.target docker.service ollama.service
PartOf=docker.service

[Service]
Type=simple
User={SERVICE_USER}
Group={SERVICE_USER}
RuntimeDirectory=lingoveil-ollama-bridge
RuntimeDirectoryMode=0755
ExecStartPre=+{python} {discovery} --output {RUNTIME_ADDRESS}
ExecStart={python} {bridge} --bind-address-file {RUNTIME_ADDRESS} --token-file {TOKEN_FILE} --port {BRIDGE_PORT}
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
CapabilityBoundingSet=
AmbientCapabilities=
RestrictAddressFamilies=AF_INET

[Install]
WantedBy=multi-user.target
"""


def check_local_ollama() -> None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            json.load(response)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise RuntimeError(
            "Ollama is not reachable at http://127.0.0.1:11434/api/tags. "
            "Start Ollama locally before installing the bridge."
        ) from exc


def ensure_service_user() -> tuple[int, int]:
    created = False
    try:
        service_group = grp.getgrnam(SERVICE_USER)
    except KeyError:
        run(["groupadd", "--system", SERVICE_USER])
        service_group = grp.getgrnam(SERVICE_USER)
    try:
        account = pwd.getpwnam(SERVICE_USER)
    except KeyError:
        run([
            "useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin",
            "--gid", SERVICE_USER, SERVICE_USER,
        ])
        account = pwd.getpwnam(SERVICE_USER)
        created = True
    if account.pw_gid != service_group.gr_gid:
        raise RuntimeError(
            f"Existing user {SERVICE_USER} has an unexpected primary group; refusing to modify it"
        )
    groups = {group.gr_name for group in grp.getgrall() if SERVICE_USER in group.gr_mem}
    docker_group = next((group for group in grp.getgrall() if group.gr_name == "docker"), None)
    if "docker" in groups or (docker_group and account.pw_gid == docker_group.gr_gid):
        raise RuntimeError(f"Existing user {SERVICE_USER} must not belong to the docker group")
    if created:
        USER_MARKER.touch(mode=0o600, exist_ok=True)
    return account.pw_uid, account.pw_gid


def bridge_request(address: str, token: str, *, attempts: int = 20) -> None:
    last_error: BaseException | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            f"http://{address}:{BRIDGE_PORT}/api/tags",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError(f"Bridge test returned HTTP {response.status}")
                json.load(response)
            return
        except urllib.error.HTTPError:
            raise
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.25)
    raise RuntimeError(
        f"Bridge did not become ready after {attempts} attempts: {last_error}"
    ) from last_error


def bridge_request_from_docker(token: str) -> bool:
    container = run(
        ["docker", "inspect", "--format", "{{.State.Running}}", "lingoveil-live"],
        check=False,
    )
    if container.returncode or container.stdout.strip() != "true":
        return False
    environment = dict(os.environ)
    environment["LINGOVEIL_BRIDGE_TEST_TOKEN"] = token
    code = (
        "import json,os,urllib.request;"
        "r=urllib.request.Request('http://host.docker.internal:11435/api/tags',"
        "headers={'Authorization':'Bearer '+os.environ['LINGOVEIL_BRIDGE_TEST_TOKEN']});"
        "json.load(urllib.request.urlopen(r,timeout=10))"
    )
    completed = subprocess.run(
        [
            "docker", "exec", "-e", "LINGOVEIL_BRIDGE_TEST_TOKEN",
            "lingoveil-live", "python", "-c", code,
        ], capture_output=True, text=True, env=environment, check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            "Bridge host test succeeded, but Docker cannot reach host.docker.internal:11435. "
            "The bridge service remains installed. Check the host firewall INPUT rules for "
            "traffic arriving on LingoVeil's Docker bridge. Diagnostic command: "
            "docker exec lingoveil-live python -c \"import socket; "
            "print(socket.gethostbyname('host.docker.internal'))\". Details: "
            + (completed.stderr.strip() or completed.stdout.strip())[-1200:]
        )
    return True


def wait_for_port_available(address: str, port: int, *, attempts: int = 20) -> None:
    last_error: OSError | None = None
    for attempt in range(attempts):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Match BridgeServer.allow_reuse_address so recently closed client
            # connections in TIME_WAIT are not mistaken for an active listener.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((address, port))
            return
        except OSError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.25)
        finally:
            probe.close()
    raise RuntimeError(f"{address}:{port} is already in use: {last_error}") from last_error


def main() -> int:
    if os.geteuid() != 0:
        print("Run this installer as root (sudo python3 ...).", file=sys.stderr)
        return 1
    if platform.system() != "Linux" or not Path("/run/systemd/system").exists():
        print("This installer requires Linux with systemd.", file=sys.stderr)
        return 1
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.", file=sys.stderr)
        return 1
    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / ".env"
    try:
        run(["docker", "info"])
        address = discover_address()
        check_local_ollama()

        # Stop only our own existing service so idempotent updates can check the port.
        run(["systemctl", "stop", SERVICE], check=False)
        wait_for_port_available(address, BRIDGE_PORT)

        INSTALL_DIR.mkdir(mode=0o755, parents=True, exist_ok=True)
        CONFIG_DIR.mkdir(mode=0o750, parents=True, exist_ok=True)
        uid, gid = ensure_service_user()
        for name in ("lingoveil_ollama_bridge.py", "discover_lingoveil_ollama_bridge_address.py"):
            target = INSTALL_DIR / name
            shutil.copyfile(project_root / "scripts" / name, target)
            target.chmod(0o755)
            os.chown(target, 0, 0)

        if TOKEN_FILE.exists():
            token = TOKEN_FILE.read_text(encoding="utf-8").strip()
            if not token:
                raise RuntimeError(f"Existing token file is empty: {TOKEN_FILE}")
        else:
            token = secrets.token_urlsafe(32)
            atomic_write(TOKEN_FILE, token + "\n", 0o640)
        os.chown(CONFIG_DIR, 0, gid)
        os.chmod(CONFIG_DIR, 0o750)
        os.chown(TOKEN_FILE, 0, gid)
        os.chmod(TOKEN_FILE, 0o640)

        existing_env = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        env_owner = env_path.stat() if env_path.exists() else None
        atomic_write(env_path, managed_env(existing_env, token), 0o600)
        if env_owner is not None:
            os.chown(env_path, env_owner.st_uid, env_owner.st_gid)
        atomic_write(UNIT_FILE, unit_text(sys.executable), 0o644)
        run(["systemctl", "daemon-reload"])
        run(["systemctl", "enable", "--now", SERVICE])
        bridge_request(address, token)
        docker_tested = bridge_request_from_docker(token)
    except (DiscoveryError, RuntimeError, OSError, subprocess.CalledProcessError, urllib.error.URLError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        return 1

    print("LingoVeil Ollama Bridge installed successfully.\n")
    print("Bridge URL:\nhttp://host.docker.internal:11435\n")
    print("Ollama remains bound to:\n127.0.0.1:11434\n")
    print(f"Detected Docker host-gateway: {address}")
    print(f"Docker-to-bridge test: {'successful' if docker_tested else 'skipped (image not built)'}")
    print("\nNext: restart LingoVeil and use Options → Models → Ollama → Test connection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
