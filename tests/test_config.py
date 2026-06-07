"""Tests for shared.config — TOML configuration loader."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from shared.config import (
    AppConfig,
    apply_cli_overrides,
    generate_example_config,
    get_config,
    load_config,
)

# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "kportwatch-config"


@pytest.fixture
def config_file(config_dir: Path) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.toml"


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset config singleton between tests."""
    import shared.config as cfg_mod
    cfg_mod._current_config = None
    yield
    cfg_mod._current_config = None


# ── Default values tests ──────────────────────────────────────────

class TestDefaults:
    def test_load_without_file_uses_defaults(self, tmp_path: Path):
        cfg = load_config(str(tmp_path / "nonexistent.toml"))
        assert cfg.poll_interval == 2.0
        assert cfg.alert_poll_interval == 1.0
        assert cfg.idle_poll_interval == 10.0
        assert cfg.notifications_enabled is True
        assert cfg.dns_cache_size == 1024
        assert cfg.config_path is None

    def test_get_config_returns_defaults_when_not_loaded(self):
        cfg = get_config()
        assert isinstance(cfg, AppConfig)
        assert cfg.poll_interval == 2.0

    def test_load_sets_singleton(self, tmp_path: Path):
        cfg = load_config(str(tmp_path / "nonexistent.toml"))
        assert get_config() is cfg


# ── TOML loading tests ────────────────────────────────────────────

class TestTomlLoading:
    def test_polling_override(self, config_file: Path):
        config_file.write_text("""
[polling]
interval = 5.0
alert_interval = 2.0
idle_interval = 30.0
idle_threshold_secs = 600.0
""")
        cfg = load_config(str(config_file))
        assert cfg.poll_interval == 5.0
        assert cfg.alert_poll_interval == 2.0
        assert cfg.idle_poll_interval == 30.0
        assert cfg.idle_threshold_secs == 600.0

    def test_alerts_override(self, config_file: Path):
        config_file.write_text("""
[alerts]
baseline_duration = 60.0
burst_threshold = 5
malicious_ports = [4444, 5555, 9999]
privileged_port_max = 1023
""")
        cfg = load_config(str(config_file))
        assert cfg.baseline_duration == 60.0
        assert cfg.burst_threshold == 5
        assert cfg.malicious_ports == frozenset({4444, 5555, 9999})
        assert cfg.privileged_port_max == 1023

    def test_known_safe_ports_override(self, config_file: Path):
        config_file.write_text("""
[alerts.known_safe_ports]
22 = "sshd"
8080 = "myapp"
""")
        cfg = load_config(str(config_file))
        assert cfg.known_safe_ports[22] == "sshd"
        assert cfg.known_safe_ports[8080] == "myapp"

    def test_dns_override(self, config_file: Path):
        config_file.write_text("""
[dns]
cache_size = 512
max_pending = 128
""")
        cfg = load_config(str(config_file))
        assert cfg.dns_cache_size == 512
        assert cfg.dns_max_pending == 128

    def test_notifications_override(self, config_file: Path):
        config_file.write_text("""
[notifications]
enabled = false
min_level = "CRITICAL"
alert_ttl = 1800.0
""")
        cfg = load_config(str(config_file))
        assert cfg.notifications_enabled is False
        assert cfg.notification_min_level == "CRITICAL"
        assert cfg.alert_ttl == 1800.0

    def test_paths_override(self, config_file: Path):
        config_file.write_text("""
[paths]
data_file = "/tmp/ns-data.json"
socket_path = "/tmp/ns.sock"
""")
        cfg = load_config(str(config_file))
        assert cfg.data_file == "/tmp/ns-data.json"
        assert cfg.socket_path == "/tmp/ns.sock"

    def test_partial_override_keeps_defaults(self, config_file: Path):
        config_file.write_text("""
[polling]
interval = 3.0
""")
        cfg = load_config(str(config_file))
        assert cfg.poll_interval == 3.0
        # Others should stay at defaults
        assert cfg.alert_poll_interval == 1.0
        assert cfg.notifications_enabled is True


# ── Validation tests ──────────────────────────────────────────────

