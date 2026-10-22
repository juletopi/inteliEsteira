"""Sensor serial -> workflow -> OpenCV real -> ponte TCP EV3 com motores virtuais."""

from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
import unittest

import cv2
import numpy as np

from app import create_app
from hardware.protocol import parse_message
from hardware.serial_adapter import SerialArduino
from tests.test_serial_adapter import FakeSerialPort
from vision.aruco import ArucoCamera, generate_aruco_png


class IntegratedContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({"TESTING": True, "AUTO_OPERATION": False,
                              "DATABASE_PATH": Path(self.temp.name) / "integration.db",
                              "HARDWARE_MODE": "mock", "CAMERA_MODE": "mock",
                              "CONVEYOR_MODE": "ev3_simulator", "EV3_SIMULATOR_DELAY": 0.01,
                              "COMMAND_TIMEOUT": 0.3, "GRIPPER_COMPLETION_TIMEOUT": 0.5,
                              "ARRIVAL_TIMEOUT": 1.0, "REQUIRE_PHYSICAL_ARRIVAL": False})
        self.addCleanup(self.app.extensions["stop_conveyor_server"])
        self.addCleanup(self.app.extensions["conveyor_device"].disconnect)
        self.client = self.app.test_client()
        self.flow = self.app.extensions["workflow"]
        self.controller = self.app.extensions["system_controller"]
        self.port = FakeSerialPort(on_write=self.firmware_reply)
        self.serial = SerialArduino(port="VIRTUAL", boot_wait=0, read_timeout=0.005,
                                    serial_factory=lambda **kwargs: self.port)
        self.serial.mode = "simulator"
        self.serial.connect()
        self.addCleanup(self.serial.disconnect)
        self.addCleanup(self.flow.shutdown)
        self.controller.gripper.arduino = self.serial
        self.app.extensions["arduino"] = self.serial
        products = self.app.extensions["product_repository"]
        products.create("CUBO-SUL", "PR")
        product = products.ensure_aruco("CUBO-SUL")
        marker = cv2.imdecode(np.frombuffer(generate_aruco_png(product["aruco_id"]), np.uint8), cv2.IMREAD_COLOR)
        self.frame = marker
        self.valid_frame = marker.copy()
        camera = ArucoCamera(aruco_resolver=products.resolve_aruco, scan_timeout=0.15, retry_interval=0.01)
        camera.capture_frame = lambda: self.frame.copy()
        camera.is_connected = lambda: True
        self.controller.camera = camera
        self.app.extensions["camera"] = camera

    @staticmethod
    def firmware_reply(port, frame, attempt):
        message = parse_message(frame)
        port.inject(f"ACK:{message.cycle_id}:{message.payload}")
        if message.payload == "SISTEMA:STATUS":
            port.inject(f"EVT:{message.cycle_id}:SISTEMA_STATUS:RESET_REQUIRED=0:CALIBRATED=1:POSE_REFERENCED=1")
        elif message.payload.startswith("GARRA:PASSO:"):
            _, _, phase, order, *_pose = message.payload.split(":")
            port.inject(f"EVT:{message.cycle_id}:GARRA_PASSO_CONCLUIDO:{phase}:{order}")
        events = {"GARRA:PEGAR": "GARRA_COLETA_CONCLUIDA",
                  "GARRA:POSICIONAR:E01": "GARRA_POSICIONAMENTO_CONCLUIDO",
                  "GARRA:SOLTAR": "GARRA_ENTREGA_CONCLUIDA", "GARRA:HOME": "GARRA_HOME_CONCLUIDO"}
        if message.payload in events:
            port.inject(f"EVT:{message.cycle_id}:{events[message.payload]}")
        # PRESENCA:CONFIGURAR so confirma. Diferente do MockArduino, o dispositivo
        # nao tem acesso ao objeto PresenceSensor que existe no computador.

    def wait_for(self, condition):
        deadline = monotonic() + 4
        while not condition() and monotonic() < deadline:
            sleep(0.01)
        self.assertTrue(condition(), self.flow.snapshot())

    def start_with_fresh_presence(self):
        # Uma presenca anterior ao inicio nao pode esconder a confirmacao nova.
        self.port.inject("SENSOR:PRESENTE:4")
        self.assertIsNotNone(self.serial.presence.wait_present(0, timeout=0.5))
        response = self.client.post("/api/flow/start")
        self.assertEqual(response.status_code, 202)
        self.wait_for(lambda: self.flow.snapshot()["proxima_caixa_liberada"])
        self.port.inject("SENSOR:PRESENTE:4")

    def test_fresh_sensor_event_drives_gripper_camera_and_ev3_with_one_cycle(self):
        self.start_with_fresh_presence()
        self.wait_for(lambda: self.controller.cycles.count_completed() == 1)
        cycle = self.controller.cycles.list_recent()[0]
        self.assertEqual(cycle["produto_id"], "CUBO-SUL")
        self.assertEqual(cycle["destino"], "R03")
        arm = [parse_message(frame) for frame in self.serial.command_log if ":GARRA:" in frame]
        profile = self.app.extensions["gripper_profile_store"].load()
        expected = [f"GARRA:PERFIL:{len(profile['pickup'])}:{len(profile['delivery'])}:{profile['motion_delay_ms']}",
                    "GARRA:AREA:P01"]
        expected.extend(f"GARRA:PASSO:P:{index}:{step['B']}:{step['A']}:{step['C']}:{step['G']}:{step['pause_ms']}"
                        for index, step in enumerate(profile["pickup"], 1))
        expected.extend(f"GARRA:PASSO:E:{index}:{step['B']}:{step['A']}:{step['C']}:{step['G']}:{step['pause_ms']}"
                        for index, step in enumerate(profile["delivery"], 1))
        self.assertEqual([frame.payload for frame in arm], expected)
        self.assertEqual({frame.cycle_id for frame in arm}, {cycle["id"]})
        belt = [parse_message(frame) for frame in self.app.extensions["conveyor_device"].command_log]
        self.assertTrue(any(frame.payload == "ESTEIRA:START" and frame.cycle_id == cycle["id"] for frame in belt))
        events = [event["tipo"] for event in self.controller.cycles.get(cycle["id"], include_events=True)["eventos"]]
        self.assertLess(events.index("OBJETO_ENTREGUE_NA_ESTEIRA"), events.index("ARUCO_LIDO"))
        self.assertLess(events.index("ARUCO_LIDO"), events.index("ESTEIRA_INICIADA"))

    def test_missing_marker_waits_for_label_then_continues_to_belt(self):
        self.frame = np.full_like(self.frame, 255)
        self.start_with_fresh_presence()
        self.wait_for(lambda: self.flow.snapshot()["fluxo"]["aguardando_leitura"])
        self.assertTrue(self.flow.running())
        commands = [parse_message(frame).payload for frame in self.app.extensions["conveyor_device"].command_log]
        self.assertNotIn("ESTEIRA:START", commands)
        self.assertTrue(self.controller.cycles.list_recent()[0]["braco_concluido"])
        self.frame = self.valid_frame
        self.wait_for(lambda: self.controller.cycles.count_completed() == 1)
        commands = [parse_message(frame).payload for frame in self.app.extensions["conveyor_device"].command_log]
        self.assertIn("ESTEIRA:START", commands)

    def test_passive_camera_read_does_not_start_a_physical_cycle(self):
        decision = self.controller.identify_camera_frame()
        self.assertEqual(decision.product.product_id, "CUBO-SUL")
        self.assertEqual(self.serial.command_log, [])
        self.assertEqual(self.controller.cycles.list_recent(), [])


if __name__ == "__main__":
    unittest.main()
