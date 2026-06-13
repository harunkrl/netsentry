"""Tests for widget/contents/ui/main.qml — structural and security checks."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MAIN_QML = Path("widget/contents/ui/main.qml")
CONFIG_XML = Path("widget/contents/config/main.xml")


class TestWidgetQmlSecurity:
    """Widget security tests — whitelist enforcement and sanitization."""

    def test_launch_tui_has_whitelist(self):
        """launchTUI() must enforce a whitelist of allowed commands."""
        content = MAIN_QML.read_text()
        # Must have an allowed array
        assert "var allowed" in content or "var allowedCommands" in content
        # Must have indexOf check
        assert "indexOf" in content

    def test_launch_tui_blocks_unknown_commands(self):
        """launchTUI() must block and return early for unknown commands."""
        content = MAIN_QML.read_text()
        # Must check against whitelist and return/bail if not matched
        assert "=== -1" in content
        assert "return" in content  # Early return on blocked command

    def test_launch_tui_shows_notification_on_block(self):
        """launchTUI() must notify the user when blocking a command."""
        content = MAIN_QML.read_text()
        # Should show a notification with the blocked command
        assert "showPassiveNotification" in content
        # Must have the blocking notification within launchTUI
        launch_tui_block = re.search(
            r"function launchTUI\(\).*?(?=function\s|\Z)",
            content,
            re.DOTALL,
        )
        assert launch_tui_block is not None
        block_body = launch_tui_block.group(0)
        assert "Blocked" in block_body or "blocked" in block_body

    def test_kill_process_sanitized(self):
        """killProcess() must only accept numeric PIDs."""
        content = MAIN_QML.read_text()
        # killProcess should strip non-numeric chars
        assert "replace(/[^0-9]/g" in content

    def test_no_eval_or_exec(self):
        """No eval() or Function() constructor allowed in QML."""
        content = MAIN_QML.read_text()
        assert "eval(" not in content
        assert "new Function(" not in content

    def test_no_xmlhttprequest(self):
        """No XMLHttpRequest (no network access from widget)."""
        content = MAIN_QML.read_text()
        assert "XMLHttpRequest" not in content

    def test_allowed_commands_list_content(self):
        """Whitelist must contain expected terminal emulators."""
        content = MAIN_QML.read_text()
        # Must have at least konsole and default command
        assert "konsole" in content
        assert "kportwatch" in content
        # Should have at least some alternatives
        assert "alacritty" in content or "kitty" in content or "foot" in content


class TestWidgetQmlStructure:
    """Widget structural tests — consistency and completeness."""

    def test_file_is_parseable(self):
        """QML file should be valid (basic syntax check)."""
        content = MAIN_QML.read_text()
        # Check balanced braces
        assert content.count("{") == content.count("}")
        # Check balanced parentheses
        assert content.count("(") == content.count(")")

    def test_config_keys_have_defaults(self):
        """Every config key in XML should have a default in QML."""
        if not CONFIG_XML.exists():
            pytest.skip("config XML not found")

        xml = CONFIG_XML.read_text()
        qml = MAIN_QML.read_text()

        # Extract config key names from XML
        xml_keys = set(re.findall(r'key="([^"]+)"', xml))
        for key in xml_keys:
            # Each key should be referenced in QML
            assert key in qml, f"Config key '{key}' in XML but not in QML"

    def test_timer_interval_reasonable(self):
        """Data refresh timers should be between 500ms and 30s."""
        content = MAIN_QML.read_text()
        intervals = re.findall(r"interval:\s*(\d+)", content)
        for val_str in intervals:
            val = int(val_str)
            # Skip UI animation timers (< 100ms is fine for animations)
            if val < 100:
                continue
            assert 500 <= val <= 30000, f"Timer interval {val}ms out of range"

    def test_model_update_uses_clear_and_append(self):
        """Model updates should use clear() + append() pattern."""
        content = MAIN_QML.read_text()
        if "model.clear" in content or "clear()" in content:
            assert "append" in content or "model.set" in content

    def test_no_hardcoded_ips(self):
        """No hardcoded IP addresses in widget code."""
        content = MAIN_QML.read_text()
        ip_pattern = re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", content)
        # Filter out obvious non-IP patterns like version numbers
        for ip in ip_pattern:
            parts = ip.split(".")
            if all(0 <= int(p) <= 255 for p in parts):
                pytest.fail(f"Hardcoded IP found: {ip}")

    def test_plasma_compatible_imports(self):
        """Imports should use Plasma 6 compatible modules."""
        content = MAIN_QML.read_text()
        # Should not use old Qt 5 style imports
        assert "org.kde.plasma.components 2" not in content
        assert "QtQuick.Controls 1" not in content
