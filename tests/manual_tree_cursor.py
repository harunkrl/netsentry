from textual.app import App, ComposeResult
from textual.widgets import Tree


class TestApp(App):
    def compose(self) -> ComposeResult:
        yield Tree("Root")

    def on_mount(self) -> None:
        tree = self.query_one(Tree)
        n = tree.root.add("Node", data=1)
        n.add_leaf("Leaf", data=2)
        tree.root.expand()
        self.call_later(self.test_cursor)

    async def test_cursor(self) -> None:
        tree = self.query_one(Tree)
        target = tree.root.children[0]

        print("Before select:", target.is_expanded)
        tree.select_node(target)
        print("After select:", target.is_expanded)

        # Also test cursor_line
        target.collapse()
        print("Before cursor_line:", target.is_expanded)
        tree.cursor_line = target.line
        print("After cursor_line:", target.is_expanded)

        self.exit()


if __name__ == "__main__":
    app = TestApp()
    app.run(headless=True)
