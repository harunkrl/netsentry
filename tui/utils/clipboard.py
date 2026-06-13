"""KPortWatch — Shared clipboard utility.

Wraps clipboard operations with consistent error handling for
Wayland/SSH/headless environments where clipboard may not work.
"""

from __future__ import annotations

import contextlib


def safe_copy_to_clipboard(app, text: str, *, notify: bool = True) -> bool:
    """Copy text to system clipboard with error handling.

    Args:
        app: Textual App instance (for clipboard and notification).
        text: The text to copy.
        notify: If True, show a notification on success.

    Returns:
        True if the copy succeeded, False otherwise.
    """
    try:
        app.copy_to_clipboard(text)
        if notify:
            app.notify("Copied to clipboard", severity="information")
        return True
    except Exception:
        with contextlib.suppress(Exception):
            app.notify("Clipboard not available in this environment", severity="warning")
        return False
