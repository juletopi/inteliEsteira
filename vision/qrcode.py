class QRCodeCamera:
    def __init__(self, camera_index=0):
        self.camera_index = camera_index

    def capture_frame(self):
        # TODO: abrir a câmera e capturar um frame com OpenCV.
        raise NotImplementedError

    def read_qrcode(self, frame):
        # TODO: detectar e retornar o conteúdo do QR Code.
        raise NotImplementedError
