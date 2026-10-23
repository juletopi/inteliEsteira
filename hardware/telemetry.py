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
        if not payload.startswith(("GARRA", "SENSOR", "PRESENCA", "DESTINO", "ESTEIRA", "SISTEMA")):
            payload = "MENSAGEM_NAO_OPERACIONAL"
        with self._lock:
            # Heartbeats nao devem apagar o historico util da operacao.
            if payload == "SISTEMA:PING":
                if direction == "RX" and message.kind == "ACK":
                    self.last_ping_at = now
                return
            self._frames.append({"data": now, "direcao": direction, "tipo": message.kind,
                                 "ciclo_id": message.cycle_id, "mensagem": payload})

    def snapshot(self):
        with self._lock:
            return list(self._frames)
