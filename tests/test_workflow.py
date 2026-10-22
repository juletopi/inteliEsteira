from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
import unittest

from app import create_app
from hardware.protocol import parse_message
from storage.queue import QueueError
from vision.aruco import build_product_payload


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "automatic.db"
        self.config = {"TESTING": True, "AUTO_OPERATION": False, "DATABASE_PATH": self.path,
                       "COMMAND_TIMEOUT": 0.03, "GRIPPER_COMPLETION_TIMEOUT": 0.15, "ARRIVAL_TIMEOUT": 0.2}
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.flow = self.app.extensions["workflow"]
        self.hardware = self.app.extensions["arduino"]
        for product, state in (("FIRST", "CE"), ("SECOND", "SP")):
            self.app.extensions["product_repository"].create(product, state)

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

    def start(self):
        self.assertEqual(self.client.post("/api/flow/start").status_code, 202)
        self.wait_for(lambda: self.flow.snapshot()["proxima_caixa_liberada"])

    def present(self, product):
        self.client.post("/api/simulation/camera", json={"produto_id": product})
        self.client.post("/api/simulation/presence", json={"presente": False})
        self.client.post("/api/simulation/presence", json={"presente": True})

    def commands(self):
        return [parse_message(frame).payload for frame in self.hardware.command_log]

    def pickups(self):
        # Cada coleta comeca pelo primeiro passo de pega do perfil do calibrador.
        return sum(command.startswith("GARRA:PASSO:P:1:") for command in self.commands())

    def released(self):
        return any(command.startswith("GARRA:PASSO:E:") for command in self.commands())

    def completed(self, count):
        self.wait_for(lambda: len([i for i in self.flow.snapshot()["itens"] if i["estado"] == "FINALIZADO"]) == count
                      and self.flow.snapshot()["proxima_caixa_liberada"])

    def test_camera_alone_does_not_authorize_pickup_or_create_queue(self):
        self.start()
        self.client.post("/api/simulation/camera", json={"produto_id": "FIRST"})
        sleep(0.06)
        self.assertEqual(self.pickups(), 0)
        self.assertEqual(self.flow.snapshot()["itens"], [])
        self.assertEqual(self.client.post("/api/queue", json={"produto_ids": ["FIRST"]}).status_code, 409)

    def test_sensor_pickup_identification_transport_and_completion_in_that_order(self):
        self.start()
        self.present("FIRST")
        self.completed(1)
        item = self.flow.snapshot()["itens"][0]
        self.assertEqual((item["produto_id"], item["macroregiao"], item["destino"]), ("FIRST", "NORDESTE", "R07"))
        events = self.app.extensions["cycle_repository"].get(item["ciclo_id"], include_events=True)["eventos"]
        names = [event["tipo"] for event in events]
        for earlier, later in (("PRESENCA_CONFIRMADA", "OBJETO_COLETADO"),
                               ("OBJETO_ENTREGUE_NA_ESTEIRA", "ARUCO_LIDO"),
                               ("ARUCO_LIDO", "ESTEIRA_INICIADA"), ("ESTEIRA_INICIADA", "DESTINO_ALCANCADO")):
            self.assertLess(names.index(earlier), names.index(later))

    def test_queue_is_created_only_after_identification_on_the_belt(self):
        self.start()
        camera = self.app.extensions["camera"]
        original = camera.scan_aruco

        def read_on_belt(**kwargs):
            self.assertTrue(self.released())
            self.assertEqual(self.flow.snapshot()["itens"], [])
            return original(**kwargs)

        camera.scan_aruco = read_on_belt
        self.present("SECOND")
        self.completed(1)

    def test_completion_event_is_required_and_presence_during_transport_is_not_replayed(self):
        self.start()
        self.app.extensions["system_controller"].arrival_timeout = 2
        self.hardware.suppress_next_arrival_event()
        self.present("FIRST")
        self.wait_for(lambda: self.app.extensions["system_controller"].state.snapshot()["estado"] == "TRANSPORTANDO")
        self.assertFalse(self.flow.snapshot()["proxima_caixa_liberada"])
        self.assertEqual(self.flow.snapshot()["itens"][0]["estado"], "PROCESSANDO")
        self.assertTrue(self.flow.snapshot()["itens"][0]["braco_concluido"])
        production = self.client.get("/api/status").get_json()["producao"][0]
        self.assertTrue(production["braco_concluido"])
        self.assertIsNotNone(production["braco_finalizado_em"])
        self.assertEqual(production["transporte_estado"], "TRANSPORTANDO")
        self.assertTrue(production["simulado"])
        self.hardware.presence.update(False)
        self.hardware.presence.update(True, 5)
        self.assertEqual(self.pickups(), 1)
        cycle = self.flow.snapshot()["itens"][0]["ciclo_id"]
        self.hardware._events.put(parse_message(f"EVT:{cycle}:DESTINO_ALCANCADO:R07"))
        self.completed(1)
        sleep(0.06)
        self.assertEqual(self.pickups(), 1)
        self.present("SECOND")
        self.completed(2)
        self.assertEqual([i["produto_id"] for i in self.flow.snapshot()["itens"]], ["FIRST", "SECOND"])

    def test_same_product_is_another_unit_only_after_a_new_presence_edge(self):
        self.start()
        self.present("FIRST")
        self.completed(1)
        # Sem nova confirmacao do sensor apos o rearme, nao ha outra coleta.
        sleep(0.2)
        self.assertEqual(self.pickups(), 1)
        self.present("FIRST")
        self.completed(2)
        items = self.flow.snapshot()["itens"]
        self.assertNotEqual(items[0]["ciclo_id"], items[1]["ciclo_id"])

    def test_no_gripper_completion_never_reads_camera_or_starts_conveyor(self):
        self.start()
        self.hardware.suppress_next_gripper_event()
        self.present("FIRST")
        self.wait_for(lambda: not self.flow.running())
        self.assertEqual(self.flow.snapshot()["fluxo"]["estado"], "ERRO")
        self.assertEqual(self.flow.snapshot()["itens"], [])
        self.assertNotIn("ESTEIRA:START", self.commands())
        self.assertFalse(self.released())

    def test_unknown_label_waits_for_operator_discard_before_next_pickup(self):
        self.start()
        self.present("UNKNOWN")
        self.wait_for(lambda: self.flow.snapshot()["fluxo"]["aguardando_leitura"])
        self.assertTrue(self.flow.running())
        self.assertTrue(self.released())
        self.assertNotIn("ESTEIRA:START", self.commands())
        self.assertEqual(self.flow.snapshot()["fluxo"]["estado"], "LENDO_ARUCO")
        self.assertEqual(self.client.post("/api/flow/start").status_code, 409)
        self.assertEqual(self.client.post("/api/flow/discard").status_code, 200)
        self.wait_for(lambda: self.flow.snapshot()["proxima_caixa_liberada"])
        self.present("FIRST")
        self.wait_for(lambda: self.app.extensions["cycle_repository"].count_completed() == 1)
        self.assertEqual(self.flow.snapshot()["itens"][0]["produto_id"], "FIRST")

    def test_missing_conveyor_completion_does_not_finish_or_accept_next_unit(self):
        self.start()
        self.hardware.suppress_next_arrival_event()
        self.present("FIRST")
        self.wait_for(lambda: not self.flow.running())
        self.assertEqual(self.flow.snapshot()["itens"][0]["estado"], "ERRO")
        self.assertEqual(self.app.extensions["cycle_repository"].count_completed(), 0)
        self.assertFalse(self.flow.snapshot()["proxima_caixa_liberada"])

    def test_stop_interrupts_active_unit_and_requires_operator_recovery(self):
        self.start()
        self.hardware.suppress_next_arrival_event()
        self.app.extensions["system_controller"].arrival_timeout = 2
        self.present("FIRST")
        self.wait_for(lambda: self.app.extensions["system_controller"].state.snapshot()["estado"] == "TRANSPORTANDO")
        self.assertEqual(self.client.post("/api/system/stop").status_code, 200)
        self.wait_for(lambda: not self.flow.running())
        self.assertEqual(self.flow.snapshot()["itens"][0]["estado"], "INTERROMPIDO")
        self.assertEqual(self.client.post("/api/flow/start").status_code, 409)

    def test_other_process_and_manual_cycle_cannot_take_active_operation(self):
        self.start()
        second = create_app(self.config)
        self.assertEqual(second.test_client().post("/api/flow/start").status_code, 409)
        self.assertEqual(self.client.post("/api/cycles", json={"qr_code": build_product_payload("FIRST")}).status_code, 409)
        self.assertEqual(second.extensions["arduino"].command_log, [])

    def test_restart_reconciles_unfinished_cycle_without_pickup_replay(self):
        self.flow.repository.acquire("old")
        cycles = self.app.extensions["cycle_repository"]
        cycles.start("unfinished", "")
        self.flow.repository.set_info("old", ciclo_id="unfinished")
        with self.app.extensions["database"].connect() as connection:
            connection.execute("UPDATE operation_runtime SET lease_until = 0")
        restarted = create_app(self.config)
        self.assertEqual(restarted.extensions["workflow"].snapshot()["fluxo"]["estado"], "INTERROMPIDO")
        self.assertEqual(restarted.test_client().post("/api/flow/start").status_code, 409)
        self.assertEqual(cycles.get("unfinished")["estado"], "PARADO")

    def test_simulated_sensor_input_cannot_override_real_arduino(self):
        self.hardware.mode = "serial"
        self.assertEqual(self.client.post("/api/simulation/presence", json={"presente": True}).status_code, 403)
        self.assertEqual(self.client.post("/api/simulation/presence", json={"presente": "true"}).status_code, 403)

    def test_idle_heartbeat_failure_reconnects_without_pickup(self):
        self.start()
        resets = self.commands().count("SISTEMA:RESET")
        self.hardware.timeout_next("SISTEMA:PING", attempts=3)
        # Sem unidade em andamento: refaz a preparacao (novo RESET) e continua ativo.
        self.wait_for(lambda: self.commands().count("SISTEMA:RESET") > resets, timeout=8)
        self.wait_for(lambda: self.flow.snapshot()["proxima_caixa_liberada"])
        self.assertTrue(self.flow.running())
        self.assertIsNone(self.flow.snapshot()["fluxo"]["erro"])
        self.assertEqual(self.pickups(), 0)
        self.present("FIRST")
        self.completed(1)

    def test_heartbeat_failure_during_unit_stops_operation(self):
        self.start()
        self.hardware.suppress_next_arrival_event()
        self.app.extensions["system_controller"].arrival_timeout = 10
        self.present("FIRST")
        self.wait_for(lambda: self.app.extensions["system_controller"].state.snapshot()["estado"] == "TRANSPORTANDO")
        self.hardware.timeout_next("SISTEMA:PING", attempts=3)
        self.wait_for(lambda: not self.flow.running(), timeout=8)
        self.assertEqual(self.flow.snapshot()["fluxo"]["erro"]["codigo"], "HEARTBEAT_FAILED")

    def test_auto_sync_references_neutral_without_operator(self):
        self.flow.auto_sync_neutral = True
        self.hardware.pose_referenced = False
        self.start()
        self.assertTrue(any(command.startswith("SISTEMA:SYNC:") for command in self.commands()))
        self.present("FIRST")
        self.completed(1)

    def test_without_auto_sync_unreferenced_arm_waits_for_operator(self):
        self.hardware.pose_referenced = False
        self.assertEqual(self.client.post("/api/flow/start").status_code, 202)
        self.wait_for(lambda: self.flow.snapshot()["fluxo"].get("estado") == "AGUARDANDO_CONEXAO")
        self.assertFalse(any(command.startswith("SISTEMA:SYNC:") for command in self.commands()))

    def test_boot_waits_for_lease_of_abruptly_killed_process(self):
        from app import _start_automatic_operation

        # Processo anterior morto sem liberar a posse: ela expira em seguida.
        self.flow.repository.acquire("killed", lease=0.6)
        _start_automatic_operation(self.app, retry_interval=0.1)
        self.wait_for(lambda: self.flow.snapshot()["proxima_caixa_liberada"], timeout=5)
        self.assertTrue(self.flow.running())

    def test_sensor_is_rearmed_after_each_unit(self):
        self.start()
        configured = sum(command.startswith("PRESENCA:CONFIGURAR:") for command in self.commands())
        self.present("FIRST")
        self.completed(1)
        self.wait_for(lambda: sum(command.startswith("PRESENCA:CONFIGURAR:") for command in self.commands()) > configured)
        self.present("SECOND")
        self.completed(2)

    def test_background_inside_limit_is_reported(self):
        # Limite do perfil e 5 cm: fundo a 6 cm cairia na faixa de histerese.
        self.hardware.presence_background_cm = 6
        self.start()
        aviso = self.flow.snapshot()["fluxo"]["aviso"]
        self.assertIn("lendo 6 cm com o limite em 5 cm", aviso)
        self.assertIn("no máximo 3 cm", aviso)
        self.hardware.presence_background_cm = -1
        self.present("FIRST")
        self.completed(1)
        self.wait_for(lambda: self.flow.snapshot()["fluxo"]["aviso"] is None)

    def test_live_distance_does_not_create_presence_edges(self):
        sensor = self.hardware.presence
        before = sensor.snapshot()["sequencia"]
        self.assertTrue(sensor.ingest_distance("SENSOR:DISTANCIA:23"))
        self.assertTrue(sensor.ingest_distance("SENSOR:DISTANCIA:-1"))
        self.assertTrue(sensor.ingest_distance("SENSOR:DISTANCIA:9"))
        snapshot = sensor.snapshot()
        self.assertEqual((snapshot["sequencia"], snapshot["presente"], snapshot["distancia_atual_cm"]), (before, None, 9))
        self.assertEqual(self.client.post("/api/sensor/leitura").get_json()["mediana_cm"], -1)

    def test_clean_operator_stop_rearms_at_boot_but_error_does_not(self):
        self.start()
        self.client.post("/api/system/stop")
        self.wait_for(lambda: not self.flow.running())
        self.assertEqual(self.client.post("/api/flow/start").status_code, 409)
        # Novo processo (boot) com o mesmo banco: a parada limpa nao bloqueia o rearme.
        restarted = create_app(self.config)
        flow = restarted.extensions["workflow"]
        try:
            flow.start(at_boot=True)
            self.wait_for(lambda: flow.snapshot()["proxima_caixa_liberada"])
        finally:
            flow.shutdown()
        flow.repository.set_info(estado="ERRO")
        again = create_app(self.config).extensions["workflow"]
        with self.assertRaises(QueueError):
            again.start(at_boot=True)

    def test_single_late_heartbeat_does_not_stop_operation(self):
        self.start()
        self.hardware.timeout_next("SISTEMA:PING")
        sleep(2.5)
        self.assertTrue(self.flow.running())
        self.present("FIRST")
        self.completed(1)

    def test_real_gripper_without_calibration_does_not_arm_automatic_pickup(self):
        self.hardware.mode = "serial"
        self.hardware.firmware_calibrated = False
        self.assertEqual(self.client.post("/api/flow/start").status_code, 202)
        self.wait_for(lambda: self.flow.snapshot()["fluxo"].get("estado") == "AGUARDANDO_CONEXAO")
        self.assertEqual(self.pickups(), 0)
        self.assertFalse(self.flow.snapshot()["proxima_caixa_liberada"])

    def test_restart_reconciles_completed_cycle_before_queue_was_updated(self):
        self.flow.repository.acquire("old")
        cycles = self.app.extensions["cycle_repository"]
        cycles.start("done", build_product_payload("FIRST"))
        self.flow.repository.detected("old", "FIRST", "done")
        self.flow.repository.set_info("old", ciclo_id="done")
        cycles.complete("done")
        with self.app.extensions["database"].connect() as connection:
            connection.execute("UPDATE operation_runtime SET lease_until = 0")
        restarted = create_app(self.config)
        self.assertEqual(restarted.extensions["workflow"].snapshot()["itens"][0]["estado"], "FINALIZADO")
        self.assertEqual(restarted.extensions["arduino"].command_log, [])

    def test_initial_catalog_only_bootstraps_an_empty_database(self):
        import json

        seed = Path(self.directory.name) / "initial.json"
        document = {"version": 1, "aruco_dictionary": "DICT_4X4_250",
                    "products": [{"produto_id": "SEED", "uf": "CE", "ativo": True, "aruco_id": 17}]}
        seed.write_text(json.dumps(document), encoding="utf-8")
        config = {**self.config, "DATABASE_PATH": Path(self.directory.name) / "seed.db",
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

    def test_embedded_conveyor_server_runs_with_the_application(self):
        app = create_app({**self.config, "DATABASE_PATH": Path(self.directory.name) / "embedded.db", "CONVEYOR_MODE": "ev3_simulator", "EV3_SIMULATOR_DELAY": 0.02})
        flow = app.extensions["workflow"]
        try:
            app.extensions["product_repository"].create("FIRST", "CE")
            flow.start()
            self.wait_for(lambda: flow.snapshot()["proxima_caixa_liberada"])
            app.extensions["camera"].enqueue_qr_code(build_product_payload("FIRST"))
            app.extensions["arduino"].presence.update(True, 5)
            self.wait_for(lambda: app.extensions["cycle_repository"].count_completed() == 1)
            self.assertEqual(len(app.extensions["conveyor_server"].motion.codes), 1)
        finally:
            flow.shutdown()
            app.extensions["conveyor_device"].disconnect()
            app.extensions["stop_conveyor_server"]()

    def test_application_starts_observer_without_a_dashboard_start_request(self):
        app = create_app({**self.config, "TESTING": False, "AUTO_OPERATION": True,
                          "DATABASE_PATH": Path(self.directory.name) / "startup.db", "BOOTSTRAP_CATALOG": False,
                          "HARDWARE_MODE": "mock", "CONVEYOR_MODE": "mock", "CAMERA_MODE": "mock"})
        flow = app.extensions["workflow"]
        try:
            self.wait_for(lambda: flow.snapshot()["proxima_caixa_liberada"])
            self.assertTrue(flow.running())
            self.assertFalse(any(parse_message(frame).payload.startswith("GARRA:PASSO:") for frame in app.extensions["arduino"].command_log))
        finally:
            flow.shutdown()

    def test_clean_idle_restart_automatically_rearms_without_replaying_a_unit(self):
        self.start()
        self.flow.shutdown()
        restarted = create_app(self.config)
        flow = restarted.extensions["workflow"]
        try:
            flow.start()
            self.wait_for(lambda: flow.snapshot()["proxima_caixa_liberada"])
            self.assertEqual(flow.snapshot()["itens"], [])
            self.assertFalse(any(parse_message(frame).payload.startswith("GARRA:PASSO:") for frame in restarted.extensions["arduino"].command_log))
        finally:
            flow.shutdown()


if __name__ == "__main__":
    unittest.main()
