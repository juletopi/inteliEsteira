from hardware.device import HardwareError
from time import monotonic


class DestinationConfirmationError(HardwareError):
    code = "DESTINATION_CONFIRMATION_ERROR"


class Conveyor:
    def __init__(self, device, *, arrival_sensor=None):
        self.device = device
        # Compatibilidade com os clientes anteriores que usavam apenas Arduino.
        self.arduino = device
        self.destination = None
        self.arrival_sensor = arrival_sensor
        self.arrival_source = getattr(device, "arrival_source", "evento_do_controlador")
        self.physical_arrival = False

    def set_destination(self, destination, cycle_id, timeout=2.0, retries=1):
        self.physical_arrival = False
        if self.arrival_sensor is not None:
            self.arrival_sensor.execute(f"SENSOR:ARMAR:{destination}", cycle_id, timeout=timeout, retries=retries)
        response = self.device.execute(
            f"DESTINO:{destination}",
            cycle_id,
            timeout=timeout,
            retries=retries,
        )
        self.destination = destination
        return response

    def start(self, cycle_id, timeout=2.0, retries=1):
        response = self.device.execute(
            "ESTEIRA:START",
            cycle_id,
            timeout=timeout,
            retries=retries,
        )
        if self.arrival_sensor is not None:
            self.arrival_sensor.execute(f"SENSOR:INICIAR:{self.destination}", cycle_id, timeout=timeout, retries=retries)
        return response

    def stop(self, cycle_id, timeout=2.0, retries=1):
        response = self.device.execute("ESTEIRA:STOP", cycle_id, timeout=timeout, retries=retries)
        if self.arrival_sensor is not None and self.arrival_sensor.is_connected():
            self.arrival_sensor.execute("SENSOR:DESARMAR", cycle_id, timeout=timeout, retries=0)
        return response

    def wait_until_destination(self, cycle_id, timeout=5.0, cancelled=None):
        deadline = monotonic() + timeout
        response = self.device.wait_for_event(
            "DESTINO_ALCANCADO",
            cycle_id,
            timeout=timeout,
            cancelled=cancelled,
        )
        self._confirm(response, self.device, cycle_id)
        if self.arrival_sensor is not None:
            response = self.arrival_sensor.wait_for_event("DESTINO_ALCANCADO", cycle_id, timeout=max(0.001, deadline - monotonic()), cancelled=cancelled)
            self._confirm(response, self.arrival_sensor, cycle_id)
        return response

    def _confirm(self, response, source_device, cycle_id):
        fields = response.payload.split(":")
        if (response.kind != "EVT" or response.cycle_id != cycle_id or len(fields) not in {2, 3}
                or fields[0] != "DESTINO_ALCANCADO" or fields[1] != self.destination):
            raise DestinationConfirmationError(f"Confirmacao {response.payload} difere do destino {self.destination}.")
        if len(fields) == 3 and fields[2] not in {"SENSOR", "SIMULADO", "MOVIMENTO_CALIBRADO"}:
            raise DestinationConfirmationError("Fonte de confirmacao de chegada desconhecida.")
        self.arrival_source = fields[2].lower() if len(fields) == 3 else getattr(source_device, "arrival_source", "evento_do_controlador")
        self.physical_arrival = self.arrival_source == "sensor"
