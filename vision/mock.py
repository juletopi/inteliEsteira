"""Simula produtos identificados por ArUco, sem acessar uma webcam."""

from collections import deque

from vision.aruco import CameraError, ArucoNotFoundError


class MockArucoCamera:
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
            raise ArucoNotFoundError("Nenhum ArUco aguardando leitura simulada.")
        return self._qr_codes.popleft()

    def read_aruco(self, frame):
        if not isinstance(frame, str) or not frame.strip():
            raise ArucoNotFoundError("Nenhum ArUco encontrado no frame.")
        return frame

    def scan_aruco(self, timeout=None, cancelled=None):
        if cancelled is not None and cancelled():
            raise CameraError("A leitura da camera foi interrompida.")
        return self.read_aruco(self.capture_frame())

    def wait_until_clear(self, timeout=0.5, cancelled=None):
        # O simulador considera a unidade retirada; nao consome a proxima leitura.
        return not (cancelled is not None and cancelled())

    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def connect(self) -> bool:
        self._connected = True
        return True
