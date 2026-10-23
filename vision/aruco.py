"""Captura pela webcam, identificacao e geracao de etiquetas ArUco."""

from __future__ import annotations

from io import BytesIO
import json
import os
from threading import RLock
from time import monotonic, sleep


class CameraError(RuntimeError):
    code = "CAMERA_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class CameraDependencyError(CameraError):
    code = "CAMERA_DEPENDENCY_ERROR"


class CameraUnavailableError(CameraError):
    code = "CAMERA_UNAVAILABLE"


class CameraCaptureError(CameraError):
    code = "CAMERA_CAPTURE_ERROR"


class ArucoNotFoundError(CameraError):
    code = "ARUCO_NOT_FOUND"


class ArucoNotRegisteredError(CameraError):
    code = "ARUCO_NOT_REGISTERED"


class ArucoCamera:
    """Adaptador OpenCV para uma webcam local.

    A captura e protegida por lock porque o painel pode solicitar uma imagem de
    preview enquanto o controller esta procurando um ArUco.
    """

    mode = "opencv"

    def __init__(
        self,
        camera_index=0,
        *,
        width=1280,
        height=720,
        scan_timeout=8.0,
        retry_interval=0.08,
        duplicate_cooldown=3.0,
        cv2_module=None,
        aruco_resolver=None,
        pickup_roi=None,
    ):
        self.camera_index = int(camera_index)
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.scan_timeout = max(0.1, float(scan_timeout))
        self.retry_interval = max(0.01, float(retry_interval))
        self.duplicate_cooldown = max(0.0, float(duplicate_cooldown))
        self._cv2 = cv2_module or _load_cv2()
        self._aruco_resolver = aruco_resolver
        aruco = getattr(self._cv2, "aruco", None)
        if aruco is None:
            raise CameraDependencyError("O OpenCV instalado nao oferece deteccao ArUco.")
        dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_250)
        self._aruco_detector = aruco.ArucoDetector(dictionary)
        self._capture = None
        self._connected = False
        self._lock = RLock()
        self._last_qr_code = None
        self._last_qr_time = 0.0
        self.pickup_roi = pickup_roi
        if pickup_roi is not None:
            if len(pickup_roi) != 4 or any(not 0 <= value <= 1 for value in pickup_roi):
                raise ValueError("A ROI deve informar x, y, largura e altura normalizados entre 0 e 1.")
            x, y, w, h = pickup_roi
            if w <= 0 or h <= 0 or x + w > 1 or y + h > 1:
                raise ValueError("A ROI deve ficar dentro do enquadramento.")

    def connect(self) -> bool:
        """Tenta abrir a webcam sem impedir que o servidor Flask inicie."""

        with self._lock:
            if self._capture is not None and self._capture.isOpened():
                return True

            # No Windows o backend padrao (Media Foundation) abriu a C270 sem entregar
            # frames e levava ~80 s; DirectShow abre em segundos. Padrao fica de reserva.
            backends = ([self._cv2.CAP_DSHOW] if os.name == "nt" and hasattr(self._cv2, "CAP_DSHOW") else []) + [None]
            capture = None
            for backend in backends:
                capture = (self._cv2.VideoCapture(self.camera_index) if backend is None
                           else self._cv2.VideoCapture(self.camera_index, backend))
                if capture is not None and capture.isOpened():
                    break
                if capture is not None:
                    capture.release()
                capture = None
            if capture is None:
                self._capture = None
                self._connected = False
                return False

            capture.set(self._cv2.CAP_PROP_FRAME_WIDTH, self.width)
            capture.set(self._cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self._capture = capture
            self._connected = True
            return True

    def disconnect(self) -> None:
        with self._lock:
            if self._capture is not None:
                self._capture.release()
            self._capture = None
            self._connected = False

    def capture_frame(self):
        with self._lock:
            if not self.connect():
                raise CameraUnavailableError(
                    f"Nao foi possivel abrir a webcam de indice {self.camera_index}."
                )

            success, frame = self._capture.read()
            if not success or frame is None:
                self.disconnect()
                raise CameraCaptureError("A webcam nao entregou um frame valido.")
            return frame

    def read_aruco(self, frame) -> str:
        if frame is None:
            raise ArucoNotFoundError("Nenhum frame foi informado para leitura.")
        if self.pickup_roi is not None:
            height, width = frame.shape[:2]
            x, y, w, h = self.pickup_roi
            frame = frame[int(y * height):max(int((y + h) * height), int(y * height) + 1),
                          int(x * width):max(int((x + w) * width), int(x * width) + 1)]

        try:
            _corners, ids, _rejected = self._aruco_detector.detectMarkers(frame)
        except Exception as exc:
            raise CameraCaptureError("O OpenCV nao conseguiu analisar o marcador ArUco.") from exc
        if ids is not None and len(ids):
            if len(ids) != 1:
                raise CameraError("Mais de um marcador ArUco na area de leitura.")
            marker_id = int(ids[0][0])
            product = self._aruco_resolver(marker_id) if self._aruco_resolver else None
            if product is None:
                raise ArucoNotRegisteredError(
                    f"O marcador ArUco {marker_id} nao esta vinculado a um produto."
                )
            return build_product_payload(product["id"])
        raise ArucoNotFoundError("Nenhum ArUco encontrado na area de leitura.")

    def scan_aruco(self, timeout=None, cancelled=None) -> str:
        """Le frames continuamente ate encontrar um QR novo ou expirar."""

        scan_timeout = self.scan_timeout if timeout is None else max(0.1, float(timeout))
        deadline = monotonic() + scan_timeout
        duplicate_seen = False

        while monotonic() < deadline:
            if cancelled is not None and cancelled():
                raise CameraError("A leitura da camera foi interrompida.")
            frame = self.capture_frame()
            try:
                qr_code = self.read_aruco(frame)
            except ArucoNotFoundError:
                sleep(self.retry_interval)
                continue

            now = monotonic()
            if (
                qr_code == self._last_qr_code
                and now - self._last_qr_time < self.duplicate_cooldown
            ):
                duplicate_seen = True
                sleep(self.retry_interval)
                continue

            self._last_qr_code = qr_code
            self._last_qr_time = now
            return qr_code

        if duplicate_seen:
            raise ArucoNotFoundError(
                "O ArUco ainda e o mesmo da leitura anterior. Retire o produto "
                "da camera e tente novamente."
            )
        raise ArucoNotFoundError(
            f"Nenhum ArUco foi encontrado em {scan_timeout:.1f} segundos."
        )

    def wait_until_clear(self, timeout=0.5, cancelled=None):
        """Barreira contra etiqueta repetida: exige tres frames sem codigo visivel."""
        deadline = monotonic() + timeout
        empty_frames = 0
        while monotonic() < deadline:
            if cancelled is not None and cancelled():
                return False
            try:
                self.read_aruco(self.capture_frame())
                empty_frames = 0
            except ArucoNotFoundError:
                empty_frames += 1
                if empty_frames >= 3:
                    self._last_qr_code = None
                    return True
            sleep(self.retry_interval)
        return False

    def encode_jpeg(self, frame, *, quality=85) -> bytes:
        quality = max(1, min(int(quality), 100))
        success, encoded = self._cv2.imencode(
            ".jpg",
            frame,
            [int(self._cv2.IMWRITE_JPEG_QUALITY), quality],
        )
        if not success:
            raise CameraCaptureError("Nao foi possivel gerar o preview da webcam.")
        return encoded.tobytes()

    def capture_jpeg(self, *, quality=85) -> bytes:
        frame = self.capture_frame()
        if self.pickup_roi is not None:
            height, width = frame.shape[:2]
            x, y, w, h = self.pickup_roi
            self._cv2.rectangle(frame, (int(x * width), int(y * height)),
                                (min(width - 1, int((x + w) * width)), min(height - 1, int((y + h) * height))), (0, 180, 0), 2)
        return self.encode_jpeg(frame, quality=quality)

    def is_connected(self) -> bool:
        # Status polling must not wait for a camera read while its lock is held.
        return self._connected

    def resolution(self) -> dict[str, int] | None:
        # Return quickly when a capture is in progress; the configured size is
        # still useful to the UI and avoids blocking the whole Flask request.
        if not self._lock.acquire(blocking=False):
            return {"largura": self.width, "altura": self.height} if self._connected else None
        try:
            if not self._connected or self._capture is None:
                return None
            return {
                "largura": int(self._capture.get(self._cv2.CAP_PROP_FRAME_WIDTH)),
                "altura": int(self._capture.get(self._cv2.CAP_PROP_FRAME_HEIGHT)),
            }
        finally:
            self._lock.release()


def build_product_payload(product_id: str) -> str:
    """Payload interno do produto resolvido pelo ID ArUco, nao uma etiqueta QR."""

    return json.dumps(
        {"produto_id": product_id},
        ensure_ascii=False,
        separators=(",", ":"),
    )


ARUCO_PRINT_SIZES_MM = (50, 40, 30, 20)


def generate_aruco_png(marker_id: int, *, size_mm: int | None = None) -> bytes:
    """Gera DICT_4X4_250 com margem branca de um modulo em cada lado."""

    marker_id = int(marker_id)
    if not 0 <= marker_id < 250:
        raise ValueError("O ID ArUco deve estar entre 0 e 249.")
    if size_mm is not None and (type(size_mm) is not int or size_mm not in ARUCO_PRINT_SIZES_MM):
        raise ValueError("Escolha um tamanho ArUco de 20, 30, 40 ou 50 mm.")
    cv2 = _load_cv2()
    aruco = getattr(cv2, "aruco", None)
    if aruco is None:
        raise CameraDependencyError("O OpenCV instalado nao oferece geracao ArUco.")
    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_250)
    marker = aruco.generateImageMarker(dictionary, marker_id, 600, borderBits=1)
    image = cv2.copyMakeBorder(marker, 100, 100, 100, 100, cv2.BORDER_CONSTANT, value=255)
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise CameraCaptureError("Nao foi possivel gerar a etiqueta ArUco.")
    png = encoded.tobytes()
    if size_mm is not None:
        from PIL import Image

        # A imagem mantem os modulos nitidos; o DPI indica a medida fisica.
        output = BytesIO()
        with Image.open(BytesIO(png)) as printable:
            dpi = printable.width * 25.4 / size_mm
            printable.save(output, format="PNG", dpi=(dpi, dpi))
        return output.getvalue()
    return png


def _load_cv2():
    try:
        import cv2
    except ImportError as exc:
        raise CameraDependencyError(
            "O OpenCV nao esta instalado. Execute pip install -r requirements.txt."
        ) from exc
    return cv2
