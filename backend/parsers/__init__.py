"""KPortWatch — Backend parsers for /proc data."""
from .inode_map import build_inode_to_pid_map
from .proc_net import parse_all_proc, parse_proc_net

__all__ = ["build_inode_to_pid_map", "parse_all_proc", "parse_proc_net"]
