import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep
import unittest

from app import create_app
from ev3.bridge import BridgeController
from ev3.calibration import CALIBRATIONS, DESTINATION_TO_CODE
from ev3.main import EV3Motion
from ev3.server import serve_client
from ev3.simulator import SimulatedMotion
from hardware.ev3_adapter import (
    EV3Adapter, EV3CommandError, EV3DisconnectedError,
    EV3OperationCancelledError, EV3TimeoutError,
)
from hardware.protocol import parse_message


TOKEN = "token-apenas-para-testes-ev3"


class FakeMotion:
    def __init__(self):
        self.codes = []
        self.done = False
        self.stops = 0
        self.failure = None

    def start(self, code):
        self.codes.append(code)

    def poll(self):
        if self.failure:
            raise RuntimeError(self.failure)
        return self.done

    def stop(self):
        self.stops += 1


class EV3BridgeTests(unittest.TestCase):
    def setUp(self):
        self.motion = FakeMotion()
        self.bridge = BridgeController(self.motion)

    def prepare(self, destination="R03", cycle="cycle_1"):
        return self.bridge.handle(f"CMD:{cycle}:DESTINO:{destination}")

    def start(self, cycle="cycle_1"):
        return self.bridge.handle(f"CMD:{cycle}:ESTEIRA:START")

    def test_maps_all_backend_destinations_to_colleague_codes(self):
        expected = {"R01": 1, "R02": 2, "R03": 9, "R04": 10,
                    "R05": 7, "R06": 8, "R07": 3, "R08": 4,
                    "R09": 5, "R10": 6}
        self.assertEqual(DESTINATION_TO_CODE, expected)
        for destination, code in expected.items():
            with self.subTest(destination=destination):
                motion = FakeMotion()
                bridge = BridgeController(motion)
                bridge.handle(f"CMD:c1:DESTINO:{destination}")
                bridge.handle("CMD:c1:ESTEIRA:START")
                self.assertEqual(motion.codes, [code])

    def test_keeps_every_original_numeric_calibration(self):
        expected = [(12, 0.7, 20, -1.0), (12, 0.3, 20, -1.0),
                    (12, 1.85, 20, -1.0), (12, 1.47, 20, -1.0),
                    (12, 1.47, 20, 1.0), (12, 1.85, 20, 1.0),
                    (12, 0.3, 20, 1.0), (12, 0.7, 20, 1.0),
                    (12, 2.3, 20, 0.0), (12, -1.0, 20, 0.0)]
        self.assertEqual([CALIBRATIONS[i][1:] for i in range(1, 11)], expected)

    def test_acknowledges_before_motor_completion_and_then_emits_event(self):
        self.prepare()
        self.assertEqual(self.start(), ["ACK:cycle_1:ESTEIRA:START"])
        self.assertEqual(self.bridge.poll(), [])
        self.motion.done = True
        self.assertEqual(self.bridge.poll(), ["EVT:cycle_1:DESTINO_ALCANCADO:R03"])
        self.assertEqual(self.bridge.poll(), [])

    def test_retries_do_not_repeat_movements_even_after_stop_and_reset(self):
        self.prepare()
        self.start()
        self.start()
        self.motion.done = True
        self.bridge.poll()
        self.bridge.handle("CMD:cycle_1:ESTEIRA:STOP")
        self.bridge.handle("CMD:cycle_1:SISTEMA:RESET")
        self.prepare()
        response = self.start()
        self.assertEqual(self.motion.codes, [9])
        self.assertIn("EVT:cycle_1:DESTINO_ALCANCADO:R03", response)

    def test_rejects_missing_or_changed_destination_and_gripper_commands(self):
        self.assertIn("DESTINATION_REQUIRED", self.start()[0])
        self.prepare()
        self.assertIn("DESTINATION_LOCKED", self.prepare("R04")[0])
        self.assertIn("COMMAND_NOT_SUPPORTED", self.bridge.handle("CMD:c1:GARRA:PEGAR")[0])
        self.assertEqual(self.motion.codes, [])

    def test_invalid_destinations_and_frames_never_start_motors(self):
        self.assertIn("INVALID_DESTINATION", self.prepare("R99")[0])
        for line in ("CMD:c1", "ACK:c1:ESTEIRA:START", "CMD:bad id:ESTEIRA:START"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                self.bridge.handle(line)
        self.assertEqual(self.motion.codes, [])

    def test_busy_cycle_does_not_change_active_route(self):
        self.prepare()
        self.start()
        self.assertIn("BUSY", self.prepare("R04", "other")[0])
        self.assertEqual(self.motion.codes, [9])

    def test_stop_interrupts_motion_and_old_cycle_cannot_restart(self):
        self.prepare()
        self.start()
        self.bridge.handle("CMD:cycle_1:ESTEIRA:STOP")
        self.assertGreater(self.motion.stops, 0)
        self.assertEqual(self.bridge.poll(), [])
        self.assertIn("CYCLE_ABORTED", self.start()[0])
        self.assertIn("RESET_REQUIRED", self.prepare("R04", "other")[0])
        self.bridge.handle("CMD:other:SISTEMA:RESET")
        self.prepare("R04", "other")
        self.start("other")
        self.assertEqual(self.motion.codes, [9, 10])

    def test_connection_loss_requires_reset_and_blocks_replay(self):
        self.prepare()
        self.start()
        self.bridge.connection_lost()
        self.assertTrue(self.bridge.needs_reset)
        self.assertIn("CYCLE_ABORTED", self.start()[0])

    def test_motion_error_emits_error_not_arrival(self):
        self.prepare()
        self.start()
        self.motion.failure = "MOTION_TIMEOUT"
        self.assertEqual(self.bridge.poll(), ["ERR:cycle_1:ESTEIRA:START:MOTION_TIMEOUT"])
        self.assertTrue(self.bridge.needs_reset)

    def test_stop_before_destination_requires_reset(self):
        self.bridge.handle("CMD:c1:ESTEIRA:STOP")
        self.assertIn("RESET_REQUIRED", self.prepare()[0])
        self.assertEqual(self.motion.codes, [])

    def test_reset_aborts_prepared_cycle_instead_of_restarting_it(self):
        self.prepare()
        self.bridge.handle("CMD:cycle_1:SISTEMA:RESET")
        self.assertIn("CYCLE_ABORTED", self.start()[0])
        self.assertEqual(self.motion.codes, [])


class FakeMotor:
    def __init__(self):
        self.control = self
        self.finished = False
        self.commands = []
        self.brakes = 0

    def run_angle(self, **kwargs):
        self.commands.append(kwargs)
        self.finished = False

    def done(self):
        return self.finished

    def brake(self):
        self.brakes += 1


class EV3MotionTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.a, self.c = FakeMotor(), FakeMotor()
        self.motion = EV3Motion(self.a, self.c, lambda: self.now, "HOLD")

    def test_runs_nonblocking_a_then_pause_then_c(self):
        self.motion.start(3)
        self.assertEqual(self.a.commands, [{"speed": 120, "rotation_angle": 666.0,
                                            "then": "HOLD", "wait": False}])
        self.assertEqual(self.c.commands, [])
        self.assertFalse(self.motion.poll())
        self.a.finished = True
        self.motion.poll()
        self.now = 299
        self.motion.poll()
        self.assertEqual(self.c.commands, [])
        self.now = 300
        self.assertFalse(self.motion.poll())
        self.assertEqual(self.c.commands[0]["rotation_angle"], -360)
        self.c.finished = True
        self.assertTrue(self.motion.poll())

    def test_sul_skips_c_and_preserves_reverse_direction(self):
        self.motion.start(10)
        self.assertEqual(self.a.commands[0]["rotation_angle"], -360)
        self.a.finished = True
        self.motion.poll()
        self.now = 300
        self.assertTrue(self.motion.poll())
        self.assertEqual(self.c.commands, [])

    def test_stop_brakes_both_motors_without_completing_cycle(self):
        self.motion.start(1)
        self.motion.stop()
        self.assertEqual((self.a.brakes, self.c.brakes), (1, 1))
        self.assertFalse(self.motion.poll())

    def test_motion_timeout_brakes_both_motors(self):
        self.motion.start(9)
        self.now = 30000
        with self.assertRaisesRegex(RuntimeError, "MOTION_TIMEOUT"):
            self.motion.poll()
        self.assertEqual((self.a.brakes, self.c.brakes), (1, 1))

    def test_invalid_code_does_not_move_motors(self):
        with self.assertRaises(ValueError):
            self.motion.start(99)
        self.assertEqual(self.a.commands, [])

    def test_both_brakes_are_attempted_if_one_motor_fails(self):
        def fail():
            raise OSError("Motor A ausente.")
        self.a.brake = fail
        with self.assertRaises(OSError):
            self.motion.stop()
        self.assertEqual(self.c.brakes, 1)


class RecordingBridge(BridgeController):
    def __init__(self, motion):
        super().__init__(motion)
        self.commands = []
        self.drop_start_ack = False

    def handle(self, line):
        self.commands.append(line)
        responses = super().handle(line)
        if line.endswith(":ESTEIRA:START") and self.drop_start_ack:
            self.drop_start_ack = False
            return [frame for frame in responses if not frame.startswith("ACK:")]
        return responses


class TCPFixture:
    def setUp(self):
        self.motion = SimulatedMotion(delay=0.01)
        self.bridge = RecordingBridge(self.motion)
        self.adapters = []
        self.shutdown = Event()
        self.connection = None
        self.watchdog = 4.0
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.listener.listen(1)
        self.listener.settimeout(0.05)
        self.worker = Thread(target=self.serve, daemon=True)
        self.worker.start()

    def serve(self):
        while not self.shutdown.is_set():
            try:
                self.connection, _address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                serve_client(self.connection, self.bridge, TOKEN, watchdog=self.watchdog)
            except (OSError, ValueError):
                pass
            finally:
                self.connection = None

    def adapter(self, **kwargs):
        adapter = EV3Adapter("127.0.0.1", self.port, token=kwargs.get("token", TOKEN),
                             connect_timeout=0.2)
        self.adapters.append(adapter)
        return adapter

    def tearDown(self):
        for adapter in self.adapters:
            adapter.disconnect()
        self.shutdown.set()
        if self.connection is not None:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.listener.close()
        self.worker.join(timeout=1)
        self.assertFalse(self.worker.is_alive())

    def wait_until(self, predicate):
        deadline = monotonic() + 1
        while not predicate() and monotonic() < deadline:
            sleep(0.005)
        self.assertTrue(predicate())


class EV3AdapterTests(TCPFixture, unittest.TestCase):
    def test_authenticates_and_buffers_arrival_after_ack(self):
        adapter = self.adapter()
        adapter.connect()
        adapter.execute("DESTINO:R08", "c1", timeout=0.2)
        adapter.execute("ESTEIRA:START", "c1", timeout=0.2)
        event = adapter.wait_for_event("DESTINO_ALCANCADO", "c1", timeout=0.5)
        self.assertEqual(event.payload, "DESTINO_ALCANCADO:R08")
        self.assertEqual(self.motion.codes, [4])
        self.assertNotIn(TOKEN, " ".join(adapter.command_log))

    def test_bad_token_never_starts_motion(self):
        adapter = self.adapter(token="chave-incorreta-para-testes")
        with self.assertRaises(EV3DisconnectedError):
            adapter.connect()
        self.assertFalse(adapter.is_connected())
        self.assertEqual(self.motion.codes, [])

    def test_missing_configuration_is_reported_without_connection(self):
        for adapter in (EV3Adapter("", token=TOKEN), EV3Adapter("localhost", token="")):
            with self.subTest(host=adapter.host), self.assertRaises(EV3DisconnectedError):
                adapter.connect()

    def test_retry_lost_ack_does_not_repeat_motor_sequence(self):
        adapter = self.adapter()
        adapter.connect()
        self.bridge.drop_start_ack = True
        adapter.execute("DESTINO:R03", "c1", timeout=0.2)
        adapter.execute("ESTEIRA:START", "c1", timeout=0.05, retries=1)
        self.assertEqual(self.motion.codes, [9])
        self.assertEqual(list(adapter.command_log).count("CMD:c1:ESTEIRA:START"), 2)

    def test_errors_are_delivered_while_waiting_for_arrival(self):
        adapter = self.adapter()
        adapter.connect()
        self.bridge.motion = FakeMotion()
        adapter.execute("DESTINO:R05", "c1", timeout=0.2)
        adapter.execute("ESTEIRA:START", "c1", timeout=0.2)
        self.bridge.motion.failure = "MOTION_TIMEOUT"
        with self.assertRaisesRegex(EV3CommandError, "MOTION_TIMEOUT"):
            adapter.wait_for_event("DESTINO_ALCANCADO", "c1", timeout=0.5)

    def test_cancellation_timeout_and_gripper_rejection(self):
        adapter = self.adapter()
        adapter.connect()
        with self.assertRaises(EV3OperationCancelledError):
            adapter.wait_for_event("DESTINO_ALCANCADO", "c1", cancelled=lambda: True)
        with self.assertRaises(EV3TimeoutError):
            adapter.wait_for_event("DESTINO_ALCANCADO", "c1", timeout=0.02)
        with self.assertRaises(EV3CommandError):
            adapter.execute("GARRA:PEGAR", "c1")

    def test_heartbeat_keeps_idle_connection_alive(self):
        adapter = self.adapter()
        adapter.connect()
        sleep(1.2)
        self.assertTrue(adapter.is_connected())
        self.assertEqual(self.bridge.commands, [])
        self.assertEqual(self.motion.codes, [])

    def test_disconnect_stops_active_motion_and_requires_reset(self):
        self.motion.delay = 5
        adapter = self.adapter()
        adapter.connect()
        adapter.execute("DESTINO:R03", "c1", timeout=0.2)
        adapter.execute("ESTEIRA:START", "c1", timeout=0.2)
        adapter.disconnect()
        self.wait_until(lambda: self.bridge.needs_reset)
        self.assertIsNone(self.motion.deadline)
        adapter.connect()
        with self.assertRaisesRegex(EV3CommandError, "RESET_REQUIRED"):
            adapter.execute("DESTINO:R04", "c2", timeout=0.2)
        adapter.execute("SISTEMA:RESET", "c2", timeout=0.2)
        adapter.execute("DESTINO:R04", "c2", timeout=0.2)

    def test_server_watchdog_stops_motion_without_heartbeat(self):
        self.watchdog = 0.15
        self.motion.delay = 5
        connection = socket.create_connection(("127.0.0.1", self.port), timeout=0.5)
        self.addCleanup(connection.close)
        connection.sendall(("AUTH:" + TOKEN + "\nCMD:c1:DESTINO:R03\nCMD:c1:ESTEIRA:START\n").encode())
        self.wait_until(lambda: bool(self.motion.codes))
        self.wait_until(lambda: self.bridge.needs_reset)
        self.assertIsNone(self.motion.deadline)

    def test_server_accepts_split_and_coalesced_tcp_frames(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=0.5) as connection:
            with connection.makefile("r", encoding="ascii") as reader:
                connection.sendall(("AUTH:" + TOKEN + "\nCMD:c1:DEST").encode())
                self.assertEqual(reader.readline().strip(), "READY:EV3")
                connection.sendall(b"INO:R03\nCMD:c1:ESTEIRA:START\n")
                self.assertEqual(reader.readline().strip(), "ACK:c1:DESTINO:R03")
                self.assertEqual(reader.readline().strip(), "ACK:c1:ESTEIRA:START")
                self.assertEqual(reader.readline().strip(), "EVT:c1:DESTINO_ALCANCADO:R03")

    def test_commands_without_authentication_never_move_motors(self):
        connection = socket.create_connection(("127.0.0.1", self.port), timeout=0.5)
        self.addCleanup(connection.close)
        connection.sendall(b"CMD:c1:DESTINO:R03\nCMD:c1:ESTEIRA:START\n")
        self.assertEqual(connection.recv(512).strip(), b"ERROR:AUTH")
        self.assertEqual(self.motion.codes, [])

    def test_disconnect_is_detected_while_waiting_for_event(self):
        self.motion.delay = 5
        adapter = self.adapter()
        adapter.connect()
        adapter.execute("DESTINO:R03", "c1", timeout=0.2)
        adapter.execute("ESTEIRA:START", "c1", timeout=0.2)
        self.connection.shutdown(socket.SHUT_RDWR)
        with self.assertRaises(EV3DisconnectedError):
            adapter.wait_for_event("DESTINO_ALCANCADO", "c1", timeout=0.5)


class EV3APITests(TCPFixture, unittest.TestCase):
    def build_app(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        app = create_app({"TESTING": True, "DATABASE_PATH": Path(temporary.name) / "ev3.db",
                          "HARDWARE_MODE": "mock", "CAMERA_MODE": "mock",
                          "CONVEYOR_MODE": "ev3", "EV3_HOST": "127.0.0.1",
                          "EV3_PORT": self.port, "EV3_TOKEN": TOKEN,
                          "EV3_CONNECT_TIMEOUT": 0.2, "COMMAND_TIMEOUT": 0.3,
                          "ARRIVAL_TIMEOUT": 0.5})
        self.adapters.append(app.extensions["conveyor_device"])
        return app

    def test_full_api_cycle_routes_every_destination_without_arduino_conveyor_commands(self):
        app = self.build_app()
        client = app.test_client()
        states = ["AM", "AM", "PR", "PR", "SP", "SP", "CE", "CE", "GO", "GO"]
        for index, uf in enumerate(states, 1):
            destination = f"R{index:02d}"
            product = f"PROD-{index}"
            with self.subTest(destination=destination):
                self.assertEqual(client.post("/api/products", json={"produto_id": product, "uf": uf}).status_code, 201)
                unavailable = [f"R{index-1:02d}"] if index % 2 == 0 else []
                response = client.post("/api/cycles", json={"qr_code": json.dumps({"produto_id": product}),
                                                            "indisponiveis": unavailable})
                self.assertEqual(response.status_code, 201, response.get_json())
                self.assertEqual(response.get_json()["destino"], destination)
                self.assertEqual(self.motion.codes[-1], DESTINATION_TO_CODE[destination])
        arduino_commands = [parse_message(frame).payload for frame in app.extensions["arduino"].command_log]
        self.assertEqual(len(arduino_commands), 30)
        self.assertTrue(all(command.startswith("GARRA:") for command in arduino_commands))
        status = client.get("/api/status").get_json()
        self.assertTrue(status["arduino"])
        self.assertTrue(status["esteira_conectada"])
        self.assertEqual(status["esteira_modo"], "ev3")
        self.assertEqual(status["esteira_confirmacao"], "movimento_calibrado")
        self.assertNotIn(TOKEN, json.dumps(status))
        self.assertEqual(status["total_ciclos"], 10)

    def test_ev3_unavailable_prevents_gripper_from_moving(self):
        app = self.build_app()
        app.extensions["conveyor_device"]._token = ""
        response = app.test_client().post("/api/cycles", json={"qr_code": '{"produto_id":"P1"}'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["erro"]["codigo"], "EV3_DISCONNECTED")
        self.assertEqual(app.extensions["arduino"].command_log, [])
        status = app.test_client().get("/api/status").get_json()
        self.assertTrue(status["arduino"])
        self.assertFalse(status["esteira_conectada"])

    def test_connect_and_reset_reach_both_devices(self):
        app = self.build_app()
        client = app.test_client()
        self.assertEqual(client.post("/api/system/connect").status_code, 200)
        self.assertEqual(client.post("/api/system/reset").status_code, 200)
        self.assertIn("SISTEMA:RESET", app.extensions["arduino"].command_log[-1])
        self.assertIn("SISTEMA:RESET", self.bridge.commands[-1])

    def test_arrival_timeout_stops_ev3_and_persists_error(self):
        self.motion.delay = 5
        app = self.build_app()
        app.extensions["product_repository"].create("P1", "SC")
        response = app.test_client().post("/api/cycles", json={"qr_code": '{"produto_id":"P1"}'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["erro"]["codigo"], "EV3_TIMEOUT")
        self.assertIsNone(self.motion.deadline)
        stored = app.extensions["cycle_repository"].list_recent()[0]
        self.assertEqual(stored["estado"], "ERRO")

    def test_status_does_not_confuse_arduino_and_ev3_connection(self):
        app = self.build_app()
        app.extensions["conveyor_device"].connect()
        app.extensions["arduino"].disconnect()
        status = app.test_client().get("/api/status").get_json()
        self.assertFalse(status["arduino"])
        self.assertTrue(status["esteira_conectada"])

    def test_api_stop_interrupts_running_ev3_cycle(self):
        self.motion.delay = 5
        app = self.build_app()
        app.extensions["product_repository"].create("P1", "SC")
        results = []

        def cycle():
            with app.test_client() as client:
                results.append(client.post("/api/cycles", json={"qr_code": '{"produto_id":"P1"}'}))

        worker = Thread(target=cycle)
        worker.start()
        self.wait_until(lambda: app.extensions["system_controller"].state.snapshot()["estado"] == "TRANSPORTANDO")
        response = app.test_client().post("/api/system/stop")
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(results[0].get_json()["erro"]["codigo"], "CYCLE_STOPPED")
        self.assertEqual(app.test_client().get("/api/status").get_json()["estado"], "PARADO")
        self.assertIsNone(self.motion.deadline)
        self.assertEqual(app.test_client().post("/api/system/reset").status_code, 200)


if __name__ == "__main__":
    unittest.main()
