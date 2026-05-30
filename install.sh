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
echo "   ✅ Python ${PY_VERSION}"

# ── 2. Create venv and install dependencies ──────────────────
echo "📦 Setting up Python virtual environment..."
if [ ! -d "${SCRIPT_DIR}/.venv" ]; then
    python3 -m venv "${SCRIPT_DIR}/.venv"
fi
source "${SCRIPT_DIR}/.venv/bin/activate"
pip install --quiet textual rich 2>/dev/null || pip3 install --quiet textual rich 2>/dev/null
echo "   ✅ Dependencies installed (textual, rich)"

# ── 3. Install Plasma widget ─────────────────────────────────
echo "🔧 Installing Plasma 6 widget..."
mkdir -p "${HOME}/.local/share/plasma/plasmoids"
ln -sfn "${SCRIPT_DIR}/widget" "${PLASMOID_DIR}"
echo "   ✅ Widget linked to ${PLASMOID_DIR}"

# ── 4. Config directory ──────────────────────────────────────
echo "📁 Creating config directory..."
mkdir -p "${HOME}/.config/netsentry"
echo "   ✅ ${HOME}/.config/netsentry"

# ── 5. Make scripts executable ───────────────────────────────
echo "🔐 Setting permissions..."
chmod +x "${SCRIPT_DIR}/widget/contents/scripts/launch-tui.sh"
echo "   ✅ Scripts executable"

# ── 6. Restart Plasma (optional) ─────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📌 Next steps:"
echo ""
echo "   1. Start the daemon:"
echo "      ${SCRIPT_DIR}/.venv/bin/python3 ${SCRIPT_DIR}/backend/netsentry-daemon.py --foreground &"
echo ""
echo "   2. Add the widget to your panel:"
echo "      Right-click panel → Add Widgets → search 'NetSentry'"
echo ""
echo "   3. Or test the TUI directly:"
echo "      ${SCRIPT_DIR}/.venv/bin/python3 ${SCRIPT_DIR}/tui/netsentry_tui.py"
echo ""
echo "   4. (Optional) Auto-start daemon with systemd:"
echo "      See README.md for the systemd user service file"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ Installation complete!"
