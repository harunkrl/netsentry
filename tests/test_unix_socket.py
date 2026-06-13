"""Tests for backend.writers.unix_socket — Unix domain socket server."""

from __future__ import annotations

import contextlib
import json
import os
import socket
import time
from pathlib import Path

import pytest
from backend.writers.unix_socket import UnixSocketServer, send_command

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def socket_path(tmp_path: Path) -> str:
    """Return a unique socket path inside tmp_path."""
    return str(tmp_path / "test-kportwatch.sock")


@pytest.fixture
def server(socket_path: str) -> UnixSocketServer:
    """Return a started UnixSocketServer bound to socket_path."""
    # Patch SOCKET_PATH so server uses our temp path
    import backend.writers.unix_socket as us_mod

    original = us_mod.SOCKET_PATH
    us_mod.SOCKET_PATH = socket_path
    srv = UnixSocketServer()
    srv.start()
    yield srv
    srv.stop()
    us_mod.SOCKET_PATH = original


@pytest.fixture
def client_sock(server: UnixSocketServer) -> socket.socket:
    """Return a connected broadcast client socket, auto-closed after test."""
    import backend.writers.unix_socket as us_mod

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(us_mod.SOCKET_PATH)
    time.sleep(0.5)  # wait for accept loop to probe and register as broadcast client
    yield s
    with contextlib.suppress(OSError):
        s.close()


# ── Server lifecycle tests ────────────────────────────────────────


class TestServerLifecycle:
    def test_start_creates_socket_file(self, server: UnixSocketServer, socket_path: str):
        assert os.path.exists(socket_path)

    def test_start_sets_running(self, server: UnixSocketServer):
        assert server.running is True

    def test_stop_clears_running(self, server: UnixSocketServer):
        server.stop()
        assert server.running is False

    def test_stop_removes_socket_file(self, server: UnixSocketServer, socket_path: str):
        server.stop()
        assert not os.path.exists(socket_path)

    def test_double_stop_no_error(self, server: UnixSocketServer):
        server.stop()
        server.stop()  # should not raise

    def test_start_removes_stale_socket(self, socket_path: str):
        """If a stale socket file exists, start() should remove it."""
        # Create a stale file
        with open(socket_path, "w") as f:
            f.write("stale")
        assert os.path.exists(socket_path)

        import backend.writers.unix_socket as us_mod

        original = us_mod.SOCKET_PATH
        us_mod.SOCKET_PATH = socket_path
        srv = UnixSocketServer()
        srv.start()
        try:
            # Should still work — old file removed and new socket bound
            assert srv.running is True
            assert os.path.exists(socket_path)
        finally:
            srv.stop()
            us_mod.SOCKET_PATH = original


# ── Client connection tests ───────────────────────────────────────


class TestClientConnection:
    def test_client_connects(self, client_sock: socket.socket):
        """Client socket should be connected."""
        assert client_sock.fileno() != -1

    def test_connected_client_registered(
        self, server: UnixSocketServer, client_sock: socket.socket
    ):
        """Server should have the client in its clients list."""
        time.sleep(0.5)
        assert len(server.clients) >= 1

    def test_multiple_clients(self, server: UnixSocketServer, socket_path: str):
        """Multiple clients should all be registered."""
        import backend.writers.unix_socket as us_mod

        clients = []
        for _ in range(3):
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(us_mod.SOCKET_PATH)
            clients.append(s)
        time.sleep(1.5)  # accept loop probes each client ~0.3s
        assert len(server.clients) == 3
        for s in clients:
            s.close()


# ── Broadcast tests ───────────────────────────────────────────────


