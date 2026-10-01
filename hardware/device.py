"""Erros comuns a controladores de hardware, independentemente do transporte."""


class HardwareError(RuntimeError):
    code = "HARDWARE_ERROR"

    def __init__(self, message):
        super().__init__(message)
        self.message = message
