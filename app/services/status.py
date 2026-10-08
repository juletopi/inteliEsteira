from flask import current_app


def get_system_status():
    controller = current_app.extensions["system_controller"]
    snapshot = controller.state.snapshot()
    arduino = controller.gripper.arduino
    conveyor_device = controller.conveyor.device
    snapshot["arduino"] = arduino.is_connected()
    snapshot["hardware_modo"] = getattr(arduino, "mode", "desconhecido")
    snapshot["arduino_porta"] = getattr(arduino, "port", None)
    snapshot["arduino_baudrate"] = getattr(arduino, "baudrate", None)
    snapshot["esteira_conectada"] = conveyor_device.is_connected()
    snapshot["esteira_modo"] = getattr(conveyor_device, "mode", "desconhecido")
    snapshot["esteira_confirmacao"] = getattr(
        conveyor_device, "arrival_source", "evento_do_controlador"
    )
    snapshot["ev3_host"] = (
        getattr(conveyor_device, "host", None)
        if snapshot["esteira_modo"] == "ev3" else None
    )
    snapshot["ev3_porta"] = (
        getattr(conveyor_device, "port", None)
        if snapshot["esteira_modo"] == "ev3" else None
    )
    camera_mode = getattr(controller.camera, "mode", "desconhecido")
    camera_connected = controller.camera.is_connected()
    if (
        camera_mode == "opencv"
        and not camera_connected
        and hasattr(controller.camera, "connect")
    ):
        camera_connected = controller.camera.connect()
    snapshot["camera"] = camera_connected
    snapshot["camera_modo"] = camera_mode
    snapshot["camera_indice"] = getattr(controller.camera, "camera_index", None)
    snapshot["camera_resolucao"] = (
        controller.camera.resolution()
        if camera_connected and hasattr(controller.camera, "resolution") else None
    )
    snapshot["total_ciclos"] = current_app.extensions[
        "cycle_repository"
    ].count_completed()
    return snapshot
