import json
from pathlib import Path
from threading import Thread
from time import monotonic, sleep
from tempfile import TemporaryDirectory
import unittest

from core.controller import CycleProcessingError, CycleStoppedError, SystemController
from core.state import SystemState
from hardware.conveyor import Conveyor
from hardware.gripper import Gripper
from hardware.mock import MockArduino
from hardware.protocol import parse_message
from storage.database import Database
from storage.repositories import CycleRepository, ProductRepository
from vision.mock import MockQRCodeCamera


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = TemporaryDirectory()
        database = Database(Path(self.temp_directory.name) / "test.db")
        database.initialize()
        self.products = ProductRepository(database)
        self.cycles = CycleRepository(database)
        self.arduino = MockArduino()
        self.arduino.connect()
        self.camera = MockQRCodeCamera()
        self.controller = SystemController(
            state=SystemState(),
            gripper=Gripper(self.arduino),
            conveyor=Conveyor(self.arduino),
            camera=self.camera,
            product_repository=self.products,
            cycle_repository=self.cycles,
            command_timeout=0.01,
            arrival_timeout=0.01,
            command_retries=1,
        )

    def tearDown(self):
        self.temp_directory.cleanup()

    def enqueue_product(self, product_id="PROD-1", state="CE"):
        self.products.create(product_id, state)
        self.camera.enqueue_qr_code(json.dumps({"produto_id": product_id}))

    def command_payloads(self):
        return [parse_message(frame).payload for frame in self.arduino.command_log]

    def test_processes_complete_cycle(self):
        self.enqueue_product()

        result = self.controller.process_next_product(
            occupancy={"R07": 3, "R08": 1}
        )

        self.assertEqual(result.macroregion, "NORDESTE")
        self.assertEqual(result.destination, "R08")
        self.assertEqual(
            self.command_payloads(),
            [
                "GARRA:PEGAR",
                "GARRA:SOLTAR",
                "GARRA:HOME",
                "DESTINO:R08",
                "ESTEIRA:START",
                "ESTEIRA:STOP",
            ],
        )
        snapshot = self.controller.state.snapshot()
        self.assertEqual(snapshot["estado"], "FINALIZADO")
        self.assertEqual(snapshot["destino"], "R08")
        self.assertEqual(snapshot["esteira"], "parada")
        stored_cycle = self.cycles.get(result.cycle_id, include_events=True)
        self.assertEqual(stored_cycle["estado"], "FINALIZADO")
        self.assertEqual(stored_cycle["produto_id"], "PROD-1")
        self.assertGreaterEqual(len(stored_cycle["eventos"]), 8)

    def test_retries_command_after_timeout(self):
        self.enqueue_product(state="PR")
        self.arduino.timeout_next("GARRA:PEGAR")

        result = self.controller.process_next_product()

        self.assertEqual(result.destination, "R03")
        self.assertEqual(self.command_payloads().count("GARRA:PEGAR"), 2)

    def test_enters_safe_error_state_when_command_fails(self):
        self.enqueue_product(state="SP")
        self.arduino.fail_next("DESTINO:R05", "MOTOR_BLOCKED")

        with self.assertRaises(CycleProcessingError) as context:
            self.controller.process_next_product()

        self.assertEqual(context.exception.code, "ARDUINO_COMMAND_ERROR")
        snapshot = self.controller.state.snapshot()
        self.assertEqual(snapshot["estado"], "ERRO")
        self.assertEqual(snapshot["esteira"], "parada")
        self.assertEqual(self.arduino.conveyor_state, "parada")

    def test_enters_error_when_camera_has_no_qr(self):
        with self.assertRaises(CycleProcessingError) as context:
            self.controller.process_next_product()

        self.assertEqual(context.exception.code, "QR_CODE_NOT_FOUND")
        self.assertEqual(self.controller.state.snapshot()["estado"], "ERRO")

    def test_reconnects_camera_before_starting_cycle(self):
        self.enqueue_product(state="AM")
        self.camera.disconnect()

        result = self.controller.process_next_product()

        self.assertTrue(self.camera.is_connected())
        self.assertEqual(result.destination, "R01")

    def test_reconnects_arduino_before_starting_cycle(self):
        self.enqueue_product(state="RS")
        self.arduino.disconnect()

        result = self.controller.process_next_product()

        self.assertTrue(self.arduino.is_connected())
        self.assertEqual(result.destination, "R03")

    def test_enters_error_when_arrival_sensor_times_out(self):
        self.enqueue_product(state="GO")
        self.arduino.suppress_next_arrival_event()

        with self.assertRaises(CycleProcessingError) as context:
            self.controller.process_next_product()

        self.assertEqual(context.exception.code, "ARDUINO_TIMEOUT")
        self.assertEqual(self.arduino.conveyor_state, "parada")

    def test_reset_recovers_from_error(self):
        with self.assertRaises(CycleProcessingError):
            self.controller.process_next_product()

        snapshot = self.controller.reset()

        self.assertEqual(snapshot["estado"], "IDLE")
        self.assertIsNone(snapshot["erro"])
        self.assertTrue(snapshot["arduino"])

    def test_operator_stop_keeps_system_stopped_instead_of_error(self):
        self.enqueue_product(state="BA")
        self.arduino.suppress_next_arrival_event()
        self.controller.arrival_timeout = 0.1
        errors = []

        def run_cycle():
            try:
                self.controller.process_next_product()
            except Exception as exc:  # A assercao abaixo verifica o tipo exato.
                errors.append(exc)

        worker = Thread(target=run_cycle)
        worker.start()
        deadline = monotonic() + 1
        while (
            self.controller.state.snapshot()["estado"] != "TRANSPORTANDO"
            and monotonic() < deadline
        ):
            sleep(0.001)

        self.controller.stop()
        worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], CycleStoppedError)
        self.assertEqual(self.controller.state.snapshot()["estado"], "PARADO")
        self.assertEqual(self.arduino.conveyor_state, "parada")


if __name__ == "__main__":
    unittest.main()
