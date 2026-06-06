"""KPortWatch — Tests for backend.alert_engine."""
import time

import pytest
from backend.alert_engine import AlertEngine
from backend.models import SocketEntry
from shared import MALICIOUS_PORTS, AlertLevel
from shared.config import CustomRule

# ── Helpers ────────────────────────────────────────────────────

def _make_entry(
    port: int,
    proto: str = "tcp",
    pid: int = 100,
    process_name: str = "testproc",
    cmdline: str = "/usr/bin/testproc",
    inode: int = 99999,
) -> SocketEntry:
    """Create a minimal SocketEntry for alert testing."""
    return SocketEntry(
        proto=proto,
        local_ip="0.0.0.0",
        local_port=port,
        remote_ip="0.0.0.0",
        remote_port=0,
        state="LISTEN",
        state_code="0A",
        uid=0,
        inode=inode,
        pid=pid,
        process_name=process_name,
        cmdline=cmdline,
    )


def _run_cycles(engine, entries_list, start_time):
    """Run multiple analyze cycles, advancing time.

    Args:
        engine: AlertEngine instance
        entries_list: list of entry-lists, one per cycle
        start_time: starting timestamp

    Returns:
        List of (alerts, current_time) for each cycle
    """
    results = []
    t = start_time
    for entries in entries_list:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda _t=t: _t)
            alerts = engine.analyze(entries)
        results.append((alerts, t))
        t += 1.0
    return results


# ── Rule 1: Malicious port → CRITICAL ──────────────────────────

class TestRule1MaliciousPort:
    def test_malicious_port_triggers_critical(self):
        """Port 4444 (Metasploit) should produce a CRITICAL alert."""
        engine = AlertEngine(baseline_duration=0)
        # Load a baseline so Rule 1 can fire without baseline interference
        engine._baseline_stable = True
        engine._baseline_ports = {4444}
        engine._baseline_start = time.time() - 1000

        entry = _make_entry(port=4444)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        assert len(alerts) >= 1
        crit = [a for a in alerts if a.level == AlertLevel.CRITICAL]
        assert len(crit) == 1
        assert crit[0].port == 4444
        assert "malicious" in crit[0].message.lower()

    def test_other_malicious_ports(self):
        """Various known malicious ports should trigger CRITICAL."""
        engine = AlertEngine(baseline_duration=0)
        engine._baseline_stable = True
        engine._baseline_ports = set(MALICIOUS_PORTS)
        engine._baseline_start = time.time() - 1000

        for port in [31337, 12345, 6667]:
            entry = _make_entry(port=port)
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(time, "time", lambda: 1700000000.0)
                alerts = engine.analyze([entry])
            crit = [a for a in alerts if a.level == AlertLevel.CRITICAL]
            assert len(crit) == 1, f"Port {port} should trigger CRITICAL"


# ── Rule 2: Unknown privileged port → WARNING ──────────────────

class TestRule2UnknownPrivilegedPort:
    def test_unknown_privileged_port_warning(self):
        """Port 999 (< 1024, not known-safe, not baseline) → WARNING."""
        engine = AlertEngine(baseline_duration=0)
        engine._baseline_stable = True
        engine._baseline_ports = set()
        engine._baseline_start = time.time() - 1000

        entry = _make_entry(port=999)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        warnings = [a for a in alerts if a.level == AlertLevel.WARNING]
        priv_warnings = [a for a in warnings if "privileged" in a.message.lower()]
        assert len(priv_warnings) == 1
        assert priv_warnings[0].port == 999

    def test_port_1024_not_privileged(self):
        """Port 1024 is NOT privileged and should not trigger Rule 2."""
        engine = AlertEngine(baseline_duration=0)
        engine._baseline_stable = True
        engine._baseline_ports = set()
        engine._baseline_start = time.time() - 1000

        entry = _make_entry(port=1024)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        priv_warnings = [a for a in alerts if "privileged" in a.message.lower()]
        assert len(priv_warnings) == 0


