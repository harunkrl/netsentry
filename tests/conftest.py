"""Shared pytest fixtures for NetSentry tests."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from backend.models import Alert, AlertLevel, InterfaceStats, ProcessInfo, Snapshot, SocketEntry


# ── File paths ─────────────────────────────────────────────────

@pytest.fixture
def tmp_data_file(tmp_path: Path) -> Path:
    """Return a path inside tmp_path suitable for netsentry data I/O."""
    return tmp_path / "netsentry-data.json"


# ── Model instances ────────────────────────────────────────────

@pytest.fixture
def sample_socket_entry() -> SocketEntry:
    """Return a SocketEntry with realistic values (listening TCP on port 22)."""
    return SocketEntry(
        proto="tcp",
        local_ip="0.0.0.0",
        local_port=22,
        remote_ip="0.0.0.0",
        remote_port=0,
        state="LISTEN",
        state_code="0A",
        uid=0,
        inode=12345,
        pid=1,
        process_name="sshd",
        cmdline="/usr/sbin/sshd -D",
    )


@pytest.fixture
def sample_alert() -> Alert:
    """Return an Alert with WARNING level."""
    return Alert(
        level=AlertLevel.WARNING,
        port=500,
        proto="tcp",
        process_name="unknown",
        pid=None,
        message="Unknown privileged port 500 detected",
        timestamp=time.time(),
    )


@pytest.fixture
def sample_snapshot(
    sample_socket_entry: SocketEntry,
    sample_alert: Alert,
) -> Snapshot:
    """Return a Snapshot with 2 listening + 1 established + 1 alert."""
    established = SocketEntry(
        proto="tcp",
        local_ip="192.168.1.10",
        local_port=44532,
        remote_ip="142.250.80.14",
        remote_port=443,
        state="ESTABLISHED",
        state_code="01",
        uid=1000,
        inode=67890,
        pid=1234,
        process_name="firefox",
        cmdline="/usr/lib/firefox/firefox",
        remote_country="United States",
        remote_country_code="US",
        remote_city="Mountain View",
        remote_lat=37.386,
        remote_lon=-122.084,
    )
    listening_extra = SocketEntry(
        proto="tcp",
        local_ip="0.0.0.0",
        local_port=80,
        remote_ip="0.0.0.0",
        remote_port=0,
        state="LISTEN",
        state_code="0A",
        uid=0,
        inode=11111,
        pid=2,
        process_name="nginx",
        cmdline="/usr/sbin/nginx",
    )
    return Snapshot(
        timestamp=time.time(),
        poll_interval_ms=2000,
        listening=[sample_socket_entry, listening_extra],
        established=[established],
        alerts=[sample_alert],
        summary={
            "total_listening": 2,
            "total_established": 1,
            "alert_count": 1,
        },
    )


# ── /proc/net content strings ─────────────────────────────────

@pytest.fixture
def proc_tcp_content() -> str:
    """Return a realistic /proc/net/tcp content string (header + 3 data lines).

    Line 0: header
    Line 1: 127.0.0.1:80 LISTEN (inode 12345)
    Line 2: 0.0.0.0:22 LISTEN (inode 67890)
    Line 3: inode=0 entry (should be skipped by parser)
    """
    return (
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 0100007F:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12345 1 0000000000000000 100 0 0 10 0\n"
        "   1: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 67890 1 0000000000000000 100 0 0 10 0\n"
        "   2: 0100007F:0035 0100007F:0035 01 00000000:00000000 00:00000000 00000000  1000        0 0 1 0000000000000000 100 0 0 10 0\n"
    )


# ── /proc/net/dev content strings ──────────────────────────────

@pytest.fixture
def proc_net_dev_content() -> str:
    """Return a realistic /proc/net/dev content string (2 header + 3 data lines).

    Interfaces: lo (loopback), wlan0, eth0.
    Parser should skip lo and return wlan0 + eth0.
    """
    return (
        "Inter-|   Receive                                                |  Transmit\n"
        " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
        "    lo:   97937    1151    0    0    0     0          0         0    97937    1151    0    0    0     0       0          0\n"
        "  wlan0: 1493759338 1197161    0    0    0     0          0         0 201984858  354400    0   39    0     0       0          0\n"
        "  eth0: 500000000 800000    1    2    0     0          0         0 300000000  600000    3    4    0     0       0          0\n"
    )


@pytest.fixture
def sample_interface_stats() -> InterfaceStats:
    """Return an InterfaceStats with wlan0 values."""
    return InterfaceStats(
        interface="wlan0",
        rx_bytes=1493759338,
        tx_bytes=201984858,
        rx_packets=1197161,
        tx_packets=354400,
        rx_errors=0,
        tx_errors=0,
        rx_drops=0,
        tx_drops=39,
        rx_rate=1024.0,
        tx_rate=512.0,
    )


# ── Process tree fixtures ─────────────────────────────────────

@pytest.fixture
def sample_inode_map() -> dict:
    """Return a sample inode→(pid, name, cmdline) mapping.

    PIDs 1 and 3034 own sockets (have network activity).
    """
    return {
        12345: (1, "systemd", "/sbin/init"),
        67890: (3034, "firefox", "/usr/lib/firefox/firefox"),
    }


@pytest.fixture
def sample_process_tree():
    """Return a sample process tree dict {pid: ProcessInfo}.

    Tree structure:
        1 (systemd) → 828 (firewalld), 2420 (sddm) → 3034 (firefox)
        2 (kthreadd) → 100 (kworker)
    """
    return {
        1: ProcessInfo(pid=1, ppid=0, name="systemd", cmdline="/sbin/init", state="S", uid=0,
                       has_network=True, children=[828, 2420]),
        2: ProcessInfo(pid=2, ppid=0, name="kthreadd", cmdline="", state="S", uid=0,
                       has_network=False, children=[100]),
        100: ProcessInfo(pid=100, ppid=2, name="kworker/0:1", cmdline="", state="S", uid=0,
                         has_network=False, children=[]),
        828: ProcessInfo(pid=828, ppid=1, name="firewalld", cmdline="/usr/bin/python3 /usr/bin/firewalld", state="S", uid=0,
                         has_network=False, children=[]),
        2420: ProcessInfo(pid=2420, ppid=1, name="sddm", cmdline="/usr/bin/sddm", state="S", uid=0,
                          has_network=False, children=[3034]),
        3034: ProcessInfo(pid=3034, ppid=2420, name="firefox", cmdline="/usr/lib/firefox/firefox", state="S", uid=1000,
                          has_network=True, children=[]),
    }


# ── GeoIP fixtures ──────────────────────────────────────────────

@pytest.fixture
def sample_geo_entry() -> SocketEntry:
    """Return a SocketEntry with populated GeoIP fields (established, non-local)."""
    return SocketEntry(
        proto="tcp",
        local_ip="192.168.1.10",
        local_port=54321,
        remote_ip="142.250.80.14",
        remote_port=443,
        state="ESTABLISHED",
        state_code="01",
        uid=1000,
        inode=99999,
        pid=1234,
        process_name="firefox",
        cmdline="/usr/lib/firefox/firefox",
        remote_hostname="sea30s12-in-f14.1e100.net",
        remote_country="United States",
        remote_country_code="US",
        remote_city="Mountain View",
        remote_lat=37.386,
        remote_lon=-122.084,
    )
