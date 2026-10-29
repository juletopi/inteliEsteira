from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import create_app
from core.classifier import STATE_TO_MACROREGION


class RegionProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "DATABASE_PATH": Path(self.temp_directory.name) / "progress.db",
        })
        self.client = self.app.test_client()
        self.cycles = self.app.extensions["cycle_repository"]
        self.products = self.app.extensions["product_repository"]
        self.sequence = 0

    def tearDown(self):
        self.temp_directory.cleanup()

    def deliver(self, state, destination, *, simulated=False, finished=True):
        self.sequence += 1
        cycle_id = f"region-{self.sequence}"
        product_id = f"PROD-{self.sequence}"
        self.products.create(product_id, state)
        self.cycles.start(cycle_id, "")
        self.cycles.add_event(cycle_id, "MODO_OPERACAO", {"simulado": simulated})
        self.cycles.set_route(
            cycle_id,
            product_id=product_id,
            state=state,
            macroregion=STATE_TO_MACROREGION[state].value,
            destination=destination,
        )
        if finished:
            self.cycles.complete(cycle_id)

    def progress(self):
        return self.client.get("/api/status").get_json()["etapas_regioes"]

    def test_five_regions_have_two_fixed_states_each(self):
        progress = self.progress()
        self.assertEqual(progress["total_regioes"], 5)
        self.assertEqual(progress["total_estados"], 10)
        self.assertEqual(progress["estados_entregues"], 0)
        self.assertEqual(
            [[(state["uf"], state["destino"]) for state in region["estados"]]
             for region in progress["regioes"]],
            [[("RO", "R01"), ("AM", "R02")], [("SC", "R03"), ("PR", "R04")],
             [("SP", "R05"), ("MG", "R06")], [("BA", "R07"), ("PE", "R08")],
             [("MT", "R09"), ("GO", "R10")]],
        )

    def test_only_confirmed_physical_delivery_to_fixed_box_completes_stage(self):
        self.deliver("RO", "R01")
        self.deliver("AM", "R02")
        self.deliver("BA", "R07", simulated=True)
        self.deliver("SP", "R06")
        self.deliver("MG", "R06", finished=False)

        progress = self.progress()
        self.assertEqual(progress["estados_entregues"], 2)
        self.assertEqual(progress["regioes_completas"], 1)
        self.assertTrue(progress["regioes"][0]["concluida"])
        self.assertFalse(progress["regioes"][1]["concluida"])

    def test_new_round_resets_steps_without_deleting_history(self):
        self.deliver("RO", "R01")
        self.assertEqual(self.progress()["estados_entregues"], 1)

        response = self.client.post("/api/region-progress/new-round")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["etapas_regioes"]["estados_entregues"], 0)
        self.assertIsNotNone(response.get_json()["etapas_regioes"]["rodada_iniciada_em"])
        self.assertEqual(self.cycles.count_completed(), 1)

        reopened = create_app({"TESTING": True, "DATABASE_PATH": self.app.config["DATABASE_PATH"]})
        self.assertEqual(reopened.test_client().get("/api/status").get_json()["etapas_regioes"]["estados_entregues"], 0)

        self.deliver("PR", "R04")
        progress = self.progress()
        self.assertEqual(progress["estados_entregues"], 1)
        self.assertFalse(progress["regioes"][0]["estados"][0]["concluido"])
        self.assertTrue(progress["regioes"][1]["estados"][1]["concluido"])

    def test_new_round_waits_for_active_delivery(self):
        workflow = self.app.extensions["workflow"]
        with patch.object(workflow, "snapshot", return_value={"fluxo": {"ciclo_id": "in-progress"}}):
            response = self.client.post("/api/region-progress/new-round")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["erro"]["codigo"], "CYCLE_IN_PROGRESS")


if __name__ == "__main__":
    unittest.main()
