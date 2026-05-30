#!/usr/bin/env python3
"""NetSentry Client — Streams JSON data from the Unix socket to stdout."""
import socket
import sys

from shared import SOCKET_PATH

def main():
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(SOCKET_PATH)
        # Read lines endlessly and flush to stdout
        f = s.makefile('r', encoding='utf-8')
        for line in f:
            print(line.strip(), flush=True)
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        print(f'{{"error": "Failed to connect to daemon socket: {e}"}}')
        sys.exit(1)

if __name__ == "__main__":
    main()
