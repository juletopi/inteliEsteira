"""Arduino virtual em localhost, usando os mesmos frames do adaptador serial."""

import argparse
from collections import defaultdict
from queue import Empty
import socket
import socketserver
from threading import Lock, Timer
from time import monotonic

from hardware.mock import MockArduino
from hardware.protocol import ProtocolError, encode_message, parse_message, validate_command
from hardware.serial_adapter import SerialArduino


class SocketArduino(SerialArduino):
    mode = "simulator"
    arrival_source = "simulado_socket"

    def __init__(self, port=8766, **kwargs):
        super().__init__(port=f"socket://127.0.0.1:{int(port)}", boot_wait=0, **kwargs)


class ProtocolSimulator(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address=("127.0.0.1", 8766), *, delay=0.3, drop_ack=(), suppress_events=(),
                 wrong_destination=False, disconnect_at=None):
        if address[0] != "127.0.0.1":
            raise ValueError("O simulador aceita apenas localhost.")
        self.delay = max(0, delay)
        self.drop_ack = set(drop_ack)
        self.suppress_events = set(suppress_events)
        self.wrong_destination = wrong_destination
        self.disconnect_at = disconnect_at
        self.client_lock = Lock()
        self.commands_applied = []
        super().__init__(address, _Handler)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        if not self.server.client_lock.acquire(blocking=False):
            return
        model = MockArduino()
        model.connect()
        write_lock = Lock()
        timers = []
        cached = {}
        stopped = set()
        ack_dropped = set()
        alive = [True]
        last_valid = monotonic()

        def send(frame):
            if not alive[0]:
                return
            try:
                with write_lock:
                    self.request.sendall((frame + "\n").encode("utf-8"))
            except OSError:
                alive[0] = False

        def complete(message):
            if message.cycle_id in stopped or not alive[0]:
                return
            payload = message.payload
            if payload.split(":", 1)[0] in self.server.suppress_events:
                return
            if payload.startswith("DESTINO_ALCANCADO:"):
                destination = payload.split(":")[1]
                if self.server.wrong_destination:
                    destination = "R10" if destination != "R10" else "R01"
                payload = f"DESTINO_ALCANCADO:{destination}:SIMULADO"
            send(encode_message("EVT", message.cycle_id, payload))

        try:
            self.request.settimeout(0.2)
            buffer = b""
            while alive[0]:
                try:
                    incoming = self.request.recv(4096)
                except socket.timeout:
                    moving = model.conveyor_state == "rodando" or model.gripper_state in {"segurando", "sobre_esteira"}
                    if moving and monotonic() - last_valid > 4:
                        break
                    continue
                if not incoming:
                    break
                buffer += incoming
                if len(buffer) > 8192:
                    break
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if len(line) > 512:
                        continue
                    try:
                        message = parse_message(line.decode("utf-8"))
                        if message.kind != "CMD":
                            raise ProtocolError("Envie CMD.")
                        command = validate_command(message.payload)
                    except (ProtocolError, UnicodeDecodeError):
                        send("ERR:SEM_CICLO:FRAME_INVALIDO")
                        continue
                    last_valid = monotonic()
                    if command == self.server.disconnect_at:
                        alive[0] = False
                        break
                    key = (message.cycle_id, command)
                    if key not in cached:
                        if message.cycle_id in stopped and command not in {"ESTEIRA:STOP", "GARRA:STOP", "SISTEMA:PING", "SISTEMA:RESET", "SENSOR:DESARMAR"}:
                            send(encode_message("ERR", message.cycle_id, f"{command}:CICLO_INTERROMPIDO"))
                            continue
                        try:
                            model.execute(command, message.cycle_id)
                        except Exception:
                            send(encode_message("ERR", message.cycle_id, f"{command}:COMANDO_REJEITADO"))
                            continue
                        cached[key] = True
                        self.server.commands_applied.append(key)
                        if command in {"ESTEIRA:STOP", "GARRA:STOP", "SISTEMA:RESET"}:
                            stopped.add(message.cycle_id)
                        events = []
                        while True:
                            try:
                                events.append(model._events.get_nowait())
                            except Empty:
                                break
                        # ACK vem primeiro. Retransmissoes nao reaplicam a acao.
                        if command not in self.server.drop_ack or key in ack_dropped:
                            send(encode_message("ACK", message.cycle_id, command))
                        else:
                            ack_dropped.add(key)
                        for event in events:
                            timer = Timer(self.server.delay, complete, args=(event,))
                            timer.daemon = True
                            timer.start()
                            timers.append(timer)
                    else:
                        send(encode_message("ACK", message.cycle_id, command))
        finally:
            alive[0] = False
            for timer in timers:
                timer.cancel()
            model.disconnect()
            self.server.client_lock.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--drop-ack", action="append", default=[], help="Comando cujo primeiro ACK sera perdido.")
    parser.add_argument("--suppress-event", action="append", default=[], help="Nome de EVT a omitir, como DESTINO_ALCANCADO.")
    parser.add_argument("--wrong-destination", action="store_true")
    parser.add_argument("--disconnect-at")
    args = parser.parse_args()
    with ProtocolSimulator(("127.0.0.1", args.port), delay=args.delay, drop_ack=args.drop_ack,
                           suppress_events=args.suppress_event, wrong_destination=args.wrong_destination,
                           disconnect_at=args.disconnect_at) as server:
        print(f"Arduino virtual em 127.0.0.1:{args.port}; sem motores ou sensores fisicos.", flush=True)
        try:
            server.serve_forever(poll_interval=0.1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
