import unittest

import cv2
import numpy as np

from vision.qrcode import (
    QRCodeCamera,
    QRCodeNotFoundError,
    build_product_qr_payload,
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

    def test_real_camera_suppresses_immediate_duplicate(self):
        camera = StaticQRCodeCamera('{"produto_id":"PROD-1"}')

        first = camera.scan_qrcode()
        with self.assertRaises(QRCodeNotFoundError) as context:
            camera.scan_qrcode()

        self.assertEqual(first, '{"produto_id":"PROD-1"}')
        self.assertIn("mesmo da leitura anterior", context.exception.message)


if __name__ == "__main__":
    unittest.main()
