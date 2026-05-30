"""Shared pytest fixtures for NetSentry tests."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from backend.models import Alert, AlertLevel, Snapshot, SocketEntry


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
