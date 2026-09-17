from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from storage.database import Database
from storage.repositories import CycleRepository, ProductRepository


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "storage.db"
        self.database = Database(self.database_path)
        self.database.initialize()
        self.products = ProductRepository(self.database)
        self.cycles = CycleRepository(self.database)

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_product_persists_when_repository_is_recreated(self):
        self.products.create("PROD-1", "CE")

        reopened = ProductRepository(Database(self.database_path))
        product = reopened.get("prod-1")

        self.assertEqual(product["id"], "PROD-1")
        self.assertEqual(product["uf"], "CE")

    def test_cycle_detail_contains_ordered_events(self):
        self.products.create("PROD-1", "SP")
        self.cycles.start("cycle-1", '{"produto_id":"PROD-1"}')
        self.cycles.set_route(
            "cycle-1",
            product_id="PROD-1",
            state="SP",
            macroregion="SUDESTE",
            destination="R05",
        )
        self.cycles.add_event("cycle-1", "DESTINO_DEFINIDO", {"destino": "R05"})
        self.cycles.complete("cycle-1")

        cycle = self.cycles.get("cycle-1", include_events=True)

        self.assertEqual(cycle["estado"], "FINALIZADO")
        self.assertEqual(cycle["destino"], "R05")
        self.assertEqual(
            [event["tipo"] for event in cycle["eventos"]],
            ["CICLO_INICIADO", "DESTINO_DEFINIDO", "CICLO_FINALIZADO"],
        )


if __name__ == "__main__":
    unittest.main()
