import atexit
import json
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
    if app.config.get("TESTING"):
        for name, value in (("CAMERA_MODE", "mock"), ("HARDWARE_MODE", "mock"), ("CONVEYOR_MODE", "arduino"),
                            ("BOOTSTRAP_CATALOG", False), ("REQUIRE_PHYSICAL_ARRIVAL", False)):
            if name not in (test_config or {}):
                app.config[name] = value

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
    from hardware.ev3_adapter import EV3Adapter
    from hardware.gripper import Gripper
    from hardware.mock import MockArduino
    from hardware.serial_adapter import SerialArduino
    from hardware.serial_simulator import SocketArduino
    from core.workflow import Workflow
    from storage.queue import QueueRepository
    from storage.catalog import import_catalog
    from storage.database import Database
    from storage.repositories import CycleRepository, ProductRepository
    from vision.mock import MockQRCodeCamera
    from vision.qrcode import QRCodeCamera

    database = Database(app.config["DATABASE_PATH"])
    database.initialize()
    if app.config.get("BOOTSTRAP_CATALOG"):
        with database.connect() as connection:
            empty = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        if empty:
            with Path(app.config["BOOTSTRAP_CATALOG_PATH"]).open(encoding="utf-8-sig") as source:
                import_catalog(database, json.load(source))
    products = ProductRepository(database)
    cycles = CycleRepository(database)
    hardware_mode = str(app.config.get("HARDWARE_MODE", "mock")).strip().lower()
    if hardware_mode == "mock":
        arduino = MockArduino()
        arduino.connect()
    elif hardware_mode in {"serial", "simulator"}:
        serial_options = dict(
            port=app.config.get("ARDUINO_PORT", "COM3"),
            baudrate=app.config.get("ARDUINO_BAUDRATE", 9600),
            read_timeout=app.config.get("ARDUINO_READ_TIMEOUT", 0.1),
            write_timeout=app.config.get("ARDUINO_WRITE_TIMEOUT", 1.0),
            boot_wait=app.config.get("ARDUINO_BOOT_WAIT", 2.0),
        )
        if hardware_mode == "simulator":
            serial_options.pop("port")
            serial_options.pop("boot_wait")
            arduino = SocketArduino(port=app.config["ARDUINO_SIMULATOR_PORT"], **serial_options)
        else:
            arduino = SerialArduino(**serial_options)
        # Porta real/virtual so abre por uma acao do operador, evitando duas conexoes
        # quando o reloader do Flask cria um processo pai e outro servidor.
        atexit.register(arduino.disconnect)
    else:
        raise RuntimeError(
            "HARDWARE_MODE deve ser 'mock', 'simulator' ou 'serial'. "
            f"Valor recebido: {hardware_mode!r}."
        )
    conveyor_mode = str(app.config.get("CONVEYOR_MODE", "arduino")).strip().lower()
    if conveyor_mode == "arduino":
        conveyor_device = arduino
    elif conveyor_mode == "mock":
        conveyor_device = MockArduino()
        conveyor_device.connect()
    elif conveyor_mode == "ev3":
        conveyor_device = EV3Adapter(
            host=app.config.get("EV3_HOST", ""),
            port=app.config.get("EV3_PORT", 8765),
            token=app.config.get("EV3_TOKEN", ""),
            connect_timeout=app.config.get("EV3_CONNECT_TIMEOUT", 2.0),
        )
        # Conecta pela tela/API ou no preflight do ciclo; iniciar Flask nao move nada.
        atexit.register(conveyor_device.disconnect)
    else:
        raise RuntimeError(
            "CONVEYOR_MODE deve ser 'arduino', 'mock' ou 'ev3'. "
            f"Valor recebido: {conveyor_mode!r}."
        )
    camera_mode = str(app.config.get("CAMERA_MODE", "mock")).strip().lower()
    if camera_mode == "mock":
        camera = MockQRCodeCamera()
    elif camera_mode == "opencv":
        camera = QRCodeCamera(
            app.config.get("CAMERA_INDEX", 0),
            width=app.config.get("CAMERA_WIDTH", 1280),
            height=app.config.get("CAMERA_HEIGHT", 720),
            scan_timeout=app.config.get("CAMERA_SCAN_TIMEOUT", 8.0),
            retry_interval=app.config.get("CAMERA_RETRY_INTERVAL", 0.08),
            duplicate_cooldown=app.config.get("CAMERA_DUPLICATE_COOLDOWN", 3.0),
            aruco_resolver=products.resolve_aruco,
            pickup_roi=app.config.get("CAMERA_PICKUP_ROI"),
        )
        atexit.register(camera.disconnect)
    else:
        raise RuntimeError(
            "CAMERA_MODE deve ser 'mock' ou 'opencv'. "
            f"Valor recebido: {camera_mode!r}."
        )
    controller = SystemController(
        state=SystemState(),
        gripper=Gripper(arduino, calibrated=app.config.get("GRIPPER_PROFILE_CALIBRATED", False)),
        conveyor=Conveyor(conveyor_device, arrival_sensor=arduino if app.config.get("ARRIVAL_SENSOR_MODE") == "arduino" and conveyor_device is not arduino else None),
        camera=camera,
        product_repository=products,
        cycle_repository=cycles,
        command_timeout=app.config.get("COMMAND_TIMEOUT", 2.0),
        arrival_timeout=app.config.get("ARRIVAL_TIMEOUT", 35.0),
        command_retries=app.config.get("COMMAND_RETRIES", 1),
        gripper_timeout=app.config.get("GRIPPER_COMPLETION_TIMEOUT", 30.0),
        require_physical_arrival=app.config.get("REQUIRE_PHYSICAL_ARRIVAL", True),
    )

    app.extensions["system_controller"] = controller
    app.extensions["arduino"] = arduino
    app.extensions["conveyor_device"] = conveyor_device
    app.extensions["camera"] = camera
    app.extensions["database"] = database
    app.extensions["product_repository"] = products
    app.extensions["cycle_repository"] = cycles
    workflow = Workflow(controller, QueueRepository(database))
    app.extensions["workflow"] = workflow
    atexit.register(workflow.shutdown)
