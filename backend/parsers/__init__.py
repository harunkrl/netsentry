"""KPortWatch — Backend parsers for /proc data."""
from .proc_net import parse_all_proc, parse_proc_net
from .inode_map import build_inode_to_pid_map

__all__ = ["parse_all_proc", "parse_proc_net", "build_inode_to_pid_map"]