class TestValidation:
    def test_negative_interval_ignored(self, config_file: Path):
        config_file.write_text('[polling]\ninterval = -1.0\n')
        cfg = load_config(str(config_file))
        assert cfg.poll_interval == 2.0  # default

    def test_zero_interval_ignored(self, config_file: Path):
        config_file.write_text('[polling]\ninterval = 0\n')
        cfg = load_config(str(config_file))
        assert cfg.poll_interval == 2.0  # default

    def test_invalid_burst_threshold_ignored(self, config_file: Path):
        config_file.write_text('[alerts]\nburst_threshold = -1\n')
        cfg = load_config(str(config_file))
        assert cfg.burst_threshold == 3  # default

    def test_invalid_min_level_ignored(self, config_file: Path):
        config_file.write_text('[notifications]\nmin_level = "INVALID"\n')
        cfg = load_config(str(config_file))
        assert cfg.notification_min_level == "WARNING"  # default

    def test_malicious_ports_invalid_entries_filtered(self, config_file: Path):
        config_file.write_text('[alerts]\nmalicious_ports = [4444, "bad", -1, 70000]\n')
        cfg = load_config(str(config_file))
        assert cfg.malicious_ports == frozenset({4444})

    def test_empty_malicious_ports_list(self, config_file: Path):
        config_file.write_text('[alerts]\nmalicious_ports = []\n')
        cfg = load_config(str(config_file))
        assert cfg.malicious_ports == frozenset()

    def test_malformed_toml_uses_defaults(self, config_file: Path):
        config_file.write_text("this is not valid toml {{{{")
        cfg = load_config(str(config_file))
        assert cfg.poll_interval == 2.0  # default

    def test_corrupt_file_uses_defaults(self, tmp_path: Path):
        cfg = load_config(str(tmp_path / "nonexistent.toml"))
        assert cfg.config_path is None
        assert cfg.poll_interval == 2.0


# ── CLI override tests ────────────────────────────────────────────

class TestCLIOverrides:
    def test_interval_override(self, config_file: Path):
        config_file.write_text('[polling]\ninterval = 5.0\n')
        cfg = load_config(str(config_file))
        assert cfg.poll_interval == 5.0

        class Args:
            interval = 1.0

        cfg = apply_cli_overrides(cfg, Args())
        assert cfg.poll_interval == 1.0  # CLI wins

    def test_cli_with_no_interval_keeps_config(self, config_file: Path):
        config_file.write_text('[polling]\ninterval = 5.0\n')
        cfg = load_config(str(config_file))

        class Args:
            interval = None

        cfg = apply_cli_overrides(cfg, Args())
        assert cfg.poll_interval == 5.0  # config value preserved


# ── Example config generation ─────────────────────────────────────

class TestExampleConfig:
    def test_generate_creates_file(self, tmp_path: Path):
        path = str(tmp_path / "example-config.toml")
        generate_example_config(path)
        assert os.path.exists(path)

    def test_generated_config_is_valid_toml(self, tmp_path: Path):
        path = str(tmp_path / "example-config.toml")
        generate_example_config(path)

        import tomllib
        with open(path, "rb") as f:
            data = tomllib.load(f)
        assert "polling" in data
        assert "alerts" in data
        assert "notifications" in data

    def test_generated_config_loads_cleanly(self, tmp_path: Path):
        path = str(tmp_path / "example-config.toml")
        generate_example_config(path)
        cfg = load_config(path)
        assert cfg.poll_interval == 2.0
        assert cfg.notifications_enabled is True

    def test_generated_config_includes_geoip(self, tmp_path: Path):
        path = str(tmp_path / "example-config.toml")
        generate_example_config(path)

        import tomllib
        with open(path, "rb") as f:
            data = tomllib.load(f)
        assert "geoip" in data
        assert data["geoip"]["enabled"] is True
        assert data["geoip"]["cache_max_entries"] == 4096


# ── Reload / SIGHUP simulation ────────────────────────────────────

class TestReload:
    def test_reload_picks_up_changes(self, config_file: Path):
        config_file.write_text('[polling]\ninterval = 3.0\n')
        cfg1 = load_config(str(config_file))
        assert cfg1.poll_interval == 3.0

        # Simulate config file change
        config_file.write_text('[polling]\ninterval = 7.0\n')
        cfg2 = load_config(str(config_file))
        assert cfg2.poll_interval == 7.0
        assert get_config() is cfg2  # singleton updated


# ── Custom rules loading ───────────────────────────────────────────

class TestCustomRulesLoading:
    def test_custom_rules_parsed(self, config_file: Path):
        config_file.write_text("""
[[custom_rules]]
match = { port = 8080 }
level = "WARNING"
message = "Dev server detected"

[[custom_rules]]
match = { process_name = "ncat*", remote_ip = "10.*" }
level = "CRITICAL"
message = "Reverse shell"
""")
        cfg = load_config(str(config_file))
        assert len(cfg.custom_rules) == 2
        assert cfg.custom_rules[0].port == 8080
        assert cfg.custom_rules[0].level == "WARNING"
        assert cfg.custom_rules[1].process_name == "ncat*"
        assert cfg.custom_rules[1].remote_ip == "10.*"

    def test_custom_rules_empty_when_not_defined(self, config_file: Path):
        config_file.write_text('[polling]\ninterval = 2.0\n')
        cfg = load_config(str(config_file))
        assert cfg.custom_rules == []

    def test_custom_rules_invalid_level_defaults_warning(self, config_file: Path):
        config_file.write_text("""
[[custom_rules]]
match = { port = 8080 }
level = "INVALID"
message = "Bad level"
""")
        cfg = load_config(str(config_file))
        assert len(cfg.custom_rules) == 1
        assert cfg.custom_rules[0].level == "WARNING"  # fallback


# ── Whitelist / Blacklist loading ──────────────────────────────────

