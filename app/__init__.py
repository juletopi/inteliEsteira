import atexit
from pathlib import Path

from flask import Flask


def create_app(test_config=None):
    project_root = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        template_folder=project_root / "templates",
    )
    app.config.from_object("config")
    if test_config:
        app.config.update(test_config)

    _configure_controller(app)

    from app.routes.api import api_bp
    from app.routes.pages import pages_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)

    return app


def _configure_controller(app):
    from core.controller import SystemController
    from core.state import SystemState
    from hardware.arduino import ArduinoError
    from hardware.conveyor import Conveyor
    from hardware.gripper import Gripper
    from hardware.mock import MockArduino
    from hardware.serial_adapter import SerialArduino
    from storage.database import Database
    from storage.repositories import CycleRepository, ProductRepository
    from vision.mock import MockQRCodeCamera
    from vision.qrcode import QRCodeCamera

    database = Database(app.config["DATABASE_PATH"])
    database.initialize()
    products = ProductRepository(database)
    cycles = CycleRepository(database)
    hardware_mode = str(app.config.get("HARDWARE_MODE", "mock")).strip().lower()
    if hardware_mode == "mock":
        arduino = MockArduino()
        arduino.connect()
    elif hardware_mode == "serial":
        arduino = SerialArduino(
            port=app.config.get("ARDUINO_PORT", "COM3"),
            baudrate=app.config.get("ARDUINO_BAUDRATE", 9600),
            read_timeout=app.config.get("ARDUINO_READ_TIMEOUT", 0.1),
            write_timeout=app.config.get("ARDUINO_WRITE_TIMEOUT", 1.0),
            boot_wait=app.config.get("ARDUINO_BOOT_WAIT", 2.0),
        )
        try:
            arduino.connect()
        except ArduinoError:
            pass
        atexit.register(arduino.disconnect)
    else:
        raise RuntimeError(
            "HARDWARE_MODE deve ser 'mock' ou 'serial'. "
            f"Valor recebido: {hardware_mode!r}."
        )
    camera_mode = str(app.config.get("CAMERA_MODE", "mock")).strip().lower()
    if camera_mode == "mock":
        camera = MockQRCodeCamera()
    elif camera_mode == "opencv":
        camera = QRCodeCamera(
            app.config.get("CAMERA_INDEX", 0),
            scan_timeout=app.config.get("CAMERA_SCAN_TIMEOUT", 8.0),
            retry_interval=app.config.get("CAMERA_RETRY_INTERVAL", 0.08),
            duplicate_cooldown=app.config.get("CAMERA_DUPLICATE_COOLDOWN", 3.0),
        )
        atexit.register(camera.disconnect)
    else:
        raise RuntimeError(
            "CAMERA_MODE deve ser 'mock' ou 'opencv'. "
            f"Valor recebido: {camera_mode!r}."
        )
    controller = SystemController(
        state=SystemState(),
        gripper=Gripper(arduino),
        conveyor=Conveyor(arduino),
        camera=camera,
        product_repository=products,
        cycle_repository=cycles,
        command_timeout=app.config.get("COMMAND_TIMEOUT", 2.0),
        arrival_timeout=app.config.get("ARRIVAL_TIMEOUT", 5.0),
        command_retries=app.config.get("COMMAND_RETRIES", 1),
    )

    app.extensions["system_controller"] = controller
    app.extensions["arduino"] = arduino
    app.extensions["camera"] = camera
    app.extensions["database"] = database
    app.extensions["product_repository"] = products
    app.extensions["cycle_repository"] = cycles