class TestBroadcast:
    def test_broadcast_sends_data_to_client(
        self, server: UnixSocketServer, client_sock: socket.socket
    ):
        payload = '{"test": true}'
        server.broadcast(payload)
        time.sleep(0.1)
        data = client_sock.recv(4096).decode("utf-8")
        assert data.strip() == payload

    def test_broadcast_adds_newline(self, server: UnixSocketServer, client_sock: socket.socket):
        server.broadcast("{}")
        time.sleep(0.1)
        data = client_sock.recv(4096).decode("utf-8")
        assert data.endswith("\n")

    def test_broadcast_to_multiple_clients(self, server: UnixSocketServer, socket_path: str):
        import backend.writers.unix_socket as us_mod

        clients = []
        for _ in range(3):
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(us_mod.SOCKET_PATH)
            clients.append(s)
        time.sleep(1.5)  # accept loop probes each client ~0.3s

        payload = '{"msg": "hello"}'
        server.broadcast(payload)
        time.sleep(0.1)

        for s in clients:
            data = s.recv(4096).decode("utf-8").strip()
            assert data == payload
            s.close()

    def test_broadcast_no_clients_no_error(self, server: UnixSocketServer):
        """Broadcast with zero clients should not raise."""
        server.broadcast('{"test": true}')

    def test_dead_client_cleaned_up(self, server: UnixSocketServer, socket_path: str):
        """A disconnected client should be removed on next broadcast."""
        import backend.writers.unix_socket as us_mod

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(us_mod.SOCKET_PATH)
        time.sleep(0.5)
        assert len(server.clients) == 1

        # Kill the client
        s.close()
        time.sleep(0.05)

        # Broadcast should detect dead client and clean up
        server.broadcast('{"cleanup": true}')
        time.sleep(0.1)
        assert len(server.clients) == 0


# ── Command request/response tests ───────────────────────────────


class TestCommandHandling:
    def test_command_handler_called(self, server: UnixSocketServer, socket_path: str):
        """Command handler receives and processes commands."""
        import backend.writers.unix_socket as us_mod

        received = []

        def handler(cmd):
            received.append(cmd)
            return {"status": "ok", "message": "done"}

        server.set_command_handler(handler)

        # Send command directly via socket
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(us_mod.SOCKET_PATH)
        s.sendall(json.dumps({"command": "test"}).encode() + b"\n")
        time.sleep(0.2)

        resp_data = s.recv(4096).decode().strip()
        resp = json.loads(resp_data)
        assert resp["status"] == "ok"
        assert len(received) == 1
        assert received[0]["command"] == "test"
        s.close()

    def test_command_response_without_handler(self, server: UnixSocketServer, socket_path: str):
        """Without a handler, commands get an error response."""
        import backend.writers.unix_socket as us_mod

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(us_mod.SOCKET_PATH)
        s.sendall(json.dumps({"command": "test"}).encode() + b"\n")
        time.sleep(0.2)

        resp_data = s.recv(4096).decode().strip()
        resp = json.loads(resp_data)
        assert resp["status"] == "error"
        assert "No command handler" in resp["message"]
        s.close()

    def test_command_handler_exception(self, server: UnixSocketServer, socket_path: str):
        """Handler exceptions are caught and returned as errors."""
        import backend.writers.unix_socket as us_mod

        def bad_handler(cmd):
            raise RuntimeError("boom")

        server.set_command_handler(bad_handler)

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(us_mod.SOCKET_PATH)
        s.sendall(json.dumps({"command": "fail"}).encode() + b"\n")
        time.sleep(0.2)

        resp_data = s.recv(4096).decode().strip()
        resp = json.loads(resp_data)
        assert resp["status"] == "error"
        assert resp["message"] == "Internal server error"
        s.close()


class TestSendCommand:
    """Tests for the send_command client helper."""

    def test_send_command_gets_response(self, server: UnixSocketServer, socket_path: str):
        """send_command sends a command and returns the response."""
        server.set_command_handler(lambda cmd: {"status": "ok", "echo": cmd.get("command")})
        resp = send_command({"command": "hello"}, timeout=2.0)
        assert resp["status"] == "ok"
        assert resp["echo"] == "hello"

    def test_send_command_no_server_raises(self, tmp_path: Path):
        """send_command raises ConnectionError if server is not running."""
        import backend.writers.unix_socket as us_mod

        original = us_mod.SOCKET_PATH
        us_mod.SOCKET_PATH = str(tmp_path / "nonexistent.sock")
        try:
            with pytest.raises(ConnectionError):
                send_command({"command": "test"}, timeout=1.0)
        finally:
            us_mod.SOCKET_PATH = original
