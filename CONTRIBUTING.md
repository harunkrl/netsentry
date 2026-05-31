# Contributing to NetSentry

First off, thank you for considering contributing to NetSentry! 

## Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/harunkrl/netsentry.git
   cd netsentry
   ```

2. **Set up a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```

3. **Run the backend daemon in the foreground:**
   ```bash
   netsentry-daemon --foreground
   ```

4. **Run the TUI:**
   ```bash
   netsentry-tui
   ```

5. **Test the Widget (Plasmoid):**
   ```bash
   plasmoidviewer -a package
   ```

## Code Style & Linting

We use `ruff` for fast linting and formatting.
Before submitting a pull request, ensure your code passes:
```bash
ruff check .
ruff format --check .
```

## Testing

Run the test suite using `pytest`:
```bash
pytest tests/ -v
```
We require a minimum test coverage of 60%. Check coverage with:
```bash
pytest tests/ -v --cov=backend --cov=tui
```

## Pull Request Process

1. Create a feature branch (`git checkout -b feature/my-new-feature`).
2. Commit your changes (`git commit -am 'Add some feature'`).
3. Push to the branch (`git push origin feature/my-new-feature`).
4. Create a new Pull Request on GitHub.
