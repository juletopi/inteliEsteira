import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
ARDUINO_PORT = os.getenv("ARDUINO_PORT", "COM3").strip()
ARDUINO_BAUDRATE = int(os.getenv("ARDUINO_BAUDRATE", "9600"))
ARDUINO_READ_TIMEOUT = float(os.getenv("ARDUINO_READ_TIMEOUT", "0.1"))
ARDUINO_WRITE_TIMEOUT = float(os.getenv("ARDUINO_WRITE_TIMEOUT", "1.0"))
ARDUINO_BOOT_WAIT = float(os.getenv("ARDUINO_BOOT_WAIT", "2.0"))
CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
CAMERA_MODE = os.getenv("CAMERA_MODE", "mock").strip().lower()
CAMERA_SCAN_TIMEOUT = float(os.getenv("CAMERA_SCAN_TIMEOUT", "8.0"))
CAMERA_RETRY_INTERVAL = float(os.getenv("CAMERA_RETRY_INTERVAL", "0.08"))
CAMERA_DUPLICATE_COOLDOWN = float(
    os.getenv("CAMERA_DUPLICATE_COOLDOWN", "3.0")
)
HARDWARE_MODE = os.getenv("HARDWARE_MODE", "mock").strip().lower()
DATABASE_PATH = PROJECT_ROOT / "data" / "inteliesteira.db"
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000
