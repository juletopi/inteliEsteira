"""Registro limitado das mensagens operacionais para diagnostico."""

from collections import deque
from datetime import datetime, timezone
from threading import RLock


class Telemetry:
    def __init__(self):
        self._lock = RLock()
        self._frames = deque(maxlen=200)
        self.last_ping_at = None

    def record(self, direction, message):
        now = datetime.now(timezone.utc).isoformat()
        payload = message.payload
        if not payload.startswith(("GARRA", "SENSOR", "DESTINO", "ESTEIRA", "SISTEMA")):
            payload = "MENSAGEM_NAO_OPERACIONAL"
        with self._lock:
            self._frames.append({"data": now, "direcao": direction, "tipo": message.kind,
                                 "ciclo_id": message.cycle_id, "mensagem": payload})
            if direction == "RX" and message.kind == "ACK" and payload == "SISTEMA:PING":
                self.last_ping_at = now

    def snapshot(self):
        with self._lock:
            return list(self._frames)
