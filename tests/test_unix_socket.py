"""Tests for backend.writers.unix_socket — Unix domain socket server."""
from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

import pytest

from backend.writers.unix_socket import UnixSocketServer


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def socket_path(tmp_path: Path) -> str:
    """Return a unique socket path inside tmp_path."""
    return str(tmp_path / "test-netsentry.sock")


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
    """Return a connected client socket, auto-closed after test."""
    import backend.writers.unix_socket as us_mod
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(us_mod.SOCKET_PATH)
    time.sleep(0.05)  # let accept loop pick it up
    yield s
    try:
        s.close()
    except OSError:
        pass


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

    def test_connected_client_registered(self, server: UnixSocketServer, client_sock: socket.socket):
        """Server should have the client in its clients list."""
        time.sleep(0.1)
        assert len(server.clients) >= 1

    def test_multiple_clients(self, server: UnixSocketServer, socket_path: str):
        """Multiple clients should all be registered."""
        import backend.writers.unix_socket as us_mod
        clients = []
        for _ in range(3):
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(us_mod.SOCKET_PATH)
            clients.append(s)
        time.sleep(0.1)
        assert len(server.clients) == 3
        for s in clients:
            s.close()


# ── Broadcast tests ───────────────────────────────────────────────

class TestBroadcast:
    def test_broadcast_sends_data_to_client(self, server: UnixSocketServer, client_sock: socket.socket):
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
        time.sleep(0.1)

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
        time.sleep(0.1)
        assert len(server.clients) == 1

        # Kill the client
        s.close()
        time.sleep(0.05)

        # Broadcast should detect dead client and clean up
        server.broadcast('{"cleanup": true}')
        time.sleep(0.1)
        assert len(server.clients) == 0
