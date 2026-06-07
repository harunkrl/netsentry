"""KPortWatch — Auto-update checker and performer.

Checks GitHub Tags API for new versions and optionally performs
a ``git pull`` + ``pip install -e .`` + daemon restart.

Uses stdlib only (urllib.request, json, subprocess).

Usage::

    from backend.update import check_for_update, perform_update

    new_version = check_for_update()
    if new_version:
        perform_update()

CLI::

    kportwatch-update --check      # check only
    kportwatch-update --apply      # check and apply
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from shared.constants import APP_VERSION, GITHUB_REPO, UPDATE_STATE_FILE

logger = logging.getLogger("kportwatch.update")

# GitHub Tags API endpoint
_TAGS_URL = f"https://api.github.com/repos/{GITHUB_REPO}/tags"


# ── Version comparison ────────────────────────────────────────

def parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a version string like 'v2.1.0' or '2.1.0' into a tuple of ints.

    Strips leading 'v' and splits on '.'.
    Returns (0,) for unparseable strings.
    """
    version_str = version_str.strip().lstrip("v")
    try:
        return tuple(int(x) for x in version_str.split("."))
    except (ValueError, AttributeError):
        return (0,)


def get_local_version() -> str:
    """Return the current installed version string."""
    return APP_VERSION


def get_latest_version() -> str | None:
    """Fetch the latest tag name from GitHub Tags API.

    Returns:
        Latest version tag string (e.g. "v2.1.0"), or None on error.
    """
    try:
        req = urllib.request.Request(
            _TAGS_URL,
            headers={"User-Agent": f"KPortWatch/{APP_VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        if isinstance(data, list) and len(data) > 0:
            tag = data[0].get("name", "")
            if tag:
                return tag
    except (urllib.error.URLError, json.JSONDecodeError, OSError, KeyError) as e:
        logger.debug("Failed to fetch latest version: %s", e)
    return None


def check_for_update() -> str | None:
    """Check if a newer version is available on GitHub.

    Returns:
        The new version string if an update is available, None otherwise.
    """
    local = get_local_version()
    latest = get_latest_version()

    if latest is None:
        return None

    if parse_version(latest) > parse_version(local):
        logger.info("Update available: %s → %s", local, latest)
        return latest

    logger.debug("Already up to date: %s", local)
    return None


# ── Update state file ─────────────────────────────────────────

def write_update_state(
    current: str,
    latest: str | None = None,
    update_available: bool = False,
    path: str = UPDATE_STATE_FILE,
) -> None:
    """Write update state to a JSON file for TUI/widget consumption.

    Best-effort: silently ignores write failures.
    """
    data = {
        "current": current,
        "latest": latest,
        "update_available": update_available,
        "last_checked": time.time(),
    }
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(json.dumps(data, ensure_ascii=False))
        os.replace(tmp, path)
    except OSError:
        pass


def read_update_state(path: str = UPDATE_STATE_FILE) -> dict | None:
    """Read the update state file. Returns None on error."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


# ── Update performer ──────────────────────────────────────────

def perform_update(restart_daemon: bool = True) -> bool:
    """Perform the update: git pull + pip install + optional daemon restart.

    Args:
        restart_daemon: If True, restart the systemd user service after update.

    Returns:
        True if the update succeeded, False otherwise.
    """
    project_dir = _find_project_dir()
    if project_dir is None:
        logger.error("Cannot find project directory — not a git clone install?")
        return False

    # 1. Verify latest tag signature (GPG) — best-effort
    latest = get_latest_version()
    if latest:
        _verify_tag(latest, project_dir)

    # 2. git pull
    try:
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.error("git pull failed: %s", result.stderr)
            return False
        logger.info("git pull: %s", result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.error("git pull error: %s", e)
        return False

    # 2. pip install -e .
    try:
        venv_python = os.path.join(project_dir, ".venv", "bin", "python")
        if not os.path.exists(venv_python):
            venv_python = sys.executable

        result = subprocess.run(
            [venv_python, "-m", "pip", "install", "-e", "."],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error("pip install failed: %s", result.stderr)
            return False
        logger.info("pip install: %s", result.stdout.strip()[-200:])
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.error("pip install error: %s", e)
        return False

    # 3. Restart daemon
    if restart_daemon:
        _restart_daemon()

    write_update_state(current=APP_VERSION, update_available=False)
    logger.info("Update completed successfully")
    return True


def _find_project_dir() -> str | None:
    """Find the project root directory by walking up from this file."""
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(10):
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def _verify_tag(tag: str, project_dir: str) -> None:
    """Verify a git tag's GPG signature (best-effort).

    Logs a warning if the tag is unsigned or verification fails.
    Does NOT block the update — signature verification is advisory.
    """
    try:
        # Fetch tags first
        subprocess.run(
            ["git", "fetch", "--tags", "origin"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )

        result = subprocess.run(
            ["git", "tag", "-v", tag],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            logger.info("Tag %s: GPG signature verified", tag)
        else:
            # git tag -v fails for unsigned tags or missing public keys
            stderr = result.stderr.strip()
            if "not a signed tag" in stderr.lower() or "not signed" in stderr.lower():
                logger.warning("Tag %s is not GPG-signed — proceeding anyway", tag)
            elif "public key" in stderr.lower() or "can't check" in stderr.lower():
                logger.warning(
                    "Tag %s: GPG key not in keyring — install the signer's key "
                    "for full verification", tag,
                )
            else:
                logger.warning("Tag %s signature verification failed: %s", tag, stderr)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug("Tag verification skipped: %s", e)


def _restart_daemon() -> None:
    """Restart the kportwatch systemd user service (best-effort)."""
    try:
        subprocess.run(
            ["systemctl", "--user", "restart", "kportwatch.service"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        logger.info("Daemon restarted via systemctl")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug("systemctl restart not available: %s", e)


# ── CLI entry point ───────────────────────────────────────────

def main() -> None:
    """CLI entry point for ``kportwatch-update``."""
    import argparse

    parser = argparse.ArgumentParser(
        description="KPortWatch — Check for and apply updates",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Only check for updates (don't apply)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Check and apply update if available",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose output",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    local = get_local_version()
    print(f"KPortWatch v{local}")

    latest = get_latest_version()
    if latest is None:
        print("Could not fetch latest version from GitHub")
        sys.exit(1)

    if parse_version(latest) > parse_version(local):
        print(f"Update available: v{local} → {latest}")

        if args.apply:
            print("Applying update...")
            if perform_update():
                print("Update applied successfully!")
            else:
                print("Update failed — check logs")
                sys.exit(1)
        elif not args.check:
            print("Run with --apply to install, or --check to only check.")
    else:
        print(f"Already up to date (latest: {latest})")

    write_update_state(
        current=local,
        latest=latest.lstrip("v") if latest else None,
        update_available=parse_version(latest) > parse_version(local),
    )


if __name__ == "__main__":
    main()
