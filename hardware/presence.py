"""Estado e bordas de presenca do HC-SR04, independentes da leitura da etiqueta."""

from threading import Condition
from time import monotonic
from datetime import datetime, timezone


class PresenceSensor:
    def __init__(self):
        self._condition = Condition()
        self._sequence = 0
        self._present = None
        self._distance = None
        self._received_at = None
        # Distancia ao vivo (mediana do firmware, 1/s); nao altera presenca nem bordas.
        self._live_distance = None
        self._live_at = None

    def update(self, present, distance=None):
        with self._condition:
            if self._present is not present:
                self._sequence += 1
            self._present = present
            self._distance = distance
            self._received_at = datetime.now(timezone.utc).isoformat() if present is not None else None
            self._condition.notify_all()

    def reset(self):
        self.update(None)

    def ingest_distance(self, line):
        fields = line.split(":")
        if len(fields) != 3 or fields[0] != "SENSOR" or fields[1] != "DISTANCIA":
            return False
        try:
            distance = int(fields[2])
        except ValueError:
            return False
        with self._condition:
            self._live_distance = distance if distance >= 0 else None
            self._live_at = datetime.now(timezone.utc).isoformat()
        return True

    def ingest(self, line):
        fields = line.split(":")
        if len(fields) != 3 or fields[0] != "SENSOR" or fields[1] not in {"PRESENTE", "AUSENTE"}:
            return False
        try:
            distance = int(fields[2])
        except ValueError:
            return False
        if fields[1] == "PRESENTE" and not 2 <= distance <= 100:
            return False
        self.update(fields[1] == "PRESENTE", distance)
        return True

    def snapshot(self):
        with self._condition:
            return {"modelo": "HC-SR04", "presente": self._present,
                    "distancia_cm": self._distance, "sequencia": self._sequence,
                    "recebido_em": self._received_at,
                    "distancia_atual_cm": self._live_distance, "medido_em": self._live_at}

    def wait_present(self, after, timeout=0.5, cancelled=None):
        deadline = monotonic() + timeout
        with self._condition:
            while monotonic() < deadline:
                if cancelled is not None and cancelled():
                    return None
                if self._present is True and self._sequence > after:
                    return self.snapshot()
                self._condition.wait(min(0.05, max(0, deadline - monotonic())))
        return None
