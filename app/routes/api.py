from io import BytesIO
import re

from flask import Blueprint, current_app, jsonify, request, send_file

from app.services.status import get_system_status
from core.classifier import (
    ClassificationError,
    DestinationUnavailableError,
    ProductNotFoundError,
    STATE_TO_MACROREGION,
    classify_qr_code,
    validate_product_id,
    validate_state,
)
from core.controller import ControllerError, CycleProcessingError, SystemBusyError
from hardware.arduino import ArduinoError
from hardware.serial_adapter import list_serial_ports
from storage.repositories import ProductAlreadyExistsError
from vision.qrcode import CameraError, generate_product_qr_png


api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.get("/status")
def status():
    return jsonify(get_system_status())


@api_bp.post("/route")
def resolve_route():
    """Valida um QR Code e devolve a regiao fisica selecionada."""

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _error_response("INVALID_REQUEST", "Envie um objeto JSON valido.", 400)

    qr_code = payload.get("qr_code")
    occupancy = payload.get("ocupacao", {})
    unavailable = payload.get("indisponiveis", [])

    if not isinstance(occupancy, dict):
        return _error_response(
            "INVALID_REQUEST",
            "O campo ocupacao deve ser um objeto JSON.",
            400,
        )
    if not isinstance(unavailable, list):
        return _error_response(
            "INVALID_REQUEST",
            "O campo indisponiveis deve ser uma lista.",
            400,
        )

    try:
        decision = classify_qr_code(
            qr_code,
            current_app.extensions["product_repository"].resolve,
            occupancy=occupancy,
            unavailable=unavailable,
        )
    except DestinationUnavailableError as exc:
        return _error_response(exc.code, exc.message, 409)
    except ProductNotFoundError as exc:
        return _error_response(exc.code, exc.message, 404)
    except ClassificationError as exc:
        return _error_response(exc.code, exc.message, 422)

    return jsonify({"ok": True, **decision.as_dict()})


@api_bp.post("/cycles")
def process_cycle():
    """Executa um ciclo completo usando os adaptadores configurados."""

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _error_response("INVALID_REQUEST", "Envie um objeto JSON valido.", 400)

    qr_code = payload.get("qr_code")
    occupancy = payload.get("ocupacao", {})
    unavailable = payload.get("indisponiveis", [])
    controller = current_app.extensions["system_controller"]
    camera_mode = getattr(controller.camera, "mode", "mock")
    if camera_mode == "mock" and not isinstance(qr_code, str):
        return _error_response(
            "INVALID_REQUEST",
            "No modo simulado, o campo qr_code deve ser uma string.",
            400,
        )
    if camera_mode != "mock" and qr_code is not None:
        return _error_response(
            "INVALID_REQUEST",
            "No modo de camera real, remova qr_code: a leitura sera feita pela webcam.",
            400,
        )
    if not isinstance(occupancy, dict) or not isinstance(unavailable, list):
        return _error_response(
            "INVALID_REQUEST",
            "Os campos ocupacao e indisponiveis possuem formato invalido.",
            400,
        )

    try:
        result = controller.process_next_product(
            qr_code=qr_code,
            occupancy=occupancy,
            unavailable=unavailable,
        )
    except SystemBusyError as exc:
        return _error_response(exc.code, exc.message, 409)
    except CycleProcessingError as exc:
        status_code = 404 if exc.code == "PRODUCT_NOT_FOUND" else 422
        return _error_response(exc.code, exc.message, status_code)
    except ControllerError as exc:
        return _error_response(exc.code, exc.message, 409)

    return jsonify({"ok": True, **result.as_dict()}), 201


@api_bp.get("/cycles")
def list_cycles():
    limit = request.args.get("limit", default=100, type=int) or 100
    cycles = current_app.extensions["cycle_repository"].list_recent(limit)
    return jsonify({"ok": True, "ciclos": cycles})


@api_bp.get("/cycles/<cycle_id>")
def get_cycle(cycle_id):
    cycle = current_app.extensions["cycle_repository"].get(
        cycle_id,
        include_events=True,
    )
    if cycle is None:
        return _error_response("CYCLE_NOT_FOUND", "Ciclo nao encontrado.", 404)
    return jsonify({"ok": True, "ciclo": cycle})


@api_bp.get("/products")
def list_products():
    products = [
        _with_macroregion(product)
        for product in current_app.extensions["product_repository"].list()
    ]
    return jsonify({"ok": True, "produtos": products})


