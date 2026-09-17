class Gripper:
    def __init__(self, arduino):
        self.arduino = arduino

    def pick_object(self, cycle_id, timeout=2.0, retries=1):
        return self.arduino.execute(
            "GARRA:PEGAR",
            cycle_id,
            timeout=timeout,
            retries=retries,
        )

    def release_object(self, cycle_id, timeout=2.0, retries=1):
        return self.arduino.execute(
            "GARRA:SOLTAR",
            cycle_id,
            timeout=timeout,
            retries=retries,
        )

    def home(self, cycle_id, timeout=2.0, retries=1):
        return self.arduino.execute(
            "GARRA:HOME",
            cycle_id,
            timeout=timeout,
            retries=retries,
        )
