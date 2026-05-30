#!/usr/bin/env bash
VENV_DIR="$HOME/NetSentry/.venv"
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
fi
export PYTHONPATH="$HOME/NetSentry${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "$HOME/NetSentry/tui/netsentry_tui.py"
