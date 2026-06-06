"""KPortWatch TUI — Unified theme system.

Single source of truth for:
  1. **TCSS themes** — CSS class-scoped per theme for Textual widgets
  2. **Rich markup colours** — alert/state colour maps for Rich text

Theme switching works by toggling a CSS class (``.theme-dark``,
``.theme-nord``, etc.) on the App widget.  All theme CSS is generated
at import time and bundled into the App's ``CSS`` class variable, so
no runtime CSS injection is needed.

Usage in the app::

    from tui.themes import ALL_THEME_CSS, apply_theme

    class KPortWatchTUI(App):
        CSS = ALL_THEME_CSS          # all themes at once

    apply_theme(app, "nord")         # toggles class → instant switch

Usage in widgets (Rich markup)::

    from tui.themes import alert_colour, state_colour
"""
from __future__ import annotations

import contextlib

# ═══════════════════════════════════════════════════════════════
# 1. Theme palette definitions
# ═══════════════════════════════════════════════════════════════

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "surface":          "#121212",
        "panel-bg":         "#1e1e2e",
        "primary":          "#00ff99",
        "primary-dim":      "#008855",
        "text":             "#e0e0e0",
        "text-dim":         "#6a6a7a",
        "warning":          "#ffcc00",
        "error":            "#ff3333",
        "table-header-bg":  "#003322",
        "table-cursor-bg":  "#005533",
        "table-hover-bg":   "#004422",
        "table-odd-bg":     "#1a1a2e",
        "statusbar-bg":     "#003311",
    },
    "nord": {
        "surface":          "#2e3440",
        "panel-bg":         "#3b4252",
        "primary":          "#a3be8c",
        "primary-dim":      "#8fbcbb",
        "text":             "#eceff4",
        "text-dim":         "#8890a0",
        "warning":          "#ebcb8b",
        "error":            "#bf616a",
        "table-header-bg":  "#434c5e",
        "table-cursor-bg":  "#4c566a",
        "table-hover-bg":   "#434c5e",
        "table-odd-bg":     "#3b4252",
        "statusbar-bg":     "#2e3440",
    },
    "solarized": {
        "surface":          "#002b36",
        "panel-bg":         "#073642",
        "primary":          "#859900",
        "primary-dim":      "#586e75",
        "text":             "#839496",
        "text-dim":         "#586e75",
        "warning":          "#b58900",
        "error":            "#dc322f",
        "table-header-bg":  "#073642",
        "table-cursor-bg":  "#586e75",
        "table-hover-bg":   "#073642",
        "table-odd-bg":     "#073642",
        "statusbar-bg":     "#073642",
    },
    "light": {
        "surface":          "#ffffff",
        "panel-bg":         "#f5f5f5",
        "primary":          "#008844",
        "primary-dim":      "#006633",
        "text":             "#1a1a1a",
        "text-dim":         "#666666",
        "warning":          "#aa8800",
        "error":            "#cc2222",
        "table-header-bg":  "#e8f5e8",
        "table-cursor-bg":  "#c8e6c8",
        "table-hover-bg":   "#d8eed8",
        "table-odd-bg":     "#f0f0f0",
        "statusbar-bg":     "#e0e0e0",
    },
}

DEFAULT_THEME = "dark"

