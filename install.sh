#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# NetSentry — Installation Script
# Arch Linux (EndeavourOS) / KDE Plasma 6.6 / Wayland
# ──────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLASMOID_ID="com.netsentry.plasmoid"
PLASMOID_DIR="${HOME}/.local/share/plasma/plasmoids/${PLASMOID_ID}"

echo "╔══════════════════════════════════════════╗"
echo "║       NetSentry Installer v1.0.0        ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Check Python ──────────────────────────────────────────
echo "🔍 Checking Python..."
if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 not found. Install with: sudo pacman -S python"
    exit 1
fi
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"; then
    echo "   ✅ Python ${PY_VERSION}"
else
    echo "❌ Python 3.10+ required, found ${PY_VERSION}"
    exit 1
fi

# ── 2. Create venv and install dependencies ──────────────────
echo "📦 Setting up Python virtual environment..."
if [ ! -d "${SCRIPT_DIR}/.venv" ]; then
    python3 -m venv "${SCRIPT_DIR}/.venv"
fi
source "${SCRIPT_DIR}/.venv/bin/activate"
# Try editable install first; falls back gracefully on Python 3.14+
# (known getpath null-char issue with editable installs on 3.14+)
if ! pip install --quiet -e "${SCRIPT_DIR}" 2>/dev/null; then
    echo "   ⚠️  Editable install skipped (Python $(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')), using direct install..."
    pip install --quiet textual rich
    # Re-install entry points without build isolation
    pip install --quiet --no-build-isolation -e "${SCRIPT_DIR}" 2>/dev/null || true
fi
echo "   ✅ Dependencies installed (textual, rich)"

# ── 3. Install Plasma widget ─────────────────────────────────
echo "🔧 Installing Plasma 6 widget..."
mkdir -p "${HOME}/.local/share/plasma/plasmoids"
# Remove old broken symlink if it exists (from earlier installs)
rm -f "${HOME}/.local/share/plasma/plasmoids/com.netsentry.helper"
# Copy files instead of symlink — kpackagetool -r deletes symlinks
rm -rf "${PLASMOID_DIR}"
cp -r "${SCRIPT_DIR}/widget" "${PLASMOID_DIR}"
echo "   ✅ Widget installed to ${PLASMOID_DIR}"

# Register with kpackagetool6 so plasmoidviewer/Plasma can discover it
if command -v kpackagetool6 &>/dev/null; then
    kpackagetool6 --type Plasma/Applet --install "${SCRIPT_DIR}/widget" 2>/dev/null || \
    kpackagetool6 --type Plasma/Applet --upgrade "${SCRIPT_DIR}/widget" 2>/dev/null || true
    echo "   ✅ Registered with kpackagetool6"
else
    echo "   ⚠️  kpackagetool6 not found, skipping package registration"
fi

# ── 4. Config directory ──────────────────────────────────────
echo "📁 Creating config directory..."
mkdir -p "${HOME}/.config/netsentry"
echo "   ✅ ${HOME}/.config/netsentry"

# ── 5. Make scripts executable & Create Symlinks ───────────────
echo "🔐 Setting permissions..."
chmod +x "${SCRIPT_DIR}/widget/contents/scripts/launch-tui.sh"
echo "   ✅ Scripts executable"

echo "🔗 Creating global symlinks in ~/.local/bin..."
mkdir -p "${HOME}/.local/bin"
ln -sf "${SCRIPT_DIR}/.venv/bin/netsentry-tui" "${HOME}/.local/bin/netsentry-tui"
ln -sf "${SCRIPT_DIR}/.venv/bin/netsentry-daemon" "${HOME}/.local/bin/netsentry-daemon"
ln -sf "${SCRIPT_DIR}/.venv/bin/netsentryctl" "${HOME}/.local/bin/netsentryctl"
ln -sf "${SCRIPT_DIR}/.venv/bin/netsentry-client" "${HOME}/.local/bin/netsentry-client"
ln -sf "${SCRIPT_DIR}/.venv/bin/netsentry-export" "${HOME}/.local/bin/netsentry-export"
ln -sf "${SCRIPT_DIR}/.venv/bin/netsentry-update" "${HOME}/.local/bin/netsentry-update"
ln -sf "${HOME}/.local/bin/netsentry-tui" "${HOME}/.local/bin/netsentry"
echo "   ✅ Symlinks created (you can now run 'netsentry' anywhere)"

# ── 6. Install systemd service ─────────────────────────────────
echo "⚙️ Installing systemd user service..."
mkdir -p "${HOME}/.config/systemd/user"
cp "${SCRIPT_DIR}/systemd/netsentry.service" "${HOME}/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now netsentry.service
systemctl --user restart netsentry.service 2>/dev/null || true
echo "   ✅ Systemd service installed and started"

# ── 7. Restart Plasma (optional) ─────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📌 Next steps:"
echo ""
echo "   1. Restart Plasma (to load the widget into the Add Widgets menu):"
echo "      systemctl restart --user plasma-plasmashell.service"
echo ""
echo "   2. Add the widget to your panel:"
echo "      Right-click panel → Add Widgets → search 'NetSentry'"
echo ""
echo "   3. The daemon is already running via systemd."
echo ""
echo "   4. Or test the TUI directly:"
echo "      netsentry-tui"
echo ""
echo "   5. Run tests:"
echo "      cd ${SCRIPT_DIR} && pytest tests/ -v"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ Installation complete!"
