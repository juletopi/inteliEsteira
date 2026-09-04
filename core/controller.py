class SystemController:
    def __init__(self, state, gripper, conveyor, camera):
        self.state = state
        self.gripper = gripper
        self.conveyor = conveyor
        self.camera = camera

    def process_next_product(self):
        # TODO: integrar captura, leitura do QR, classificação e comando de destino.
        raise NotImplementedError

    def reset(self):
        # TODO: enviar reset ao hardware e devolver o estado para IDLE.
        raise NotImplementedError
