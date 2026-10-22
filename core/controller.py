"""Orquestracao de um ciclo completo da celula de triagem."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Lock
from uuid import uuid4

from core.classifier import ClassificationError, classify_qr_code
from hardware.device import HardwareError
from vision.aruco import CameraError


class ControllerError(RuntimeError):
    code = "CONTROLLER_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SystemBusyError(ControllerError):
    code = "SYSTEM_BUSY"


class SystemNotReadyError(ControllerError):
    code = "SYSTEM_NOT_READY"


class CycleStoppedError(ControllerError):
    code = "CYCLE_STOPPED"


class CycleProcessingError(ControllerError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CycleResult:
    cycle_id: str
    product_id: str
    state: str
    macroregion: str
    destination: str
    status: str = "FINALIZADO"

    def as_dict(self):
        return {
            "ciclo_id": self.cycle_id,
            "produto": {"id": self.product_id, "uf": self.state},
            "macroregiao": self.macroregion,
            "destino": self.destination,
            "estado": self.status,
        }


class SystemController:
    def __init__(
        self,
        state,
        gripper,
        conveyor,
        camera,
        product_repository,
        cycle_repository,
        *,
        command_timeout=2.0,
        arrival_timeout=5.0,
        command_retries=1,
        gripper_timeout=30.0,
        require_physical_arrival=True,
        gripper_profile_provider=None,
    ):
        self.state = state
        self.gripper = gripper
        self.conveyor = conveyor
        self.camera = camera
        self.products = product_repository
        self.cycles = cycle_repository
        self.command_timeout = command_timeout
        self.arrival_timeout = arrival_timeout
        self.command_retries = command_retries
        self.gripper_timeout = gripper_timeout
        self.require_physical_arrival = require_physical_arrival
        self.gripper_profile_provider = gripper_profile_provider
        self.gripper_firmware_status = None
        self._cycle_lock = Lock()
        self._stop_requested = Event()
        self._external_cancelled = None

        self.state.update(**self._connection_status())

    def identify_camera_frame(self):
        """Valida a etiqueta atual sem movimentar hardware ou registrar um ciclo."""
        if not self._cycle_lock.acquire(blocking=False):
            raise SystemBusyError("Existe um ciclo em processamento. Aguarde para testar a camera.")
        try:
            captured = self.camera.read_aruco(self.camera.capture_frame())
            return classify_qr_code(
                captured, self.products.resolve,
                occupancy=self.cycles.destination_counts(),
            )
        finally:
            self._cycle_lock.release()

    def process_next_product(self, *, qr_code=None, occupancy=None, unavailable=None,
                             identified_qr_code=None, expected_product_id=None, cycle_id=None,
                             on_identified=None, presence_confirmed=False, cancelled=None):
        if not self._cycle_lock.acquire(blocking=False):
            raise SystemBusyError("Ja existe um ciclo em processamento.")

        cycle_id = cycle_id or uuid4().hex[:12]
        cycle_recorded = False
        try:
            self._external_cancelled = cancelled
            self._stop_requested.clear()
            self._ensure_not_stopped()
            current_state = self.state.snapshot()["estado"]
            if current_state == "ERRO":
                raise SystemNotReadyError(
                    "O sistema esta em erro e precisa ser resetado."
                )
            if current_state == "PARADO":
                raise SystemNotReadyError(
                    "O sistema esta parado e precisa ser resetado."
                )
            self._connect_hardware()
            self.ensure_operation_ready()
            self.require_gripper_ready()

            if not self.camera.is_connected():
                connected = (
                    self.camera.connect() if hasattr(self.camera, "connect") else False
                )
                if not connected:
                    raise SystemNotReadyError(
                        "A camera nao esta disponivel para iniciar o ciclo."
                    )

            if qr_code is not None:
                if not hasattr(self.camera, "enqueue_qr_code"):
                    raise SystemNotReadyError(
                        "A camera configurada nao aceita entrada simulada."
                    )
                self.camera.enqueue_qr_code(qr_code)

            self.cycles.start(cycle_id, qr_code or "")
            cycle_recorded = True
            self.cycles.add_event(cycle_id, "MODO_OPERACAO", {
                "simulado": any(getattr(device, "mode", "mock") in {"mock", "simulator", "ev3_simulator"}
                                for _name, device in self._hardware_devices()),
            })

            self.state.transition(
                "AGUARDANDO_OBJETO",
                ciclo_id=cycle_id,
                produto=None,
                qr_code=None,
                uf=None,
                macroregiao=None,
                destino=None,
                erro=None,
                chegada_confirmacao=None,
                chegada_fisica=False,
            )

            if presence_confirmed:
                self.cycles.add_event(cycle_id, "PRESENCA_CONFIRMADA", {"sensor": "HC-SR04"})
            profile = self.gripper_profile_provider() if self.gripper_profile_provider else None
            if profile:
                self.gripper.configure_profile(profile, cycle_id, timeout=self.command_timeout,
                                               retries=self.command_retries)
            self.gripper.set_pickup_area(cycle_id, timeout=self.command_timeout, retries=self.command_retries)
            self.cycles.add_event(cycle_id, "AREA_COLETA_CONFIGURADA", {"area": self.gripper.pickup_zone})
            self.state.transition("PEGANDO_OBJETO")
            self.cycles.set_status(cycle_id, "PEGANDO_OBJETO")
            if profile:
                for index, step in enumerate(profile["pickup"], 1):
                    self._ensure_not_stopped()
                    response = self.gripper.move_profile_step(
                        "pickup", index, step, cycle_id, timeout=self.command_timeout,
                        retries=self.command_retries, event_timeout=self.gripper_timeout,
                        cancelled=self._cancelled)
                    self.cycles.add_event(cycle_id, "GARRA_PASSO_CONCLUIDO", {
                        "fase": "pegar", "ordem": index, "nome": step["name"],
                        "confirmacao": response.payload,
                    })
                self.state.update(garra="segurando")
                self.cycles.add_event(cycle_id, "OBJETO_COLETADO", {
                    "confirmacao": "todos_os_passos_de_pega_concluidos", "area": self.gripper.pickup_zone,
                    "perfil": profile["version"],
                })
                self.state.transition("POSICIONANDO_OBJETO")
                self.cycles.set_status(cycle_id, "POSICIONANDO_OBJETO")
                last_grip_progress = 0.0
                opened, closed = profile["gripper"]["open"], profile["gripper"]["closed"]
                for index, step in enumerate(profile["delivery"], 1):
                    self._ensure_not_stopped()
                    progress = (step["G"] - closed) / (opened - closed)
                    if self.state.snapshot()["estado"] == "POSICIONANDO_OBJETO" and progress >= 0.5 and progress > last_grip_progress:
                        self.state.transition("SOLTANDO_OBJETO")
                        self.cycles.set_status(cycle_id, "SOLTANDO_OBJETO")
                    response = self.gripper.move_profile_step(
                        "delivery", index, step, cycle_id, timeout=self.command_timeout,
                        retries=self.command_retries, event_timeout=self.gripper_timeout,
                        cancelled=self._cancelled)
                    self.cycles.add_event(cycle_id, "GARRA_PASSO_CONCLUIDO", {
                        "fase": "entregar", "ordem": index, "nome": step["name"],
                        "confirmacao": response.payload,
                    })
                    last_grip_progress = progress
                if self.state.snapshot()["estado"] == "POSICIONANDO_OBJETO":
                    self.state.transition("SOLTANDO_OBJETO")
                    self.cycles.set_status(cycle_id, "SOLTANDO_OBJETO")
                self.cycles.add_event(cycle_id, "GARRA_POSICIONADA_SOBRE_ESTEIRA", {
                    "confirmacao": "sequencia_de_entrega_concluida", "perfil": profile["version"],
                })
                self.cycles.add_event(cycle_id, "OBJETO_ENTREGUE_NA_ESTEIRA", {
                    "confirmacao": "todos_os_passos_de_entrega_concluidos", "area": "E01",
                    "perfil": profile["version"],
                })
                self.cycles.add_event(cycle_id, "GARRA_RETORNOU", {
                    "confirmacao": "ultimo_passo_no_neutro", "perfil": profile["version"],
                })
            else:
                for action, event, phase in ((self.gripper.pick_object, "OBJETO_COLETADO", None),
                                             (self.gripper.place_on_conveyor, "GARRA_POSICIONADA_SOBRE_ESTEIRA", "POSICIONANDO_OBJETO"),
                                             (self.gripper.release_object, "OBJETO_ENTREGUE_NA_ESTEIRA", "SOLTANDO_OBJETO"),
                                             (self.gripper.home, "GARRA_RETORNOU", None)):
                    self._ensure_not_stopped()
                    if phase:
                        self.state.transition(phase)
                        self.cycles.set_status(cycle_id, phase)
                    response = action(cycle_id, timeout=self.command_timeout, retries=self.command_retries,
                                      event_timeout=self.gripper_timeout, cancelled=self._cancelled)
                    self.cycles.add_event(cycle_id, event, {"confirmacao": response.payload, "area": self.gripper.pickup_zone})
                    if event == "OBJETO_COLETADO":
                        self.state.update(garra="segurando")
            self._ensure_not_stopped()
            self.state.transition("OBJETO_POSICIONADO", garra="livre")
            self.cycles.add_event(cycle_id, "OBJETO_POSICIONADO")
            self.state.transition("LENDO_ARUCO")
            self.cycles.set_status(cycle_id, "LENDO_ARUCO")
            captured_qr_code = identified_qr_code if identified_qr_code is not None else self.camera.scan_aruco(
                cancelled=self._cancelled)
            self.cycles.set_qr_code(cycle_id, captured_qr_code)
            self.cycles.add_event(cycle_id, "ARUCO_LIDO")
            self._ensure_not_stopped()
            self.state.transition("VALIDANDO_ARUCO", qr_code=captured_qr_code)

            decision = classify_qr_code(
                captured_qr_code,
                self.products.resolve,
                occupancy=occupancy,
                unavailable=unavailable,
            )
            if expected_product_id is not None and decision.product.product_id.lower() != expected_product_id.lower():
                raise ClassificationError(f"Esperado {expected_product_id}; a camera identificou {decision.product.product_id}.")
            self._ensure_not_stopped()
            self.state.transition(
                "DESTINO_DEFINIDO",
                produto=decision.product.product_id,
                uf=decision.product.state,
                macroregiao=decision.macroregion.value,
                destino=decision.destination,
            )
            self.cycles.set_route(
                cycle_id,
                product_id=decision.product.product_id,
                state=decision.product.state,
                macroregion=decision.macroregion.value,
                destination=decision.destination,
            )
            self.cycles.add_event(
                cycle_id,
                "DESTINO_DEFINIDO",
                {
                    "macroregiao": decision.macroregion.value,
                    "destino": decision.destination,
                },
            )
            if on_identified is not None:
                on_identified(cycle_id, decision)
            self._ensure_not_stopped()

            self.conveyor.set_destination(
                decision.destination,
                cycle_id,
                timeout=self.command_timeout,
                retries=self.command_retries,
            )
            self._ensure_not_stopped()
            self.conveyor.start(
                cycle_id,
                timeout=self.command_timeout,
                retries=self.command_retries,
            )
            self.cycles.set_status(cycle_id, "TRANSPORTANDO")
            self.cycles.add_event(cycle_id, "ESTEIRA_INICIADA")
            self._ensure_not_stopped()
            self.state.transition("TRANSPORTANDO", esteira="rodando")

            self.conveyor.wait_until_destination(
                cycle_id,
                timeout=self.arrival_timeout,
                cancelled=self._cancelled,
            )
            self._ensure_not_stopped()
            real_hardware = any(getattr(device, "mode", "mock") in {"serial", "ev3"} for _name, device in self._hardware_devices())
            if real_hardware and self.conveyor.arrival_source.startswith("simulad"):
                raise HardwareError("Hardware real nao pode concluir com evento de esteira simulada.")
            if (self.require_physical_arrival and real_hardware
                    and not self.conveyor.physical_arrival):
                raise HardwareError("Chegada fisica nao confirmada: instale o sensor no destino; rotacoes calibradas nao comprovam chegada.")
            self.state.update(chegada_confirmacao=self.conveyor.arrival_source, chegada_fisica=self.conveyor.physical_arrival)
            self.cycles.add_event(
                cycle_id,
                "DESTINO_ALCANCADO",
                {
                    "destino": decision.destination,
                    "confirmacao": self.conveyor.arrival_source,
                    "fisica": self.conveyor.physical_arrival,
                },
            )
            self.conveyor.stop(
                cycle_id,
                timeout=self.command_timeout,
                retries=self.command_retries,
            )
            self.cycles.add_event(cycle_id, "ESTEIRA_CONCLUIDA", {"destino": decision.destination})
            self.state.transition("FINALIZADO", esteira="parada")
            self.cycles.complete(cycle_id)

            return CycleResult(
                cycle_id=cycle_id,
                product_id=decision.product.product_id,
                state=decision.product.state,
                macroregion=decision.macroregion.value,
                destination=decision.destination,
            )
        except (ClassificationError, HardwareError, CameraError) as exc:
            self._safe_stop(cycle_id)
            if self._cancelled():
                self.state.stop()
                if cycle_recorded:
                    self.cycles.stop(cycle_id)
                raise CycleStoppedError(
                    "O ciclo foi interrompido pelo operador."
                ) from exc
            code = getattr(exc, "code", "CYCLE_ERROR")
            message = getattr(exc, "message", str(exc))
            self.state.fail(code, message)
            if cycle_recorded:
                self.cycles.fail(cycle_id, code, message)
            raise CycleProcessingError(code, message) from exc
        except ControllerError:
            raise
        except Exception as exc:
            self._safe_stop(cycle_id)
            if self._cancelled():
                self.state.stop()
                if cycle_recorded:
                    self.cycles.stop(cycle_id)
                raise CycleStoppedError("O ciclo foi interrompido pelo operador.") from exc
            self.state.fail("UNEXPECTED_ERROR", str(exc))
            if cycle_recorded:
                self.cycles.fail(cycle_id, "UNEXPECTED_ERROR", str(exc))
            raise CycleProcessingError("UNEXPECTED_ERROR", str(exc)) from exc
        finally:
            self._external_cancelled = None
            self.state.update(**self._connection_status())
            self._cycle_lock.release()

    def ensure_operation_ready(self):
        if self.require_physical_arrival and getattr(self.conveyor.device, "mode", "mock") == "ev3":
            sensor = self.conveyor.arrival_sensor
            if sensor is None or getattr(sensor, "mode", "mock") != "serial":
                raise SystemNotReadyError("Configure um sensor real de chegada no Arduino: o EV3 atual confirma rotacoes, nao a presenca do produto no destino.")

    def read_gripper_firmware_status(self):
        device = self.gripper.arduino
        cycle_id = "FW_STATUS"
        device.execute("SISTEMA:STATUS", cycle_id, timeout=self.command_timeout, retries=0)
        message = device.wait_for_event("SISTEMA_STATUS", cycle_id, timeout=self.command_timeout)
        status = {}
        for field in message.payload.split(":")[1:]:
            key, separator, value = field.partition("=")
            if separator:
                status[key.lower()] = value == "1"
        if not {"reset_required", "calibrated", "pose_referenced"}.issubset(status):
            raise SystemNotReadyError("O firmware não informou o estado de calibração e referência esperado.")
        self.gripper_firmware_status = status
        return status

    def require_gripper_ready(self):
        status = self.read_gripper_firmware_status()
        if status["reset_required"]:
            raise SystemNotReadyError("O Arduino ainda exige Resetar a operação.")
        if not status["calibrated"]:
            raise SystemNotReadyError("Calibração do automático não validada no Arduino. No módulo Calibração, teste os pontos e pressione ‘Validar para operação coletiva’.")
        if not status["pose_referenced"]:
            raise SystemNotReadyError("Confirme o braço fisicamente no ponto neutro pelo Dashboard antes de iniciar movimentos.")
        return status

    def confirm_neutral_pose(self):
        if not self._cycle_lock.acquire(blocking=False):
            raise SystemBusyError("Aguarde o comando atual terminar antes de confirmar o neutro.")
        try:
            profile = self.gripper_profile_provider() if self.gripper_profile_provider else None
            if not profile:
                raise SystemNotReadyError("Não há perfil de garra salvo para determinar o ponto neutro.")
            device = self.gripper.arduino
            if not device.is_connected():
                device.connect()
            neutral = profile["neutral"]
            command = f"SISTEMA:SYNC:{neutral['B']}:{neutral['A']}:{neutral['C']}:{neutral['G']}"
            response = device.execute(command, "POSE_SYNC", timeout=self.command_timeout, retries=0)
            event = device.wait_for_event("POSE_REFERENCE_CONFIRMED", "POSE_SYNC", timeout=self.command_timeout)
            status = self.read_gripper_firmware_status()
            if not status["pose_referenced"]:
                raise SystemNotReadyError("O Arduino não confirmou a referência da pose neutra.")
            return {"pose": neutral, "perfil": profile["version"], "ack": response.payload,
                    "evento": event.payload, "firmware": status}
        finally:
            self._cycle_lock.release()

    def read_presence_distance(self):
        """Mede o HC-SR04 agora (mediana de 9 disparos); -1 quando nao ha eco."""
        device = self.gripper.arduino
        device.execute("PRESENCA:LEITURA", "PRESENCA_LEITURA", timeout=self.command_timeout, retries=0)
        event = device.wait_for_event("PRESENCA_LEITURA", "PRESENCA_LEITURA", timeout=self.command_timeout + 1)
        median, low, high, valid = (int(value) for value in event.payload.split(":")[1:5])
        return {"mediana_cm": median, "minima_cm": low, "maxima_cm": high, "leituras_validas": valid}

    def ensure_neutral_reference(self):
        """Operacao automatica: assume o braco no neutro salvo, sem clique do operador.

        No primeiro movimento os servos sao energizados nos angulos do neutro; se o braco
        estiver fora dele, salta para o neutro antes de seguir o perfil suavemente.
        """
        status = self.read_gripper_firmware_status()
        if status["pose_referenced"]:
            return status
        try:
            self.confirm_neutral_pose()
        except HardwareError:
            # Servos ainda energizados apos uma parada: o SYNC so aceita servos soltos.
            self.release_servos()
            self.confirm_neutral_pose()
        return self.gripper_firmware_status

    def release_servos(self):
        """Solta os servos para alinhar o braco a mao antes de confirmar o neutro."""
        if not self._cycle_lock.acquire(blocking=False):
            raise SystemBusyError("Aguarde o comando atual terminar antes de soltar os servos.")
        try:
            device = self.gripper.arduino
            if not device.is_connected():
                device.connect()
            response = device.execute("SISTEMA:LIBERAR", "LIBERAR", timeout=self.command_timeout, retries=0)
            self.state.update(garra="livre")
            return {"ack": response.payload, "firmware": self.read_gripper_firmware_status()}
        finally:
            self._cycle_lock.release()

    def reset(self):
        if not self._cycle_lock.acquire(blocking=False):
            raise SystemBusyError("Nao e possivel resetar durante um ciclo ativo.")
        try:
            cycle_id = self.state.snapshot()["ciclo_id"] or uuid4().hex[:12]
            self._connect_hardware()
            if not self.camera.is_connected() and hasattr(self.camera, "connect"):
                self.camera.connect()

            for _label, device in self._hardware_devices():
                device.execute(
                    "SISTEMA:RESET",
                    cycle_id,
                    timeout=self.command_timeout,
                    retries=self.command_retries,
                )
            self._stop_requested.clear()
            self.state.reset(**self._connection_status())
            return self.state.snapshot()
        except (HardwareError, CameraError) as exc:
            code = getattr(exc, "code", "RESET_ERROR")
            message = getattr(exc, "message", str(exc))
            self.state.fail(code, message)
            raise CycleProcessingError(code, message) from exc
        finally:
            self.state.update(**self._connection_status())
            self._cycle_lock.release()

    def connect_components(self):
        if not self._cycle_lock.acquire(blocking=False):
            raise SystemBusyError("Nao e possivel conectar durante um ciclo ativo.")
        try:
            self._connect_hardware()
            if not self.camera.is_connected() and hasattr(self.camera, "connect"):
                self.camera.connect()

            camera_connected = self.camera.is_connected()
            self.state.update(**self._connection_status())
            if not camera_connected:
                raise SystemNotReadyError("A camera nao foi conectada.")
            return self.state.snapshot()
        except (HardwareError, CameraError) as exc:
            message = getattr(exc, "message", str(exc))
            raise SystemNotReadyError(message) from exc
        finally:
            self.state.update(**self._connection_status())
            self._cycle_lock.release()

    def stop(self):
        self._stop_requested.set()
        cycle_id = self.state.snapshot()["ciclo_id"] or uuid4().hex[:12]
        self._safe_stop(cycle_id)
        self.state.stop()
        self.cycles.stop(cycle_id)
        return self.state.snapshot()

    def _ensure_not_stopped(self):
        if self._cancelled():
            raise CycleStoppedError("O ciclo foi interrompido pelo operador.")

    def _cancelled(self):
        return self._stop_requested.is_set() or bool(self._external_cancelled and self._external_cancelled())

    def _safe_stop(self, cycle_id):
        try:
            if self.conveyor.device.is_connected():
                self.conveyor.stop(
                    cycle_id,
                    timeout=self.command_timeout,
                    retries=0,
                )
        except HardwareError:
            pass
        try:
            if self.gripper.arduino.is_connected():
                self.gripper.stop(cycle_id, timeout=self.command_timeout)
        except HardwareError:
            pass

    def _hardware_devices(self):
        yield "Arduino da garra", self.gripper.arduino
        if self.conveyor.device is not self.gripper.arduino:
            yield "controlador da esteira", self.conveyor.device

    def _connect_hardware(self):
        for label, device in self._hardware_devices():
            if not device.is_connected():
                device.connect()
            if not device.is_connected():
                raise SystemNotReadyError(f"O {label} nao esta disponivel.")
            device.execute("SISTEMA:PING", "DIAGNOSTICO", timeout=self.command_timeout, retries=0)

    def _connection_status(self):
        return {
            "arduino": self.gripper.arduino.is_connected(),
            "esteira_conectada": self.conveyor.device.is_connected(),
            "camera": self.camera.is_connected(),
        }
