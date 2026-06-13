#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# KPortWatch — Uninstallation Script
# ──────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KPW_VERSION=$(python3 -c "
import tomllib, pathlib
d = tomllib.loads(pathlib.Path('${SCRIPT_DIR}/pyproject.toml').read_text())
print(d.get('project', {}).get('version', '0.0.0'))
" 2>/dev/null || echo "2.1.0")

echo "╔════════════════════════════════════════════╗"
printf "║   KPortWatch Uninstaller v%%s   ║\n" "$KPW_VERSION"
echo "╚════════════════════════════════════════════╝"
echo ""

# ── 0. Check if KPortWatch is installed ──────────────────────
KPW_SERVICE="${HOME}/.config/systemd/user/kportwatch.service"
KPW_PLASMOID="${HOME}/.local/share/plasma/plasmoids/com.kportwatch.plasmoid"
KPW_POLKIT="/usr/share/polkit-1/actions/com.kportwatch.helper.policy"
if [ ! -f "${KPW_SERVICE}" ] && [ ! -d "${KPW_PLASMOID}" ] && [ ! -f "${KPW_POLKIT}" ] \
   && [ ! -d "${HOME}/.config/kportwatch" ] && [ ! -d "${HOME}/.local/share/kportwatch" ]; then
    echo "ℹ️  KPortWatch does not appear to be installed (no service, widget,"
    echo "    config, runtime data or Polkit policy found). Nothing to uninstall."
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Nothing to do. Exiting."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    exit 0
fi

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
read -r -p "   Delete configuration files? (y/N) " reply
if [[ "${reply:-}" =~ ^[Yy]$ ]]; then
    rm -rf "${HOME}/.config/kportwatch"
    echo "   ✅ Config deleted"
else
    echo "   ℹ️  Config preserved at ~/.config/kportwatch"
fi

RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}"
rm -f "${RUNTIME_DIR}/kportwatch-data.json"
rm -f "${RUNTIME_DIR}/kportwatch.sock"
rm -f "${RUNTIME_DIR}/kportwatch.pid"
rm -f "${RUNTIME_DIR}/kportwatch-update.json"
rm -rf "${HOME}/.local/share/kportwatch"
echo "   ✅ Config, cache and runtime files deleted"

# ── 5. Remove Polkit policy ──────────────────────────────────
echo "🔒 Removing Polkit policy..."
POLKIT_FILE="/usr/share/polkit-1/actions/com.kportwatch.helper.policy"
if [ ! -f "${POLKIT_FILE}" ]; then
    echo "   ✅ Polkit policy not installed"
else
    # Warn before interactive sudo so the password prompt isn't a surprise.
    # (sudo writes its prompt to /dev/tty, which can get visually lost after the
    # echo above and make the script appear to hang.)
    if ! sudo -n true 2>/dev/null; then
        echo "   🔐 Removing the system-wide Polkit policy requires your password:"
    fi
    if sudo rm "${POLKIT_FILE}"; then
        echo "   ✅ Polkit policy removed"
    else
        echo "   ⚠️  Could not remove Polkit policy (needs root)"
        echo "      Run manually: sudo rm ${POLKIT_FILE}"
    fi
fi

# ── 6. Restart Plasma ────────────────────────────────────────
read -r -p "   Restart KDE Plasma panel now? (y/N) " reply
if [[ "${reply:-}" =~ ^[Yy]$ ]]; then
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
