from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from storage.database import Database
from storage.catalog import export_catalog
from storage.repositories import ArucoMarkerConflictError, CycleRepository, ProductRepository


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

    def test_existing_database_migrates_without_losing_products_or_markers(self):
        path = self.database_path.parent / "legacy.db"
        with sqlite3.connect(path) as connection:
            connection.executescript("""
                CREATE TABLE products (
                    product_id TEXT PRIMARY KEY COLLATE NOCASE, state TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE aruco_markers (
                    marker_id INTEGER PRIMARY KEY, product_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE
                );
                INSERT INTO products VALUES ('LEGACY', 'CE', 1, '2026-01-01', '2026-01-01');
                INSERT INTO aruco_markers VALUES (17, 'LEGACY');
            """)
        connection.close()
        legacy = export_catalog(Database(path))
        self.assertEqual(legacy["products"][0]["aruco_id"], 17)
        migrated = Database(path)
        migrated.initialize()
        migrated.initialize()
        repository = ProductRepository(migrated)
        self.assertEqual(repository.get("LEGACY")["aruco_id"], 17)
        self.assertTrue(repository.delete("LEGACY"))
        self.assertIsNone(repository.get("LEGACY", include_inactive=True))
        with migrated.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM aruco_markers").fetchone()[0], 1)

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

    def test_concurrent_products_cannot_claim_the_same_marker(self):
        self.products.create("FIRST", "SP")
        self.products.create("SECOND", "CE")

        def claim(product_id):
            try:
                return self.products.ensure_aruco(product_id, marker_id=17)["id"]
            except ArucoMarkerConflictError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ("FIRST", "SECOND")))
        winners = [value for value in results if value is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(self.products.resolve_aruco(17)["id"], winners[0])
        loser = "SECOND" if winners[0] == "FIRST" else "FIRST"
        self.assertIsNone(self.products.get(loser)["aruco_id"])

    def test_automatic_marker_skips_restored_ids_and_keeps_existing_binding(self):
        self.products.create("RESTORED", "SP")
        self.products.create("NEW", "CE")
        self.products.ensure_aruco("RESTORED", marker_id=0)
        self.assertEqual(self.products.ensure_aruco("NEW")["aruco_id"], 1)
        reopened = ProductRepository(Database(self.database_path))
        self.assertEqual(reopened.ensure_aruco("restored")["aruco_id"], 0)
        self.products.deactivate("RESTORED")
        self.assertEqual(reopened.resolve_aruco(0)["id"], "RESTORED")
        self.assertFalse(reopened.resolve_aruco(0)["ativo"])


if __name__ == "__main__":
    unittest.main()
