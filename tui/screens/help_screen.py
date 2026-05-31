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
- `/` : Open search/filter bar (filters both port table and connection log)
- `f` : Toggle the search/filter bar visibility
- `Esc` : Clear filter and hide search bar / Close this help screen / Close detail screen
- `e` : Export the current snapshot to `~/netsentry_export.json`
- `Enter` : Show detailed view of the selected connection
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
