#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# KPortWatch — Uninstallation Script
# ──────────────────────────────────────────────────────────────
set -e

echo "╔══════════════════════════════════════════╗"
echo "║      KPortWatch Uninstaller v2.1.0       ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Stop and disable systemd service ──────────────────────
echo "🛑 Stopping and disabling background daemon..."
if systemctl --user is-active --quiet kportwatch.service; then
    systemctl --user disable --now kportwatch.service || true
    echo "   ✅ Daemon stopped"
else
    echo "   ✅ Daemon is not running"
fi

echo "🗑️ Removing systemd service file..."
rm -f "${HOME}/.config/systemd/user/kportwatch.service"
systemctl --user daemon-reload
echo "   ✅ Systemd configuration cleaned"

# ── 2. Remove Plasma Widget ──────────────────────────────────
echo "🗑️ Removing KDE Plasma Widget..."
rm -rf "${HOME}/.local/share/plasma/plasmoids/com.kportwatch.plasmoid"
echo "   ✅ Widget removed from ~/.local/share/plasma/plasmoids/"

# ── 3. Remove Global Symlinks ────────────────────────────────
echo "🔗 Removing global commands from ~/.local/bin..."
rm -f "${HOME}/.local/bin/kportwatch"
rm -f "${HOME}/.local/bin/kportwatch-tui"
rm -f "${HOME}/.local/bin/kportwatch-daemon"
rm -f "${HOME}/.local/bin/kportwatchctl"
rm -f "${HOME}/.local/bin/kportwatch-client"
rm -f "${HOME}/.local/bin/kportwatch-export"
rm -f "${HOME}/.local/bin/kportwatch-update"
echo "   ✅ Symlinks removed"

# ── 4. Remove Config and Runtime Data ────────────────────────
echo "🧹 Cleaning up configuration and runtime data..."
read -p "   Delete configuration files? (y/N) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf "${HOME}/.config/kportwatch"
    echo "   Config deleted"
else
    echo "   Config preserved at ~/.config/kportwatch"
fi

RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}"
rm -f "${RUNTIME_DIR}/kportwatch-data.json"
rm -f "${RUNTIME_DIR}/kportwatch.sock"
rm -f "${RUNTIME_DIR}/kportwatch.pid"
rm -f "${RUNTIME_DIR}/kportwatch-update.json"
rm -rf "${HOME}/.local/share/kportwatch"
echo "   ✅ Config, cache and runtime files deleted"

# ── 5. Restart Plasma ────────────────────────────────────────
read -p "   Restart KDE Plasma panel now? (y/N) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Restarting KDE Plasma panel..."
if systemctl --user is-active --quiet plasma-plasmashell.service; then
    systemctl restart --user plasma-plasmashell.service
    echo "   ✅ Plasma restarted"
else
    echo "   Plasma restart skipped — changes will apply on next login"
fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Uninstallation complete!"
echo "Note: The KPortWatch source folder and Python virtual environment"
echo "were NOT deleted. You can safely delete the repository folder now."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
