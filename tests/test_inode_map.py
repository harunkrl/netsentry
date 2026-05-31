from unittest.mock import patch
from backend.parsers.inode_map import _read_file_safe, build_inode_to_pid_map

def test_read_file_safe(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello\n")
    assert _read_file_safe(str(f)) == "hello"
    assert _read_file_safe(str(tmp_path / "nonexistent")) is None

@patch("backend.parsers.inode_map.os.listdir")
@patch("backend.parsers.inode_map.os.readlink")
@patch("backend.parsers.inode_map._read_file_safe")
def test_build_inode_to_pid_map(mock_read_file, mock_readlink, mock_listdir):
    def listdir_side_effect(path):
        if path == "/proc":
            return ["123", "abc", "456"]
        elif path == "/proc/123/fd":
            return ["0", "1", "2"]
        elif path == "/proc/456/fd":
            return ["0"]
        raise FileNotFoundError()

    def readlink_side_effect(path):
        if path == "/proc/123/fd/1":
            return "socket:[9999]"
        elif path == "/proc/123/fd/2":
            return "anon_inode:[eventpoll]"
        elif path == "/proc/456/fd/0":
            return "socket:[8888]"
        raise OSError()

    def read_file_side_effect(path):
        if "comm" in path:
            return "test_proc"
        if "cmdline" in path:
            return "test_proc\x00--arg1\x00"
        return None

    mock_listdir.side_effect = listdir_side_effect
    mock_readlink.side_effect = readlink_side_effect
    mock_read_file.side_effect = read_file_side_effect

    m = build_inode_to_pid_map()
    assert 9999 in m
    assert m[9999] == (123, "test_proc", "test_proc --arg1")
    assert 8888 in m
    assert m[8888] == (456, "test_proc", "test_proc --arg1")
