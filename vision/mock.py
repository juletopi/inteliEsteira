"""Webcam simulada que entrega QR Codes enfileirados pela API ou pelos testes."""

from collections import deque

from vision.qrcode import CameraError, QRCodeNotFoundError


class MockQRCodeCamera:
    mode = "mock"

    def __init__(self):
        self._qr_codes = deque()
        self._connected = True

    def enqueue_qr_code(self, qr_code: str) -> None:
        self._qr_codes.append(qr_code)

    def capture_frame(self):
        if not self._connected:
            raise CameraError("Webcam simulada desconectada.")
        if not self._qr_codes:
            raise QRCodeNotFoundError("Nenhum QR Code aguardando leitura.")
        return self._qr_codes.popleft()

    def read_qrcode(self, frame):
        if not isinstance(frame, str) or not frame.strip():
            raise QRCodeNotFoundError("Nenhum QR Code encontrado no frame.")
        return frame

    def scan_qrcode(self, timeout=None, cancelled=None):
        if cancelled is not None and cancelled():
            raise CameraError("A leitura da camera foi interrompida.")
        return self.read_qrcode(self.capture_frame())

    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def connect(self) -> bool:
        self._connected = True
        return True
