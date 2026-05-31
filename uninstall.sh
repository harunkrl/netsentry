#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# NetSentry — Uninstallation Script
# ──────────────────────────────────────────────────────────────
set -e

echo "╔══════════════════════════════════════════╗"
echo "║      NetSentry Uninstaller v1.0.0       ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Stop and disable systemd service ──────────────────────
echo "🛑 Stopping and disabling background daemon..."
if systemctl --user is-active --quiet netsentry.service; then
    systemctl --user disable --now netsentry.service || true
    echo "   ✅ Daemon stopped"
else
    echo "   ✅ Daemon is not running"
fi

echo "🗑️ Removing systemd service file..."
rm -f "${HOME}/.config/systemd/user/netsentry.service"
systemctl --user daemon-reload
echo "   ✅ Systemd configuration cleaned"

# ── 2. Remove Plasma Widget ──────────────────────────────────
echo "🗑️ Removing KDE Plasma Widget..."
rm -rf "${HOME}/.local/share/plasma/plasmoids/com.netsentry.plasmoid"
echo "   ✅ Widget removed from ~/.local/share/plasma/plasmoids/"

# ── 3. Remove Global Symlinks ────────────────────────────────
echo "🔗 Removing global commands from ~/.local/bin..."
rm -f "${HOME}/.local/bin/netsentry"
rm -f "${HOME}/.local/bin/netsentry-tui"
rm -f "${HOME}/.local/bin/netsentry-daemon"
echo "   ✅ Symlinks removed"

# ── 4. Remove Config and Runtime Data ────────────────────────
echo "🧹 Cleaning up configuration and runtime data..."
rm -rf "${HOME}/.config/netsentry"

RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}"
rm -f "${RUNTIME_DIR}/netsentry-data.json"
rm -f "${RUNTIME_DIR}/netsentry.sock"
rm -f "${RUNTIME_DIR}/netsentry.pid"
echo "   ✅ Config and cache files deleted"

# ── 5. Restart Plasma ────────────────────────────────────────
echo "🔄 Restarting KDE Plasma panel to apply changes..."
if systemctl --user is-active --quiet plasma-plasmashell.service; then
    systemctl restart --user plasma-plasmashell.service
    echo "   ✅ Plasma restarted"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Uninstallation complete!"
echo "Note: The NetSentry source folder and Python virtual environment"
echo "were NOT deleted. You can safely delete the repository folder now."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
