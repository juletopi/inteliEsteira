class Gripper:
    def __init__(self, arduino):
        self.arduino = arduino

    def pick_object(self):
        # TODO: enviar GARRA:PEGAR e tratar a resposta do Arduino.
        raise NotImplementedError

    def release_object(self):
        # TODO: enviar GARRA:SOLTAR e tratar a resposta do Arduino.
        raise NotImplementedError

    def home(self):
        # TODO: enviar GARRA:HOME.
        raise NotImplementedError
