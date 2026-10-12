from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from time import monotonic, sleep
import unittest

from app import create_app
from hardware.protocol import parse_message
from hardware.serial_simulator import ProtocolSimulator


class SerialSimulatorTests(unittest.TestCase):
    def start_simulator(self, **options):
        self.server = ProtocolSimulator(("127.0.0.1", 0), delay=0.01, **options)
        self.worker = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.worker.start()
        self.directory = TemporaryDirectory()
        self.app = create_app({"TESTING": True, "DATABASE_PATH": Path(self.directory.name) / "simulator.db",
                               "HARDWARE_MODE": "simulator", "ARDUINO_SIMULATOR_PORT": self.server.server_address[1],
                               "COMMAND_TIMEOUT": 0.1, "GRIPPER_COMPLETION_TIMEOUT": 0.3, "ARRIVAL_TIMEOUT": 0.3})
        self.client = self.app.test_client()
        self.flow = self.app.extensions["workflow"]
        self.flow.scan_interval = 0.005
        for product, state in (("FIRST", "CE"), ("SECOND", "AM")):
            self.app.extensions["product_repository"].create(product, state)

    def tearDown(self):
        if hasattr(self, "app"):
            self.flow.shutdown()
            self.app.extensions["arduino"].disconnect()
            self.server.shutdown()
            self.server.server_close()
            self.worker.join(timeout=1)
            self.directory.cleanup()

    def run_flow(self, products=("FIRST",)):
        self.assertEqual(self.client.post("/api/queue", json={"produto_ids": list(products)}).status_code, 201)
        for product in products:
            self.client.post("/api/simulation/camera", json={"produto_id": product})
        self.assertEqual(self.client.post("/api/flow/start").status_code, 202)
        deadline = monotonic() + 5
        while self.flow.running() and monotonic() < deadline:
            sleep(0.01)
        self.assertFalse(self.flow.running(), self.flow.snapshot())

    def test_full_protocol_flow_and_lost_ack_do_not_repeat_gripper_action(self):
        self.start_simulator(drop_ack=("GARRA:PEGAR",))
        self.run_flow()
        self.assertEqual(self.app.extensions["cycle_repository"].count_completed(), 1)
        picks = [key for key in self.server.commands_applied if key[1] == "GARRA:PEGAR"]
        self.assertEqual(len(picks), 1)
        wire = [parse_message(frame).payload for frame in self.app.extensions["arduino"].command_log]
        self.assertEqual(wire.count("GARRA:PEGAR"), 2)
        diagnostic = self.client.get("/api/diagnostics").get_json()
        self.assertEqual(diagnostic["dispositivos"][0]["modo"], "simulator")
        self.assertIsNotNone(diagnostic["dispositivos"][0]["ping_em"])
        frames = diagnostic["dispositivos"][0]["mensagens"]
        self.assertTrue(any(frame["tipo"] == "ACK" and frame["mensagem"] == "GARRA:PEGAR" for frame in frames))
        self.assertTrue(any(frame["tipo"] == "EVT" and frame["mensagem"] == "GARRA_COLETA_CONCLUIDA" for frame in frames))
        self.assertFalse(diagnostic["chegada"]["fisica"])
        self.assertEqual(diagnostic["chegada"]["fonte"], "simulado")

    def test_ack_only_gripper_fault_blocks_the_next_unit(self):
        self.start_simulator(suppress_events=("GARRA_COLETA_CONCLUIDA",))
        self.run_flow(("FIRST", "SECOND"))
        self.assertEqual(self.flow.repository.head()["estado"], "ERRO")
        commands = [command for _cycle, command in self.server.commands_applied]
        self.assertNotIn("GARRA:POSICIONAR:E01", commands)
        self.assertNotIn("ESTEIRA:START", commands)
        self.assertEqual(self.app.extensions["cycle_repository"].count_completed(), 0)

    def test_wrong_destination_is_not_accepted_as_arrival(self):
        self.start_simulator(wrong_destination=True)
        self.run_flow()
        self.assertEqual(self.flow.repository.head()["estado"], "ERRO")
        self.assertEqual(self.app.extensions["cycle_repository"].count_completed(), 0)

    def test_connection_loss_is_visible_and_does_not_advance_queue(self):
        self.start_simulator(disconnect_at="GARRA:POSICIONAR:E01")
        self.run_flow(("FIRST", "SECOND"))
        self.assertEqual(self.flow.repository.head()["estado"], "ERRO")
        self.assertFalse(self.app.extensions["arduino"].is_connected())
        self.assertEqual(self.app.extensions["cycle_repository"].count_completed(), 0)


if __name__ == "__main__":
    unittest.main()
