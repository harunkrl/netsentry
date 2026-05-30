"""NetSentry — Backend writers for data output."""
from .json_file import read_snapshot, write_snapshot

__all__ = ["read_snapshot", "write_snapshot"]
