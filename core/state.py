SYSTEM_STATES = (
    "IDLE",
    "QR_DETECTADO",
    "PRODUTO_IDENTIFICADO",
    "COMANDO_ENVIADO",
    "PROCESSANDO",
    "FINALIZADO",
    "ERRO",
)


class SystemState:
    def __init__(self):
        self.data = {
            "estado": "IDLE",
            "produto": None,
            "qr_code": None,
            "destino": None,
            "arduino": False,
            "garra": "livre",
            "esteira": "parada",
        }

    def snapshot(self):
        return self.data.copy()
