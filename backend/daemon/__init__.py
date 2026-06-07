"""KPortWatch daemon package — thin orchestrator and decoupled components."""

__all__ = ["DaemonController"]


def __getattr__(name: str):
    """Lazy import to avoid circular dependency during incremental migration."""
    if name == "DaemonController":
        from backend.daemon.controller import DaemonController
        return DaemonController
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
