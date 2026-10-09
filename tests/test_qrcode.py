from io import BytesIO
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from vision.qrcode import (
    ArucoNotRegisteredError,
    QRCodeCamera,
    QRCodeNotFoundError,
    build_product_qr_payload,
    generate_aruco_png,
    generate_product_qr_png,
)


class StaticQRCodeCamera(QRCodeCamera):
    def __init__(self, qr_code):
        super().__init__(
            scan_timeout=0.1,
            retry_interval=0.01,
            duplicate_cooldown=10.0,
            cv2_module=cv2,
        )
        self.qr_code = qr_code

    def capture_frame(self):
        return object()

    def read_qrcode(self, frame):
        return self.qr_code


class QRCodeTests(unittest.TestCase):
    def test_camera_requests_720p_and_reports_actual_resolution(self):
        class Capture:
            def __init__(self, accept_resolution):
                self.accept_resolution = accept_resolution
                self.properties = {
                    cv2.CAP_PROP_FRAME_WIDTH: 640,
                    cv2.CAP_PROP_FRAME_HEIGHT: 480,
                }
                self.settings = []
                self.opened = True

            def isOpened(self):
                return self.opened

            def set(self, property_id, value):
                self.settings.append((property_id, value))
                if self.accept_resolution:
                    self.properties[property_id] = value
                return self.accept_resolution

            def get(self, property_id):
                return self.properties[property_id]

            def release(self):
                self.opened = False

        for accepted, expected in (
            (True, {"largura": 1280, "altura": 720}),
            (False, {"largura": 640, "altura": 480}),
        ):
            with self.subTest(accepted=accepted):
                capture = Capture(accepted)
                with patch.object(cv2, "VideoCapture", return_value=capture) as open_camera:
                    camera = QRCodeCamera(camera_index=1, cv2_module=cv2)
                    self.assertTrue(camera.connect())
                    open_camera.assert_called_once_with(1)
                self.assertEqual(
                    capture.settings,
                    [
                        (cv2.CAP_PROP_FRAME_WIDTH, 1280),
                        (cv2.CAP_PROP_FRAME_HEIGHT, 720),
                    ],
                )
                self.assertEqual(camera.resolution(), expected)
                camera.disconnect()
                self.assertIsNone(camera.resolution())

    def test_generated_png_can_be_decoded_by_opencv(self):
        expected = '{"produto_id":"PROD-QR-001"}'
        png = generate_product_qr_png("PROD-QR-001")
        frame = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
        camera = QRCodeCamera(cv2_module=cv2)

        decoded = camera.read_qrcode(frame)

        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(decoded, expected)

    def test_payload_is_canonical_json(self):
        self.assertEqual(
            build_product_qr_payload("PROD-8"),
            '{"produto_id":"PROD-8"}',
        )

    def test_generated_aruco_resolves_to_product(self):
        png = generate_aruco_png(17)
        frame = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
        camera = QRCodeCamera(
            cv2_module=cv2,
            aruco_resolver=lambda marker_id: {"id": "PROD-17"} if marker_id == 17 else None,
        )

        self.assertEqual(frame.shape[:2], (800, 800))
        self.assertEqual(camera.read_qrcode(frame), '{"produto_id":"PROD-17"}')

    def test_unregistered_aruco_is_rejected(self):
        png = generate_aruco_png(18)
        frame = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
        camera = QRCodeCamera(cv2_module=cv2, aruco_resolver=lambda _id: None)

        with self.assertRaises(ArucoNotRegisteredError):
            camera.read_qrcode(frame)

    def test_print_sizes_preserve_marker_and_record_physical_png_dimensions(self):
        reference = cv2.imdecode(np.frombuffer(generate_aruco_png(17), dtype=np.uint8), cv2.IMREAD_COLOR)
        camera = QRCodeCamera(
            cv2_module=cv2,
            aruco_resolver=lambda marker_id: {"id": "PROD-17"} if marker_id == 17 else None,
        )
        for size in (50, 40, 30, 20):
            with self.subTest(size_mm=size):
                png = generate_aruco_png(17, size_mm=size)
                with Image.open(BytesIO(png)) as image:
                    for pixels, dpi in zip(image.size, image.info["dpi"]):
                        self.assertAlmostEqual(pixels / dpi * 25.4, size, delta=0.01)
                frame = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
                np.testing.assert_array_equal(frame, reference)
                self.assertEqual(camera.read_qrcode(frame), '{"produto_id":"PROD-17"}')

    def test_real_camera_suppresses_immediate_duplicate(self):
        camera = StaticQRCodeCamera('{"produto_id":"PROD-1"}')

        first = camera.scan_qrcode()
        with self.assertRaises(QRCodeNotFoundError) as context:
            camera.scan_qrcode()

        self.assertEqual(first, '{"produto_id":"PROD-1"}')
        self.assertIn("mesmo da leitura anterior", context.exception.message)

    def test_pickup_roi_limits_identification_and_rejects_multiple_markers(self):
        from vision.qrcode import CameraError
        left = cv2.imdecode(np.frombuffer(generate_aruco_png(17), dtype=np.uint8), cv2.IMREAD_COLOR)
        right = cv2.imdecode(np.frombuffer(generate_aruco_png(18), dtype=np.uint8), cv2.IMREAD_COLOR)
        frame = np.concatenate((left, right), axis=1)
        resolver = lambda marker: {"id": "LEFT" if marker == 17 else "RIGHT"}
        all_frame = QRCodeCamera(cv2_module=cv2, aruco_resolver=resolver)
        with self.assertRaises(CameraError):
            all_frame.read_qrcode(frame)
        bounded = QRCodeCamera(cv2_module=cv2, aruco_resolver=resolver, pickup_roi=(0, 0, 0.5, 1))
        self.assertEqual(bounded.read_qrcode(frame), '{"produto_id":"LEFT"}')

    def test_clear_label_barrier_does_not_depend_only_on_duplicate_timer(self):
        marker = cv2.imdecode(np.frombuffer(generate_aruco_png(17), dtype=np.uint8), cv2.IMREAD_COLOR)
        camera = QRCodeCamera(cv2_module=cv2, aruco_resolver=lambda _marker: {"id": "PRODUCT"})
        camera.capture_frame = lambda: marker
        self.assertFalse(camera.wait_until_clear(timeout=0.15))
        white = np.full_like(marker, 255)
        camera.capture_frame = lambda: white
        self.assertTrue(camera.wait_until_clear(timeout=1))


if __name__ == "__main__":
    unittest.main()
