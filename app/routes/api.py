from io import BytesIO
import re
import json
from pathlib import Path

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
from storage.queue import QueueError
from storage.gripper_profile import GripperProfileError
from vision.aruco import build_product_payload
from storage.repositories import (
    ArucoMarkerConflictError,
    ArucoMarkersExhaustedError,
    ProductAlreadyExistsError,
    ProductNotRegisteredError,
)
from vision.labels import generate_aruco_batch_pdf, generate_aruco_pdf
from vision.aruco import (
    ARUCO_PRINT_SIZES_MM, ArucoNotRegisteredError, CameraError,
    ArucoNotFoundError, generate_aruco_png,
)


api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.get("/status")
def status():
    return jsonify(get_system_status())


@api_bp.post("/route")
def resolve_route():
    """Valida o payload interno do produto e devolve a regiao selecionada."""

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

    if current_app.extensions["workflow"].running():
        return _error_response("SYSTEM_BUSY", "A fila esta controlando a operacao. Pare o fluxo antes de executar um ciclo avulso.", 409)
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
def delete_product(product_id):
    deleted = current_app.extensions["product_repository"].delete(product_id)
    if not deleted:
        return _error_response("PRODUCT_NOT_FOUND", "Produto nao encontrado.", 404)
    return jsonify({"ok": True, "produto_id": product_id, "excluido": True})


@api_bp.get("/products/<product_id>/qrcode")
def product_qrcode(product_id):
    return _error_response("QR_CODE_REMOVED", "QR Code desativado. Utilize a etiqueta ArUco do produto.", 410)


@api_bp.post("/products/<product_id>/aruco")
def register_product_aruco(product_id):
    payload = request.get_json(silent=True) if request.get_data() else {}
    if not isinstance(payload, dict):
        return _error_response("INVALID_REQUEST", "Envie um objeto JSON valido.", 400)
    marker_id = payload.get("aruco_id")
    if "aruco_id" in payload and (type(marker_id) is not int or not 0 <= marker_id <= 249):
        return _error_response(
            "INVALID_REQUEST", "O aruco_id deve ser um inteiro entre 0 e 249.", 400
        )
    try:
        product = current_app.extensions["product_repository"].ensure_aruco(
            product_id, marker_id=marker_id
        )
    except ArucoMarkerConflictError as exc:
        return _error_response("ARUCO_ID_CONFLICT", str(exc), 409)
    except ArucoMarkersExhaustedError as exc:
        return _error_response("ARUCO_IDS_EXHAUSTED", str(exc), 409)
    if product is None:
        return _error_response("PRODUCT_NOT_FOUND", "Produto nao encontrado.", 404)
    return jsonify({"ok": True, "produto": _with_macroregion(product)})


