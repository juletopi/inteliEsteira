"""Contrato usado pelos adaptadores de Arduino real e simulado."""

from __future__ import annotations

from abc import ABC, abstractmethod

from hardware.device import HardwareError
from hardware.protocol import ProtocolMessage


class ArduinoError(HardwareError):
    code = "ARDUINO_ERROR"


class ArduinoDisconnectedError(ArduinoError):
    code = "ARDUINO_DISCONNECTED"


class ArduinoCommandError(ArduinoError):
    code = "ARDUINO_COMMAND_ERROR"


class ArduinoTimeoutError(ArduinoError):
    code = "ARDUINO_TIMEOUT"


class ArduinoOperationCancelledError(ArduinoError):
    code = "ARDUINO_OPERATION_CANCELLED"


class Arduino(ABC):
    """Interface independente da biblioteca serial usada na implementacao real."""

    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def execute(
        self,
        command: str,
        cycle_id: str,
        timeout: float = 2.0,
        retries: int = 1,
    ) -> ProtocolMessage:
        raise NotImplementedError

    @abstractmethod
    def wait_for_event(
        self,
        event_name: str,
        cycle_id: str,
        timeout: float = 5.0,
        cancelled=None,
    ) -> ProtocolMessage:
        raise NotImplementedError

    @abstractmethod
    def is_connected(self) -> bool:
        raise NotImplementedError