# ── Rule 3: New port after baseline → INFO ─────────────────────

class TestRule3NewPortAfterBaseline:
    def test_new_port_info_alert(self):
        """A new port seen after baseline stabilizes → INFO alert."""
        engine = AlertEngine(baseline_duration=5.0)
        t0 = 1700000000.0

        # Baseline entries
        baseline_entry = _make_entry(port=80)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0)
            engine.update_baseline([baseline_entry])

        # Simulate time passing — first check sets _last_ports = {80}
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0 + engine.baseline_duration + 1)
            engine.update_baseline([baseline_entry])

        # Second check with same ports → current_ports == _last_ports → stable
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0 + engine.baseline_duration + 2)
            engine.update_baseline([baseline_entry])

        assert engine.is_baseline_complete()

        # Now introduce a new port
        new_entry = _make_entry(port=9000)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0 + engine.baseline_duration + 2)
            alerts = engine.analyze([baseline_entry, new_entry])

        info_alerts = [a for a in alerts if a.level == AlertLevel.INFO and a.port == 9000]
        assert len(info_alerts) == 1
        assert "new listening port" in info_alerts[0].message.lower()


# ── Rule 4: Process with no cmdline → WARNING ──────────────────

class TestRule4NoCmdline:
    def test_no_cmdline_triggers_warning(self):
        """An entry with empty cmdline should trigger a WARNING."""
        engine = AlertEngine(baseline_duration=0)
        engine._baseline_stable = True
        engine._baseline_ports = {8080}
        engine._baseline_start = time.time() - 1000

        entry = _make_entry(port=8080, cmdline="")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        no_cmdline_alerts = [a for a in alerts if "no cmdline" in a.message.lower()]
        assert len(no_cmdline_alerts) == 1

    def test_none_cmdline_triggers_warning(self):
        """An entry with cmdline=None should trigger a WARNING."""
        engine = AlertEngine(baseline_duration=0)
        engine._baseline_stable = True
        engine._baseline_ports = {8080}
        engine._baseline_start = time.time() - 1000

        entry = _make_entry(port=8080, cmdline=None)
        # from_dict doesn't accept None for cmdline through _make_entry,
        # but we set it directly
        entry.cmdline = None
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        no_cmdline_alerts = [a for a in alerts if "no cmdline" in a.message.lower()]
        assert len(no_cmdline_alerts) == 1

    def test_normal_cmdline_no_warning(self):
        """An entry with a valid cmdline should not trigger Rule 4."""
        engine = AlertEngine(baseline_duration=0)
        engine._baseline_stable = True
        engine._baseline_ports = {8080}
        engine._baseline_start = time.time() - 1000

        entry = _make_entry(port=8080, cmdline="/usr/bin/app")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        no_cmdline_alerts = [a for a in alerts if "no cmdline" in a.message.lower()]
        assert len(no_cmdline_alerts) == 0


# ── Rule 5: 3+ new ports in one cycle → WARNING burst ──────────

class TestRule5Burst:
    def test_burst_three_new_ports(self):
        """3+ new ports in a single cycle should produce a burst WARNING."""
        engine = AlertEngine(baseline_duration=5.0)
        t0 = 1700000000.0

        # Baseline with no ports initially
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0)
            engine.update_baseline([])

        # Stabilize: same empty set — first check sets _last_ports = set()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0 + engine.baseline_duration + 1)
            engine.update_baseline([])

        # Second check with same ports → stable
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0 + engine.baseline_duration + 2)
            engine.update_baseline([])

        assert engine.is_baseline_complete()

        # Now introduce 3 new ports at once
        new_entries = [
            _make_entry(port=8000, inode=10001),
            _make_entry(port=8001, inode=10002),
            _make_entry(port=8002, inode=10003),
        ]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0 + engine.baseline_duration + 2)
            alerts = engine.analyze(new_entries)

        burst_alerts = [a for a in alerts if "burst" in a.message.lower()]
        assert len(burst_alerts) == 1
        assert burst_alerts[0].level == AlertLevel.WARNING
        assert "3" in burst_alerts[0].message

    def test_two_new_ports_no_burst(self):
        """2 new ports in one cycle should NOT produce a burst alert."""
        engine = AlertEngine(baseline_duration=5.0)
        t0 = 1700000000.0

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0)
            engine.update_baseline([])

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0 + engine.baseline_duration + 1)
            engine.update_baseline([])

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0 + engine.baseline_duration + 2)
            engine.update_baseline([])

        assert engine.is_baseline_complete()

        new_entries = [
            _make_entry(port=8000, inode=10001),
            _make_entry(port=8001, inode=10002),
        ]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0 + engine.baseline_duration + 2)
            alerts = engine.analyze(new_entries)

        burst_alerts = [a for a in alerts if "burst" in a.message.lower()]
        assert len(burst_alerts) == 0


