from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from storage.catalog import (
    CatalogError, backup_database, export_catalog, import_catalog, main,
    validate_catalog, verify_catalog,
)
from storage.database import Database
from storage.repositories import ArucoMarkerConflictError, ProductRepository


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database = Database(self.root / "original.db")
        self.database.initialize()
        self.products = ProductRepository(self.database)
        self.products.create("PROD-0087", "CE")
        self.products.ensure_aruco("PROD-0087", marker_id=17)
        self.document = export_catalog(self.database)

    def tearDown(self):
        self.directory.cleanup()

    def test_catalog_restores_exact_mapping_to_another_database(self):
        other = Database(self.root / "presentation.db")
        other.initialize()
        # Outra ordem de cadastro nao muda o ID definido no catalogo.
        repository = ProductRepository(other)
        repository.create("OTHER", "SP")
        repository.ensure_aruco("OTHER", marker_id=0)
        import_catalog(other, self.document)
        self.assertEqual(verify_catalog(other, self.document, require_aruco=True), 1)
        self.assertEqual(repository.resolve_aruco(17)["id"], "PROD-0087")
        self.assertEqual(repository.resolve_aruco(17)["uf"], "CE")
        before = repository.list()
        import_catalog(other, self.document)
        self.assertEqual(repository.list(), before)

    def test_marker_conflict_rolls_back_all_imported_products(self):
        document = deepcopy(self.document)
        document["products"].insert(0, {"produto_id": "NEW", "uf": "SP", "ativo": True, "aruco_id": 12})
        other = Database(self.root / "conflict.db")
        other.initialize()
        repository = ProductRepository(other)
        repository.create("OWNER", "AM")
        repository.ensure_aruco("OWNER", marker_id=17)
        before = repository.list()
        with self.assertRaises(CatalogError):
            import_catalog(other, document)
        self.assertEqual(repository.list(), before)
        self.assertIsNone(repository.resolve_aruco(12))

    def test_import_refuses_to_change_registered_state_activity_or_marker(self):
        before = self.products.list()
        for field, value in (("uf", "AM"), ("ativo", False), ("aruco_id", 18), ("aruco_id", None)):
            with self.subTest(field=field, value=value):
                document = deepcopy(self.document)
                document["products"][0][field] = value
                with self.assertRaises(CatalogError):
                    import_catalog(self.database, document)
                self.assertEqual(self.products.list(), before)

    def test_verify_detects_changed_state_and_missing_markers(self):
        self.products.update("PROD-0087", state="AM", active=True)
        with self.assertRaises(CatalogError):
            verify_catalog(self.database, self.document)
        self.products.create("NO-MARKER", "SP")
        current = export_catalog(self.database)
        self.assertEqual(verify_catalog(self.database, current), 2)
        with self.assertRaises(CatalogError):
            verify_catalog(self.database, current, require_aruco=True)

    def test_catalog_rejects_duplicate_products_markers_and_wrong_dictionary(self):
        for conflict in ("product", "marker", "dictionary", "boolean-id"):
            with self.subTest(conflict=conflict):
                document = deepcopy(self.document)
                if conflict == "dictionary":
                    document["aruco_dictionary"] = "DICT_5X5_250"
                elif conflict == "boolean-id":
                    document["products"][0]["aruco_id"] = True
                else:
                    product = deepcopy(document["products"][0])
                    product["produto_id"] = "prod-0087" if conflict == "product" else "OTHER"
                    product["aruco_id"] = 18 if conflict == "product" else 17
                    document["products"].append(product)
                with self.assertRaises(CatalogError):
                    validate_catalog(document)

    def test_sqlite_backup_preserves_mapping_and_refuses_to_overwrite(self):
        destination = self.root / "backup.db"
        backup_database(self.database, destination)
        copied = Database(destination)
        self.assertEqual(export_catalog(copied), self.document)
        with copied.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        with self.assertRaises(FileExistsError):
            backup_database(self.database, destination)
        with self.assertRaises(FileExistsError):
            backup_database(self.database, self.database.path)
        self.assertEqual(export_catalog(self.database), self.document)

    def test_command_line_export_import_verify_and_preserve_saved_catalog(self):
        catalog = self.root / "catalog.json"
        restored = self.root / "restored.db"
        with redirect_stdout(io.StringIO()) as output:
            main(["export", str(catalog), "--database", str(self.database.path)])
            main(["import", str(catalog), "--database", str(restored)])
            main(["verify", str(catalog), "--database", str(restored), "--require-aruco"])
        self.assertIn("OK: 1 produtos conferidos", output.getvalue())
        self.assertEqual(json.loads(catalog.read_text(encoding="utf-8")), self.document)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(["export", str(catalog), "--database", str(self.database.path)])
        self.assertEqual(error.exception.code, 1)

    def test_deleted_products_remain_deleted_and_reserve_markers_on_another_machine(self):
        self.products.delete("PROD-0087")
        document = export_catalog(self.database)
        self.assertTrue(document["products"][0]["excluido"])
        self.assertFalse(document["products"][0]["ativo"])
        other = Database(self.root / "presentation.db")
        other.initialize()
        import_catalog(other, document)
        repository = ProductRepository(other)
        self.assertEqual(repository.list(), [])
        self.assertIsNone(repository.resolve_aruco(17))
        repository.create("NEW", "SP")
        with self.assertRaises(ArucoMarkerConflictError):
            repository.ensure_aruco("NEW", marker_id=17)
        self.assertEqual(verify_catalog(other, document, require_aruco=True), 1)
        with self.assertRaises(CatalogError):
            import_catalog(other, self.document)
        self.assertIsNone(repository.get("PROD-0087", include_inactive=True))

    def test_import_propagates_deletion_to_previously_imported_catalog(self):
        other = Database(self.root / "presentation.db")
        other.initialize()
        import_catalog(other, self.document)
        self.products.delete("PROD-0087")
        document = export_catalog(self.database)
        import_catalog(other, document)
        self.assertIsNone(ProductRepository(other).get("PROD-0087", include_inactive=True))
        self.assertEqual(verify_catalog(other, document), 1)

    def test_old_catalog_without_deleted_flag_is_still_accepted(self):
        self.assertNotIn("excluido", self.document["products"][0])
        self.assertEqual(verify_catalog(self.database, self.document), 1)
        invalid = deepcopy(self.document)
        invalid["products"][0]["excluido"] = True
        with self.assertRaises(CatalogError):
            validate_catalog(invalid)

    def test_import_rolls_back_deletion_when_another_product_conflicts(self):
        self.products.create("OTHER", "CE")
        before = export_catalog(self.database)
        document = deepcopy(self.document)
        document["products"][0].update({"ativo": False, "excluido": True})
        document["products"].append({"produto_id": "OTHER", "uf": "SP", "ativo": True, "aruco_id": None})
        with self.assertRaises(CatalogError):
            import_catalog(self.database, document)
        self.assertEqual(export_catalog(self.database), before)
        self.assertTrue(self.products.get("PROD-0087")["ativo"])


if __name__ == "__main__":
    unittest.main()
