"""Maquina de comandos do EV3, compativel com MicroPython e testavel no PC."""

try:
    from .calibration import DESTINATION_TO_CODE
except ImportError:
    from calibration import DESTINATION_TO_CODE


class BridgeController:
    def __init__(self, motion):
        self.motion = motion
        self.cycles = {}
        self.history = []
        self.pending = None
        self.active = None
        self.needs_reset = False

    @staticmethod
    def frame(kind, cycle, payload):
        return kind + ":" + cycle + ":" + payload

    def handle(self, line):
        parts = line.strip().split(":", 2)
        if len(parts) != 3 or parts[0] != "CMD":
            raise ValueError("INVALID_FRAME")
        _kind, cycle, command = parts
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        if not 1 <= len(cycle) <= 32 or any(c not in alphabet for c in cycle):
            raise ValueError("INVALID_CYCLE")
        command = command.strip().upper()
        ack = self.frame("ACK", cycle, command)

        if command == "SISTEMA:PING":
            return [ack]

        if command == "ESTEIRA:STOP" or command == "SISTEMA:RESET":
            interrupted = self.active or self.pending
            previous = self.cycles.get(cycle)
            self.abort()
            # STOP de um ciclo concluido e a parada normal, nao uma emergencia.
            if command == "SISTEMA:RESET":
                self.needs_reset = False
            elif interrupted or previous is None or previous["status"] != "completed":
                self.needs_reset = True
            return [ack]

        record = self.cycles.get(cycle)
        if command.startswith("DESTINO:"):
            destination = command[8:]
            if destination not in DESTINATION_TO_CODE:
                return self.error(cycle, command, "INVALID_DESTINATION")
            if record is not None:
                if destination != record["destination"]:
                    return self.error(cycle, command, "DESTINATION_LOCKED")
                return [ack]
            if self.needs_reset:
                return self.error(cycle, command, "RESET_REQUIRED")
            if self.pending or self.active:
                return self.error(cycle, command, "BUSY")
            self.cycles[cycle] = {"destination": destination, "status": "ready"}
            self.history.append(cycle)
            if len(self.history) > 128:
                del self.cycles[self.history.pop(0)]
            self.pending = cycle
            return [ack]

        if command == "ESTEIRA:START":
            if record is None:
                return self.error(cycle, command, "DESTINATION_REQUIRED")
            if record["status"] == "completed":
                return [ack, self.arrived(cycle, record)]
            if record["status"] == "running":
                return [ack]  # Repeticao nao executa os motores novamente.
            if record["status"] != "ready":
                return self.error(cycle, command, "CYCLE_ABORTED")
            if self.needs_reset:
                return self.error(cycle, command, "RESET_REQUIRED")
            try:
                self.motion.start(DESTINATION_TO_CODE[record["destination"]])
            except Exception:
                self.abort()
                self.needs_reset = True
                return self.error(cycle, command, "MOTION_FAILED")
            record["status"] = "running"
            self.active = cycle
            return [ack]
        return self.error(cycle, command, "COMMAND_NOT_SUPPORTED")

    def poll(self):
        if self.active is None:
            return []
        cycle = self.active
        record = self.cycles[cycle]
        try:
            done = self.motion.poll()
        except Exception as exc:
            code = "MOTION_TIMEOUT" if str(exc) == "MOTION_TIMEOUT" else "MOTION_FAILED"
            self.abort()
            self.needs_reset = True
            return self.error(cycle, "ESTEIRA:START", code)
        if not done:
            return []
        record["status"] = "completed"
        self.active = None
        self.pending = None
        # Sem sensor: confirma fim das rotacoes, nao posicao medida do produto.
        return [self.arrived(cycle, record)]

    def abort(self):
        cycle = self.active or self.pending
        if cycle is not None:
            self.cycles[cycle]["status"] = "aborted"
        self.active = None
        self.pending = None
        try:
            self.motion.stop()
        except Exception:
            # O defeito fisico deve ser inspecionado antes de novo ciclo.
            self.needs_reset = True
            raise

    def connection_lost(self):
        self.needs_reset = True
        self.abort()

    def error(self, cycle, command, code):
        return [self.frame("ERR", cycle, command + ":" + code)]

    def arrived(self, cycle, record):
        return self.frame("EVT", cycle, "DESTINO_ALCANCADO:" + record["destination"])
