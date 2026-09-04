from flask import Flask
from pathlib import Path


def create_app():
    project_root = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        template_folder=project_root / "templates",
    )

    from app.routes.api import api_bp
    from app.routes.pages import pages_bp

    # TODO: registrar blueprints adicionais para garra, câmera e esteira quando as APIs forem implementadas.
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)

    return app
