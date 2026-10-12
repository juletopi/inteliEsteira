class Gripper:
    def __init__(self, arduino, *, pickup_zone="P01", calibrated=False):
        self.arduino = arduino
        if pickup_zone != "P01":
            raise ValueError("A area de coleta disponivel e P01.")
        self.pickup_zone = pickup_zone
        self.calibrated = bool(calibrated)

    def set_pickup_area(self, cycle_id, timeout=2.0, retries=1):
        return self.arduino.execute(f"GARRA:AREA:{self.pickup_zone}", cycle_id, timeout=timeout, retries=retries)

    def pick_object(self, cycle_id, timeout=2.0, retries=1, event_timeout=30.0, cancelled=None):
        return self._operation("GARRA:PEGAR", "GARRA_COLETA_CONCLUIDA", cycle_id, timeout, retries, event_timeout, cancelled)

    def release_object(self, cycle_id, timeout=2.0, retries=1, event_timeout=30.0, cancelled=None):
        return self._operation("GARRA:SOLTAR", "GARRA_ENTREGA_CONCLUIDA", cycle_id, timeout, retries, event_timeout, cancelled)

    def place_on_conveyor(self, cycle_id, timeout=2.0, retries=1, event_timeout=30.0, cancelled=None):
        return self._operation("GARRA:POSICIONAR:E01", "GARRA_POSICIONAMENTO_CONCLUIDO", cycle_id, timeout, retries, event_timeout, cancelled)

    def home(self, cycle_id, timeout=2.0, retries=1, event_timeout=30.0, cancelled=None):
        return self._operation("GARRA:HOME", "GARRA_HOME_CONCLUIDO", cycle_id, timeout, retries, event_timeout, cancelled)

    def stop(self, cycle_id, timeout=2.0):
        return self.arduino.execute("GARRA:STOP", cycle_id, timeout=timeout, retries=0)

    def _operation(self, command, event, cycle_id, timeout, retries, event_timeout, cancelled):
        self.arduino.execute(command, cycle_id, timeout=timeout, retries=retries)
        return self.arduino.wait_for_event(event, cycle_id, timeout=event_timeout, cancelled=cancelled)
