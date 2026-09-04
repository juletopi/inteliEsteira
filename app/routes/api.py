from flask import Blueprint, jsonify
from app.services.status import get_system_status


api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.get("/status")
def status():
    return jsonify(get_system_status())


# TODO: criar endpoints POST para iniciar, parar e resetar o sistema.
# TODO: criar endpoints POST para comandos de garra, câmera e esteira.
# TODO: validar comandos recebidos antes de encaminhá-los ao controller.
# TODO: padronizar respostas JSON com estado, comando aceito e erro opcional.
