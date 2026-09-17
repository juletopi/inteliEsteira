from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock


SYSTEM_STATES = (
    "IDLE",
    "AGUARDANDO_OBJETO",
    "PEGANDO_OBJETO",
    "OBJETO_POSICIONADO",
    "LENDO_QR",
    "VALIDANDO_QR",
    "DESTINO_DEFINIDO",
    "TRANSPORTANDO",
    "FINALIZADO",
    "PARADO",
    "ERRO",
)


ALLOWED_TRANSITIONS = {
    "IDLE": {"AGUARDANDO_OBJETO"},
    "AGUARDANDO_OBJETO": {"PEGANDO_OBJETO", "PARADO", "ERRO"},
    "PEGANDO_OBJETO": {"OBJETO_POSICIONADO", "PARADO", "ERRO"},
    "OBJETO_POSICIONADO": {"LENDO_QR", "PARADO", "ERRO"},
    "LENDO_QR": {"VALIDANDO_QR", "PARADO", "ERRO"},
    "VALIDANDO_QR": {"DESTINO_DEFINIDO", "PARADO", "ERRO"},
    "DESTINO_DEFINIDO": {"TRANSPORTANDO", "PARADO", "ERRO"},
    "TRANSPORTANDO": {"FINALIZADO", "PARADO", "ERRO"},
    "FINALIZADO": {"AGUARDANDO_OBJETO", "IDLE"},
    "PARADO": {"IDLE"},
    "ERRO": {"IDLE"},
}


class InvalidStateTransition(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SystemState:
    def __init__(self):
        self._lock = RLock()
        self.data = {
            "estado": "IDLE",
            "ciclo_id": None,
            "produto": None,
            "qr_code": None,
            "uf": None,
            "macroregiao": None,
            "destino": None,
            "arduino": False,
            "camera": False,
            "garra": "livre",
            "esteira": "parada",
            "erro": None,
            "atualizado_em": _now_iso(),
        }

    def snapshot(self):
        with self._lock:
            return deepcopy(self.data)

    def transition(self, new_state, **changes):
        if new_state not in SYSTEM_STATES:
            raise InvalidStateTransition(f"Estado desconhecido: {new_state}.")

        with self._lock:
            current_state = self.data["estado"]
            if new_state not in ALLOWED_TRANSITIONS[current_state]:
                raise InvalidStateTransition(
                    f"Transicao invalida: {current_state} -> {new_state}."
                )
            self.data.update(changes)
            self.data["estado"] = new_state
            self.data["atualizado_em"] = _now_iso()
            return deepcopy(self.data)

    def update(self, **changes):
        protected_fields = {"estado", "atualizado_em"}
        if protected_fields.intersection(changes):
            raise ValueError("Use transition() para alterar o estado do sistema.")
        with self._lock:
            self.data.update(changes)
            self.data["atualizado_em"] = _now_iso()
            return deepcopy(self.data)

    def fail(self, code, message):
        with self._lock:
            self.data["estado"] = "ERRO"
            self.data["esteira"] = "parada"
            self.data["erro"] = {
                "codigo": code,
                "mensagem": message,
            }
            self.data["atualizado_em"] = _now_iso()
            return deepcopy(self.data)

    def stop(self):
        with self._lock:
            self.data["estado"] = "PARADO"
            self.data["esteira"] = "parada"
            self.data["atualizado_em"] = _now_iso()
            return deepcopy(self.data)

    def reset(self, *, arduino=False, camera=False):
        with self._lock:
            self.data.update(
                {
                    "estado": "IDLE",
                    "ciclo_id": None,
                    "produto": None,
                    "qr_code": None,
                    "uf": None,
                    "macroregiao": None,
                    "destino": None,
                    "arduino": arduino,
                    "camera": camera,
                    "garra": "livre",
                    "esteira": "parada",
                    "erro": None,
                    "atualizado_em": _now_iso(),
                }
            )
            return deepcopy(self.data)