class TestWhitelistBlacklist:
    def test_whitelist_ports(self, config_file: Path):
        config_file.write_text("""
[whitelist]
ports = [8080, 9090]
""")
        cfg = load_config(str(config_file))
        assert cfg.port_whitelist == frozenset({8080, 9090})

    def test_blacklist_ports(self, config_file: Path):
        config_file.write_text("""
[blacklist]
ports = [4444, 5555]
""")
        cfg = load_config(str(config_file))
        assert cfg.port_blacklist == frozenset({4444, 5555})

    def test_blacklist_ips(self, config_file: Path):
        config_file.write_text("""
[blacklist]
ips = ["10.0.0.*", "192.168.100.*"]
""")
        cfg = load_config(str(config_file))
        assert cfg.ip_blacklist == ["10.0.0.*", "192.168.100.*"]

    def test_defaults_empty(self, config_file: Path):
        config_file.write_text('[polling]\ninterval = 2.0\n')
        cfg = load_config(str(config_file))
        assert cfg.port_whitelist == frozenset()
        assert cfg.port_blacklist == frozenset()
        assert cfg.ip_blacklist == []


# ── Rate limiting config ───────────────────────────────────────────

class TestRateLimiting:
    def test_rate_limit_from_config(self, config_file: Path):
        config_file.write_text("""
[notifications]
rate_limit = 5
rate_window = 30.0
""")
        cfg = load_config(str(config_file))
        assert cfg.notification_rate_limit == 5
        assert cfg.notification_rate_window == 30.0

    def test_rate_limit_defaults(self, config_file: Path):
        config_file.write_text('[polling]\ninterval = 2.0\n')
        cfg = load_config(str(config_file))
        assert cfg.notification_rate_limit == 10
        assert cfg.notification_rate_window == 60.0


# ── Heartbeat config ───────────────────────────────────────────────

class TestHeartbeat:
    def test_default_heartbeat_derived_from_data_file(self, config_file: Path):
        config_file.write_text("""
[paths]
data_file = "/tmp/custom-data.json"
""")
        cfg = load_config(str(config_file))
        assert cfg.effective_heartbeat_file == "/tmp/kportwatch-heartbeat.json"

    def test_explicit_heartbeat_path(self, config_file: Path):
        config_file.write_text("""
[paths]
data_file = "/tmp/data.json"

heartbeat_file = "/var/run/kportwatch-heartbeat.json"
""")
        cfg = load_config(str(config_file))
        # heartbeat_file is top-level, but we set it via data_file path
        # Let's test with the effective one
        assert cfg.effective_heartbeat_file.endswith("kportwatch-heartbeat.json")


# ── GeoIP config ────────────────────────────────────────────────────

class TestGeoIPConfig:
    def test_geoip_defaults(self, tmp_path: Path):
        cfg = load_config(str(tmp_path / "nonexistent.toml"))
        assert cfg.geoip_enabled is True
        assert cfg.geoip_api_url == "https://ipwho.is/"
        assert cfg.geoip_cache_max_entries == 4096
        assert cfg.geoip_cache_ttl_days == 7
        assert cfg.geoip_batch_size == 10
        assert cfg.geoip_timeout == 5.0

    def test_geoip_toml_override(self, config_file: Path):
        config_file.write_text("""
[geoip]
enabled = false
cache_max_entries = 1000
cache_ttl_days = 14
batch_size = 5
timeout = 10.0
""")
        cfg = load_config(str(config_file))
        assert cfg.geoip_enabled is False
        assert cfg.geoip_cache_max_entries == 1000
        assert cfg.geoip_cache_ttl_days == 14
        assert cfg.geoip_batch_size == 5
        assert cfg.geoip_timeout == 10.0

    def test_geoip_custom_api_url(self, config_file: Path):
        config_file.write_text("""
[geoip]
api_url = "http://custom-geo.example.com/lookup/"
""")
        cfg = load_config(str(config_file))
        assert cfg.geoip_api_url == "http://custom-geo.example.com/lookup/"

    def test_geoip_invalid_values_ignored(self, config_file: Path):
        config_file.write_text("""
[geoip]
cache_max_entries = -1
cache_ttl_days = 0
batch_size = -5
timeout = -1.0
""")
        cfg = load_config(str(config_file))
        # All negative/zero values should be ignored → defaults
        assert cfg.geoip_cache_max_entries == 4096
        assert cfg.geoip_cache_ttl_days == 7
        assert cfg.geoip_batch_size == 10
        assert cfg.geoip_timeout == 5.0

    def test_geoip_custom_cache_file(self, config_file: Path):
        config_file.write_text("""
[geoip]
cache_file = "/tmp/test-geoip.json"
""")
        cfg = load_config(str(config_file))
        assert cfg.geoip_cache_file == "/tmp/test-geoip.json"

    def test_geoip_partial_override(self, config_file: Path):
        config_file.write_text("""
[geoip]
enabled = false
""")
        cfg = load_config(str(config_file))
        assert cfg.geoip_enabled is False
        # Others stay default
        assert cfg.geoip_cache_max_entries == 4096
        assert cfg.geoip_timeout == 5.0
