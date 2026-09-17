"""Orquestracao de um ciclo completo da celula de triagem."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Lock
from uuid import uuid4

from core.classifier import ClassificationError, classify_qr_code
from hardware.arduino import ArduinoError
from vision.qrcode import CameraError


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
        self._cycle_lock = Lock()
        self._stop_requested = Event()

        self.state.update(
            arduino=self.conveyor.arduino.is_connected(),
            camera=self.camera.is_connected(),
        )

    def process_next_product(self, *, qr_code=None, occupancy=None, unavailable=None):
        if not self._cycle_lock.acquire(blocking=False):
            raise SystemBusyError("Ja existe um ciclo em processamento.")

        cycle_id = uuid4().hex[:12]
        cycle_recorded = False
        try:
            self._stop_requested.clear()
            current_state = self.state.snapshot()["estado"]
            if current_state == "ERRO":
                raise SystemNotReadyError(
                    "O sistema esta em erro e precisa ser resetado."
                )
            if current_state == "PARADO":
                raise SystemNotReadyError(
                    "O sistema esta parado e precisa ser resetado."
                )

            arduino = self.conveyor.arduino
            if not arduino.is_connected():
                arduino.connect()
                if not arduino.is_connected():
                    raise SystemNotReadyError(
                        "O Arduino nao esta disponivel para iniciar o ciclo."
                    )

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

            self.state.transition(
                "AGUARDANDO_OBJETO",
                ciclo_id=cycle_id,
                produto=None,
                qr_code=None,
                uf=None,
                macroregiao=None,
                destino=None,
                erro=None,
            )

            self.state.transition("PEGANDO_OBJETO")
            self.gripper.pick_object(
                cycle_id,
                timeout=self.command_timeout,
                retries=self.command_retries,
            )
            self.cycles.add_event(cycle_id, "OBJETO_COLETADO")
            self._ensure_not_stopped()
            self.state.update(garra="segurando")
            self.gripper.release_object(
                cycle_id,
                timeout=self.command_timeout,
                retries=self.command_retries,
            )
            self.gripper.home(
                cycle_id,
                timeout=self.command_timeout,
                retries=self.command_retries,
            )
            self.cycles.add_event(cycle_id, "OBJETO_POSICIONADO")
            self._ensure_not_stopped()
            self.state.transition("OBJETO_POSICIONADO", garra="livre")

            self.state.transition("LENDO_QR")
            captured_qr_code = self.camera.scan_qrcode(
                cancelled=self._stop_requested.is_set
            )
            self.cycles.set_qr_code(cycle_id, captured_qr_code)
            self.cycles.add_event(cycle_id, "QR_LIDO")
            self._ensure_not_stopped()
            self.state.transition("VALIDANDO_QR", qr_code=captured_qr_code)

            decision = classify_qr_code(
                captured_qr_code,
                self.products.resolve,
                occupancy=occupancy,
                unavailable=unavailable,
            )
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

            self.conveyor.set_destination(
                decision.destination,
                cycle_id,
                timeout=self.command_timeout,
                retries=self.command_retries,
            )
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
                cancelled=self._stop_requested.is_set,
            )
            self._ensure_not_stopped()
            self.cycles.add_event(
                cycle_id,
                "DESTINO_ALCANCADO",
                {"destino": decision.destination},
            )
            self.conveyor.stop(
                cycle_id,
                timeout=self.command_timeout,
                retries=self.command_retries,
            )
            self.state.transition("FINALIZADO", esteira="parada")
            self.cycles.complete(cycle_id)

            return CycleResult(
                cycle_id=cycle_id,
                product_id=decision.product.product_id,
                state=decision.product.state,
                macroregion=decision.macroregion.value,
                destination=decision.destination,
            )
        except (ClassificationError, ArduinoError, CameraError) as exc:
            self._safe_stop(cycle_id)
            if self._stop_requested.is_set():
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
            self.state.fail("UNEXPECTED_ERROR", str(exc))
            if cycle_recorded:
                self.cycles.fail(cycle_id, "UNEXPECTED_ERROR", str(exc))
            raise CycleProcessingError("UNEXPECTED_ERROR", str(exc)) from exc
        finally:
            self._cycle_lock.release()

    def reset(self):
        if not self._cycle_lock.acquire(blocking=False):
            raise SystemBusyError("Nao e possivel resetar durante um ciclo ativo.")
        try:
            cycle_id = self.state.snapshot()["ciclo_id"] or uuid4().hex[:12]
            if not self.conveyor.arduino.is_connected():
                self.conveyor.arduino.connect()
            if not self.camera.is_connected() and hasattr(self.camera, "connect"):
                self.camera.connect()

            self.conveyor.arduino.execute(
                "SISTEMA:RESET",
                cycle_id,
                timeout=self.command_timeout,
                retries=self.command_retries,
            )
            self._stop_requested.clear()
            self.state.reset(
                arduino=self.conveyor.arduino.is_connected(),
                camera=self.camera.is_connected(),
            )
            return self.state.snapshot()
        except (ArduinoError, CameraError) as exc:
            code = getattr(exc, "code", "RESET_ERROR")
            message = getattr(exc, "message", str(exc))
            self.state.fail(code, message)
            raise CycleProcessingError(code, message) from exc
        finally:
            self._cycle_lock.release()

    def connect_components(self):
        if not self._cycle_lock.acquire(blocking=False):
            raise SystemBusyError("Nao e possivel conectar durante um ciclo ativo.")
        try:
            arduino = self.conveyor.arduino
            if not arduino.is_connected():
                arduino.connect()
            if not self.camera.is_connected() and hasattr(self.camera, "connect"):
                self.camera.connect()

            arduino_connected = arduino.is_connected()
            camera_connected = self.camera.is_connected()
            self.state.update(
                arduino=arduino_connected,
                camera=camera_connected,
            )
            if not arduino_connected:
                raise SystemNotReadyError("O Arduino nao foi conectado.")
            if not camera_connected:
                raise SystemNotReadyError("A camera nao foi conectada.")
            return self.state.snapshot()
        except (ArduinoError, CameraError) as exc:
            self.state.update(
                arduino=self.conveyor.arduino.is_connected(),
                camera=self.camera.is_connected(),
            )
            message = getattr(exc, "message", str(exc))
            raise SystemNotReadyError(message) from exc
        finally:
            self._cycle_lock.release()

    def stop(self):
        self._stop_requested.set()
        cycle_id = self.state.snapshot()["ciclo_id"] or uuid4().hex[:12]
        self._safe_stop(cycle_id)
        self.state.stop()
        self.cycles.stop(cycle_id)
        return self.state.snapshot()

    def _ensure_not_stopped(self):
        if self._stop_requested.is_set():
            raise CycleStoppedError("O ciclo foi interrompido pelo operador.")

    def _safe_stop(self, cycle_id):
        try:
            if self.conveyor.arduino.is_connected():
                self.conveyor.stop(
                    cycle_id,
                    timeout=self.command_timeout,
                    retries=0,
                )
        except ArduinoError:
            pass
