"""Simulador TCP: mesma ponte do EV3, sem pybricks nem motores reais."""

import argparse
import os
import socketserver
from threading import Lock
from time import monotonic

from ev3.bridge import BridgeController
from ev3.server import run_server, serve_client, validate_token


class SimulatedMotion:
    def __init__(self, delay=0.1):
        self.delay = delay
        self.deadline = None
        self.codes = []

    def start(self, code):
        self.codes.append(code)
        self.deadline = monotonic() + self.delay

    def poll(self):
        if self.deadline is not None and monotonic() >= self.deadline:
            self.deadline = None
            return True
        return False

    def stop(self):
        self.deadline = None


class EV3Simulator(socketserver.ThreadingTCPServer):
    """Ponte real em localhost, com ciclo de vida controlavel pela bancada."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address=("127.0.0.1", 0), *, token, delay=0.1):
        if address[0] != "127.0.0.1":
            raise ValueError("O simulador aceita apenas localhost.")
        validate_token(token)
        self.token = token
        self.motion = SimulatedMotion(delay)
        self.bridge = BridgeController(self.motion)
        self.client_lock = Lock()
        super().__init__(address, _Handler)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        if not self.server.client_lock.acquire(blocking=False):
            return
        try:
            serve_client(self.request, self.server.bridge, self.server.token)
        except (OSError, ValueError, RuntimeError):
            pass
        finally:
            self.server.client_lock.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    # Restrito ao proprio computador; nao precisa de um EV3 para exercitar a API.
    run_server(SimulatedMotion(), os.getenv("EV3_TOKEN", ""), "127.0.0.1", args.port)
