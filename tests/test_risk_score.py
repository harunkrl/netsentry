"""Tests for backend.risk_score — Port risk scoring."""
from __future__ import annotations

from backend.models import SocketEntry
from backend.risk_score import calculate_risk_score, score_entries

# ── Fixtures ──────────────────────────────────────────────────────

def _make_entry(port: int, cmdline: str = "/usr/bin/app", **kwargs) -> SocketEntry:
    return SocketEntry(
        proto="tcp", local_ip="0.0.0.0", local_port=port,
        remote_ip="0.0.0.0", remote_port=0, state="LISTEN",
        state_code="0A", uid=0, inode=99999,
        process_name="test", cmdline=cmdline, **kwargs,
    )


# ── Risk score tests ──────────────────────────────────────────────

class TestRiskScore:
    def test_malicious_port_gets_high_score(self):
        entry = _make_entry(port=4444)
        result = calculate_risk_score(entry)
        assert result["score"] >= 80
        assert "malicious_port" in result["factors"]

    def test_blacklisted_port_gets_high_score(self):
        entry = _make_entry(port=9090)
        result = calculate_risk_score(entry, port_blacklist={9090})
        assert result["score"] >= 60
        assert "blacklisted" in result["factors"]

    def test_privileged_unknown_port(self):
        entry = _make_entry(port=500)
        result = calculate_risk_score(entry)
        assert result["score"] >= 40
        assert "privileged_unknown" in result["factors"]

    def test_known_safe_port_low_score(self):
        entry = _make_entry(port=22, cmdline="/usr/sbin/sshd")
        result = calculate_risk_score(entry, baseline_ports={22})
        assert result["score"] == 0
        assert result["factors"] == []

    def test_not_in_baseline(self):
        entry = _make_entry(port=8080, cmdline="/app")
        result = calculate_risk_score(entry, baseline_ports={22, 80})
        assert "not_in_baseline" in result["factors"]

    def test_no_cmdline_adds_score(self):
        entry = _make_entry(port=8080, cmdline="")
        result = calculate_risk_score(entry)
        assert "no_cmdline" in result["factors"]
        assert result["score"] >= 15

    def test_ephemeral_port_adds_score(self):
        entry = _make_entry(port=55000, cmdline="/app")
        result = calculate_risk_score(entry, baseline_ports={55000})
        assert "ephemeral_port" in result["factors"]

    def test_score_capped_at_100(self):
        entry = _make_entry(port=4444, cmdline="")  # malicious + no_cmdline
        result = calculate_risk_score(entry, port_blacklist={4444})
        assert result["score"] <= 100

    def test_multiple_factors_stack(self):
        entry = _make_entry(port=500, cmdline="")  # privileged + no_cmdline
        result = calculate_risk_score(entry)
        assert len(result["factors"]) >= 2

    def test_returns_dict_structure(self):
        entry = _make_entry(port=22)
        result = calculate_risk_score(entry)
        assert "score" in result
        assert "factors" in result
        assert isinstance(result["score"], int)
        assert isinstance(result["factors"], list)


# ── score_entries tests ────────────────────────────────────────────

class TestScoreEntries:
    def test_sorted_by_risk_descending(self):
        entries = [
            _make_entry(port=22, cmdline="/sshd"),      # safe
            _make_entry(port=4444, cmdline="/evil"),      # malicious
            _make_entry(port=500, cmdline=""),            # privileged + no cmdline
        ]
        scored = score_entries(entries, baseline_ports={22, 500})
        scores = [s["score"] for _, s in scored]
        # Should be sorted high to low
        assert scores == sorted(scores, reverse=True)

    def test_empty_list(self):
        scored = score_entries([])
        assert scored == []
