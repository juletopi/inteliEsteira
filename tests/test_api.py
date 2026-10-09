import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app import create_app
from hardware.arduino import ArduinoDisconnectedError
from vision.qrcode import QRCodeCamera


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "test.db"
        app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": self.database_path,
            }
        )
        self.client = app.test_client()

    def tearDown(self):
        self.temp_directory.cleanup()

    def register_product(self, product_id, state):
        response = self.client.post(
            "/api/products",
            json={"produto_id": product_id, "uf": state},
        )
        self.assertEqual(response.status_code, 201)
        return response.get_json()["produto"]

    @staticmethod
    def qr(product_id):
        return json.dumps({"produto_id": product_id})

    def test_pages_and_status_are_available(self):
        for path in (
            "/",
            "/conexao",
            "/linha-de-producao",
            "/produtos",
            "/api/status",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

        status = self.client.get("/api/status").get_json()
        self.assertEqual(status["camera_modo"], "mock")
        self.assertIsNone(status["camera_resolucao"])
        self.assertEqual(status["hardware_modo"], "mock")

    def test_dashboard_exposes_operational_controls(self):
        response = self.client.get("/")
        html = response.get_data(as_text=True)

        for element_id in (
            "product-id",
            "check-button",
            "start-button",
            "stop-button",
            "reset-button",
            "operation-feedback",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', html)

        self.assertNotIn('id="product-state"', html)
        self.assertIn("/api/route", html)
        self.assertIn("/api/cycles", html)
        self.assertIn("/api/system/stop", html)
        self.assertIn("/api/system/reset", html)

    def test_product_and_history_pages_expose_dynamic_tables(self):
        products_html = self.client.get("/produtos").get_data(as_text=True)
        history_html = self.client.get("/linha-de-producao").get_data(as_text=True)

        self.assertIn('id="product-form"', products_html)
        self.assertIn('id="products-table-body"', products_html)
        self.assertIn("/api/products", products_html)
        self.assertIn("Baixar QR", products_html)
        self.assertIn("Baixar ArUco", products_html)
        self.assertIn('text: "Excluir"', products_html)
        self.assertIn('id="aruco-size"', products_html)
        self.assertIn('id="aruco-format"', products_html)
        self.assertIn('id="select-all-products"', products_html)
        self.assertIn('id="download-batch-button"', products_html)
        self.assertIn('id="history-table-body"', history_html)
        self.assertIn("/api/cycles", history_html)

    def test_connection_page_exposes_real_diagnostics(self):
        html = self.client.get("/conexao").get_data(as_text=True)

        for element_id in (
            "gripper-connection-status",
            "conveyor-connection-status",
            "camera-connection-status",
            "connect-components-button",
            "refresh-ports-button",
            "ports-list",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', html)
        self.assertIn("/api/system/connect", html)
        self.assertIn("/api/hardware/ports", html)

    def test_mock_components_can_be_reconnected_by_api(self):
        arduino = self.client.application.extensions["arduino"]
        camera = self.client.application.extensions["camera"]
        arduino.disconnect()
        camera.disconnect()

        response = self.client.post("/api/system/connect")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["sistema"]["arduino"])
        self.assertTrue(response.get_json()["sistema"]["camera"])

    def test_serial_ports_endpoint_returns_a_list(self):
        response = self.client.get("/api/hardware/ports")

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.get_json()["portas"], list)

    def test_app_starts_when_serial_arduino_is_unavailable(self):
        serial_database = Path(self.temp_directory.name) / "serial.db"
        with patch(
            "hardware.serial_adapter.SerialArduino.connect",
            side_effect=ArduinoDisconnectedError("Arduino ausente."),
        ):
            serial_app = create_app(
                {
                    "TESTING": True,
                    "DATABASE_PATH": serial_database,
                    "HARDWARE_MODE": "serial",
                    "ARDUINO_BOOT_WAIT": 0,
                }
            )

        status = serial_app.test_client().get("/api/status").get_json()
        self.assertEqual(status["hardware_modo"], "serial")
        self.assertFalse(status["arduino"])

    def test_product_registration_listing_and_deactivation(self):
        product = self.register_product("PROD-001", "CE")
        listing = self.client.get("/api/products").get_json()["produtos"]
        deactivated = self.client.put("/api/products/PROD-001", json={"ativo": False})

        self.assertEqual(product["macroregiao"], "NORDESTE")
        self.assertEqual(len(listing), 1)
        self.assertEqual(deactivated.status_code, 200)
        self.assertFalse(deactivated.get_json()["produto"]["ativo"])
        self.assertEqual(len(self.client.get("/api/products").get_json()["produtos"]), 1)
        activated = self.client.put("/api/products/PROD-001", json={"ativo": True})
        self.assertTrue(activated.get_json()["produto"]["ativo"])

    def test_delete_product_removes_it_from_catalog_and_rejects_further_operations(self):
        self.register_product("REMOVE", "CE")
        response = self.client.delete("/api/products/REMOVE")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["excluido"])
        self.assertEqual(self.client.get("/api/products").get_json()["produtos"], [])
        self.assertEqual(self.client.delete("/api/products/REMOVE").status_code, 404)
        self.assertEqual(self.client.delete("/api/products/UNKNOWN").status_code, 404)
        self.assertEqual(self.client.put("/api/products/REMOVE", json={"ativo": True}).status_code, 404)
        self.assertEqual(self.client.get("/api/products/REMOVE/qrcode").status_code, 404)
        self.assertEqual(self.client.post("/api/products/REMOVE/aruco").status_code, 404)
        route = self.client.post("/api/route", json={"qr_code": self.qr("REMOVE")})
        self.assertEqual(route.status_code, 404)
        self.assertEqual(self.client.post("/api/products", json={"produto_id": "REMOVE", "uf": "SP"}).status_code, 409)

    def test_delete_preserves_cycle_history_and_reserves_old_marker(self):
        self.register_product("REMOVE", "CE")
        self.client.post("/api/products/REMOVE/aruco", json={"aruco_id": 0})
        cycle = self.client.post("/api/cycles", json={"qr_code": self.qr("REMOVE")})
        self.assertEqual(cycle.status_code, 201)
        path = f"/api/cycles/{cycle.get_json()['ciclo_id']}"
        before = self.client.get(path).get_json()
        self.assertEqual(self.client.delete("/api/products/remove").status_code, 200)
        self.assertEqual(self.client.get(path).get_json(), before)
        repository = self.client.application.extensions["product_repository"]
        self.assertIsNone(repository.resolve_aruco(0))
        self.register_product("NEW", "SP")
        rejected = self.client.post("/api/products/NEW/aruco", json={"aruco_id": 0})
        self.assertEqual(rejected.status_code, 409)
        automatic = self.client.post("/api/products/NEW/aruco")
        self.assertEqual(automatic.get_json()["produto"]["aruco_id"], 1)
        restarted = create_app({"TESTING": True, "DATABASE_PATH": self.database_path})
        self.assertIsNone(restarted.extensions["product_repository"].get("REMOVE", include_inactive=True))

    def test_batch_cannot_print_deleted_product_and_rolls_back_new_bindings(self):
        self.register_product("NEW", "CE")
        self.register_product("REMOVE", "SP")
        self.client.delete("/api/products/REMOVE")
        response = self.client.post("/api/products/aruco/batch", json={
            "products": [{"produto_id": "NEW"}, {"produto_id": "REMOVE"}],
        })
        self.assertEqual(response.status_code, 404)
        self.assertIsNone(self.client.application.extensions["product_repository"].get("NEW")["aruco_id"])

    def test_product_qrcode_is_generated_as_png(self):
        self.register_product("PROD-QR-1", "MG")

        response = self.client.get("/api/products/PROD-QR-1/qrcode?download=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        self.assertTrue(response.data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertIn("qr-PROD-QR-1.png", response.headers["Content-Disposition"])

    def test_unknown_product_has_no_qrcode(self):
        response = self.client.get("/api/products/UNKNOWN/qrcode")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["erro"]["codigo"], "PRODUCT_NOT_FOUND")

    def test_aruco_registration_download_and_cycle(self):
        self.register_product("PROD-ARUCO", "MG")
        path = "/api/products/PROD-ARUCO/aruco"
        self.assertEqual(self.client.get(path).status_code, 404)

        first = self.client.post(path)
        second = self.client.post(path)
        self.assertEqual(first.status_code, 200)
        marker_id = first.get_json()["produto"]["aruco_id"]
        self.assertEqual(second.get_json()["produto"]["aruco_id"], marker_id)

        image = self.client.get(path + "?download=1")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.mimetype, "image/png")
        self.assertIn("attachment", image.headers["Content-Disposition"])
        frame = cv2.imdecode(np.frombuffer(image.data, dtype=np.uint8), cv2.IMREAD_COLOR)
        repository = self.client.application.extensions["product_repository"]
        camera = QRCodeCamera(cv2_module=cv2, aruco_resolver=repository.resolve_aruco)
        self.assertEqual(camera.read_qrcode(frame), self.qr("PROD-ARUCO").replace(": ", ":"))

        camera.mode = "opencv"
        camera.capture_frame = lambda: frame
        controller = self.client.application.extensions["system_controller"]
        controller.camera = camera
        with patch.object(camera, "connect", return_value=True):
            cycle = self.client.post("/api/cycles", json={})
        self.assertEqual(cycle.status_code, 201)
        self.assertEqual(cycle.get_json()["produto"]["id"], "PROD-ARUCO")

        restarted = create_app({"TESTING": True, "DATABASE_PATH": self.database_path})
        stored = restarted.extensions["product_repository"].resolve_aruco(marker_id)
        self.assertEqual(stored["id"], "PROD-ARUCO")

    def test_unknown_product_cannot_register_aruco(self):
        response = self.client.post("/api/products/UNKNOWN/aruco")
        self.assertEqual(response.status_code, 404)

    def test_aruco_print_downloads_keep_the_registered_id(self):
        self.register_product("PRINT", "CE")
        path = "/api/products/PRINT/aruco"
        self.client.post(path, json={"aruco_id": 17})
        for size in ("50", "40", "30", "20", "all"):
            with self.subTest(size=size):
                response = self.client.get(path + f"?download=1&format=pdf&size_mm={size}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "application/pdf")
                self.assertTrue(response.data.startswith(b"%PDF-"))
                suffix = "4-tamanhos" if size == "all" else f"{size}mm"
                self.assertIn(f"aruco-PRINT-id17-{suffix}.pdf", response.headers["Content-Disposition"])
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                if size != "all":
                    png = self.client.get(path + f"?download=1&size_mm={size}")
                    self.assertEqual(png.status_code, 200)
                    self.assertEqual(png.mimetype, "image/png")
                    self.assertIn(f"aruco-PRINT-id17-{size}mm.png", png.headers["Content-Disposition"])
        repository = self.client.application.extensions["product_repository"]
        self.assertEqual(repository.get("PRINT")["aruco_id"], 17)
        default_pdf = self.client.get(path + "?format=pdf")
        self.assertIn("-20mm.pdf", default_pdf.headers["Content-Disposition"])

    def test_aruco_download_rejects_invalid_print_options(self):
        self.register_product("PRINT", "CE")
        path = "/api/products/PRINT/aruco"
        self.client.post(path, json={"aruco_id": 17})
        for query in ("size_mm=0", "size_mm=21", "size_mm=20.0", "size_mm=", "size_mm=all", "format=svg"):
            with self.subTest(query=query):
                response = self.client.get(path + "?" + query)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["erro"]["codigo"], "INVALID_REQUEST")
        repository = self.client.application.extensions["product_repository"]
        self.assertEqual(repository.get("PRINT")["aruco_id"], 17)

    def test_aruco_batch_pdf_uses_registered_products_and_regions(self):
        from vision.labels import generate_aruco_batch_pdf

        self.register_product("NORTHEAST", "CE")
        self.register_product("SOUTHEAST", "SP")
        self.client.post("/api/products/NORTHEAST/aruco", json={"aruco_id": 17})
        self.client.post("/api/products/SOUTHEAST/aruco", json={"aruco_id": 18})
        with patch("app.routes.api.generate_aruco_batch_pdf", wraps=generate_aruco_batch_pdf) as render:
            response = self.client.post("/api/products/aruco/batch", json={
                "products": [{"produto_id": "NORTHEAST", "uf": "AM"}, {"produto_id": "SOUTHEAST"}],
                "size_mm": 40,
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF-"))
        self.assertIn("aruco-lote-40mm.pdf", response.headers["Content-Disposition"])
        products = render.call_args.args[0]
        self.assertEqual([(p["id"], p["uf"], p["aruco_id"]) for p in products],
                         [("NORTHEAST", "CE", 17), ("SOUTHEAST", "SP", 18)])
        self.assertEqual(render.call_args.kwargs, {"size_mm": 40})

    def test_aruco_batch_reserves_old_ids_before_assigning_new_ones(self):
        for product_id in ("NEW", "OLD"):
            self.register_product(product_id, "CE")
        request = {"products": [{"produto_id": "NEW"}, {"produto_id": "OLD", "aruco_id": 0}], "size_mm": "all"}
        first = self.client.post("/api/products/aruco/batch", json=request)
        self.assertEqual(first.status_code, 200)
        self.assertIn("4-tamanhos.pdf", first.headers["Content-Disposition"])
        repository = self.client.application.extensions["product_repository"]
        self.assertEqual(repository.get("NEW")["aruco_id"], 1)
        self.assertEqual(repository.get("OLD")["aruco_id"], 0)
        second = self.client.post("/api/products/aruco/batch", json=request)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data, second.data)

    def test_aruco_batch_conflict_and_unknown_product_leave_no_partial_bindings(self):
        self.register_product("OWNER", "SP")
        self.register_product("NEW", "CE")
        self.register_product("OTHER", "CE")
        self.client.post("/api/products/OWNER/aruco", json={"aruco_id": 0})
        repository = self.client.application.extensions["product_repository"]
        before = repository.list()
        cases = [
            ([{"produto_id": "NEW", "aruco_id": 17}, {"produto_id": "OTHER", "aruco_id": 0}], 409),
            ([{"produto_id": "NEW"}, {"produto_id": "UNKNOWN"}], 404),
        ]
        for products, status in cases:
            with self.subTest(status=status):
                response = self.client.post("/api/products/aruco/batch", json={"products": products})
                self.assertEqual(response.status_code, status)
                self.assertEqual(repository.list(), before)

    def test_aruco_batch_rejects_invalid_selection_before_assigning_ids(self):
        self.register_product("PRODUCT", "SP")
        cases = [None, [], {}, {"products": []}, {"products": "PRODUCT"},
                 {"products": [{"produto_id": "PRODUCT"}, {"produto_id": "product"}]},
                 {"products": [{"produto_id": "PRODUCT", "aruco_id": True}]},
                 {"products": [{"produto_id": "PRODUCT", "aruco_id": None}]},
                 {"products": [None]}, {"products": [{"produto_id": "PRODUCT"}] * 251}]
        cases += [{"products": [{"produto_id": "PRODUCT"}], "size_mm": size}
                  for size in (None, True, 21, "20", [], 20.0)]
        for payload in cases:
            with self.subTest(payload=payload):
                response = self.client.post("/api/products/aruco/batch", json=payload)
                self.assertEqual(response.status_code, 400)
        repository = self.client.application.extensions["product_repository"]
        self.assertIsNone(repository.get("PRODUCT")["aruco_id"])

    def test_aruco_batch_exhaustion_rolls_back_last_available_id(self):
        database = self.client.application.extensions["database"]
        with database.connect() as connection:
            connection.executemany(
                "INSERT INTO products (product_id, state, active, created_at, updated_at) VALUES (?, 'SP', 1, '2026-01-01', '2026-01-01')",
                [(f"OWNER-{marker}",) for marker in range(249)],
            )
            connection.executemany(
                "INSERT INTO aruco_markers (marker_id, product_id) VALUES (?, ?)",
                [(marker, f"OWNER-{marker}") for marker in range(249)],
            )
        self.register_product("NEW", "CE")
        self.register_product("OTHER", "CE")
        response = self.client.post("/api/products/aruco/batch", json={
            "products": [{"produto_id": "NEW"}, {"produto_id": "OTHER"}],
        })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["erro"]["codigo"], "ARUCO_IDS_EXHAUSTED")
        repository = self.client.application.extensions["product_repository"]
        self.assertIsNone(repository.get("NEW")["aruco_id"])
        self.assertIsNone(repository.get("OTHER")["aruco_id"])
        self.assertIsNone(repository.resolve_aruco(249))

    def test_restored_aruco_matches_old_label_and_survives_restart(self):
        # A etiqueta ja existia antes de este banco receber o cadastro.
        from vision.qrcode import generate_aruco_png

        old_png = generate_aruco_png(17)
        self.register_product("OTHER", "SP")
        self.client.post("/api/products/OTHER/aruco")
        self.register_product("PROD-0087", "CE")
        path = "/api/products/PROD-0087/aruco"
        restored = self.client.post(path, json={"aruco_id": 17})
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.get_json()["produto"]["aruco_id"], 17)

        restarted = create_app({"TESTING": True, "DATABASE_PATH": self.database_path})
        client = restarted.test_client()
        for payload in ({}, {"aruco_id": 17}):
            repeated = client.post(path, json=payload)
            self.assertEqual(repeated.status_code, 200)
            self.assertEqual(repeated.get_json()["produto"]["aruco_id"], 17)
        regenerated = client.get(path + "?download=1")
        self.assertEqual(regenerated.data, old_png)

        repository = restarted.extensions["product_repository"]
        frame = cv2.imdecode(np.frombuffer(old_png, dtype=np.uint8), cv2.IMREAD_COLOR)
        camera = QRCodeCamera(cv2_module=cv2, aruco_resolver=repository.resolve_aruco)
        self.assertEqual(camera.read_qrcode(frame), '{"produto_id":"PROD-0087"}')
        route = client.post("/api/route", json={"qr_code": camera.read_qrcode(frame)})
        self.assertEqual(route.status_code, 200)
        self.assertEqual(route.get_json()["produto"], {"id": "PROD-0087", "uf": "CE"})

    def test_aruco_conflicts_preserve_both_products(self):
        self.register_product("FIRST", "SP")
        self.register_product("SECOND", "CE")
        first_path = "/api/products/FIRST/aruco"
        second_path = "/api/products/SECOND/aruco"
        self.assertEqual(self.client.post(first_path, json={"aruco_id": 0}).status_code, 200)
        for path, marker_id in ((second_path, 0), (first_path, 17)):
            with self.subTest(path=path):
                response = self.client.post(path, json={"aruco_id": marker_id})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.get_json()["erro"]["codigo"], "ARUCO_ID_CONFLICT")
        products = self.client.get("/api/products").get_json()["produtos"]
        self.assertEqual([(p["id"], p["aruco_id"]) for p in products], [("FIRST", 0), ("SECOND", None)])

    def test_aruco_rejects_invalid_ids_and_request_bodies(self):
        self.register_product("PRODUCT", "SP")
        path = "/api/products/PRODUCT/aruco"
        for marker_id in (-1, 250, True, False, "17", 17.0, None):
            with self.subTest(marker_id=marker_id):
                response = self.client.post(path, json={"aruco_id": marker_id})
                self.assertEqual(response.status_code, 400)
        for body in ("null", "[]", "{invalid", '"text"'):
            with self.subTest(body=body):
                response = self.client.post(path, data=body, content_type="application/json")
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_mock_camera_preview_is_not_available(self):
        response = self.client.get("/api/camera/frame")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json()["erro"]["codigo"],
            "CAMERA_PREVIEW_UNAVAILABLE",
        )

    def test_real_camera_mode_accepts_cycle_without_qr_in_request(self):
        self.register_product("CAMERA-1", "RJ")
        camera = self.client.application.extensions["camera"]
        camera.mode = "opencv"
        camera.enqueue_qr_code(self.qr("CAMERA-1"))

        response = self.client.post("/api/cycles", json={})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["produto"]["id"], "CAMERA-1")

    def test_duplicate_product_is_rejected(self):
        self.register_product("PROD-001", "CE")
        duplicate = self.client.post(
            "/api/products",
            json={"produto_id": "PROD-001", "uf": "SP"},
        )

        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(
            duplicate.get_json()["erro"]["codigo"],
            "PRODUCT_ALREADY_EXISTS",
        )

    def test_inactive_product_cannot_be_routed(self):
        self.register_product("PROD-001", "CE")
        self.client.put("/api/products/PROD-001", json={"ativo": False})

        response = self.client.post(
            "/api/route",
            json={"qr_code": self.qr("PROD-001")},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["erro"]["codigo"], "PRODUCT_INACTIVE")

    def test_route_returns_least_occupied_destination(self):
        self.register_product("PROD-0087", "CE")
        response = self.client.post(
            "/api/route",
            json={
                "qr_code": self.qr("PROD-0087"),
                "ocupacao": {"R07": 2, "R08": 1},
                "indisponiveis": [],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "ok": True,
                "produto": {"id": "PROD-0087", "uf": "CE"},
                "macroregiao": "NORDESTE",
                "destino": "R08",
                "candidatos": ["R07", "R08"],
            },
        )

    def test_route_rejects_invalid_request_body(self):
        response = self.client.post(
            "/api/route",
            data="not-json",
            content_type="text/plain",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["erro"]["codigo"], "INVALID_REQUEST")

    def test_route_rejects_unknown_product(self):
        response = self.client.post(
            "/api/route",
            json={"qr_code": self.qr("NOT-REGISTERED")},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["erro"]["codigo"], "PRODUCT_NOT_FOUND")

    def test_route_reports_unavailable_region(self):
        self.register_product("PROD-1", "SP")
        response = self.client.post(
            "/api/route",
            json={
                "qr_code": self.qr("PROD-1"),
                "indisponiveis": ["R05", "R06"],
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json()["erro"]["codigo"],
            "DESTINATION_UNAVAILABLE",
        )

    def test_cycle_is_persisted_with_events(self):
        self.register_product("PROD-9", "SC")
        response = self.client.post(
            "/api/cycles",
            json={
                "qr_code": self.qr("PROD-9"),
                "ocupacao": {"R03": 5, "R04": 0},
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["destino"], "R04")
        cycle_id = response.get_json()["ciclo_id"]
        history = self.client.get("/api/cycles").get_json()["ciclos"]
        detail = self.client.get(f"/api/cycles/{cycle_id}").get_json()["ciclo"]
        status = self.client.get("/api/status").get_json()

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["estado"], "FINALIZADO")
        self.assertGreaterEqual(len(detail["eventos"]), 8)
        self.assertEqual(status["total_ciclos"], 1)

    def test_products_and_cycles_survive_app_restart(self):
        self.register_product("PERSIST-1", "PA")
        cycle = self.client.post(
            "/api/cycles",
            json={"qr_code": self.qr("PERSIST-1")},
        )
        self.assertEqual(cycle.status_code, 201)

        restarted_app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": self.database_path,
            }
        )
        restarted_client = restarted_app.test_client()

        products = restarted_client.get("/api/products").get_json()["produtos"]
        cycles = restarted_client.get("/api/cycles").get_json()["ciclos"]
        self.assertEqual(products[0]["id"], "PERSIST-1")
        self.assertEqual(cycles[0]["produto_id"], "PERSIST-1")
        self.assertEqual(cycles[0]["estado"], "FINALIZADO")

    def test_cycle_error_requires_reset(self):
        self.register_product("PROD-11", "GO")
        invalid_cycle = self.client.post(
            "/api/cycles",
            json={"qr_code": self.qr("NOT-REGISTERED")},
        )
        blocked_cycle = self.client.post(
            "/api/cycles",
            json={"qr_code": self.qr("PROD-11")},
        )
        reset = self.client.post("/api/system/reset")
        recovered_cycle = self.client.post(
            "/api/cycles",
            json={"qr_code": self.qr("PROD-11")},
        )

        self.assertEqual(invalid_cycle.status_code, 404)
        self.assertEqual(
            invalid_cycle.get_json()["erro"]["codigo"],
            "PRODUCT_NOT_FOUND",
        )
        self.assertEqual(blocked_cycle.status_code, 409)
        self.assertEqual(
            blocked_cycle.get_json()["erro"]["codigo"],
            "SYSTEM_NOT_READY",
        )
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(reset.get_json()["sistema"]["estado"], "IDLE")
        self.assertEqual(recovered_cycle.status_code, 201)
        self.assertEqual(recovered_cycle.get_json()["produto"]["id"], "PROD-11")


if __name__ == "__main__":
    unittest.main()
