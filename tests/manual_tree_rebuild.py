from textual.app import App, ComposeResult
from textual.widgets import Tree


class TestApp(App):
    def compose(self) -> ComposeResult:
        yield Tree("Root")

    def on_mount(self) -> None:
        tree = self.query_one(Tree)
        self.expanded_pids = set()
        self.build_tree(tree)
        self.call_later(self.simulate_user)

    def build_tree(self, tree):
        n1 = tree.root.add("Node 1", data=1)
        n1_1 = n1.add("Node 1.1", data=11)
        n1_1.add_leaf("Leaf 1.1.1", data=111)

        n2 = tree.root.add("Node 2", data=2)
        n2.add_leaf("Leaf 2.1", data=21)

        tree.root.expand()

        # Restore
        def restore(node):
            if getattr(node, "data", None) in self.expanded_pids:
                node.expand()
            for child in getattr(node, "children", []):
                restore(child)

        restore(tree.root)

    def save_state(self, tree):
        self.expanded_pids.clear()

        def collect(node):
            if node.is_expanded and getattr(node, "data", None) is not None:
                self.expanded_pids.add(node.data)
            for child in getattr(node, "children", []):
                collect(child)

        collect(tree.root)

    async def simulate_user(self) -> None:
        tree = self.query_one(Tree)
        # expand Node 1 manually
        tree.root.children[0].expand()
        print("Before refresh:", tree.root.children[0].is_expanded)
        self.save_state(tree)
        print("Saved PIDs:", self.expanded_pids)
        tree.clear()
        self.build_tree(tree)
        print("After rebuild:", tree.root.children[0].is_expanded)
        self.exit()


if __name__ == "__main__":
    app = TestApp()
    app.run(headless=True)
