import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import create_app
from hardware.arduino import ArduinoDisconnectedError


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
        deactivated = self.client.delete("/api/products/PROD-001")

        self.assertEqual(product["macroregiao"], "NORDESTE")
        self.assertEqual(len(listing), 1)
        self.assertEqual(deactivated.status_code, 200)
        self.assertFalse(deactivated.get_json()["produto"]["ativo"])

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
        self.client.delete("/api/products/PROD-001")

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
