import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
ARDUINO_PORT = os.getenv("ARDUINO_PORT", "COM3").strip()
ARDUINO_BAUDRATE = int(os.getenv("ARDUINO_BAUDRATE", "9600"))
ARDUINO_READ_TIMEOUT = float(os.getenv("ARDUINO_READ_TIMEOUT", "0.1"))
ARDUINO_WRITE_TIMEOUT = float(os.getenv("ARDUINO_WRITE_TIMEOUT", "1.0"))
ARDUINO_BOOT_WAIT = float(os.getenv("ARDUINO_BOOT_WAIT", "2.0"))
CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
CAMERA_MODE = os.getenv("CAMERA_MODE", "opencv").strip().lower()
CAMERA_WIDTH = int(os.getenv("CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("CAMERA_HEIGHT", "720"))
CAMERA_SCAN_TIMEOUT = float(os.getenv("CAMERA_SCAN_TIMEOUT", "8.0"))
CAMERA_RETRY_INTERVAL = float(os.getenv("CAMERA_RETRY_INTERVAL", "0.08"))
CAMERA_DUPLICATE_COOLDOWN = float(
    os.getenv("CAMERA_DUPLICATE_COOLDOWN", "3.0")
)
HARDWARE_MODE = os.getenv("HARDWARE_MODE", "mock").strip().lower()
CONVEYOR_MODE = os.getenv("CONVEYOR_MODE", "arduino").strip().lower()
EV3_HOST = os.getenv("EV3_HOST", "").strip()
EV3_PORT = int(os.getenv("EV3_PORT", "8765"))
EV3_TOKEN = os.getenv("EV3_TOKEN", "").strip()
EV3_CONNECT_TIMEOUT = float(os.getenv("EV3_CONNECT_TIMEOUT", "2.0"))
COMMAND_TIMEOUT = float(os.getenv("COMMAND_TIMEOUT", "2.0"))
COMMAND_RETRIES = int(os.getenv("COMMAND_RETRIES", "1"))
# A maior sequencia do EV3 leva mais que os antigos 5 segundos.
ARRIVAL_TIMEOUT = float(os.getenv("ARRIVAL_TIMEOUT", "35.0"))
DATABASE_PATH = PROJECT_ROOT / "data" / "inteliesteira.db"
BOOTSTRAP_CATALOG = os.getenv("BOOTSTRAP_CATALOG", "1").strip().lower() in {"1", "true", "sim"}
BOOTSTRAP_CATALOG_PATH = PROJECT_ROOT / "data" / "catalogo-inicial.json"
CAMERA_PICKUP_ROI = tuple(float(value) for value in os.getenv("CAMERA_PICKUP_ROI", "0,0,1,1").split(","))
GRIPPER_PROFILE_CALIBRATED = os.getenv("GRIPPER_PROFILE_CALIBRATED", "0").strip().lower() in {"1", "true", "sim"}
GRIPPER_COMPLETION_TIMEOUT = float(os.getenv("GRIPPER_COMPLETION_TIMEOUT", "30"))
REQUIRE_PHYSICAL_ARRIVAL = os.getenv("REQUIRE_PHYSICAL_ARRIVAL", "1").strip().lower() in {"1", "true", "sim"}
ARRIVAL_SENSOR_MODE = os.getenv("ARRIVAL_SENSOR_MODE", "conveyor").strip().lower()
ARDUINO_SIMULATOR_PORT = int(os.getenv("ARDUINO_SIMULATOR_PORT", "8766"))
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000
