import unittest

from hardware.conveyor import Conveyor, DestinationConfirmationError
from hardware.mock import MockArduino
from hardware.protocol import parse_message


class ArrivalConfirmationTests(unittest.TestCase):
    def test_external_sensor_does_not_emit_arrival_before_conveyor_start(self):
        motor, sensor = MockArduino(), MockArduino()
        motor.connect()
        sensor.connect()
        conveyor = Conveyor(motor, arrival_sensor=sensor)
        conveyor.set_destination("R07", "unit_1")
        self.assertTrue(sensor._events.empty())
        conveyor.start("unit_1")
        event = conveyor.wait_until_destination("unit_1", timeout=0.1)
        self.assertEqual(event.payload, "DESTINO_ALCANCADO:R07:SIMULADO")
        self.assertFalse(conveyor.physical_arrival)
        commands = [parse_message(frame).payload for frame in sensor.command_log]
        self.assertEqual(commands, ["SENSOR:ARMAR:R07", "SENSOR:INICIAR:R07"])

    def test_receipt_requires_event_current_cycle_and_correct_destination(self):
        device = MockArduino()
        device.connect()
        conveyor = Conveyor(device)
        conveyor.destination = "R07"
        for frame in ("ACK:unit_1:DESTINO_ALCANCADO:R07:SENSOR", "EVT:old_unit:DESTINO_ALCANCADO:R07:SENSOR",
                      "EVT:unit_1:DESTINO_ALCANCADO:R08:SENSOR", "EVT:unit_1:DESTINO_ALCANCADO:R07:DESCONHECIDO"):
            with self.subTest(frame=frame), self.assertRaises(DestinationConfirmationError):
                conveyor._confirm(parse_message(frame), device, "unit_1")
        conveyor._confirm(parse_message("EVT:unit_1:DESTINO_ALCANCADO:R07:SENSOR"), device, "unit_1")
        self.assertTrue(conveyor.physical_arrival)
        self.assertEqual(conveyor.arrival_source, "sensor")


if __name__ == "__main__":
    unittest.main()
