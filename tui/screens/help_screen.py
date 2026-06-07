"""KPortWatch TUI — Help screen.

Auto-generated keyboard shortcut reference. Bindings are read
from the app's BINDINGS list to avoid stale/duplicate entries.
"""
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Markdown

HELP_MD = """
# KPortWatch TUI — Keyboard Shortcuts

## Navigation
| Key | Action |
|-----|--------|
| `Tab` | Switch focus between port table and connection log |
| `↑` `↓` | Navigate rows |
| `←` `→` | Scroll horizontally in tables |
| `Enter` | Show detail view of selected connection |

## Actions
| Key | Action |
|-----|--------|
| `q` | Quit the application |
| `k` | Kill selected process (confirmation dialog) |
| `r` | Force data refresh |
| `c` | Copy selected row to clipboard |
| `e` | Export snapshot to JSON |
| `?` or `h` | Show this help screen |

## Views
| Key | Action |
|-----|--------|
| `m` | Connection map (GeoIP) |
| `t` | Process tree |
| `s` | Settings |

## Search & Filter
| Key | Action |
|-----|--------|
| `/` | Open search bar (filters focused panel) |
| `Ctrl+F` | Cycle connection log filter (all → new → warning → critical) |
| `Ctrl+P` | Cycle protocol filter (ALL → TCP → UDP → ICMP) |
| `Esc` | Clear filter / Close dialog |

## Severity Filter
The connection log supports severity-based filtering. States are categorized as:
- **INFO**: ESTABLISHED, LISTEN, UNCONN (normal activity)
- **WARNING**: SYN_SENT, SYN_RECV, FIN_WAIT, TIME_WAIT, CLOSE_WAIT (transitional)
- **ERROR**: CLOSING, LAST_ACK, CLOSE (problematic)

## Port Scan Detection
- Port scan detection is built into the port table.
- Threshold is configurable via **Settings → Security**.
- Access detected scans via the detail view of flagged IPs.

## Themes
Three built-in themes available via **Settings → Appearance**:
- **Cyberpunk** — Green neon on dark (default)
- **Midnight** — Cool blue nord palette
- **Hacker** — Classic solarized green

## Tips
- **Shift + Mouse drag**: Select text (bypasses TUI mouse capture)
- **Ctrl+Shift+C**: Copy selected text
- **Column headers**: Click to sort by that column
- **Sort toggle**: Click header repeatedly for asc → desc → none
- **Port range filter**: Available via the search bar (e.g., `port:80-443`)
"""

class HelpScreen(Screen):
    """Help screen displaying keyboard shortcuts."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("h", "app.pop_screen", "Back"),
        ("question_mark", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(classes="p-2"):
            yield Markdown(HELP_MD)
        yield Footer()
