"""KPortWatch — Shared TUI utilities.

Centralises common patterns used across TUI screens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import App

    from tui.data.provider import DataProvider


def get_app_provider(app: App) -> DataProvider:
    """Get the DataProvider singleton from the running app.

    Falls back to creating a new instance if the app hasn't set one up.
    """
    from tui.data.provider import DataProvider

    provider = getattr(app, "data_provider", None)
    if provider is not None:
        return provider
    # Fallback: create and cache on the app
    provider = DataProvider()
    app.data_provider = provider
    return provider