@api_bp.post("/products")
def create_product():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _error_response("INVALID_REQUEST", "Envie um objeto JSON valido.", 400)

    try:
        product_id = validate_product_id(payload.get("produto_id"))
        state = validate_state(payload.get("uf"))
        product = current_app.extensions["product_repository"].create(
            product_id,
            state,
        )
    except ProductAlreadyExistsError as exc:
        return _error_response("PRODUCT_ALREADY_EXISTS", str(exc), 409)
    except ClassificationError as exc:
        return _error_response(exc.code, exc.message, 422)

    return jsonify({"ok": True, "produto": _with_macroregion(product)}), 201


@api_bp.put("/products/<product_id>")
def update_product(product_id):
    repository = current_app.extensions["product_repository"]
    existing = repository.get(product_id, include_inactive=True)
    if existing is None:
        return _error_response("PRODUCT_NOT_FOUND", "Produto nao encontrado.", 404)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _error_response("INVALID_REQUEST", "Envie um objeto JSON valido.", 400)

    active = payload.get("ativo", existing["ativo"])
    if not isinstance(active, bool):
        return _error_response(
            "INVALID_REQUEST",
            "O campo ativo deve ser verdadeiro ou falso.",
            400,
        )

    try:
        state = validate_state(payload.get("uf", existing["uf"]))
    except ClassificationError as exc:
        return _error_response(exc.code, exc.message, 422)

    product = repository.update(product_id, state=state, active=active)
    return jsonify({"ok": True, "produto": _with_macroregion(product)})


@api_bp.delete("/products/<product_id>")
def deactivate_product(product_id):
    product = current_app.extensions["product_repository"].deactivate(product_id)
    if product is None:
        return _error_response("PRODUCT_NOT_FOUND", "Produto nao encontrado.", 404)
    return jsonify({"ok": True, "produto": _with_macroregion(product)})


@api_bp.get("/products/<product_id>/qrcode")
def product_qrcode(product_id):
    """Entrega o QR canonico de um produto cadastrado em formato PNG."""

    product = current_app.extensions["product_repository"].get(
        product_id,
        include_inactive=True,
    )
    if product is None:
        return _error_response("PRODUCT_NOT_FOUND", "Produto nao encontrado.", 404)

    try:
        png = generate_product_qr_png(product["id"])
    except CameraError as exc:
        return _error_response(exc.code, exc.message, 503)

    safe_product_id = re.sub(r"[^A-Za-z0-9._-]+", "_", product["id"])
    as_attachment = request.args.get("download", "").lower() in {"1", "true", "sim"}
    response = send_file(
        BytesIO(png),
        mimetype="image/png",
        download_name=f"qr-{safe_product_id}.png",
        as_attachment=as_attachment,
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@api_bp.get("/camera/frame")
def camera_frame():
    """Entrega um frame JPEG para o preview quando a webcam real esta ativa."""

    camera = current_app.extensions["camera"]
    if getattr(camera, "mode", "mock") != "opencv" or not hasattr(
        camera, "capture_jpeg"
    ):
        return _error_response(
            "CAMERA_PREVIEW_UNAVAILABLE",
            "O preview so esta disponivel no modo opencv.",
            409,
        )

    try:
        jpeg = camera.capture_jpeg()
    except CameraError as exc:
        return _error_response(exc.code, exc.message, 503)

    response = send_file(BytesIO(jpeg), mimetype="image/jpeg", max_age=0)
    response.headers["Cache-Control"] = "no-store"
    return response


@api_bp.post("/system/stop")
def stop_system():
    controller = current_app.extensions["system_controller"]
    return jsonify({"ok": True, "sistema": controller.stop()})


@api_bp.post("/system/connect")
def connect_system():
    controller = current_app.extensions["system_controller"]
    try:
        snapshot = controller.connect_components()
    except ControllerError as exc:
        return _error_response(exc.code, exc.message, 503)
    return jsonify({"ok": True, "sistema": snapshot})


@api_bp.get("/hardware/ports")
def hardware_ports():
    try:
        ports = list_serial_ports()
    except ArduinoError as exc:
        return _error_response(exc.code, exc.message, 503)
    return jsonify({"ok": True, "portas": ports})


@api_bp.post("/system/reset")
def reset_system():
    controller = current_app.extensions["system_controller"]
    try:
        snapshot = controller.reset()
    except ControllerError as exc:
        return _error_response(exc.code, exc.message, 409)
    return jsonify({"ok": True, "sistema": snapshot})


def _error_response(code: str, message: str, status_code: int):
    return jsonify(
        {
            "ok": False,
            "erro": {
                "codigo": code,
                "mensagem": message,
            },
        }
    ), status_code


def _with_macroregion(product: dict) -> dict:
    return {
        **product,
        "macroregiao": STATE_TO_MACROREGION[product["uf"]].value,
    }
