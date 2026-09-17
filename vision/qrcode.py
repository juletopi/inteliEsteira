"""Captura pela webcam, leitura e geracao dos QR Codes do projeto."""

from __future__ import annotations

from io import BytesIO
import json
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


class QRCodeNotFoundError(CameraError):
    code = "QR_CODE_NOT_FOUND"


class QRCodeCamera:
    """Adaptador OpenCV para uma webcam local.

    A captura e protegida por lock porque o painel pode solicitar uma imagem de
    preview enquanto o controller esta procurando um QR Code.
    """

    mode = "opencv"

    def __init__(
        self,
        camera_index=0,
        *,
        scan_timeout=8.0,
        retry_interval=0.08,
        duplicate_cooldown=3.0,
        cv2_module=None,
    ):
        self.camera_index = int(camera_index)
        self.scan_timeout = max(0.1, float(scan_timeout))
        self.retry_interval = max(0.01, float(retry_interval))
        self.duplicate_cooldown = max(0.0, float(duplicate_cooldown))
        self._cv2 = cv2_module or _load_cv2()
        self._detector = self._cv2.QRCodeDetector()
        self._capture = None
        self._lock = RLock()
        self._last_qr_code = None
        self._last_qr_time = 0.0

    def connect(self) -> bool:
        """Tenta abrir a webcam sem impedir que o servidor Flask inicie."""

        with self._lock:
            if self._capture is not None and self._capture.isOpened():
                return True

            capture = self._cv2.VideoCapture(self.camera_index)
            if capture is None or not capture.isOpened():
                if capture is not None:
                    capture.release()
                self._capture = None
                return False

            self._capture = capture
            return True

    def disconnect(self) -> None:
        with self._lock:
            if self._capture is not None:
                self._capture.release()
            self._capture = None

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

    def read_qrcode(self, frame) -> str:
        if frame is None:
            raise QRCodeNotFoundError("Nenhum frame foi informado para leitura.")

        try:
            decoded, _points, _straight = self._detector.detectAndDecode(frame)
        except Exception as exc:
            raise CameraCaptureError(
                "O OpenCV nao conseguiu analisar o frame da webcam."
            ) from exc

        decoded = decoded.strip() if isinstance(decoded, str) else ""
        if not decoded:
            raise QRCodeNotFoundError("Nenhum QR Code encontrado no frame.")
        return decoded

    def scan_qrcode(self, timeout=None, cancelled=None) -> str:
        """Le frames continuamente ate encontrar um QR novo ou expirar."""

        scan_timeout = self.scan_timeout if timeout is None else max(0.1, float(timeout))
        deadline = monotonic() + scan_timeout
        duplicate_seen = False

        while monotonic() < deadline:
            if cancelled is not None and cancelled():
                raise CameraError("A leitura da camera foi interrompida.")
            frame = self.capture_frame()
            try:
                qr_code = self.read_qrcode(frame)
            except QRCodeNotFoundError:
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
            raise QRCodeNotFoundError(
                "O QR Code ainda e o mesmo da leitura anterior. Retire o produto "
                "da camera e tente novamente."
            )
        raise QRCodeNotFoundError(
            f"Nenhum QR Code foi encontrado em {scan_timeout:.1f} segundos."
        )

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
        return self.encode_jpeg(self.capture_frame(), quality=quality)

    def is_connected(self) -> bool:
        with self._lock:
            return self._capture is not None and self._capture.isOpened()


def build_product_qr_payload(product_id: str) -> str:
    """Gera o JSON canonico gravado no QR Code."""

    return json.dumps(
        {"produto_id": product_id},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def generate_product_qr_png(product_id: str) -> bytes:
    """Gera um PNG pronto para imprimir ou exibir no produto."""

    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_M
    except ImportError as exc:
        raise CameraDependencyError(
            "A biblioteca qrcode nao esta instalada. Execute pip install -r requirements.txt."
        ) from exc

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(build_product_qr_payload(product_id))
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _load_cv2():
    try:
        import cv2
    except ImportError as exc:
        raise CameraDependencyError(
            "O OpenCV nao esta instalado. Execute pip install -r requirements.txt."
        ) from exc
    return cv2
