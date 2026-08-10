#!/usr/bin/env python3
"""Resolve Docker's host-gateway address without exposing it to the bridge process."""

from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

DEFAULT_DOCKER_CONFIG = Path("/etc/docker/daemon.json")


class DiscoveryError(RuntimeError):
    pass


def _ipv4(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.version == 4 and not address.is_unspecified:
            result.append(str(address))
    return result


def configured_host_gateways(path: Path = DEFAULT_DOCKER_CONFIG) -> list[str]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoveryError(f"Invalid Docker daemon configuration {path}: {exc}") from exc
    configured = data.get("host-gateway-ips", data.get("host-gateway-ip", []))
    if isinstance(configured, str):
        configured = [configured]
    if not isinstance(configured, list):
        raise DiscoveryError("Docker host-gateway-ips must be a string or list")
    return _ipv4([str(value) for value in configured])


def dockerd_cli_host_gateways(proc_root: Path = Path("/proc")) -> list[str]:
    values: list[str] = []
    try:
        process_dirs = list(proc_root.iterdir())
    except OSError:
        return []
    for process_dir in process_dirs:
        if not process_dir.name.isdigit():
            continue
        try:
            args = (process_dir / "cmdline").read_bytes().decode(errors="replace").split("\0")
        except OSError:
            continue
        if not args or Path(args[0]).name != "dockerd":
            continue
        for index, argument in enumerate(args):
            if argument.startswith("--host-gateway-ip="):
                values.append(argument.partition("=")[2])
            elif argument == "--host-gateway-ip" and index + 1 < len(args):
                values.append(args[index + 1])
    return _ipv4(values)


def bridge_gateways(inspect_data: object) -> list[str]:
    networks = inspect_data if isinstance(inspect_data, list) else [inspect_data]
    values: list[str] = []
    for network in networks:
        if not isinstance(network, dict):
            continue
        ipam = network.get("IPAM") or {}
        configs = ipam.get("Config") or []
        for config in configs:
            if isinstance(config, dict) and config.get("Gateway"):
                values.append(str(config["Gateway"]))
    return _ipv4(values)


def _docker_json(args: list[str], runner: Callable[..., subprocess.CompletedProcess[str]]) -> object:
    try:
        completed = runner(
            ["docker", *args], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DiscoveryError(f"Docker is not available: {exc}") from exc
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise DiscoveryError(f"Docker command failed: {detail}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise DiscoveryError("Docker returned invalid JSON") from exc


def running_lingoveil_resolutions(
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[str]:
    try:
        completed = runner(
            [
                "docker", "ps", "--filter",
                "label=com.docker.compose.service=lingoveil-live", "--format", "{{.ID}}",
            ], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode:
        return []
    resolved: list[str] = []
    for container_id in completed.stdout.split():
        probe = runner(
            ["docker", "exec", container_id, "getent", "ahostsv4", "host.docker.internal"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if probe.returncode == 0:
            resolved.extend(line.split()[0] for line in probe.stdout.splitlines() if line.split())
    return _ipv4(resolved)


def discover_address(
    *,
    docker_config: Path = DEFAULT_DOCKER_CONFIG,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    verify_running_container: bool = True,
) -> str:
    explicit = configured_host_gateways(docker_config) + dockerd_cli_host_gateways()
    inspect_data = _docker_json(["network", "inspect", "bridge"], runner)
    defaults = bridge_gateways(inspect_data)
    candidates = explicit or defaults
    unique = sorted(set(candidates))
    if len(unique) != 1:
        raise DiscoveryError(
            "Docker host-gateway IPv4 address is missing or ambiguous: "
            + (", ".join(unique) if unique else "no gateway found")
        )
    selected = unique[0]
    if verify_running_container:
        actual = sorted(set(running_lingoveil_resolutions(runner)))
        if actual and actual != [selected]:
            raise DiscoveryError(
                "host.docker.internal resolves differently in the running LingoVeil "
                f"container ({', '.join(actual)}) than discovery ({selected})"
            )
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-container-check", action="store_true")
    args = parser.parse_args()
    try:
        address = discover_address(verify_running_container=not args.no_container_check)
        if args.output:
            args.output.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            temporary = args.output.with_suffix(".tmp")
            temporary.write_text(address + "\n", encoding="ascii")
            temporary.chmod(0o644)
            temporary.replace(args.output)
        else:
            print(address)
        return 0
    except DiscoveryError as exc:
        print(f"LingoVeil Ollama Bridge discovery failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
