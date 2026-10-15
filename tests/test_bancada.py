from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.bancada import request_ok, smoke_test, virtual_bench, wait_for


class BenchTests(unittest.TestCase):
    def test_queue_routes_all_ten_destinations_through_both_controllers(self):
        with TemporaryDirectory() as folder:
            with virtual_bench(Path(folder) / "bench.db") as devices:
                smoke_test(*devices)

    def test_missing_pickup_completion_never_starts_ev3(self):
        with TemporaryDirectory() as folder:
            with virtual_bench(Path(folder) / "bench.db", arduino_options={
                "suppress_events": ("GARRA_COLETA_CONCLUIDA",),
            }) as (app, arduino, ev3):
                app.extensions["system_controller"].gripper_timeout = 0.15
                client = app.test_client()
                request_ok(client, "/api/simulation/camera", json={"produto_id": "TESTE-AM"})
                request_ok(client, "/api/flow/start")
                wait_for(app, lambda snapshot: snapshot["proxima_caixa_liberada"])
                request_ok(client, "/api/simulation/presence", json={"presente": True})
                # Esta falha e esperada; nao usar wait_for, que a reporta como excecao.
                worker = app.extensions["workflow"]._worker
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(app.extensions["workflow"].snapshot()["fluxo"]["estado"], "ERRO")
                self.assertEqual(app.extensions["workflow"].snapshot()["itens"], [])
                self.assertEqual(ev3.motion.codes, [])
                self.assertFalse(any(command == "GARRA:POSICIONAR:E01" for _cycle, command in arduino.commands_applied))

    def test_selected_bench_database_keeps_catalog_aruco_and_queue_on_restart(self):
        with TemporaryDirectory() as folder:
            database = Path(folder) / "bench.db"
            with virtual_bench(database) as (app, _arduino, _ev3):
                client = app.test_client()
                request_ok(client, "/api/products", json={"produto_id": "MEU-TESTE", "uf": "AM"})
                marker = request_ok(client, "/api/products/MEU-TESTE/aruco")
                request_ok(client, "/api/flow/start")
                wait_for(app, lambda snapshot: snapshot["proxima_caixa_liberada"])
                request_ok(client, "/api/simulation/camera", json={"produto_id": "MEU-TESTE"})
                request_ok(client, "/api/simulation/presence", json={"presente": True})
                wait_for(app, lambda snapshot: bool(snapshot["itens"]) and snapshot["itens"][0]["estado"] == "FINALIZADO")
            with virtual_bench(database) as (app, _arduino, _ev3):
                self.assertIsNotNone(app.extensions["product_repository"].get("MEU-TESTE"))
                same_marker = request_ok(app.test_client(), "/api/products/MEU-TESTE/aruco")
                self.assertEqual(marker, same_marker)
                self.assertEqual(app.extensions["workflow"].snapshot()["itens"][0]["produto_id"], "MEU-TESTE")
                self.assertFalse(app.extensions["workflow"].running())


if __name__ == "__main__":
    unittest.main()
