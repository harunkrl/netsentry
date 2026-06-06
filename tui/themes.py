"""KPortWatch TUI — Theme system built on Textual's native themes.

Uses Textual 8.x Theme dataclass and ``app.theme`` reactive property.
Registers custom KPortWatch themes and maps display names to theme keys.

Usage in the app::

    from tui.themes import register_kpw_themes, apply_theme

    class KPortWatchTUI(App):
        def on_mount(self):
            register_kpw_themes(self)
            apply_theme(self, "cyberpunk")

Usage in widgets (Rich markup)::

    from tui.themes import alert_colour, state_colour
"""
from __future__ import annotations

from textual.theme import Theme

# ═══════════════════════════════════════════════════════════════
# 1. KPortWatch custom themes
# ═══════════════════════════════════════════════════════════════

KPW_THEMES: dict[str, Theme] = {
    "cyberpunk": Theme(
        name="cyberpunk",
        primary="#00ff99",
        secondary="#008855",
        warning="#ffcc00",
        error="#ff3333",
        success="#00ff99",
        accent="#00ff99",
        foreground="#e0e0e0",
        background="#121212",
        surface="#1e1e2e",
        panel="#1e1e2e",
        dark=True,
    ),
    "kpw-light": Theme(
        name="kpw-light",
        primary="#008844",
        secondary="#006633",
        warning="#aa8800",
        error="#cc2222",
        success="#008844",
        accent="#008844",
        foreground="#1a1a1a",
        background="#ffffff",
        surface="#f5f5f5",
        panel="#f5f5f5",
        dark=False,
    ),
}

DEFAULT_THEME = "cyberpunk"

# User-facing display names → internal theme keys
THEME_DISPLAY_MAP: dict[str, str] = {
    "Cyberpunk": "cyberpunk",
    "Midnight": "nord",
    "Hacker": "solarized-dark",
    "Daylight": "kpw-light",
}
THEME_DISPLAY_NAMES = list(THEME_DISPLAY_MAP.keys())


def display_name_to_key(display_name: str) -> str:
    """Convert a user-facing theme name to the internal theme key."""
    return THEME_DISPLAY_MAP.get(display_name, DEFAULT_THEME)


def key_to_display_name(key: str) -> str:
    """Convert an internal theme key to the user-facing name."""
    for name, k in THEME_DISPLAY_MAP.items():
        if k == key:
            return name
    return THEME_DISPLAY_NAMES[0]


# ═══════════════════════════════════════════════════════════════
# 2. Rich markup colour maps (for DataTable content, not Textual)
# ═══════════════════════════════════════════════════════════════

ALERT_COLOURS: dict[str, str] = {
    "CRITICAL": "bold red",
    "WARNING":  "bold yellow",
    "INFO":     "cyan",
    "LOW":      "dim cyan",
}

STATE_COLOURS: dict[str, str] = {
    "ESTABLISHED": "bold green",
    "LISTEN":      "bold cyan",
    "TIME_WAIT":   "dim",
    "CLOSE_WAIT":  "dim red",
    "SYN_SENT":    "cyan",
    "SYN_RECV":    "cyan",
    "FIN_WAIT1":   "dim yellow",
    "FIN_WAIT2":   "dim yellow",
    "CLOSING":     "dim red",
    "LAST_ACK":    "dim red",
    "CLOSE":       "dim",
    "UNCONN":      "dim",
}


def alert_colour(level: str) -> str:
    return ALERT_COLOURS.get(level.upper(), "white")


def state_colour(state: str) -> str:
    return STATE_COLOURS.get(state, "white")


# ═══════════════════════════════════════════════════════════════
# 3. Theme registration and switching
# ═══════════════════════════════════════════════════════════════

def register_kpw_themes(app) -> None:
    """Register KPortWatch custom themes with the Textual app.

    Built-in themes (nord, solarized-dark, etc.) are already available
    in Textual 8.x. Only our custom themes need registration.
    """
    for theme in KPW_THEMES.values():
        app.register_theme(theme)


def get_theme_names() -> list[str]:
    """Return all available theme keys (custom + built-in that we map to)."""
    return list(set(KPW_THEMES.keys()) | set(THEME_DISPLAY_MAP.values()))


def current_theme_key(app) -> str:
    """Get the current theme key from the app."""
    t = app.current_theme
    return t.name if t else DEFAULT_THEME


def apply_theme_by_name(app, display_name: str) -> None:
    """Switch the TUI theme by user-facing display name (e.g. 'Cyberpunk')."""
    key = display_name_to_key(display_name)
    apply_theme(app, key)


def apply_theme(app, theme_name: str) -> None:
    """Switch the TUI to *theme_name* using Textual's native theme system.

    Textual handles all CSS generation from the Theme dataclass fields.
    Switching is just setting ``app.theme = name``.
    """
    valid = get_theme_names()
    if theme_name not in valid:
        theme_name = DEFAULT_THEME

    # Textual's reactive theme property handles the switch
    app.theme = theme_name

    # Persist to config
    try:
        from shared.config import save_config_setting
        save_config_setting("tui", "color_theme", theme_name)
    except Exception:
        pass
