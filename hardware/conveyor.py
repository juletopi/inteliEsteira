class Conveyor:
    def __init__(self, arduino):
        self.arduino = arduino
        self.destination = None

    def set_destination(self, destination, cycle_id, timeout=2.0, retries=1):
        response = self.arduino.execute(
            f"DESTINO:{destination}",
            cycle_id,
            timeout=timeout,
            retries=retries,
        )
        self.destination = destination
        return response

    def start(self, cycle_id, timeout=2.0, retries=1):
        return self.arduino.execute(
            "ESTEIRA:START",
            cycle_id,
            timeout=timeout,
            retries=retries,
        )

    def stop(self, cycle_id, timeout=2.0, retries=1):
        return self.arduino.execute(
            "ESTEIRA:STOP",
            cycle_id,
            timeout=timeout,
            retries=retries,
        )

    def wait_until_destination(self, cycle_id, timeout=5.0, cancelled=None):
        response = self.arduino.wait_for_event(
            "DESTINO_ALCANCADO",
            cycle_id,
            timeout=timeout,
            cancelled=cancelled,
        )
        _, destination = response.payload.split(":", 1)
        if destination != self.destination:
            raise RuntimeError(
                f"Destino confirmado ({destination}) difere do esperado ({self.destination})."
            )
        return response
