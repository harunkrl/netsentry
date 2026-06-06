#!/usr/bin/env python3
"""KPortWatch Client — Streams JSON data from the Unix socket to stdout."""
import contextlib
import socket
import sys

from shared import SOCKET_PATH

CONNECT_TIMEOUT = 5.0  # seconds


def main():
    s = None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(CONNECT_TIMEOUT)
        s.connect(SOCKET_PATH)
        # Switch to blocking reads with no timeout for streaming
        s.settimeout(None)
        f = s.makefile('r', encoding='utf-8')
        for line in f:
            print(line.strip(), flush=True)
    except KeyboardInterrupt:
        sys.exit(0)
    except TimeoutError:
        print('{"error": "Timed out connecting to daemon — is kportwatch running?"}')
        sys.exit(1)
    except FileNotFoundError:
        print(f'{{"error": "Socket not found at {SOCKET_PATH} — is kportwatch running?"}}')
        sys.exit(1)
    except ConnectionRefusedError:
        print('{"error": "Daemon refused connection — may be starting up"}')
        sys.exit(1)
    except Exception as e:
        print(f'{{"error": "Failed to connect to daemon socket: {e}"}}')
        sys.exit(1)
    finally:
        if s:
            with contextlib.suppress(Exception):
                s.close()


if __name__ == "__main__":
    main()
