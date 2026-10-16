from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import create_app
from storage.automatic_catalog import AutomaticCatalog, CatalogPersistenceError
from storage.catalog import export_catalog
from storage.database import Database
from storage.repositories import ArucoMarkerConflictError, ProductRepository


class AutomaticCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "inteliesteira.json"
        self.database, self.products = self.open_database(self.root / "original.db", self.path)

    def tearDown(self):
        self.temp.cleanup()

    def open_database(self, path, catalog):
        database = Database(path)
        database.initialize()
        AutomaticCatalog(database, catalog).initialize()
        return database, ProductRepository(database)

    def document(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_every_catalog_change_is_saved_automatically(self):
        self.products.create("BOX", "AM")
        self.assertEqual(self.document()["products"][0]["uf"], "AM")
        self.products.ensure_aruco("BOX", marker_id=37)
        self.assertEqual(self.document()["products"][0]["aruco_id"], 37)
        self.products.update("BOX", state="SP", active=False)
        self.assertEqual(self.document()["products"][0]["uf"], "SP")
        self.assertFalse(self.document()["products"][0]["ativo"])
        self.products.delete("BOX")
        self.assertTrue(self.document()["products"][0]["excluido"])

    def test_copying_only_json_to_another_machine_restores_all_ids_on_startup(self):
        self.products.create("BOX", "AM")
        self.products.ensure_aruco("BOX", marker_id=37)
        self.products.create("DELETED", "SP")
        self.products.ensure_aruco("DELETED", marker_id=12)
        self.products.delete("DELETED")
        target = self.root / "other-machine" / "inteliesteira.json"
        target.parent.mkdir()
        shutil.copyfile(self.path, target)
        database, products = self.open_database(target.with_suffix(".db"), target)
        self.assertEqual(products.resolve_aruco(37)["id"], "BOX")
        self.assertEqual(products.resolve_aruco(37)["uf"], "AM")
        self.assertIsNone(products.get("DELETED"))
        self.assertEqual(export_catalog(database), self.document())
        products.create("NEW", "CE")
        with self.assertRaises(ArucoMarkerConflictError):
            products.ensure_aruco("NEW", marker_id=12)

    def test_updated_json_is_loaded_even_with_an_existing_database(self):
        self.products.create("BOX", "AM")
        self.products.ensure_aruco("BOX", marker_id=37)
        document = self.document()
        document["products"][0].update(uf="CE", ativo=False)
        document["products"].append({"produto_id": "OTHER", "uf": "PR", "ativo": True, "aruco_id": 5})
        self.path.write_text(json.dumps(document), encoding="utf-8")
        database, products = self.open_database(self.database.path, self.path)
        self.assertEqual(products.get("BOX", include_inactive=True)["uf"], "CE")
        self.assertFalse(products.get("BOX", include_inactive=True)["ativo"])
        self.assertEqual(products.resolve_aruco(5)["id"], "OTHER")

    def test_existing_local_database_is_migrated_without_losing_products(self):
        legacy = Database(self.root / "legacy.db")
        legacy.initialize()
        products = ProductRepository(legacy)
        products.create("LOCAL", "CE")
        products.ensure_aruco("LOCAL", marker_id=8)
        catalog = self.root / "legacy.json"
        AutomaticCatalog(legacy, catalog).initialize()
        self.assertEqual(json.loads(catalog.read_text())["products"][0]["aruco_id"], 8)

    def test_empty_database_keeps_an_empty_valid_json(self):
        self.assertEqual(self.document()["products"], [])
        self.open_database(self.database.path, self.path)
        self.assertEqual(self.products.list(), [])

    def test_first_upgrade_merges_existing_json_and_preserves_local_edits(self):
        self.products.create("REMOTE", "AM")
        self.products.ensure_aruco("REMOTE", marker_id=7)
        legacy = Database(self.root / "legacy.db")
        legacy.initialize()
        products = ProductRepository(legacy)
        products.create("REMOTE", "SP")
        products.ensure_aruco("REMOTE", marker_id=7)
        products.create("LOCAL", "CE")
        AutomaticCatalog(legacy, self.path).initialize()
        self.assertEqual(products.get("REMOTE")["uf"], "SP")
        self.assertEqual(products.get("LOCAL")["uf"], "CE")
        self.assertEqual({p["produto_id"] for p in self.document()["products"]}, {"LOCAL", "REMOTE"})

    def test_external_marker_conflict_preserves_file_and_rolls_back_all_changes(self):
        self.products.create("BOX", "AM")
        self.products.ensure_aruco("BOX", marker_id=37)
        document = self.document()
        document["products"][0]["aruco_id"] = 8
        document["products"].insert(0, {"produto_id": "OTHER", "uf": "PR", "ativo": True, "aruco_id": 5})
        self.path.write_text(json.dumps(document), encoding="utf-8")
        before = self.path.read_bytes()
        with self.assertRaises(CatalogPersistenceError):
            self.open_database(self.database.path, self.path)
        self.assertEqual(self.path.read_bytes(), before)
        with self.database.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT marker_id FROM aruco_markers").fetchone()[0], 37)

    def test_normal_application_saves_and_reopens_without_catalog_configuration(self):
        options = {"AUTO_OPERATION": False, "DATABASE_PATH": self.root / "normal.db",
                   "CAMERA_MODE": "mock", "HARDWARE_MODE": "mock", "CONVEYOR_MODE": "arduino",
                   "BOOTSTRAP_CATALOG": False, "CATALOG_PATH": None}
        app = create_app(options)
        client = app.test_client()
        self.assertEqual(client.post("/api/products", json={"produto_id": "NORMAL", "uf": "AM"}).status_code, 201)
        self.assertTrue((self.root / "normal.json").is_file())
        restarted = create_app(options)
        self.assertEqual(restarted.extensions["product_repository"].get("NORMAL")["uf"], "AM")

    def test_corrupt_json_is_not_overwritten_and_sqlite_is_preserved(self):
        self.products.create("BOX", "AM")
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(CatalogPersistenceError):
            self.database.catalog_store.synchronize()
        self.assertEqual(self.path.read_text(), "{broken")
        with self.database.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0], 1)

    def test_failed_write_is_recovered_after_restart_without_losing_saved_data(self):
        self.products.create("BOX", "AM")
        before = self.path.read_bytes()
        with patch("storage.automatic_catalog.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(CatalogPersistenceError):
                self.products.ensure_aruco("BOX", marker_id=37)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.root.glob(".catalog-*.tmp")), [])
        database, products = self.open_database(self.database.path, self.path)
        self.assertEqual(products.resolve_aruco(37)["id"], "BOX")
        self.assertEqual(self.document()["products"][0]["aruco_id"], 37)

    def test_bulk_marker_conflict_does_not_write_partial_json(self):
        self.products.create("A", "AM")
        self.products.ensure_aruco("A", marker_id=2)
        self.products.create("B", "SP")
        before = self.path.read_bytes()
        with self.assertRaises(ArucoMarkerConflictError):
            self.products.ensure_aruco_batch([{"produto_id": "B", "aruco_id": 3}, {"produto_id": "A", "aruco_id": 4}])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIsNone(self.products.get("B")["aruco_id"])

    def test_concurrent_requests_do_not_lose_products_or_marker_assignments(self):
        def create(index):
            product_id = f"BOX-{index}"
            self.products.create(product_id, "AM")
            self.products.ensure_aruco(product_id, marker_id=index)
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(create, range(12)))
        self.assertEqual(len(self.document()["products"]), 12)
        self.assertEqual({p["aruco_id"] for p in self.document()["products"]}, set(range(12)))

    def test_two_application_databases_read_changes_from_the_same_json(self):
        other_db, other_products = self.open_database(self.root / "bench.db", self.path)
        self.products.create("BOX", "AM")
        self.products.ensure_aruco("BOX", marker_id=37)
        self.assertEqual(other_products.resolve_aruco(37)["id"], "BOX")
        other_products.update("BOX", state="SP", active=True)
        self.assertEqual(self.products.get("BOX")["uf"], "SP")

    def test_api_saves_without_export_import_controls(self):
        app = create_app({"TESTING": True, "DATABASE_PATH": self.root / "api.db", "CATALOG_PATH": self.root / "api.json"})
        client = app.test_client()
        self.assertEqual(client.post("/api/products", json={"produto_id": "API-BOX", "uf": "CE"}).status_code, 201)
        self.assertEqual(json.loads((self.root / "api.json").read_text())["products"][0]["produto_id"], "API-BOX")
        self.assertEqual(client.get("/api/catalog/export").status_code, 404)
        self.assertEqual(client.post("/api/catalog/import", json={}).status_code, 404)
        html = client.get("/produtos").get_data(as_text=True)
        self.assertNotIn("Exportar catálogo (JSON)", html)
        self.assertNotIn("Importar catálogo (JSON)", html)
