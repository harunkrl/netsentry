import socket
import os
import threading
import logging
from typing import List

from shared import SOCKET_PATH

logger = logging.getLogger("netsentry.unix_socket")

class UnixSocketServer:
    def __init__(self):
        self.clients: List[socket.socket] = []
        self.server: socket.socket | None = None
        self.running = False
        self.thread: threading.Thread | None = None

    def start(self):
        if os.path.exists(SOCKET_PATH):
            try:
                os.unlink(SOCKET_PATH)
            except OSError:
                pass
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.server.bind(SOCKET_PATH)
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
                client, _ = self.server.accept()
                self.clients.append(client)
            except OSError:
                if self.running:
                    continue
                break

    def broadcast(self, json_data: str):
        dead_clients = []
        data = json_data.encode('utf-8') + b'\n'
        for client in self.clients:
            try:
                client.sendall(data)
            except OSError:
                dead_clients.append(client)
        
        for client in dead_clients:
            self.clients.remove(client)
            try:
                client.close()
            except OSError:
                pass

    def stop(self):
        self.running = False
        if self.server:
            try:
                self.server.close()
            except OSError:
                pass
        for client in self.clients:
            try:
                client.close()
            except OSError:
                pass
        if os.path.exists(SOCKET_PATH):
            try:
                os.unlink(SOCKET_PATH)
            except OSError:
                pass
