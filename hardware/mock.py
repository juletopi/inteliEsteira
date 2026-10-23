"""Simulador deterministico do Arduino para desenvolvimento e testes."""

from __future__ import annotations

from collections import defaultdict, deque
from queue import Empty, Queue
from threading import RLock
from time import monotonic

from hardware.arduino import (
    Arduino,
    ArduinoCommandError,
    ArduinoDisconnectedError,
    ArduinoOperationCancelledError,
    ArduinoTimeoutError,
)
from hardware.protocol import (
    ProtocolMessage,
    encode_message,
    parse_message,
    validate_command,
)
from hardware.telemetry import Telemetry
from hardware.presence import PresenceSensor


class MockArduino(Arduino):
    mode = "mock"
    port = None
    baudrate = None
    arrival_source = "simulado"

    def __init__(self):
        self._connected = False
        self._lock = RLock()
        self._events: Queue[ProtocolMessage] = Queue()
        self._failures: dict[str, deque[str]] = defaultdict(deque)
        self._timeouts: dict[str, int] = defaultdict(int)
        self._suppress_arrival_events = 0
        self.command_log: list[str] = []
        self.gripper_state = "home"
        self.conveyor_state = "parada"
        self.destination: str | None = None
        self.telemetry = Telemetry()
        self.presence = PresenceSensor()
        self.pickup_zone = "P01"
        self.sensor_destination = None
        self._suppress_gripper = defaultdict(int)
        self.profile_counts = None
        self.profile_next = ("P", 1)
        self.firmware_calibrated = True
        self.pose_referenced = True
        self.reset_required = False
        self.presence_background_cm = -1  # sem eco: area livre

    def connect(self) -> None:
        with self._lock:
            self._connected = True

    def disconnect(self) -> None:
        with self._lock:
            self._connected = False
            self.conveyor_state = "parada"

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    def fail_next(self, command: str, error_code: str = "SIMULATED_FAILURE") -> None:
        normalized = validate_command(command)
        self._failures[normalized].append(error_code.strip().upper())

    def timeout_next(self, command: str, attempts: int = 1) -> None:
        normalized = validate_command(command)
        self._timeouts[normalized] += max(1, attempts)

    def suppress_next_arrival_event(self) -> None:
        self._suppress_arrival_events += 1

    def suppress_next_gripper_event(self, command=None):
        # Sem comando: omite a proxima conclusao da garra, seja passo do perfil ou acao antiga.
        self._suppress_gripper[validate_command(command) if command else "*"] += 1

    def _take_gripper_suppression(self, command):
        for key in (command, "*"):
            if self._suppress_gripper[key]:
                self._suppress_gripper[key] -= 1
                return True
        return False

    def execute(
        self,
        command: str,
        cycle_id: str,
        timeout: float = 2.0,
        retries: int = 1,
    ) -> ProtocolMessage:
        del timeout  # O simulador responde imediatamente ou injeta um timeout.
        normalized = validate_command(command)
        attempts = max(1, retries + 1)

        with self._lock:
            if not self._connected:
                raise ArduinoDisconnectedError("Arduino simulado desconectado.")

            for _ in range(attempts):
                frame = encode_message("CMD", cycle_id, normalized)
                self.command_log.append(frame)
                self.telemetry.record("TX", parse_message(frame))

                if self._timeouts[normalized] > 0:
                    self._timeouts[normalized] -= 1
                    continue

                if self._failures[normalized]:
                    error_code = self._failures[normalized].popleft()
                    raise ArduinoCommandError(
                        f"Arduino rejeitou {normalized}: {error_code}."
                    )

                self._apply_command(normalized, cycle_id)
                response = parse_message(encode_message("ACK", cycle_id, normalized))
                self.telemetry.record("RX", response)
                return response

        raise ArduinoTimeoutError(
            f"Arduino nao confirmou {normalized} apos {attempts} tentativa(s)."
        )

    def wait_for_event(
        self,
        event_name: str,
        cycle_id: str,
        timeout: float = 5.0,
        cancelled=None,
    ) -> ProtocolMessage:
        if not self.is_connected():
            raise ArduinoDisconnectedError("Arduino simulado desconectado.")

        expected = event_name.strip().upper()
        deferred: list[ProtocolMessage] = []
        deadline = monotonic() + max(0.001, timeout)
        try:
            while True:
                if not self.is_connected():
                    raise ArduinoDisconnectedError("Arduino simulado desconectado.")
                if cancelled is not None and cancelled():
                    raise ArduinoOperationCancelledError(
                        f"Espera pelo evento {expected} interrompida."
                    )
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise ArduinoTimeoutError(
                        f"Evento {expected} nao recebido para o ciclo {cycle_id}."
                    )
                try:
                    message = self._events.get(timeout=min(remaining, 0.05))
                except Empty as exc:
                    if monotonic() >= deadline:
                        raise ArduinoTimeoutError(
                            f"Evento {expected} nao recebido para o ciclo {cycle_id}."
                        ) from exc
                    continue

                event_name_received = message.payload.split(":", 1)[0]
                if message.cycle_id == cycle_id and event_name_received == expected:
                    self.telemetry.record("RX", message)
                    return message
                deferred.append(message)
        finally:
            for message in deferred:
                self._events.put(message)

    def _apply_command(self, command: str, cycle_id: str) -> None:
        if command.startswith("PRESENCA:CONFIGURAR:"):
            self.presence.reset()
            return
        if command == "SISTEMA:PING":
            return
        if command == "SISTEMA:STATUS":
            payload = (f"SISTEMA_STATUS:RESET_REQUIRED={int(self.reset_required)}:"
                       f"CALIBRATED={int(self.firmware_calibrated)}:POSE_REFERENCED={int(self.pose_referenced)}")
            self._events.put(parse_message(encode_message("EVT", cycle_id, payload)))
            return
        if command == "PRESENCA:LEITURA":
            distance = self.presence_background_cm
            payload = f"PRESENCA_LEITURA:{distance}:{distance}:{distance}:{0 if distance < 0 else 9}"
            self._events.put(parse_message(encode_message("EVT", cycle_id, payload)))
            return
        if command == "SISTEMA:LIBERAR":
            self.pose_referenced = False
            return
        if command.startswith("SISTEMA:SYNC:"):
            self.pose_referenced = True
            self._events.put(parse_message(encode_message("EVT", cycle_id, "POSE_REFERENCE_CONFIRMED")))
            return
        if command.startswith("GARRA:PERFIL:"):
            _garra, _perfil, pickup_count, delivery_count, _speed = command.split(":")
            self.profile_counts = (int(pickup_count), int(delivery_count))
            self.profile_next = ("P", 1)
            return
        if command == "GARRA:AREA:P01":
            self.pickup_zone = "P01"
            return
        if command.startswith("GARRA:PASSO:"):
            _prefix, _label, phase, order, *_pose = command.split(":")
            order = int(order)
            if self.profile_counts is None or (phase, order) != self.profile_next:
                raise ArduinoCommandError("PASSO_FORA_DE_ORDEM")
            completion = f"GARRA_PASSO_CONCLUIDO:{phase}:{order}"
            if self._take_gripper_suppression(command):
                pass
            else:
                self._events.put(parse_message(encode_message("EVT", cycle_id, completion)))
            pickup_count, delivery_count = self.profile_counts
            if phase == "P" and order < pickup_count:
                self.profile_next = ("P", order + 1)
            elif phase == "P":
                self.profile_next = ("E", 1)
            elif order < delivery_count:
                self.profile_next = ("E", order + 1)
            else:
                self.profile_next = ("E", delivery_count + 1)
            return
        completions = {"GARRA:PEGAR": "GARRA_COLETA_CONCLUIDA", "GARRA:SOLTAR": "GARRA_ENTREGA_CONCLUIDA",
                       "GARRA:HOME": "GARRA_HOME_CONCLUIDO", "GARRA:POSICIONAR:E01": "GARRA_POSICIONAMENTO_CONCLUIDO"}
        if command in completions:
            if self._take_gripper_suppression(command):
                pass
            else:
                self._events.put(parse_message(encode_message("EVT", cycle_id, completions[command])))
        if command == "GARRA:STOP":
            self.gripper_state = "parada"
            return
        if command.startswith("SENSOR:ARMAR:"):
            self.sensor_destination = command[13:]
            return
        if command.startswith("SENSOR:INICIAR:"):
            destination = command[15:]
            if destination != self.sensor_destination:
                raise ArduinoCommandError("O sensor do destino nao foi armado.")
            if self._suppress_arrival_events:
                self._suppress_arrival_events -= 1
            else:
                self._events.put(parse_message(encode_message("EVT", cycle_id, f"DESTINO_ALCANCADO:{destination}:SIMULADO")))
            return
        if command == "SENSOR:DESARMAR":
            self.sensor_destination = None
            return
        if command == "GARRA:PEGAR":
            self.gripper_state = "segurando"
            return
        if command == "GARRA:SOLTAR":
            self.gripper_state = "livre"
            return
        if command == "GARRA:HOME":
            self.gripper_state = "home"
            return
        if command == "GARRA:POSICIONAR:E01":
            self.gripper_state = "sobre_esteira"
            return
        if command.startswith("DESTINO:"):
            self.destination = command.removeprefix("DESTINO:")
            return
        if command == "ESTEIRA:START":
            if self.destination is None:
                raise ArduinoCommandError("Nenhum destino foi configurado.")
            self.conveyor_state = "rodando"
            if self._suppress_arrival_events > 0:
                self._suppress_arrival_events -= 1
            else:
                event = encode_message(
                    "EVT",
                    cycle_id,
                    f"DESTINO_ALCANCADO:{self.destination}",
                )
                self._events.put(parse_message(event))
            return
        if command == "ESTEIRA:STOP":
            self.conveyor_state = "parada"
            return
        if command == "SISTEMA:RESET":
            self.gripper_state = "home"
            self.conveyor_state = "parada"
            self.destination = None
            self.reset_required = False