@api_bp.get("/products/<product_id>/aruco")
def product_aruco(product_id):
    product = current_app.extensions["product_repository"].get(
        product_id, include_inactive=True
    )
    if product is None:
        return _error_response("PRODUCT_NOT_FOUND", "Produto nao encontrado.", 404)
    if product["aruco_id"] is None:
        return _error_response("ARUCO_NOT_REGISTERED", "Gere o ArUco deste produto primeiro.", 404)
    file_format = request.args.get("format", "png").lower()
    raw_size = request.args.get("size_mm")
    if file_format not in {"png", "pdf"}:
        return _error_response("INVALID_REQUEST", "Escolha o formato png ou pdf.", 400)
    if raw_size is not None and raw_size not in {str(size) for size in ARUCO_PRINT_SIZES_MM} | {"all"}:
        return _error_response("INVALID_REQUEST", "Escolha size_mm=20, 30, 40, 50 ou all.", 400)
    if raw_size == "all" and file_format != "pdf":
        return _error_response("INVALID_REQUEST", "Os quatro tamanhos juntos exigem formato pdf.", 400)
    size_mm = None if raw_size in {None, "all"} else int(raw_size)
    suffix = ""
    try:
        if file_format == "pdf":
            size_mm = 20 if raw_size is None else size_mm
            content = generate_aruco_pdf(product["id"], product["aruco_id"], size_mm=size_mm)
            suffix = "-4-tamanhos" if size_mm is None else f"-{size_mm}mm"
        else:
            content = generate_aruco_png(product["aruco_id"], size_mm=size_mm)
            if size_mm is not None:
                suffix = f"-{size_mm}mm"
    except CameraError as exc:
        return _error_response(exc.code, exc.message, 503)
    safe_product_id = re.sub(r"[^A-Za-z0-9._-]+", "_", product["id"])
    as_attachment = request.args.get("download", "").lower() in {"1", "true", "sim"}
    response = send_file(
        BytesIO(content), mimetype="application/pdf" if file_format == "pdf" else "image/png",
        download_name=f"aruco-{safe_product_id}-id{product['aruco_id']}{suffix}.{file_format}",
        as_attachment=as_attachment, max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@api_bp.post("/products/aruco/batch")
def product_aruco_batch():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _error_response("INVALID_REQUEST", "Envie um objeto JSON valido.", 400)
    items = payload.get("products")
    if not isinstance(items, list) or not 1 <= len(items) <= 250:
        return _error_response("INVALID_REQUEST", "Selecione de 1 a 250 produtos.", 400)
    size = payload.get("size_mm", 20)
    if size != "all" and (type(size) is not int or size not in ARUCO_PRINT_SIZES_MM):
        return _error_response("INVALID_REQUEST", "Escolha size_mm=20, 30, 40, 50 ou all.", 400)
    requests, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            return _error_response("INVALID_REQUEST", "Cada item deve informar produto_id.", 400)
        try:
            product_id = validate_product_id(item.get("produto_id"))
        except ClassificationError as exc:
            return _error_response("INVALID_REQUEST", exc.message, 400)
        if product_id.lower() in seen:
            return _error_response("INVALID_REQUEST", f"Produto repetido no lote: {product_id}.", 400)
        seen.add(product_id.lower())
        marker_id = item.get("aruco_id")
        if "aruco_id" in item and (type(marker_id) is not int or not 0 <= marker_id <= 249):
            return _error_response("INVALID_REQUEST", "O aruco_id deve ser um inteiro de 0 a 249.", 400)
        requests.append({"produto_id": product_id, "aruco_id": marker_id})
    try:
        products = current_app.extensions["product_repository"].ensure_aruco_batch(requests)
        content = generate_aruco_batch_pdf(products, size_mm=None if size == "all" else size)
    except ProductNotRegisteredError as exc:
        return _error_response("PRODUCT_NOT_FOUND", str(exc), 404)
    except ArucoMarkerConflictError as exc:
        return _error_response("ARUCO_ID_CONFLICT", str(exc), 409)
    except ArucoMarkersExhaustedError as exc:
        return _error_response("ARUCO_IDS_EXHAUSTED", str(exc), 409)
    except CameraError as exc:
        return _error_response(exc.code, exc.message, 503)
    suffix = "4-tamanhos" if size == "all" else f"{size}mm"
    response = send_file(
        BytesIO(content), mimetype="application/pdf", as_attachment=True,
        download_name=f"aruco-lote-{suffix}.pdf", max_age=0,
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


@api_bp.post("/camera/identify")
def identify_camera_frame():
    """Diagnostico de um frame, sem iniciar fila, garra ou esteira."""
    if current_app.extensions["workflow"].running():
        return _error_response("SYSTEM_BUSY", "Pare o fluxo automatico antes de testar a camera.", 409)
    controller = current_app.extensions["system_controller"]
    if getattr(controller.camera, "mode", None) != "opencv":
        return _error_response("CAMERA_PREVIEW_UNAVAILABLE", "O diagnostico exige camera real no modo opencv.", 409)
    try:
        decision = current_app.extensions["camera_monitor"].observe_once()
    except SystemBusyError as exc:
        return _error_response(exc.code, exc.message, 409)
    except (ArucoNotFoundError, ArucoNotRegisteredError) as exc:
        return _error_response(exc.code, exc.message, 422)
    except CameraError as exc:
        return _error_response(exc.code, exc.message, 503)
    except ProductNotFoundError as exc:
        return _error_response(exc.code, exc.message, 404)
    except DestinationUnavailableError as exc:
        return _error_response(exc.code, exc.message, 409)
    except ClassificationError as exc:
        return _error_response(exc.code, exc.message, 422)
    return jsonify({"ok": True, "diagnostico": True, **decision.as_dict()})


@api_bp.post("/system/stop")
def stop_system():
    return jsonify({"ok": True, "sistema": current_app.extensions["workflow"].stop()})


@api_bp.post("/system/connect")
def connect_system():
    if current_app.extensions.get("calibration_session"):
        return _error_response("CALIBRATION_ACTIVE", "Encerre a sessão do calibrador antes de conectar o backend ao Arduino.", 409)
    controller = current_app.extensions["system_controller"]
    warnings = []
    labels = {"Arduino da garra": "garra", "controlador da esteira": "esteira"}
    for label, device in controller._hardware_devices():
        try:
            if not device.is_connected():
                device.connect()
            if not device.is_connected():
                raise ControllerError(f"O {label} nao ficou conectado.")
            device.execute("SISTEMA:PING", "DIAGNOSTICO", timeout=controller.command_timeout, retries=0)
        except Exception as exc:
            try:
                device.disconnect()
            except Exception:
                pass
            warnings.append(f"{labels.get(label, label)}: {getattr(exc, 'message', str(exc))}")
    try:
        if not controller.camera.is_connected() and hasattr(controller.camera, "connect"):
            controller.camera.connect()
    except Exception as exc:
        warnings.append(f"camera: {getattr(exc, 'message', str(exc))}")
    snapshot = controller._connection_status()
    controller.state.update(**snapshot)
    return jsonify({"ok": True, "sistema": snapshot, "avisos": warnings,
                    "conectados": sum(bool(value) for value in snapshot.values())})


@api_bp.post("/system/connect/conveyor")
def connect_conveyor():
    controller = current_app.extensions["system_controller"]
    device = controller.conveyor.device
    if getattr(device, "mode", None) not in {"ev3", "ev3_simulator"}:
        return _error_response("EV3_NOT_SELECTED", "Selecione e aplique LEGO EV3 como controlador da esteira primeiro.", 409)
    try:
        if not device.is_connected():
            device.connect()
        device.execute("SISTEMA:PING", "DIAGNOSTICO", timeout=controller.command_timeout, retries=0)
    except Exception as exc:
        try:
            device.disconnect()
        except Exception:
            pass
        controller.state.update(**controller._connection_status())
        return _error_response(getattr(exc, "code", "EV3_CONNECTION_FAILED"), getattr(exc, "message", str(exc)), 503)
    controller.state.update(**controller._connection_status())
    return jsonify({"ok": True, "conectado": True, "modo": device.mode,
                    "host": getattr(device, "host", None), "porta": getattr(device, "port", None)})


@api_bp.get("/hardware/ports")
def hardware_ports():
    try:
        ports = list_serial_ports()
    except ArduinoError as exc:
        return _error_response(exc.code, exc.message, 503)
    return jsonify({"ok": True, "portas": ports})


@api_bp.get("/system/config")
def system_config():
    app = current_app
    return jsonify({"ok": True, "configuracao": _public_system_config(app),
                    "calibracao_ativa": bool(app.extensions.get("calibration_session"))})


@api_bp.post("/system/config")
def save_system_config():
    app = current_app
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _error_response("INVALID_REQUEST", "Envie as configuracoes em JSON.", 400)
    if app.extensions.get("calibration_session"):
        return _error_response("CALIBRATION_ACTIVE", "Desconecte o calibrador antes de alterar a configuracao.", 409)
    workflow = app.extensions["workflow"]
    if workflow.running() or (workflow._worker is not None and workflow._worker.is_alive()):
        return _error_response("SYSTEM_BUSY", "Pare o fluxo automatico e aguarde a parada antes de aplicar configuracoes.", 409)
    try:
        settings = _validate_system_config(payload)
        _apply_system_config(app, settings)
        path = app.extensions["local_system_config_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        # Preserva opcoes gravadas fora desta tela (ex.: AUTO_SYNC_NEUTRAL).
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stored = {}
        stored = {**(stored if isinstance(stored, dict) else {}), **settings}
        path.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    except (ValueError, OSError, RuntimeError) as exc:
        return _error_response("CONFIGURATION_FAILED", str(exc), 400)
    return jsonify({"ok": True, "configuracao": _public_system_config(app),
                    "mensagem": "Configuracao aplicada e salva neste computador. Conecte os dispositivos quando estiver pronto."})


@api_bp.post("/calibration/session/start")
def start_calibration_session():
    app = current_app
    if app.extensions.get("calibration_session"):
        return jsonify({"ok": True, "mensagem": "A sessao de calibracao ja esta ativa."})
    workflow = app.extensions["workflow"]
    if workflow.running() or (workflow._worker is not None and workflow._worker.is_alive()):
        workflow.stop()
        if workflow._worker is not None:
            workflow._worker.join(timeout=4)
        if workflow._worker is not None and workflow._worker.is_alive():
            return _error_response("SYSTEM_BUSY", "O fluxo ainda esta encerrando. Tente assumir o controle novamente em alguns segundos.", 409)
    arduino = app.extensions["system_controller"].gripper.arduino
    try:
        if arduino.is_connected():
            arduino.disconnect()
    except Exception as exc:
        return _error_response("SERIAL_RELEASE_FAILED", f"Nao foi possivel liberar a porta do Arduino: {exc}", 503)
    app.extensions["calibration_session"] = True
    return jsonify({"ok": True, "mensagem": "Fluxo parado e porta serial liberada para o calibrador."})


@api_bp.post("/calibration/session/release")
def release_calibration_session():
    current_app.extensions["calibration_session"] = False
    return jsonify({"ok": True})


@api_bp.get("/calibration/profile")
def get_calibration_profile():
    store = current_app.extensions["gripper_profile_store"]
    try:
        profile = store.load()
    except GripperProfileError as exc:
        return _error_response("GRIPPER_PROFILE_INVALID", str(exc), 503)
    return jsonify({"ok": True, "perfil": profile, "origem": store.source()})


@api_bp.post("/calibration/profile")
def save_calibration_profile():
    app = current_app
    if not app.extensions.get("calibration_session"):
        return _error_response("CALIBRATION_SESSION_REQUIRED", "Assuma o controle do calibrador antes de transferir o fluxo.", 409)
    workflow = app.extensions["workflow"]
    if workflow.running() or (workflow._worker is not None and workflow._worker.is_alive()):
        return _error_response("SYSTEM_BUSY", "Encerre o fluxo automático antes de substituir a trajetória.", 409)
    payload = request.get_json(silent=True)
    try:
        profile = app.extensions["gripper_profile_store"].save(payload)
    except GripperProfileError as exc:
        return _error_response("GRIPPER_PROFILE_INVALID", str(exc), 400)
    except OSError as exc:
        return _error_response("GRIPPER_PROFILE_SAVE_FAILED", f"Não foi possível salvar o fluxo: {exc}.", 503)
    return jsonify({"ok": True, "perfil": profile, "origem": "personalizado",
                    "mensagem": "Fluxo transferido para a operação coletiva."})


@api_bp.post("/system/reset")
def reset_system():
    if current_app.extensions.get("calibration_session"):
        return _error_response("CALIBRATION_ACTIVE", "Encerre a sessão do calibrador antes de resetar o sistema.", 409)
    controller = current_app.extensions["system_controller"]
    try:
        snapshot = current_app.extensions["workflow"].reset()
    except QueueError as exc:
        return _error_response(exc.code, str(exc), 409)
    except ControllerError as exc:
        return _error_response(exc.code, exc.message, 409)
    return jsonify({"ok": True, "sistema": snapshot})


@api_bp.post("/system/confirm-neutral")
def confirm_neutral_pose():
    app = current_app
    if app.extensions.get("calibration_session"):
        return _error_response("CALIBRATION_ACTIVE", "Encerre o calibrador antes de confirmar o neutro pelo Dashboard.", 409)
    flow_snapshot = app.extensions["workflow"].snapshot()["fluxo"]
    if flow_snapshot.get("ciclo_id"):
        return _error_response("SYSTEM_BUSY", "Aguarde o ciclo atual terminar antes de confirmar o neutro.", 409)
    try:
        result = app.extensions["system_controller"].confirm_neutral_pose()
    except (GripperProfileError, ArduinoError, ControllerError) as exc:
        return _error_response(getattr(exc, "code", "POSE_SYNC_FAILED"), getattr(exc, "message", str(exc)), 409)
    return jsonify({"ok": True, **result,
                    "mensagem": "Referência lógica atualizada. O firmware não moveu os servos."})


@api_bp.post("/sensor/leitura")
def read_presence_sensor():
    app = current_app
    if app.extensions.get("calibration_session"):
        return _error_response("CALIBRATION_ACTIVE", "Encerre o calibrador antes de medir o sensor.", 409)
    flow = app.extensions["workflow"].snapshot()["fluxo"]
    if flow.get("ativo") and flow.get("ciclo_id"):
        return _error_response("SYSTEM_BUSY", "Aguarde o ciclo atual terminar para medir o sensor.", 409)
    try:
        reading = app.extensions["system_controller"].read_presence_distance()
    except (ArduinoError, ControllerError) as exc:
        return _error_response(getattr(exc, "code", "SENSOR_READ_FAILED"), getattr(exc, "message", str(exc)), 409)
    return jsonify({"ok": True, **reading})


@api_bp.post("/system/release-servos")
def release_servos():
    app = current_app
    if app.extensions.get("calibration_session"):
        return _error_response("CALIBRATION_ACTIVE", "Encerre o calibrador antes de soltar os servos pelo Dashboard.", 409)
    flow = app.extensions["workflow"].snapshot()["fluxo"]
    if flow.get("ativo") and flow.get("ciclo_id"):
        return _error_response("SYSTEM_BUSY", "Aguarde o ciclo atual terminar antes de soltar os servos.", 409)
    try:
        result = app.extensions["system_controller"].release_servos()
    except (ArduinoError, ControllerError) as exc:
        return _error_response(getattr(exc, "code", "RELEASE_FAILED"), getattr(exc, "message", str(exc)), 409)
    return jsonify({"ok": True, **result, "mensagem": "Servos soltos. Alinhe o braço no neutro e confirme."})


@api_bp.get("/queue")
def operation_queue():
    return jsonify({"ok": True, **current_app.extensions["workflow"].snapshot()})


@api_bp.post("/queue")
def enqueue_products():
    return _error_response("AUTOMATIC_QUEUE", "A fila e criada pela identificacao da camera. Cadastro manual de unidades desativado.", 409)


@api_bp.delete("/queue/<int:item_id>")
def cancel_queue_item(item_id):
    try:
        current_app.extensions["workflow"].repository.edit(item_id, "cancel")
    except QueueError as exc:
        return _error_response(exc.code, str(exc), 409)
    return jsonify({"ok": True, **current_app.extensions["workflow"].snapshot()})


@api_bp.post("/queue/<int:item_id>/retry")
def retry_queue_item(item_id):
    return _error_response("AUTOMATIC_QUEUE", "Uma nova tentativa requer inspecao e nova deteccao do HC-SR04.", 409)


@api_bp.post("/flow/start")
def start_flow():
    if current_app.extensions.get("calibration_session"):
        return _error_response("CALIBRATION_ACTIVE", "Encerre a sessão do calibrador antes de iniciar o fluxo automático.", 409)
    try:
        snapshot = current_app.extensions["workflow"].start()
    except QueueError as exc:
        return _error_response(exc.code, str(exc), 409)
    except ControllerError as exc:
        return _error_response(exc.code, exc.message, 409)
    except (ArduinoError, CameraError) as exc:
        return _error_response(exc.code, exc.message, 503)
    return jsonify({"ok": True, **snapshot}), 202


@api_bp.post("/simulation/camera")
def simulate_camera_read():
    camera = current_app.extensions["camera"]
    if getattr(camera, "mode", None) != "mock":
        return _error_response("SIMULATION_DISABLED", "A camera real nao aceita leituras injetadas pela API.", 403)
    payload = request.get_json(silent=True)
    try:
        product_id = validate_product_id(payload.get("produto_id") if isinstance(payload, dict) else None)
    except ClassificationError as exc:
        return _error_response(exc.code, exc.message, 400)
    camera.enqueue_qr_code(build_product_payload(product_id))
    return jsonify({"ok": True})


@api_bp.post("/simulation/presence")
def simulate_presence():
    arduino = current_app.extensions["arduino"]
    if getattr(arduino, "mode", None) not in {"mock", "simulator"}:
        return _error_response("SIMULATION_DISABLED", "O HC-SR04 real nao aceita presenca injetada pela API.", 403)
    payload = request.get_json(silent=True)
    present = payload.get("presente") if isinstance(payload, dict) else None
    if not isinstance(present, bool):
        return _error_response("INVALID_REQUEST", "Envie presente como verdadeiro ou falso.", 400)
    arduino.presence.update(present, 5 if present else -1)
    return jsonify({"ok": True, "sensor": arduino.presence.snapshot()})


@api_bp.get("/diagnostics")
def operational_diagnostics():
    controller = current_app.extensions["system_controller"]
    devices = []
    for name, device in controller._hardware_devices():
        telemetry = getattr(device, "telemetry", None)
        devices.append({"nome": name, "modo": getattr(device, "mode", "desconhecido"),
                        "conectado": device.is_connected(), "ping_em": telemetry.last_ping_at if telemetry else None,
                        "erro_conexao": getattr(device, "_reader_error", None),
                        "mensagens": telemetry.snapshot()[-40:] if telemetry else []})
    cycle_id = controller.state.snapshot()["ciclo_id"]
    return jsonify({"ok": True, "dispositivos": devices,
                    "ciclo": controller.cycles.get(cycle_id, include_events=True) if cycle_id else None,
                    "chegada": {"fonte": controller.conveyor.arrival_source, "fisica": controller.conveyor.physical_arrival},
                    "fila": current_app.extensions["workflow"].snapshot()})


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


def _validate_system_config(payload):
    hardware = str(payload.get("hardware_mode", "serial")).strip().lower()
    conveyor = str(payload.get("conveyor_mode", "arduino")).strip().lower()
    camera = str(payload.get("camera_mode", "opencv")).strip().lower()
    if hardware not in {"serial", "mock"}:
        raise ValueError("Escolha Arduino serial ou simulado.")
    if conveyor not in {"arduino", "mock", "ev3", "ev3_simulator"}:
        raise ValueError("Modo da esteira invalido.")
    if camera not in {"opencv", "mock"}:
        raise ValueError("Modo da camera invalido.")
    port = str(payload.get("arduino_port", "COM3")).strip()
    if hardware == "serial" and not port:
        raise ValueError("Informe a porta serial do Arduino, por exemplo COM3.")
    try:
        baud = int(payload.get("arduino_baudrate", 9600))
        camera_index = int(payload.get("camera_index", 0))
        ev3_port = int(payload.get("ev3_port", 8765))
    except (TypeError, ValueError) as exc:
        raise ValueError("Baud rate, índice da câmera e porta EV3 devem ser números inteiros.") from exc
    if baud not in {9600, 19200, 38400, 57600, 115200}:
        raise ValueError("Baud rate não suportado pela interface.")
    if camera_index < 0 or not 1 <= ev3_port <= 65535:
        raise ValueError("Índice da câmera ou porta EV3 fora da faixa válida.")
    return {
        "HARDWARE_MODE": hardware,
        "ARDUINO_PORT": port or "COM3",
        "ARDUINO_BAUDRATE": baud,
        "CONVEYOR_MODE": conveyor,
        "EV3_HOST": str(payload.get("ev3_host", "")).strip(),
        "EV3_PORT": ev3_port,
        "EV3_TOKEN": str(payload.get("ev3_token", "")).strip() or str(current_app.config.get("EV3_TOKEN", "")),
        "CAMERA_MODE": camera,
        "CAMERA_INDEX": camera_index,
        "GRIPPER_PROFILE_CALIBRATED": bool(payload.get("gripper_calibrated", True)),
    }


def _public_system_config(app):
    return {
        "hardware_mode": app.config.get("HARDWARE_MODE", "mock"),
        "arduino_port": app.config.get("ARDUINO_PORT", "COM3"),
        "arduino_baudrate": app.config.get("ARDUINO_BAUDRATE", 9600),
        "conveyor_mode": app.config.get("CONVEYOR_MODE", "arduino"),
        "ev3_host": app.config.get("EV3_HOST", ""),
        "ev3_port": app.config.get("EV3_PORT", 8765),
        "ev3_token_configured": bool(app.config.get("EV3_TOKEN", "")),
        "camera_mode": app.config.get("CAMERA_MODE", "opencv"),
        "camera_index": app.config.get("CAMERA_INDEX", 0),
        "gripper_calibrated": app.extensions["system_controller"].gripper.calibrated,
    }


def _apply_system_config(app, settings):
    import atexit
    from threading import Thread
    from secrets import token_hex
    from core.controller import SystemController
    from hardware.conveyor import Conveyor
    from hardware.ev3_adapter import EV3Adapter
    from hardware.gripper import Gripper
    from hardware.mock import MockArduino
    from hardware.serial_adapter import SerialArduino
    from vision.mock import MockArucoCamera
    from vision.aruco import ArucoCamera

    controller = app.extensions["system_controller"]
    if settings["HARDWARE_MODE"] == "mock":
        arduino = MockArduino()
        arduino.connect()
    else:
        arduino = SerialArduino(port=settings["ARDUINO_PORT"], baudrate=settings["ARDUINO_BAUDRATE"],
                                read_timeout=app.config.get("ARDUINO_READ_TIMEOUT", 0.1),
                                write_timeout=app.config.get("ARDUINO_WRITE_TIMEOUT", 1.0),
                                boot_wait=app.config.get("ARDUINO_BOOT_WAIT", 2.0))

    new_server = None
    new_server_thread = None
    conveyor_mode = settings["CONVEYOR_MODE"]
    if conveyor_mode == "arduino":
        conveyor_device = arduino
    elif conveyor_mode == "mock":
        conveyor_device = MockArduino()
        conveyor_device.connect()
    else:
        host, port, token = settings["EV3_HOST"], settings["EV3_PORT"], settings["EV3_TOKEN"]
        if conveyor_mode == "ev3_simulator":
            from ev3.simulator import EV3Simulator
            token = token_hex(16)
            new_server = EV3Simulator(token=token, delay=app.config.get("EV3_SIMULATOR_DELAY", 0.3))
            new_server_thread = Thread(target=new_server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            new_server_thread.start()
            host, port = new_server.server_address
        conveyor_device = EV3Adapter(host=host, port=port, token=token,
                                     connect_timeout=app.config.get("EV3_CONNECT_TIMEOUT", 2.0))
        if conveyor_mode == "ev3_simulator":
            conveyor_device.mode = "ev3_simulator"
            conveyor_device.arrival_source = "simulado"

    camera_mode = settings["CAMERA_MODE"]
    if camera_mode == "mock":
        camera = MockArucoCamera()
    else:
        camera = ArucoCamera(settings["CAMERA_INDEX"], width=app.config.get("CAMERA_WIDTH", 1280),
                             height=app.config.get("CAMERA_HEIGHT", 720),
                             scan_timeout=app.config.get("CAMERA_SCAN_TIMEOUT", 8.0),
                             retry_interval=app.config.get("CAMERA_RETRY_INTERVAL", 0.08),
                             duplicate_cooldown=app.config.get("CAMERA_DUPLICATE_COOLDOWN", 3.0),
                             aruco_resolver=app.extensions["product_repository"].resolve_aruco,
                             pickup_roi=app.config.get("CAMERA_PICKUP_ROI"))

    monitor = app.extensions["camera_monitor"]
    monitor.shutdown()
    old_devices = {id(device): device for device in (controller.gripper.arduino, controller.conveyor.device)}
    for device in old_devices.values():
        try:
            device.disconnect()
        except Exception:
            pass
    try:
        controller.camera.disconnect()
    except Exception:
        pass
    old_server_stop = app.extensions.pop("stop_conveyor_server", None)
    if old_server_stop:
        old_server_stop()

    controller.gripper = Gripper(arduino, pickup_zone=controller.gripper.pickup_zone,
                                 calibrated=settings["GRIPPER_PROFILE_CALIBRATED"])
    controller.conveyor = Conveyor(conveyor_device,
        arrival_sensor=arduino if app.config.get("ARRIVAL_SENSOR_MODE") == "arduino" and conveyor_device is not arduino else None)
    controller.camera = camera
    app.extensions.update(arduino=arduino, conveyor_device=conveyor_device, camera=camera)
    if new_server is not None:
        def stop_server():
            new_server.shutdown()
            new_server.server_close()
            new_server_thread.join(timeout=1)
        app.extensions["conveyor_server"] = new_server
        app.extensions["stop_conveyor_server"] = stop_server
        atexit.register(stop_server)
    for key, value in settings.items():
        app.config[key] = value
    monitor.start()
