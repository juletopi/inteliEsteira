"""Protocolo textual compartilhado entre o backend e o Arduino."""

from __future__ import annotations

from dataclasses import dataclass
import re


MESSAGE_TYPES = {"CMD", "ACK", "EVT", "ERR"}
VALID_DESTINATIONS = tuple(f"R{index:02d}" for index in range(1, 11))
CYCLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class ProtocolMessage:
    kind: str
    cycle_id: str
    payload: str


def encode_message(kind: str, cycle_id: str, payload: str) -> str:
    normalized_kind = str(kind).strip().upper()
    normalized_cycle_id = str(cycle_id).strip()
    normalized_payload = str(payload).strip().upper()

    if normalized_kind not in MESSAGE_TYPES:
        raise ProtocolError(f"Tipo de mensagem desconhecido: {normalized_kind}.")
    if not CYCLE_ID_PATTERN.fullmatch(normalized_cycle_id):
        raise ProtocolError("Identificador de ciclo invalido.")
    if not normalized_payload or "\n" in normalized_payload or "\r" in normalized_payload:
        raise ProtocolError("Payload do protocolo invalido.")

    return f"{normalized_kind}:{normalized_cycle_id}:{normalized_payload}"


def parse_message(raw_message: str) -> ProtocolMessage:
    if not isinstance(raw_message, str):
        raise ProtocolError("A mensagem serial deve ser uma string.")

    parts = raw_message.strip().split(":", 2)
    if len(parts) != 3:
        raise ProtocolError("Mensagem serial malformada.")

    kind, cycle_id, payload = parts
    encoded = encode_message(kind, cycle_id, payload)
    normalized_kind, normalized_cycle_id, normalized_payload = encoded.split(":", 2)
    return ProtocolMessage(normalized_kind, normalized_cycle_id, normalized_payload)


def validate_command(command: str) -> str:
    if not isinstance(command, str):
        raise ProtocolError("O comando deve ser uma string.")

    normalized = command.strip().upper()
    fixed_commands = {
        "GARRA:PEGAR",
        "GARRA:SOLTAR",
        "GARRA:HOME",
        "ESTEIRA:START",
        "ESTEIRA:STOP",
        "SISTEMA:RESET",
    }
    if normalized in fixed_commands:
        return normalized

    if normalized.startswith("DESTINO:"):
        destination = normalized.removeprefix("DESTINO:")
        if destination in VALID_DESTINATIONS:
            return normalized

    raise ProtocolError(f"Comando desconhecido: {normalized or '<vazio>'}.")
