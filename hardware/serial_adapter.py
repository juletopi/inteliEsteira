"""Adaptador do protocolo da InteliEsteira para uma porta serial real."""

from __future__ import annotations

from collections import deque
from threading import Condition, Event, Lock, RLock, Thread, current_thread
from time import monotonic, sleep

from hardware.arduino import (
    Arduino,
    ArduinoCommandError,
    ArduinoDisconnectedError,
    ArduinoOperationCancelledError,
    ArduinoTimeoutError,
)
from hardware.protocol import (
    ProtocolError,
    ProtocolMessage,
    encode_message,
    parse_message,
    validate_command,
)


MAX_SERIAL_FRAME_LENGTH = 512


class SerialArduino(Arduino):
    """Arduino real com leitura em background e correlacao por ciclo."""

    mode = "serial"

    def __init__(
        self,
        port="COM3",
        baudrate=9600,
        *,
        read_timeout=0.1,
        write_timeout=1.0,
        boot_wait=2.0,
        serial_factory=None,
    ):
        self.port = str(port).strip()
        self.baudrate = int(baudrate)
        self.read_timeout = max(0.01, float(read_timeout))
        self.write_timeout = max(0.01, float(write_timeout))
        self.boot_wait = max(0.0, float(boot_wait))
        self._serial_factory = serial_factory or _create_serial_connection
        self._serial = None
        self._reader = None
        self._reader_error = None
        self._stop_reader = Event()
        self._lifecycle_lock = RLock()
        self._write_lock = Lock()
        self._messages: deque[ProtocolMessage] = deque()
        self._condition = Condition()
        self.invalid_frames: deque[str] = deque(maxlen=20)
        self.command_log: list[str] = []

    def connect(self) -> bool:
        with self._lifecycle_lock:
            if self.is_connected():
                return True
            self._close_serial()
            self._reader_error = None
            self._stop_reader.clear()

            if not self.port:
                raise ArduinoDisconnectedError("A porta serial do Arduino esta vazia.")

            try:
                connection = self._serial_factory(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=self.read_timeout,
                    write_timeout=self.write_timeout,
                )
            except Exception as exc:
                raise ArduinoDisconnectedError(
                    f"Nao foi possivel abrir o Arduino em {self.port}: {exc}."
                ) from exc

            if not getattr(connection, "is_open", False):
                try:
                    connection.close()
                except Exception:
                    pass
                raise ArduinoDisconnectedError(
                    f"A porta serial {self.port} nao foi aberta."
                )

            self._serial = connection
            if self.boot_wait:
                sleep(self.boot_wait)
            try:
                if hasattr(connection, "reset_input_buffer"):
                    connection.reset_input_buffer()
            except Exception as exc:
                self._close_serial()
                raise ArduinoDisconnectedError(
                    f"Falha ao preparar a porta {self.port}: {exc}."
                ) from exc

            with self._condition:
                self._messages.clear()

            self._reader = Thread(
                target=self._reader_loop,
                name=f"inteliesteira-serial-{self.port}",
                daemon=True,
            )
            self._reader.start()
            return True

    def disconnect(self) -> None:
        with self._lifecycle_lock:
            self._stop_reader.set()
            reader = self._reader
            self._close_serial()
            with self._condition:
                self._condition.notify_all()

        if (
            reader is not None
            and reader is not current_thread()
            and reader.is_alive()
        ):
            reader.join(timeout=max(0.2, self.read_timeout * 3))

        with self._lifecycle_lock:
            self._reader = None

    def is_connected(self) -> bool:
        with self._lifecycle_lock:
            return self._connection_available()

    def execute(
        self,
        command: str,
        cycle_id: str,
        timeout: float = 2.0,
        retries: int = 1,
    ) -> ProtocolMessage:
        try:
            normalized = validate_command(command)
        except ProtocolError as exc:
            raise ArduinoCommandError(str(exc)) from exc

        attempts = max(1, int(retries) + 1)
        timeout = max(0.01, float(timeout))
        self._require_connected()

        for _attempt in range(attempts):
            frame = encode_message("CMD", cycle_id, normalized)
            self._send_frame(frame)
            response = self._wait_for_message(
                lambda message: (
                    message.cycle_id == cycle_id
                    and (
                        (message.kind == "ACK" and message.payload == normalized)
                        or message.kind == "ERR"
                    )
                ),
                timeout=timeout,
            )
            if response is None:
                continue
            if response.kind == "ERR":
                raise ArduinoCommandError(
                    f"Arduino rejeitou {normalized}: {response.payload}."
                )
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
        expected = str(event_name).strip().upper()
        timeout = max(0.01, float(timeout))
        self._require_connected()
        deadline = monotonic() + timeout

        while True:
            if cancelled is not None and cancelled():
                raise ArduinoOperationCancelledError(
                    f"Espera pelo evento {expected} interrompida."
                )
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ArduinoTimeoutError(
                    f"Evento {expected} nao recebido para o ciclo {cycle_id}."
                )

            response = self._wait_for_message(
                lambda message: (
                    message.kind == "EVT"
                    and message.cycle_id == cycle_id
                    and message.payload.split(":", 1)[0] == expected
                ),
                timeout=min(remaining, 0.05),
            )
            if response is not None:
                return response

    def _send_frame(self, frame: str) -> None:
        self._require_connected()
        encoded = f"{frame}\n".encode("utf-8")
        try:
            with self._write_lock:
                self._serial.write(encoded)
                if hasattr(self._serial, "flush"):
                    self._serial.flush()
                self.command_log.append(frame)
        except Exception as exc:
            self._mark_connection_failed(exc)
            raise ArduinoDisconnectedError(
                f"Falha ao enviar comando para {self.port}: {exc}."
            ) from exc

    def _wait_for_message(self, predicate, *, timeout: float):
        deadline = monotonic() + max(0.001, timeout)
        with self._condition:
            while True:
                message = self._take_message(predicate)
                if message is not None:
                    return message
                if not self._connection_available():
                    detail = f": {self._reader_error}" if self._reader_error else ""
                    raise ArduinoDisconnectedError(
                        f"A conexao serial com {self.port} foi perdida{detail}."
                    )
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(timeout=remaining)

    def _take_message(self, predicate):
        for index, message in enumerate(self._messages):
            if predicate(message):
                del self._messages[index]
                return message
        return None

    def _reader_loop(self) -> None:
        while not self._stop_reader.is_set():
            try:
                raw = self._serial.readline()
            except Exception as exc:
                if not self._stop_reader.is_set():
                    self._mark_connection_failed(exc)
                return

            if not raw:
                continue
            try:
                text = raw.decode("utf-8").strip()
            except (AttributeError, UnicodeDecodeError):
                self.invalid_frames.append(repr(raw)[:MAX_SERIAL_FRAME_LENGTH])
                continue
            if not text or len(text) > MAX_SERIAL_FRAME_LENGTH:
                self.invalid_frames.append(text[:MAX_SERIAL_FRAME_LENGTH])
                continue
            try:
                message = parse_message(text)
            except ProtocolError:
                self.invalid_frames.append(text)
                continue

            with self._condition:
                self._messages.append(message)
                self._condition.notify_all()

    def _require_connected(self) -> None:
        if not self.is_connected():
            raise ArduinoDisconnectedError(
                f"Arduino nao conectado na porta {self.port}."
            )

    def _connection_available(self) -> bool:
        return bool(
            self._serial is not None
            and getattr(self._serial, "is_open", False)
            and self._reader is not None
            and self._reader.is_alive()
            and self._reader_error is None
        )

    def _mark_connection_failed(self, exc: Exception) -> None:
        self._reader_error = str(exc)
        self._stop_reader.set()
        self._close_serial()
        with self._condition:
            self._condition.notify_all()

    def _close_serial(self) -> None:
        connection = self._serial
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        self._serial = None


def list_serial_ports() -> list[dict[str, str]]:
    """Lista portas detectadas sem abrir nenhuma conexao."""

    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise ArduinoDisconnectedError(
            "A biblioteca pyserial nao esta instalada."
        ) from exc

    return [
        {
            "porta": port.device,
            "descricao": port.description,
            "hardware_id": port.hwid,
        }
        for port in sorted(list_ports.comports(), key=lambda item: item.device)
    ]


def _create_serial_connection(**kwargs):
    try:
        import serial
    except ImportError as exc:
        raise ArduinoDisconnectedError(
            "A biblioteca pyserial nao esta instalada."
        ) from exc
    return serial.Serial(**kwargs)
