from textual.app import ComposeResult
from textual.screen import Screen
from textual.containers import VerticalScroll
from textual.widgets import Header, Footer, Markdown

HELP_MD = """
# NetSentry TUI Help

**Keyboard Shortcuts**
- `?` or `h` : Show this help screen
- `q` : Quit the application
- `k` : Kill the currently selected process (opens confirmation dialog)
- `r` : Force an immediate data refresh
- `t` : Open process tree view (hierarchical view of all running processes)
- `m` : Open connection map view (GeoIP map of outbound connections)
- `/` : Open search/filter bar (filters both port table and connection log)
- `f` : Toggle the search/filter bar visibility
- `c` : Copy selected row to clipboard (PortTable, ConnectionLog, or map table)
- `n` : Toggle TUI toast notifications on/off (saved persistently)
- `Esc` : Clear filter and hide search bar / Close this help screen / Close detail screen
- `e` : Export the current snapshot to `~/netsentry_export.json`
- `Enter` : Show detailed view of the selected connection

**Tips**
- **Shift + Mouse drag**: Select text with the mouse (bypasses TUI mouse capture). Use `Ctrl+Shift+C` or middle-click to copy.
- **Tab**: Switch focus between the port table and connection log.
- **Arrow keys**: Navigate rows and scroll horizontally in tables.
- **Column headers**: Click to sort by that column.
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
