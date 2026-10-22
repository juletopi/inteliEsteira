class Gripper:
    def __init__(self, arduino, *, pickup_zone="P01", calibrated=False):
        self.arduino = arduino
        if pickup_zone != "P01":
            raise ValueError("A area de coleta disponivel e P01.")
        self.pickup_zone = pickup_zone
        self.calibrated = bool(calibrated)

    def set_pickup_area(self, cycle_id, timeout=2.0, retries=1):
        return self.arduino.execute(f"GARRA:AREA:{self.pickup_zone}", cycle_id, timeout=timeout, retries=retries)

    def configure_profile(self, profile, cycle_id, timeout=2.0, retries=1):
        command = f"GARRA:PERFIL:{len(profile['pickup'])}:{len(profile['delivery'])}:{profile['motion_delay_ms']}"
        return self.arduino.execute(command, cycle_id, timeout=timeout, retries=retries)

    def move_profile_step(self, phase, index, step, cycle_id, *, timeout=2.0, retries=1,
                          event_timeout=30.0, cancelled=None):
        phase_code = "P" if phase == "pickup" else "E"
        command = (f"GARRA:PASSO:{phase_code}:{index}:{step['B']}:{step['A']}:{step['C']}:{step['G']}:{step['pause_ms']}")
        self.arduino.execute(command, cycle_id, timeout=timeout, retries=retries)
        return self.arduino.wait_for_event("GARRA_PASSO_CONCLUIDO", cycle_id,
                                           timeout=event_timeout, cancelled=cancelled)

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
