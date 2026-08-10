import http.client
import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import discover_lingoveil_ollama_bridge_address as discovery
import install_lingoveil_ollama_bridge as installer
import lingoveil_ollama_bridge as bridge
import uninstall_lingoveil_ollama_bridge as uninstaller

class FakeResponse:
    def __init__(self, status=200, body=b'{"models":[]}'):
        self.status = status
        self._body = body
    def getheader(self, name, default=None):
        return "application/json" if name.lower() == "content-type" else default
    def read(self, amount):
        return self._body[:amount]
class FakeConnection:
    response = FakeResponse()

    error = None
    requests = []
    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock = None
    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers))

        if self.error:
            raise self.error
    def getresponse(self):
        return self.response
    def close(self):
        pass
class BridgeTests(unittest.TestCase):
    def setUp(self):
        FakeConnection.response = FakeResponse()

        FakeConnection.error = None
        FakeConnection.requests = []
        self.server = bridge.BridgeServer(("127.0.0.1", 0), "correct-token")

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

        self.thread.start()

    def tearDown(self):
        self.server.shutdown()

        self.server.server_close()

        self.thread.join()

    def request(self, method, path, *, token="correct-token", body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)

        request_headers = dict(headers or {})

        if token is not None:
            request_headers["Authorization"] = f"Bearer {token}"
        with patch.object(bridge.http.client, "HTTPConnection", FakeConnection):
            connection.request(method, path, body=body, headers=request_headers)

            response = connection.getresponse()

            data = response.read()

        connection.close()

        return response.status, data
    def test_authentication(self):
        self.assertEqual(self.request("GET", "/api/tags")[0], 200)

        self.assertEqual(self.request("GET", "/api/tags", token=None)[0], 401)

        self.assertEqual(self.request("GET", "/api/tags", token="wrong")[0], 401)

    def test_exact_allowlist(self):
        payload = b"{}"
        json_headers = {"Content-Type": "application/json"}

        self.assertEqual(self.request("GET", "/api/tags")[0], 200)

        self.assertEqual(self.request("POST", "/api/show", body=payload, headers=json_headers)[0], 200)

        self.assertEqual(self.request("POST", "/api/chat", body=payload, headers=json_headers)[0], 200)

        for method, path in (
            ("POST", "/api/pull"), ("GET", "/unknown"),
            ("GET", "/api/chat"), ("POST", "/api/chat/"),
            ("POST", "/api//chat"), ("POST", "/api/%63hat"),
            ("GET", "/api/tags?x=1"),
        ):
            self.assertEqual(self.request(method, path, body=payload, headers=json_headers)[0], 403)

    def test_request_validation_and_header_filtering(self):
        self.assertEqual(self.request("POST", "/api/chat", body=b"{}", headers={})[0], 415)

        status, _ = self.request(
            "POST", "/api/chat", body=b"{}",
            headers={"Content-Type": "application/json", "Transfer-Encoding": "chunked"},
        )

        self.assertEqual(status, 400)

        self.request(
            "POST", "/api/chat", body=b"{}",
            headers={"Content-Type": "application/json", "X-Forwarded-For": "evil"},
        )

        upstream_headers = FakeConnection.requests[-1][3]
        self.assertEqual(set(upstream_headers), {"Host", "Content-Type", "Content-Length"})

    def test_missing_and_oversize_content_length_with_raw_socket(self):
        def raw(extra):
            sock = socket.create_connection(("127.0.0.1", self.server.server_port), timeout=2)

            request = (
                "POST /api/chat HTTP/1.1\r\nHost: x\r\n"
                "Authorization: Bearer correct-token\r\nContent-Type: application/json\r\n"
                + extra + "\r\n"
            ).encode()

            sock.sendall(request)

            response = sock.recv(512)

            sock.close()

            return int(response.split(b" ", 2)[1])

        self.assertEqual(raw(""), 411)

        self.assertEqual(raw(f"Content-Length: {bridge.MAX_REQUEST_BODY + 1}\r\n"), 413)

    def test_upstream_errors_and_response_limit(self):
        FakeConnection.error = ConnectionRefusedError()

        self.assertEqual(self.request("GET", "/api/tags")[0], 502)

        FakeConnection.error = socket.timeout()

        self.assertEqual(self.request("GET", "/api/tags")[0], 502)

        FakeConnection.error = None
        FakeConnection.response = FakeResponse(body=b"x" * (bridge.MAX_RESPONSE_BODY + 1))

        self.assertEqual(self.request("GET", "/api/tags")[0], 502)

