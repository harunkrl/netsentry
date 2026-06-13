"""KPortWatch — Custom alert rule dataclass."""

from __future__ import annotations

from fnmatch import fnmatch

__all__ = ["CustomRule"]


class CustomRule:
    """A user-defined alert rule from config.toml.

    Match conditions use AND logic — all must be True for the rule to trigger.
    """

    __slots__ = (
        "level",
        "message",
        "port",
        "port_pattern",
        "process_name",
        "proto",
        "remote_ip",
    )

    def __init__(
        self,
        port: int | None = None,
        port_pattern: str | None = None,
        remote_ip: str | None = None,
        process_name: str | None = None,
        proto: str | None = None,
        level: str = "WARNING",
        message: str = "Custom rule triggered",
    ):
        self.port = port
        self.port_pattern = port_pattern
        self.remote_ip = remote_ip
        self.process_name = process_name
        self.proto = proto
        self.level = level
        self.message = message

    def matches(self, entry) -> bool:
        """Check if a SocketEntry matches all conditions."""
        from backend.models import SocketEntry

        if not isinstance(entry, SocketEntry):
            return False
        if self.port is not None and entry.local_port != self.port:
            return False
        if self.port_pattern is not None and not fnmatch(str(entry.local_port), self.port_pattern):
            return False
        if self.remote_ip is not None:
            ip = entry.remote_ip or ""
            if not fnmatch(ip, self.remote_ip):
                return False
        if self.process_name is not None:
            name = entry.process_name or ""
            if not fnmatch(name, self.process_name):
                return False
        return not (self.proto is not None and entry.proto != self.proto)

    def __repr__(self) -> str:
        conditions = []
        if self.port is not None:
            conditions.append(f"port={self.port}")
        if self.port_pattern is not None:
            conditions.append(f"pattern={self.port_pattern}")
        if self.remote_ip is not None:
            conditions.append(f"ip={self.remote_ip}")
        if self.process_name is not None:
            conditions.append(f"proc={self.process_name}")
        if self.proto is not None:
            conditions.append(f"proto={self.proto}")
        return f"CustomRule({' '.join(conditions)} → {self.level})"
