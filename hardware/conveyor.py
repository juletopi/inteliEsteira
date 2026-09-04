class Conveyor:
    def __init__(self, arduino):
        self.arduino = arduino

    def start(self):
        # TODO: enviar ESTEIRA:START e tratar a resposta do Arduino.
        raise NotImplementedError

    def stop(self):
        # TODO: enviar ESTEIRA:STOP e tratar a resposta do Arduino.
        raise NotImplementedError