class DiscoveryTests(unittest.TestCase):
    @staticmethod
    def completed(stdout="", stderr="", returncode=0):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def test_default_bridge_ipv4_and_multiple_ipam(self):
        data = [{"IPAM": {"Config": [
            {"Subnet": "fd00::/64", "Gateway": "fd00::1"},
            {"Subnet": "172.31.0.0/16", "Gateway": "172.31.0.1"},
        ]}}]
        self.assertEqual(discovery.bridge_gateways(data), ["172.31.0.1"])

        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            def runner(args, **kwargs):
                if args[1:3] == ["network", "inspect"]:
                    return self.completed(json.dumps(data))

                return self.completed("")

            self.assertEqual(
                discovery.discover_address(
                    docker_config=missing, runner=runner, verify_running_container=False
                ), "172.31.0.1"
            )

    def test_no_gateway_ambiguity_conflict_and_docker_failure(self):
        self.assertEqual(discovery.bridge_gateways([{"IPAM": {"Config": []}}]), [])

        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "daemon.json"
            config.write_text('{"host-gateway-ips":["172.17.0.1","172.18.0.1"]}')

            runner = lambda args, **kwargs: self.completed('[{"IPAM":{"Config":[]}}]')

            with self.assertRaises(discovery.DiscoveryError):
                discovery.discover_address(
                    docker_config=config, runner=runner, verify_running_container=False
                )

            failing = lambda args, **kwargs: self.completed("", "daemon unavailable", 1)

            with self.assertRaises(discovery.DiscoveryError):
                discovery.discover_address(
                    docker_config=Path(directory) / "none", runner=failing,
                    verify_running_container=False,
                )

    def test_running_container_conflict(self):
        data = '[{"IPAM":{"Config":[{"Gateway":"172.17.0.1"}]}}]'
        def runner(args, **kwargs):
            if args[1:3] == ["network", "inspect"]:
                return self.completed(data)

            if args[1] == "ps":
                return self.completed("abc\n")

            if args[1] == "exec":
                return self.completed("172.19.0.1 STREAM host.docker.internal\n")

            return self.completed("")

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(discovery.DiscoveryError):
                discovery.discover_address(
                    docker_config=Path(directory) / "none", runner=runner
                )

class InstallerEnvTests(unittest.TestCase):
    def test_env_is_idempotent_and_uninstall_preserves_other_values(self):
        original = "KEEP=yes\n"
        first = installer.managed_env(original, "token-one")

        second = installer.managed_env(first, "token-one")

        self.assertEqual(first, second)

        self.assertEqual(second.count("LINGOVEIL_OLLAMA_BRIDGE_TOKEN="), 1)

        removed = installer.managed_env(second, None)

        self.assertEqual(removed, original)

    def test_bridge_readiness_retries_connection_refused(self):
        class Response:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return b'{"models":[]}'
        responses = [
            installer.urllib.error.URLError(ConnectionRefusedError()),
            Response(),
        ]
        def urlopen(*args, **kwargs):
            result = responses.pop(0)

            if isinstance(result, BaseException):
                raise result
            return result
        with patch.object(installer.urllib.request, "urlopen", urlopen), patch.object(
            installer.time, "sleep", lambda _: None
        ):
            installer.bridge_request("172.17.0.1", "secret", attempts=2)

        self.assertEqual(responses, [])

    def test_port_check_retries_while_previous_service_stops(self):
        class Probe:
            attempts = 0
            def bind(self, address):
                self.attempts += 1
                if self.attempts == 1:
                    raise OSError(98, "in use")

            def close(self):
                pass
        probe = Probe()

        with patch.object(installer.socket, "socket", lambda *args: probe), patch.object(
            installer.time, "sleep", lambda _: None
        ):
            installer.wait_for_port_available("172.17.0.1", 11435, attempts=2)

        self.assertEqual(probe.attempts, 2)

    def test_docker_test_uses_running_lingoveil_container(self):
        inspect = subprocess.CompletedProcess([], 0, "true\n", "")

        success = subprocess.CompletedProcess([], 0, "", "")

        with patch.object(installer, "run", return_value=inspect), patch.object(
            installer.subprocess, "run", return_value=success
        ) as execute:
            self.assertTrue(installer.bridge_request_from_docker("secret"))

        command = execute.call_args.args[0]
        self.assertEqual(command[:5], [
            "docker", "exec", "-e", "LINGOVEIL_BRIDGE_TEST_TOKEN", "lingoveil-live",
        ])

        self.assertNotIn("docker run", " ".join(command))

    def test_docker_test_skips_when_lingoveil_is_not_running(self):
        stopped = subprocess.CompletedProcess([], 0, "false\n", "")

        with patch.object(installer, "run", return_value=stopped), patch.object(
            installer.subprocess, "run"
        ) as execute:
            self.assertFalse(installer.bridge_request_from_docker("secret"))

        execute.assert_not_called()

class UninstallerTests(unittest.TestCase):
    def test_stop_is_verified_before_files_are_removed(self):
        stopped = subprocess.CompletedProcess([], 0, "", "")

        with tempfile.TemporaryDirectory() as directory, patch.object(
            uninstaller, "RUNTIME_ADDRESS", Path(directory) / "missing"
        ), patch.object(uninstaller, "discover_address", return_value="172.17.0.1"), patch.object(
            uninstaller.subprocess, "run", return_value=stopped
        ) as execute, patch.object(uninstaller, "wait_for_port_available") as wait:
            uninstaller.stop_installed_service("loaded")

        self.assertEqual(execute.call_args_list[0].args[0], [
            "systemctl", "stop", uninstaller.SERVICE,
        ])

        wait.assert_called_once_with("172.17.0.1", uninstaller.BRIDGE_PORT, attempts=40)

    def test_failed_stop_aborts_before_port_check(self):
        failed = subprocess.CompletedProcess([], 1, "", "stop failed")

        with patch.object(uninstaller.subprocess, "run", return_value=failed), patch.object(
            uninstaller, "wait_for_port_available"
        ) as wait:
            with self.assertRaisesRegex(RuntimeError, "Could not stop"):
                uninstaller.stop_installed_service("loaded")

        wait.assert_not_called()

if __name__ == "__main__":
    unittest.main()