# ── Baseline learning lifecycle ────────────────────────────────

class TestBaselineLearning:
    def test_not_stable_initially(self):
        """Baseline should not be stable right after creation."""
        engine = AlertEngine(baseline_duration=300.0)
        assert not engine.is_baseline_complete()

    def test_stable_after_duration_and_stable_ports(self):
        """Baseline becomes stable after duration elapses and ports are stable."""
        engine = AlertEngine(baseline_duration=5.0)
        t0 = 1700000000.0

        entry = _make_entry(port=80)

        # Cycle 1: start baseline
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0)
            engine.update_baseline([entry])
        assert not engine.is_baseline_complete()

        # Cycle 2: duration elapsed, first stability check → sets _last_ports
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0 + engine.baseline_duration + 1)
            engine.update_baseline([entry])

        # Cycle 3: same ports → current_ports == _last_ports → stable
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0 + engine.baseline_duration + 2)
            engine.update_baseline([entry])

        assert engine.is_baseline_complete()

    def test_baseline_saves_and_loads(self, tmp_path):
        """Baseline port set roundtrips through save/load."""
        baseline_file = str(tmp_path / "baseline.json")
        engine = AlertEngine(baseline_duration=5.0)
        engine._baseline_ports = {22, 80, 443}

        engine.save_baseline(baseline_file)

        engine2 = AlertEngine(baseline_duration=5.0)
        loaded = engine2.load_baseline(baseline_file)
        assert loaded is True
        assert engine2._baseline_ports == {22, 80, 443}
        assert engine2.is_baseline_complete()

    def test_load_missing_baseline_returns_false(self, tmp_path):
        """Loading a non-existent baseline file returns False."""
        engine = AlertEngine()
        result = engine.load_baseline(str(tmp_path / "missing.json"))
        assert result is False

    def test_baseline_off_by_one(self):
        """Baseline becomes stable exactly at baseline_duration + 1 cycle
        (when the second cycle with same ports confirms stability)."""
        engine = AlertEngine(baseline_duration=10.0)
        t0 = 1700000000.0
        entry = _make_entry(port=80)

        # Cycle 0: start
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0)
            engine.update_baseline([entry])
        assert not engine.is_baseline_complete()

        # Cycle at exactly baseline_duration: duration met, first measurement
        # With the fix (_last_ports=None treated as stable match), this should
        # now stabilize correctly after duration + 1 cycle
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: t0 + engine.baseline_duration)
            engine.update_baseline([entry])
        # With the fix: _last_ports is None → treated as stable → should stabilize
        assert engine.is_baseline_complete()


# ── Known-safe ports don't trigger alerts ──────────────────────

class TestKnownSafePorts:
    def test_known_safe_port_no_alert(self):
        """Known-safe ports (e.g. 22, 80, 443) should not trigger privileged-port alerts."""
        engine = AlertEngine(baseline_duration=0)
        engine._baseline_stable = True
        engine._baseline_ports = {22, 80, 443}
        engine._baseline_start = time.time() - 1000

        for port in [22, 80, 443]:
            entry = _make_entry(port=port, cmdline="/usr/sbin/sshd")
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(time, "time", lambda: 1700000000.0)
                alerts = engine.analyze([entry])

            # No WARNING for privileged port, no INFO for new port
            warning_priv = [a for a in alerts if "privileged" in a.message.lower()]
            info_new = [a for a in alerts if "new listening" in a.message.lower()]
            assert len(warning_priv) == 0, f"Port {port} should not trigger privileged-port warning"
            assert len(info_new) == 0, f"Port {port} should not trigger new-port info"


