"""Simulador TCP: mesma ponte do EV3, sem pybricks nem motores reais."""

import argparse
import os
from time import monotonic

from ev3.server import run_server


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    # Restrito ao proprio computador; nao precisa de um EV3 para exercitar a API.
    run_server(SimulatedMotion(), os.getenv("EV3_TOKEN", ""), "127.0.0.1", args.port)
