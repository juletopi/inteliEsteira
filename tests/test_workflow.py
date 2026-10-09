import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, sleep
import unittest

from app import create_app
from hardware.protocol import parse_message
from vision.qrcode import build_product_qr_payload


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "queue.db"
        self.config = {"TESTING": True, "DATABASE_PATH": self.path, "COMMAND_TIMEOUT": 0.03,
                       "GRIPPER_COMPLETION_TIMEOUT": 0.1, "ARRIVAL_TIMEOUT": 0.1}
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.flow = self.app.extensions["workflow"]
        self.flow.scan_interval = 0.005
        self.products = self.app.extensions["product_repository"]
        for product, uf in (("FIRST", "CE"), ("SECOND", "SP"), ("THIRD", "AM")):
            self.products.create(product, uf)
        self.hardware = self.app.extensions["arduino"]

    def tearDown(self):
        self.flow.shutdown()
        self.assertFalse(self.flow._worker is not None and self.flow._worker.is_alive())
        self.directory.cleanup()

    def wait_for(self, predicate, timeout=3):
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            if predicate():
                return
            sleep(0.005)
        self.assertTrue(predicate(), self.flow.snapshot())

    def plan(self, ids):
        response = self.client.post("/api/queue", json={"produto_ids": ids})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["ids"]

    def scan(self, product):
        self.assertEqual(self.client.post("/api/simulation/camera", json={"produto_id": product}).status_code, 200)

    def commands(self):
        return [parse_message(frame).payload for frame in self.hardware.command_log]

    def test_planned_order_is_persistent_and_does_not_start_movement(self):
        self.plan(["SECOND", "FIRST", "FIRST"])
        restarted = create_app(self.config)
        items = restarted.extensions["workflow"].snapshot()["itens"]
        self.assertEqual([item["produto_id"] for item in items], ["SECOND", "FIRST", "FIRST"])
        self.assertTrue(all(item["estado"] == "PENDENTE" for item in items))
        self.assertEqual(self.hardware.command_log, [])

    def test_wrong_product_waits_and_camera_authorizes_only_the_queue_head(self):
        self.plan(["FIRST", "SECOND"])
        self.assertEqual(self.client.post("/api/flow/start").status_code, 202)
        self.scan("SECOND")
        self.wait_for(lambda: self.flow.snapshot()["fluxo"].get("detectado") == "SECOND")
        self.assertNotIn("GARRA:PEGAR", self.commands())
        self.assertNotIn("ESTEIRA:START", self.commands())
        self.scan("FIRST")
        self.wait_for(lambda: self.app.extensions["cycle_repository"].count_completed() == 1)
        self.assertEqual(self.flow.repository.head()["produto_id"], "SECOND")
        self.scan("SECOND")
        self.wait_for(lambda: not self.flow.running())
        cycles = self.app.extensions["cycle_repository"].list_recent()
        self.assertEqual([cycle["produto_id"] for cycle in reversed(cycles)], ["FIRST", "SECOND"])
        self.assertEqual(self.flow.snapshot()["fluxo"]["estado"], "CONCLUIDO")

    def test_repeated_product_requires_label_to_leave_capture_area(self):
        self.plan(["FIRST", "FIRST"])
        clear = Event()
        self.app.extensions["camera"].wait_until_clear = lambda timeout, cancelled: clear.wait(timeout)
        self.scan("FIRST")
        self.scan("FIRST")
        self.client.post("/api/flow/start")
        self.wait_for(lambda: self.flow.snapshot()["fluxo"].get("estado") == "AGUARDANDO_AREA_LIVRE")
        self.assertEqual(self.commands().count("GARRA:PEGAR"), 1)
        clear.set()
        self.wait_for(lambda: not self.flow.running())
        self.assertEqual(self.commands().count("GARRA:PEGAR"), 2)

    def test_ack_without_gripper_completion_does_not_release_or_start_conveyor(self):
        self.plan(["FIRST", "SECOND"])
        self.hardware.suppress_next_gripper_event()
        self.scan("FIRST")
        self.client.post("/api/flow/start")
        self.wait_for(lambda: not self.flow.running())
        self.assertEqual(self.flow.repository.head()["estado"], "ERRO")
        self.assertNotIn("GARRA:POSICIONAR:E01", self.commands())
        self.assertNotIn("GARRA:SOLTAR", self.commands())
        self.assertNotIn("ESTEIRA:START", self.commands())
        frames = self.hardware.telemetry.snapshot()
        self.assertTrue(any(frame["tipo"] == "ACK" and frame["mensagem"] == "GARRA:PEGAR" for frame in frames))
        self.assertEqual(self.app.extensions["cycle_repository"].count_completed(), 0)

    def test_missing_arrival_blocks_completion_and_the_next_product(self):
        self.plan(["FIRST", "SECOND"])
        self.hardware.suppress_next_arrival_event()
        self.scan("FIRST")
        self.scan("SECOND")
        self.client.post("/api/flow/start")
        self.wait_for(lambda: not self.flow.running())
        self.assertEqual(self.flow.repository.head()["estado"], "ERRO")
        self.assertEqual(self.commands().count("GARRA:PEGAR"), 1)
        self.assertEqual(self.app.extensions["cycle_repository"].count_completed(), 0)
        self.assertEqual(self.client.post("/api/system/reset").status_code, 200)
        self.assertEqual(self.client.post("/api/flow/start").status_code, 409)

    def test_stop_keeps_job_interrupted_and_requires_an_explicit_new_attempt(self):
        ids = self.plan(["FIRST"])
        self.hardware.suppress_next_gripper_event()
        self.app.extensions["system_controller"].gripper_timeout = 3
        self.scan("FIRST")
        self.client.post("/api/flow/start")
        self.wait_for(lambda: self.app.extensions["system_controller"].state.snapshot()["estado"] == "PEGANDO_OBJETO")
        old_cycle = self.flow.repository.head()["ciclo_id"]
        self.assertEqual(self.client.post("/api/system/stop").status_code, 200)
        self.wait_for(lambda: not self.flow.running())
        self.assertEqual(self.flow.repository.head()["estado"], "INTERROMPIDO")
        self.assertEqual(self.client.post("/api/system/reset").status_code, 200)
        self.assertEqual(self.client.post("/api/flow/start").status_code, 409)
        self.assertEqual(self.client.post(f"/api/queue/{ids[0]}/retry").status_code, 200)
        self.scan("FIRST")
        self.assertEqual(self.client.post("/api/flow/start").status_code, 202)
        self.wait_for(lambda: not self.flow.running())
        new_cycle = self.flow.repository.recent()[0]["ciclo_id"]
        self.assertNotEqual(new_cycle, old_cycle)
        self.assertEqual(self.app.extensions["cycle_repository"].get(old_cycle)["estado"], "PARADO")

    def test_second_process_and_manual_cycle_cannot_bypass_the_active_queue(self):
        ids = self.plan(["FIRST"])
        self.client.post("/api/flow/start")
        second = create_app(self.config)
        self.assertEqual(second.test_client().post("/api/flow/start").status_code, 409)
        self.assertEqual(self.client.post("/api/cycles", json={"qr_code": build_product_qr_payload("SECOND")}).status_code, 409)
        self.assertEqual(self.client.delete(f"/api/queue/{ids[0]}").status_code, 409)
        self.assertEqual(self.client.post("/api/queue", json={"produto_ids": ["SECOND"]}).status_code, 409)
        self.assertEqual(second.extensions["arduino"].command_log, [])

    def test_restart_marks_incomplete_job_interrupted_without_replaying_it(self):
        ids = self.plan(["FIRST"])
        self.flow.repository.acquire("old-process")
        self.flow.repository.claim("old-process", ids[0], "old-cycle")
        self.app.extensions["cycle_repository"].start("old-cycle", build_product_qr_payload("FIRST"))
        with self.app.extensions["database"].connect() as connection:
            connection.execute("UPDATE operation_runtime SET lease_until = 0")
        restarted = create_app(self.config)
        head = restarted.extensions["workflow"].repository.head()
        self.assertEqual(head["estado"], "INTERROMPIDO")
        self.assertEqual(restarted.extensions["arduino"].command_log, [])
        self.assertEqual(restarted.test_client().post("/api/flow/start").status_code, 409)

    def test_restart_reconciles_already_completed_cycle_without_repeating_pickup(self):
        ids = self.plan(["FIRST"])
        self.flow.repository.acquire("old-process")
        self.flow.repository.claim("old-process", ids[0], "old-cycle")
        self.app.extensions["system_controller"].process_next_product(
            identified_qr_code=build_product_qr_payload("FIRST"), cycle_id="old-cycle")
        with self.app.extensions["database"].connect() as connection:
            connection.execute("UPDATE operation_runtime SET lease_until = 0")
        restarted = create_app(self.config)
        self.assertEqual(restarted.extensions["workflow"].repository.items(), [])
        self.assertEqual(restarted.extensions["workflow"].repository.recent()[0]["estado"], "FINALIZADO")
        self.assertEqual(restarted.extensions["arduino"].command_log, [])

    def test_minimum_json_bootstraps_only_an_empty_database(self):
        seed = Path(self.directory.name) / "initial.json"
        document = {"version": 1, "aruco_dictionary": "DICT_4X4_250",
                    "products": [{"produto_id": "SEED", "uf": "CE", "ativo": True, "aruco_id": 17}]}
        seed.write_text(json.dumps(document), encoding="utf-8")
        config = {**self.config, "DATABASE_PATH": Path(self.directory.name) / "fresh.db",
                  "BOOTSTRAP_CATALOG": True, "BOOTSTRAP_CATALOG_PATH": seed}
        initial = create_app(config)
        self.assertEqual(initial.extensions["product_repository"].get("SEED")["aruco_id"], 17)
        initial.extensions["product_repository"].create("CUSTOM", "SP")
        document["products"][0].update({"uf": "AM", "aruco_id": 18})
        seed.write_text(json.dumps(document), encoding="utf-8")
        repeated = create_app(config)
        self.assertEqual(repeated.extensions["product_repository"].get("SEED")["uf"], "CE")
        self.assertEqual(repeated.extensions["product_repository"].get("SEED")["aruco_id"], 17)
        self.assertIsNotNone(repeated.extensions["product_repository"].get("CUSTOM"))

    def test_real_camera_cannot_receive_injected_identifiers(self):
        self.app.extensions["camera"].mode = "opencv"
        self.assertEqual(self.client.post("/api/simulation/camera", json={"produto_id": "FIRST"}).status_code, 403)
        self.assertEqual(self.client.post("/api/cycles", json={"qr_code": build_product_qr_payload("FIRST")}).status_code, 400)

    def test_failed_heartbeat_reports_communication_failure_without_movement(self):
        self.plan(["FIRST"])
        self.assertEqual(self.client.post("/api/flow/start").status_code, 202)
        self.hardware.timeout_next("SISTEMA:PING")
        self.wait_for(lambda: not self.flow.running())
        info = self.flow.snapshot()["fluxo"]
        self.assertEqual(info["estado"], "ERRO")
        self.assertEqual(info["erro"]["codigo"], "HEARTBEAT_FAILED")
        self.assertNotIn("GARRA:PEGAR", self.commands())

    def test_real_gripper_requires_calibrated_profiles_before_start(self):
        self.plan(["FIRST"])
        self.hardware.mode = "serial"
        self.assertEqual(self.client.post("/api/flow/start").status_code, 409)
        self.assertNotIn("GARRA:PEGAR", self.commands())

    def test_claimed_real_hardware_does_not_finish_on_simulated_arrival(self):
        self.hardware.mode = "serial"
        controller = self.app.extensions["system_controller"]
        controller.gripper.calibrated = True
        controller.require_physical_arrival = True
        self.plan(["FIRST"])
        self.scan("FIRST")
        self.assertEqual(self.client.post("/api/flow/start").status_code, 202)
        self.wait_for(lambda: not self.flow.running())
        self.assertEqual(self.flow.repository.head()["estado"], "ERRO")
        self.assertEqual(self.app.extensions["cycle_repository"].count_completed(), 0)

    def test_opencv_aruco_frames_drive_the_chosen_queue_without_typed_identifiers(self):
        import cv2
        import numpy as np
        from vision.qrcode import QRCodeCamera, generate_aruco_png
        self.products.ensure_aruco("FIRST", marker_id=17)
        self.products.ensure_aruco("SECOND", marker_id=18)
        first = cv2.imdecode(np.frombuffer(generate_aruco_png(17), dtype=np.uint8), cv2.IMREAD_COLOR)
        second = cv2.imdecode(np.frombuffer(generate_aruco_png(18), dtype=np.uint8), cv2.IMREAD_COLOR)
        current_frame = [first]
        camera = QRCodeCamera(cv2_module=cv2, aruco_resolver=self.products.resolve_aruco,
                              retry_interval=0.01, duplicate_cooldown=0)
        camera.capture_frame = lambda: current_frame[0]
        camera.connect = lambda: True
        camera.is_connected = lambda: True
        self.app.extensions["camera"] = camera
        self.app.extensions["system_controller"].camera = camera
        self.plan(["SECOND", "FIRST"])
        self.assertEqual(self.client.post("/api/flow/start").status_code, 202)
        self.wait_for(lambda: self.flow.snapshot()["fluxo"].get("detectado") == "FIRST")
        self.assertNotIn("GARRA:PEGAR", self.commands())
        current_frame[0] = second
        self.wait_for(lambda: self.app.extensions["cycle_repository"].count_completed() == 1)
        current_frame[0] = np.full_like(first, 255)
        self.wait_for(lambda: self.flow.snapshot()["fluxo"].get("estado") == "AGUARDANDO_LEITURA" and
                      self.flow.snapshot()["fluxo"].get("esperado") == "FIRST")
        current_frame[0] = first
        self.wait_for(lambda: not self.flow.running())
        cycles = self.app.extensions["cycle_repository"].list_recent()
        self.assertEqual([cycle["produto_id"] for cycle in reversed(cycles)], ["SECOND", "FIRST"])


if __name__ == "__main__":
    unittest.main()