# ── Rule 0: Whitelist — port skipped entirely ────────────────────

class TestWhitelist:
    def test_whitelisted_port_no_alerts(self):
        """Whitelisted ports should produce zero alerts."""
        engine = AlertEngine(baseline_duration=0, port_whitelist={4444})
        engine._baseline_stable = True
        engine._baseline_ports = set()
        engine._baseline_start = time.time() - 1000

        entry = _make_entry(port=4444)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        assert len(alerts) == 0

    def test_whitelisted_port_overrides_malicious(self):
        """Even a malicious port is silenced if whitelisted."""
        engine = AlertEngine(baseline_duration=0, port_whitelist={4444})
        engine._baseline_stable = True
        engine._baseline_ports = set()
        engine._baseline_start = time.time() - 1000

        entry = _make_entry(port=4444)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        assert len(alerts) == 0


# ── Rule 0b: Blacklist — always CRITICAL ──────────────────────────

class TestBlacklist:
    def test_blacklisted_port_triggers_critical(self):
        """Blacklisted port should always trigger CRITICAL."""
        engine = AlertEngine(baseline_duration=0, port_blacklist={9090})
        engine._baseline_stable = True
        engine._baseline_ports = {9090}
        engine._baseline_start = time.time() - 1000

        entry = _make_entry(port=9090)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        crit = [a for a in alerts if a.level == AlertLevel.CRITICAL]
        assert len(crit) == 1
        assert "blacklisted" in crit[0].message.lower()

    def test_ip_blacklist_triggers_critical(self):
        """Connection from blacklisted IP should trigger CRITICAL."""
        engine = AlertEngine(baseline_duration=0, ip_blacklist=["10.0.0.*"])
        engine._baseline_stable = True
        engine._baseline_ports = {80}
        engine._baseline_start = time.time() - 1000

        entry = SocketEntry(
            proto="tcp", local_ip="0.0.0.0", local_port=80,
            remote_ip="10.0.0.5", remote_port=12345,
            state="ESTABLISHED", state_code="01",
            uid=1000, inode=50000, pid=1,
            process_name="test", cmdline="/test",
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        ip_alerts = [a for a in alerts if "blacklisted ip" in a.message.lower()]
        assert len(ip_alerts) == 1

    def test_ip_blacklist_no_match(self):
        """Connection from non-blacklisted IP should not trigger IP alert."""
        engine = AlertEngine(baseline_duration=0, ip_blacklist=["10.0.0.*"])
        engine._baseline_stable = True
        engine._baseline_ports = {80}
        engine._baseline_start = time.time() - 1000

        entry = SocketEntry(
            proto="tcp", local_ip="0.0.0.0", local_port=80,
            remote_ip="192.168.1.5", remote_port=12345,
            state="ESTABLISHED", state_code="01",
            uid=1000, inode=50000, pid=1,
            process_name="test", cmdline="/test",
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        ip_alerts = [a for a in alerts if "blacklisted ip" in a.message.lower()]
        assert len(ip_alerts) == 0


# ── Rule 6: Custom rules ──────────────────────────────────────────

class TestCustomRules:
    def _stable_engine(self, **kwargs) -> AlertEngine:
        engine = AlertEngine(baseline_duration=0, **kwargs)
        engine._baseline_stable = True
        engine._baseline_ports = {8080}
        engine._baseline_start = time.time() - 1000
        return engine

    def test_custom_port_rule(self):
        """Custom rule matching a specific port."""
        rules = [CustomRule(port=8080, level="CRITICAL", message="Dev server detected")]
        engine = self._stable_engine(custom_rules=rules)
        entry = _make_entry(port=8080)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        custom = [a for a in alerts if a.message == "Dev server detected"]
        assert len(custom) == 1
        assert custom[0].level == AlertLevel.CRITICAL

    def test_custom_process_name_glob(self):
        """Custom rule with process_name glob pattern."""
        rules = [CustomRule(process_name="ncat*", level="CRITICAL", message="Reverse shell")]
        engine = self._stable_engine(custom_rules=rules)
        entry = _make_entry(port=8080, process_name="ncat-linux")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        custom = [a for a in alerts if a.message == "Reverse shell"]
        assert len(custom) == 1

    def test_custom_port_pattern(self):
        """Custom rule with port glob pattern."""
        rules = [CustomRule(port_pattern="808*", level="WARNING", message="8080 range")]
        engine = self._stable_engine(custom_rules=rules)
        entry = _make_entry(port=8081)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        custom = [a for a in alerts if a.message == "8080 range"]
        assert len(custom) == 1

    def test_custom_rule_no_match(self):
        """Custom rule that doesn't match should produce no alert."""
        rules = [CustomRule(port=9999, level="CRITICAL", message="Should not fire")]
        engine = self._stable_engine(custom_rules=rules)
        entry = _make_entry(port=8080)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        custom = [a for a in alerts if a.message == "Should not fire"]
        assert len(custom) == 0

    def test_custom_rule_proto_filter(self):
        """Custom rule with proto filter only matches that protocol."""
        rules = [CustomRule(port=8080, proto="udp", level="WARNING", message="UDP alert")]
        engine = self._stable_engine(custom_rules=rules)
        tcp_entry = _make_entry(port=8080, proto="tcp")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([tcp_entry])

        custom = [a for a in alerts if a.message == "UDP alert"]
        assert len(custom) == 0  # TCP should not match UDP rule

    def test_multiple_custom_rules(self):
        """Multiple custom rules should each independently trigger."""
        rules = [
            CustomRule(port=8080, level="WARNING", message="Rule A"),
            CustomRule(process_name="testproc", level="INFO", message="Rule B"),
        ]
        engine = self._stable_engine(custom_rules=rules)
        entry = _make_entry(port=8080, process_name="testproc")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(time, "time", lambda: 1700000000.0)
            alerts = engine.analyze([entry])

        messages = [a.message for a in alerts]
        assert "Rule A" in messages
        assert "Rule B" in messages


# ── CustomRule.matches unit tests ──────────────────────────────────

class TestCustomRuleMatches:
    def test_port_match(self):
        entry = _make_entry(port=8080)
        rule = CustomRule(port=8080)
        assert rule.matches(entry) is True

    def test_port_no_match(self):
        entry = _make_entry(port=9090)
        rule = CustomRule(port=8080)
        assert rule.matches(entry) is False

    def test_port_pattern_match(self):
        entry = _make_entry(port=8081)
        rule = CustomRule(port_pattern="808*")
        assert rule.matches(entry) is True

    def test_remote_ip_match(self):
        entry = SocketEntry(
            proto="tcp", local_ip="0.0.0.0", local_port=80,
            remote_ip="192.168.1.5", remote_port=443,
            state="ESTABLISHED", state_code="01",
            uid=1000, inode=50000,
        )
        rule = CustomRule(remote_ip="192.168.1.*")
        assert rule.matches(entry) is True

    def test_process_name_match(self):
        entry = _make_entry(port=8080, process_name="python3")
        rule = CustomRule(process_name="python*")
        assert rule.matches(entry) is True

    def test_and_logic_all_must_match(self):
        entry = _make_entry(port=8080, proto="tcp", process_name="nginx")
        # port matches, proto matches, but process doesn't
        rule = CustomRule(port=8080, proto="tcp", process_name="apache*")
        assert rule.matches(entry) is False

    def test_no_conditions_matches_everything(self):
        entry = _make_entry(port=8080)
        rule = CustomRule()
        assert rule.matches(entry) is True