# User-facing theme names → internal theme keys
THEME_DISPLAY_MAP: dict[str, str] = {
    "Cyberpunk": "dark",
    "Midnight": "nord",
    "Hacker": "solarized",
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
# 2. Rich markup colour maps
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
# 3. TCSS generation — class-scoped per theme
# ═══════════════════════════════════════════════════════════════

def _generate_theme_css(theme_name: str) -> str:
    """Generate TCSS for one theme, scoped under ``.theme-{name}``."""
    c = THEMES[theme_name]
    on_primary = "#000000"
    on_error = "#ffffff"

    return f"""
/* ── {theme_name.capitalize()} Theme ──────────────────────── */
.theme-{theme_name} Screen {{
    background: {c['surface']};
    color: {c['text']};
}}

.theme-{theme_name} #port-table {{
    height: auto;
    min-height: 8;
    max-height: 60%;
    border: round {c['primary-dim']};
    padding: 0 1;
    background: {c['panel-bg']};
    overflow-y: auto;
}}

.theme-{theme_name} #connection-log {{
    height: 1fr;
    border: round {c['primary-dim']};
    padding: 0 1;
    background: {c['panel-bg']};
    overflow-y: auto;
}}

.theme-{theme_name} #status-bar {{
    height: auto;
    background: {c['statusbar-bg']};
    color: {c['primary']};
    content-align: center middle;
    text-style: bold;
    padding: 0 1;
}}

.theme-{theme_name} Input {{
    border: round {c['primary-dim']};
    background: {c['panel-bg']};
    color: {c['text']};
}}

.theme-{theme_name} DataTable {{
    background: {c['panel-bg']};
}}
.theme-{theme_name} DataTable > .datatable--header {{
    background: {c['table-header-bg']};
    color: {c['primary']};
    text-style: bold;
}}
.theme-{theme_name} DataTable > .datatable--header:hover {{
    background: {c['table-cursor-bg']};
}}
.theme-{theme_name} DataTable > .datatable--cursor {{
    background: {c['table-cursor-bg']};
    color: {c['text']};
}}
.theme-{theme_name} DataTable > .datatable--hover {{
    background: {c['table-hover-bg']};
}}
.theme-{theme_name} DataTable > .datatable--odd-row {{
    background: {c['table-odd-bg']};
}}

.theme-{theme_name} ScrollBar {{
    background: {c['surface']};
    color: {c['primary']};
}}
.theme-{theme_name} ScrollBar > .scrollbar--thumb {{
    background: {c['primary-dim']};
}}
.theme-{theme_name} ScrollBar > .scrollbar--thumb:hover {{
    background: {c['primary']};
}}

.theme-{theme_name} Button {{
    background: {c['primary-dim']};
    color: {on_primary};
}}
.theme-{theme_name} Button.variant-warning {{
    background: {c['warning']};
    color: {on_primary};
}}
.theme-{theme_name} Button.variant-error {{
    background: {c['error']};
    color: {on_error};
}}
"""


def _generate_all_themes_css() -> str:
    """Generate combined TCSS for all themes, each scoped by class."""
    parts = [
        "/* ═══ KPortWatch Theme System — auto-generated ═══ */\n",
        ".hidden { display: none; }\n",
    ]
    for name in THEMES:
        parts.append(_generate_theme_css(name))
    return "\n".join(parts)


# Pre-generate at import time — assign this to App.CSS
ALL_THEME_CSS: str = _generate_all_themes_css()


# ═══════════════════════════════════════════════════════════════
# 4. Runtime theme switching (class toggle)
# ═══════════════════════════════════════════════════════════════

_current_theme: str = DEFAULT_THEME


def current_theme() -> str:
    return _current_theme


def get_theme_names() -> list[str]:
    return list(THEMES.keys())


def apply_theme_by_name(app, display_name: str) -> None:
    """Switch the TUI theme by user-facing display name (e.g. 'Cyberpunk')."""
    key = display_name_to_key(display_name)
    apply_theme(app, key)


def apply_theme(app, theme_name: str) -> None:
    """Switch the TUI to *theme_name* by toggling a CSS class on the app.

    This is the correct Textual way: all theme CSS lives in App.CSS,
    each scoped under ``.theme-{name}``.  Switching is just a class
    add/remove.
    """
    global _current_theme

    if theme_name not in THEMES:
        theme_name = DEFAULT_THEME

    # Remove old theme class
    old_class = f"theme-{_current_theme}"
    with contextlib.suppress(Exception):
        app.remove_class(old_class)

    _current_theme = theme_name

    # Add new theme class — Textual re-renders automatically
    new_class = f"theme-{theme_name}"
    app.add_class(new_class)

    # Persist to config
    try:
        from shared.config import save_config_setting
        save_config_setting("tui", "color_theme", theme_name)
    except Exception:
        pass
