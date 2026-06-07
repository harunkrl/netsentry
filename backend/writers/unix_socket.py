import contextlib
import json
import logging
import os
import socket
import threading
from collections.abc import Callable

from shared import SOCKET_PATH

logger = logging.getLogger("kportwatch.unix_socket")

class UnixSocketServer:
    """Unix domain socket server supporting both broadcast and request/response.

    Broadcast mode: clients connect long-lived and receive JSON snapshots.
    Command mode: clients send a JSON command and receive a JSON response.
    """

    def __init__(self):
        self.clients: list[socket.socket] = []
        self._clients_lock = threading.Lock()
        self.server: socket.socket | None = None
        self.running = False
        self.thread: threading.Thread | None = None
        self._command_handler: Callable[[dict], dict] | None = None

    def set_command_handler(self, handler: Callable[[dict], dict]):
        """Register a handler for command requests. Handler receives a dict, returns a dict."""
        self._command_handler = handler

    def start(self):
        if os.path.exists(SOCKET_PATH):
            with contextlib.suppress(OSError):
                os.unlink(SOCKET_PATH)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.server.bind(SOCKET_PATH)
            os.chmod(SOCKET_PATH, 0o600)
            self.server.listen(5)
            self.running = True
            self.thread = threading.Thread(target=self._accept_loop, daemon=True)
            self.thread.start()
            logger.info("Unix socket server listening on %s", SOCKET_PATH)
        except OSError as e:
            logger.error("Failed to start Unix socket server: %s", e)
            self.server = None

    def _accept_loop(self):
        while self.running and self.server:
            try:
                self.server.settimeout(1.0)
                client, _ = self.server.accept()
                # Quick probe: is this a command client?
                try:
                    client.settimeout(0.3)
                    data = client.recv(4096)
                    if data:
                        self._handle_client_message(client, data)
                    else:
                        # Connection closed immediately — ignore
                        client.close()
                except TimeoutError:
                    # No initial message within probe window — broadcast subscriber
                    client.settimeout(None)  # Reset to blocking for broadcast
                    with self._clients_lock:
                        self.clients.append(client)
                    logger.debug("Broadcast client connected (no initial message)")
                except OSError:
                    with contextlib.suppress(OSError):
                        client.close()
            except TimeoutError:
                continue
            except OSError:
                if self.running:
                    continue
                break

    def _handle_client_message(self, client: socket.socket, data: bytes):
        """Handle an initial message from a client."""
        try:
            message = json.loads(data.decode('utf-8').strip())
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Not valid JSON — treat as broadcast subscriber
            with self._clients_lock:
                self.clients.append(client)
            return

        if isinstance(message, dict) and "command" in message:
            # Command request — handle and respond
            self._handle_command(client, message)
        else:
            # Not a command — treat as broadcast subscriber
            with self._clients_lock:
                self.clients.append(client)

    def _handle_command(self, client: socket.socket, command: dict):
        """Process a command request and send back a response."""
        if self._command_handler:
            try:
                response = self._command_handler(command)
            except Exception as e:
                logger.error("Command handler error: %s", e)
                response = {"status": "error", "message": str(e)}
        else:
            response = {"status": "error", "message": "No command handler registered"}

        try:
            response_data = json.dumps(response).encode('utf-8') + b'\n'
            client.sendall(response_data)
        except OSError as e:
            logger.error("Failed to send command response: %s", e)
        finally:
            with contextlib.suppress(OSError):
                client.close()

    def broadcast(self, json_data: str):
        dead_clients = []
        data = json_data.encode('utf-8') + b'\n'
        with self._clients_lock:
            for client in self.clients:
                try:
                    client.sendall(data)
                except OSError:
                    dead_clients.append(client)

            for client in dead_clients:
                self.clients.remove(client)
        for client in dead_clients:
            with contextlib.suppress(OSError):
                client.close()

    def stop(self):
        self.running = False
        if self.server:
            with contextlib.suppress(OSError):
                self.server.close()
        with self._clients_lock:
            for client in self.clients:
                with contextlib.suppress(OSError):
                    client.close()
            self.clients.clear()
        if os.path.exists(SOCKET_PATH):
            with contextlib.suppress(OSError):
                os.unlink(SOCKET_PATH)


def send_command(command: dict, timeout: float = 5.0) -> dict:
    """Send a command to the Unix socket server and return the response.

    Args:
        command: Dict with at least a "command" key.
        timeout: Socket timeout in seconds.

    Returns:
        Response dict from the server.

    Raises:
        ConnectionError: If the server is not running.
        TimeoutError: If the server doesn't respond in time.
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(SOCKET_PATH)
        sock.sendall(json.dumps(command).encode('utf-8') + b'\n')
        response_data = b""
        max_size = 10 * 1024 * 1024  # 10MB safety limit
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response_data += chunk
            if len(response_data) > max_size:
                raise ValueError("Response exceeds maximum allowed size (10MB)")
            if b'\n' in response_data:
                break
        if not response_data:
            raise ConnectionError("Empty response from server")
        return json.loads(response_data.decode('utf-8').strip())
    except TimeoutError:
        raise TimeoutError("Server did not respond in time") from None
    except OSError as e:
        raise ConnectionError(f"Cannot connect to server: {e}") from e
    finally:
        sock.close()
