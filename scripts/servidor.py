"""Servidor de bancada fisica, sem reloader nem conexoes duplicadas."""

from app import create_app
from config import FLASK_HOST, FLASK_PORT


if __name__ == "__main__":
    app = create_app()
    try:
        app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, use_reloader=False)
    finally:
        app.extensions["camera_monitor"].shutdown()
        app.extensions["workflow"].shutdown()
