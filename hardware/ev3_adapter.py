"""Cliente TCP do EV3; usa o contrato CMD/ACK/EVT/ERR da esteira."""

from collections import deque
import re
import socket
from threading import Condition, Event, Lock, RLock, Thread, current_thread
from time import monotonic

from hardware.device import HardwareError
from hardware.protocol import ProtocolError, encode_message, parse_message, validate_command
from hardware.telemetry import Telemetry


class EV3DisconnectedError(HardwareError):
    code = "EV3_DISCONNECTED"


class EV3CommandError(HardwareError):
    code = "EV3_COMMAND_ERROR"


class EV3TimeoutError(HardwareError):
    code = "EV3_TIMEOUT"


class EV3OperationCancelledError(HardwareError):
    code = "EV3_OPERATION_CANCELLED"


class EV3Adapter:
    mode = "ev3"
    arrival_source = "movimento_calibrado"

    def __init__(self, host, port=8765, *, token="", connect_timeout=2.0):
        self.host = str(host).strip()
        self.port = int(port)
        self._token = str(token).strip()
        self.connect_timeout = max(0.05, float(connect_timeout))
        self._socket = None
        self._reader = None
        self._stop_reader = Event()
        self._reader_error = None
        self._lifecycle_lock = RLock()
        self._write_lock = Lock()
        self._condition = Condition()
        self._messages = deque(maxlen=256)
        self.command_log = deque(maxlen=256)
        self.invalid_frames = deque(maxlen=20)
        self.telemetry = Telemetry()

    def connect(self):
        with self._lifecycle_lock:
            if self.is_connected():
                return True
            if not self.host or not 1 <= self.port <= 65535:
                raise EV3DisconnectedError("Configure EV3_HOST e EV3_PORT corretamente.")
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", self._token):
                raise EV3DisconnectedError(
                    "EV3_TOKEN deve conter 16 a 128 letras, numeros, '_' ou '-'."
                )
            connection = None
            try:
                connection = socket.create_connection(
                    (self.host, self.port), timeout=self.connect_timeout
                )
                connection.settimeout(0.1)
                connection.sendall(f"AUTH:{self._token}\n".encode("ascii"))
                buffer = self._authenticate(connection)
            except Exception as exc:
                if connection is not None:
                    connection.close()
                if isinstance(exc, EV3DisconnectedError):
                    raise
                raise EV3DisconnectedError(
                    f"Nao foi possivel conectar ao EV3 em {self.host}:{self.port}: {exc}."
                ) from exc
            self._socket = connection
            self._reader_error = None
            self._stop_reader = Event()
            with self._condition:
                self._messages.clear()
            self._reader = Thread(
                target=self._reader_loop,
                args=(connection, self._stop_reader, buffer),
                name="inteliesteira-ev3",
                daemon=True,
            )
            self._reader.start()
            return True

    def _authenticate(self, connection):
        deadline = monotonic() + self.connect_timeout
        buffer = b""
        while monotonic() < deadline:
            try:
                data = connection.recv(512)
            except socket.timeout:
                continue
            if not data:
                break
            buffer += data
            if len(buffer) > 512:
                break
            if b"\n" in buffer:
                line, remaining = buffer.split(b"\n", 1)
                if line.strip() == b"READY:EV3":
                    return remaining
                raise EV3DisconnectedError("EV3 rejeitou a autenticacao ou o protocolo.")
        raise EV3DisconnectedError("EV3 nao confirmou a autenticacao no prazo.")

    def disconnect(self):
        with self._lifecycle_lock:
            self._stop_reader.set()
            connection, reader = self._socket, self._reader
            self._socket = None
            if connection is not None:
                self._close(connection)
            with self._condition:
                self._condition.notify_all()
        if reader is not None and reader is not current_thread():
            reader.join(timeout=0.5)

    def is_connected(self):
        return bool(
            self._socket is not None
            and self._reader is not None
            and self._reader.is_alive()
            and self._reader_error is None
        )

    def execute(self, command, cycle_id, timeout=2.0, retries=1):
        try:
            normalized = validate_command(command)
            if normalized.startswith("GARRA:"):
                raise ProtocolError("O EV3 controla somente a esteira.")
            frame = encode_message("CMD", cycle_id, normalized)
        except ProtocolError as exc:
            raise EV3CommandError(str(exc)) from exc
        attempts = max(1, int(retries) + 1)
        for _attempt in range(attempts):
            self._send_frame(frame)
            response = self._wait_for_message(
                lambda message: message.cycle_id == cycle_id and (
                    (message.kind == "ACK" and message.payload == normalized)
                    or message.kind == "ERR"
                ),
                timeout,
            )
            if response is not None:
                self._check_error(response)
                return response
        raise EV3TimeoutError(
            f"EV3 nao confirmou {normalized} apos {attempts} tentativa(s)."
        )

    def wait_for_event(self, event_name, cycle_id, timeout=5.0, cancelled=None):
        expected = str(event_name).strip().upper()
        deadline = monotonic() + max(0.01, float(timeout))
        while monotonic() < deadline:
            if cancelled is not None and cancelled():
                raise EV3OperationCancelledError("Espera pelo EV3 interrompida.")
            response = self._wait_for_message(
                lambda message: message.cycle_id == cycle_id and (
                    message.kind == "ERR" or (
                        message.kind == "EVT"
                        and message.payload.split(":", 1)[0] == expected
                    )
                ),
                min(0.05, max(0.001, deadline - monotonic())),
            )
            if response is not None:
                self._check_error(response)
                return response
        raise EV3TimeoutError(f"Evento {expected} nao recebido do EV3 para {cycle_id}.")

    @staticmethod
    def _check_error(message):
        if message.kind == "ERR":
            raise EV3CommandError(f"EV3 informou uma falha: {message.payload}.")

    def _wait_for_message(self, predicate, timeout):
        deadline = monotonic() + max(0.001, float(timeout))
        with self._condition:
            while True:
                for index, message in enumerate(self._messages):
                    if predicate(message):
                        del self._messages[index]
                        return message
                if not self.is_connected():
                    raise EV3DisconnectedError("A conexao com o EV3 foi perdida.")
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def _send_frame(self, frame, *, record=True):
        connection = self._socket
        if not self.is_connected():
            raise EV3DisconnectedError("EV3 nao conectado.")
        try:
            with self._write_lock:
                connection.sendall((frame + "\n").encode("ascii"))
                if record:
                    self.command_log.append(frame)
                    self.telemetry.record("TX", parse_message(frame))
        except OSError as exc:
            self._connection_failed(connection, exc)
            raise EV3DisconnectedError("Falha ao enviar comando ao EV3.") from exc

    def _reader_loop(self, connection, stopped, buffer):
        last_received = monotonic()
        next_ping = last_received + 1.0
        try:
            while not stopped.is_set():
                now = monotonic()
                if now - last_received >= 4.0:
                    raise OSError("EV3 sem resposta ao heartbeat.")
                if now >= next_ping:
                    self._send_frame("PING", record=False)
                    next_ping = now + 1.0
                try:
                    data = connection.recv(512)
                except socket.timeout:
                    continue
                if not data:
                    raise OSError("EV3 encerrou a conexao.")
                buffer += data
                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    if len(raw) > 512:
                        raise OSError("Mensagem do EV3 excede o limite.")
                    if raw.strip() == b"PONG":
                        last_received = monotonic()
                        continue
                    try:
                        line = raw.decode("ascii").strip()
                        message = parse_message(line)
                        if message.kind not in {"ACK", "EVT", "ERR"}:
                            raise ProtocolError("Resposta inesperada.")
                    except (UnicodeError, ProtocolError):
                        self.invalid_frames.append(repr(raw)[:512])
                        continue
                    last_received = monotonic()
                    with self._condition:
                        self.telemetry.record("RX", message)
                        self._messages.append(message)
                        self._condition.notify_all()
                if len(buffer) > 512:
                    raise OSError("Mensagem do EV3 excede o limite.")
        except (OSError, HardwareError) as exc:
            if not stopped.is_set():
                self._connection_failed(connection, exc)

    def _connection_failed(self, connection, exc):
        if self._socket is connection:
            self._reader_error = str(exc)
            self._socket = None
            self._stop_reader.set()
            self._close(connection)
            with self._condition:
                self._condition.notify_all()

    @staticmethod
    def _close(connection):
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        connection.close()
