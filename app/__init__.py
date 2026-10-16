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

    from storage.automatic_catalog import CatalogPersistenceError

    @app.errorhandler(CatalogPersistenceError)
    def catalog_storage_error(error):
        return {"ok": False, "erro": {"codigo": "CATALOG_STORAGE_ERROR", "mensagem": str(error)}}, 503

    _configure_controller(app)

    from app.routes.api import api_bp
    from app.routes.pages import pages_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)

    if app.config.get("AUTO_OPERATION", True) and not app.config.get("TESTING"):
        try:
            app.extensions["workflow"].start()
        except (ValueError, RuntimeError) as exc:
            app.logger.warning("Operacao automatica aguarda recuperacao: %s", exc)

    if not app.config.get("TESTING"):
        app.extensions["camera_monitor"].start()

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
    from storage.automatic_catalog import AutomaticCatalog
    from storage.database import Database
    from storage.repositories import CycleRepository, ProductRepository
    from vision.mock import MockArucoCamera
    from vision.aruco import ArucoCamera

    database = Database(app.config["DATABASE_PATH"])
    database.initialize()
    catalog_path = app.config.get("CATALOG_PATH")
    if catalog_path is None and not app.config.get("TESTING"):
        catalog_path = database.path.with_suffix(".json")
    if app.config.get("BOOTSTRAP_CATALOG") and (catalog_path is None or not Path(catalog_path).exists()):
        with database.connect() as connection:
            empty = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        if empty:
            with Path(app.config["BOOTSTRAP_CATALOG_PATH"]).open(encoding="utf-8-sig") as source:
                import_catalog(database, json.load(source))
    if catalog_path is not None:
        store = AutomaticCatalog(database, catalog_path)
        store.initialize()
        app.extensions["catalog_store"] = store
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
    elif conveyor_mode in {"ev3", "ev3_simulator"}:
        ev3_host = app.config.get("EV3_HOST", "")
        ev3_port = app.config.get("EV3_PORT", 8765)
        ev3_token = app.config.get("EV3_TOKEN", "")
        if conveyor_mode == "ev3_simulator":
            from secrets import token_hex
            from threading import Thread
            from ev3.simulator import EV3Simulator

            ev3_token = token_hex(16)
            server = EV3Simulator(token=ev3_token, delay=app.config.get("EV3_SIMULATOR_DELAY", 0.3))
            server_thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            server_thread.start()
            ev3_host, ev3_port = server.server_address
            app.extensions["conveyor_server"] = server

            def stop_conveyor_server():
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=1)

            app.extensions["stop_conveyor_server"] = stop_conveyor_server
            atexit.register(stop_conveyor_server)
        conveyor_device = EV3Adapter(
            host=ev3_host,
            port=ev3_port,
            token=ev3_token,
            connect_timeout=app.config.get("EV3_CONNECT_TIMEOUT", 2.0),
        )
        if conveyor_mode == "ev3_simulator" or app.config.get("EV3_IS_SIMULATED"):
            conveyor_device.mode = "ev3_simulator"
            conveyor_device.arrival_source = "simulado"
        # Conecta pela tela/API ou no preflight do ciclo; iniciar Flask nao move nada.
        atexit.register(conveyor_device.disconnect)
    else:
        raise RuntimeError(
            "CONVEYOR_MODE deve ser 'arduino', 'mock', 'ev3' ou 'ev3_simulator'. "
            f"Valor recebido: {conveyor_mode!r}."
        )
    camera_mode = str(app.config.get("CAMERA_MODE", "mock")).strip().lower()
    if camera_mode == "mock":
        camera = MockArucoCamera()
    elif camera_mode == "opencv":
        camera = ArucoCamera(
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
        require_physical_arrival=app.config.get("REQUIRE_PHYSICAL_ARRIVAL", False),
    )

    app.extensions["system_controller"] = controller
    app.extensions["arduino"] = arduino
    app.extensions["conveyor_device"] = conveyor_device
    app.extensions["camera"] = camera
    app.extensions["database"] = database
    app.extensions["product_repository"] = products
    app.extensions["cycle_repository"] = cycles
    workflow = Workflow(controller, QueueRepository(database),
                        presence_distance=app.config.get("PRESENCE_DISTANCE_CM", 10),
                        presence_stable_ms=app.config.get("PRESENCE_STABLE_MS", 3000))
    app.extensions["workflow"] = workflow
    atexit.register(workflow.shutdown)
    from app.services.camera_monitor import CameraMonitor

    monitor = CameraMonitor(controller, workflow)
    app.extensions["camera_monitor"] = monitor
    atexit.register(monitor.shutdown)
