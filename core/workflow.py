"""Operacao automatica: HC-SR04, coleta, identificacao e termino da esteira."""

from threading import Event, RLock, Thread
from uuid import uuid4

from core.controller import ControllerError
from hardware.device import HardwareError
from storage.queue import QueueError
from vision.aruco import CameraError


class Workflow:
    def __init__(self, controller, repository, *, scan_interval=0.1, presence_distance=10, presence_stable_ms=3000):
        if not 2 <= presence_distance <= 100 or presence_stable_ms not in {3000, 4000, 5000}:
            raise ValueError("HC-SR04: configure distancia de 2 a 100 cm e estabilidade de 3000, 4000 ou 5000 ms.")
        self.controller = controller
        self.repository = repository
        self.scan_interval = scan_interval
        self.presence_distance = presence_distance
        self.presence_stable_ms = presence_stable_ms
        self._lock = RLock()
        self._stop = Event()
        self._prepared = Event()
        self._worker = None
        self._fault = None
        self._closing_idle = False
        self.repository.recover()

    @property
    def sensor(self):
        return self.controller.gripper.arduino.presence

    def snapshot(self):
        info = self.repository.runtime()
        state = self.controller.state.snapshot()
        if info["ativo"] and info.get("ciclo_id") and state["ciclo_id"] == info["ciclo_id"]:
            info["estado"] = state["estado"]
        return {"modo": "automatico", "fluxo": info, "itens": self.repository.automatic_items(),
                "sensor": self.sensor.snapshot(), "area_coleta": self.controller.gripper.pickup_zone,
                "area_leitura": "E01", "proxima_caixa_liberada": bool(info["ativo"] and info.get("estado") == "AGUARDANDO_SENSOR")}

    def running(self):
        return self.repository.runtime()["ativo"]

    def start(self):
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise QueueError("O fluxo automatico ja esta ativo.")
            self.repository.recover()
            if self.repository.runtime().get("estado") in {"ERRO", "INTERROMPIDO", "PARADO"}:
                raise QueueError("Inspecione o cubo e resete a operacao antes de rearmar o sensor.")
            if self.controller.state.snapshot()["estado"] in {"ERRO", "PARADO"}:
                raise QueueError("Resete o sistema antes de retomar o fluxo.")
            owner = uuid4().hex
            self.repository.acquire(owner, lease=30)
            self._stop.clear()
            self._prepared.clear()
            self._fault = None
            self._closing_idle = False
            self._worker = Thread(target=self._run, args=(owner,), name="inteliesteira-automatico", daemon=True)
            self._worker.start()
        return self.snapshot()

    def stop(self):
        with self._lock:
            self._stop.set()
            result = self.controller.stop()
            self.repository.request_stop()
            self.repository.set_info(estado="PARADO")
            return result

    def reset(self):
        with self._lock:
            if self.running() or self._worker is not None and self._worker.is_alive():
                raise QueueError("Aguarde a parada do fluxo antes de resetar.")
            result = self.controller.reset()
            self.repository.set_info(estado="PRONTO", erro=None, aviso=None, ciclo_id=None)
            return result

    def shutdown(self):
        if self._worker is not None and self._worker.is_alive():
            self._closing_idle = self.repository.runtime().get("ciclo_id") is None
            self.stop()
            self._worker.join(timeout=3)

    def _heartbeat(self, owner, finished):
        while not finished.wait(1):
            try:
                if not self.repository.heartbeat(owner):
                    if not self.repository.runtime()["parada_solicitada"]:
                        raise QueueError("A operacao perdeu a posse da fila.")
                    self._stop.set()
                    self.controller.stop()
                    return
                if self._prepared.is_set():
                    for _name, device in self.controller._hardware_devices():
                        device.execute("SISTEMA:PING", "HEARTBEAT", timeout=min(0.5, self.controller.command_timeout), retries=0)
            except Exception as exc:
                self._fault = {"codigo": "HEARTBEAT_FAILED", "mensagem": str(exc)}
                self._stop.set()
                self.controller.stop()
                return

    def _prepare(self, owner):
        while not self._stop.is_set():
            try:
                self.controller.ensure_operation_ready()
                self.controller.connect_components()
                self.controller.reset()
                self.controller.gripper.arduino.execute(
                    f"PRESENCA:CONFIGURAR:{self.presence_distance}:{self.presence_stable_ms}", "PRESENCA",
                    timeout=self.controller.command_timeout, retries=self.controller.command_retries,
                )
                self._prepared.set()
                self.repository.set_info(owner, erro=None, aviso=None, ciclo_id=None)
                return True
            except (ControllerError, HardwareError, CameraError) as exc:
                self.repository.set_info(owner, estado="AGUARDANDO_CONEXAO", aviso=str(exc), ciclo_id=None)
                self._stop.wait(2)
        return False

    def _run(self, owner):
        finished = Event()
        heartbeat = Thread(target=self._heartbeat, args=(owner, finished), daemon=True)
        heartbeat.start()
        active_job = None
        try:
            cursor = self.sensor.snapshot()["sequencia"]
            if not self._prepare(owner):
                return
            while not self._stop.is_set():
                self.repository.set_info(owner, estado="AGUARDANDO_SENSOR", ciclo_id=None, detectado=None, aviso=None)
                present = self.sensor.wait_present(cursor, timeout=0.5, cancelled=self._stop.is_set)
                if present is None:
                    continue
                cursor = present["sequencia"]
                if self._stop.is_set():
                    break
                cycle_id = uuid4().hex[:12]
                self.repository.set_info(owner, estado="COLETANDO", ciclo_id=cycle_id)

                def identified(cycle, decision):
                    nonlocal active_job
                    active_job = self.repository.detected(owner, decision.product.product_id, cycle)
                    self.repository.set_info(owner, detectado=decision.product.product_id)

                self.controller.process_next_product(
                    cycle_id=cycle_id, presence_confirmed=True, on_identified=identified,
                    occupancy=self.controller.cycles.destination_counts(),
                    cancelled=self._stop.is_set,
                )
                self.repository.finish(owner, active_job, "FINALIZADO")
                active_job = None
                # Bordas ocorridas durante a operacao nao autorizam outra coleta.
                cursor = self.sensor.snapshot()["sequencia"]
        except Exception as exc:
            error = self._fault or {"codigo": getattr(exc, "code", "FLOW_ERROR"), "mensagem": str(exc)}
            stopped = self._stop.is_set() and self._fault is None
            self.controller._safe_stop(self.controller.state.snapshot()["ciclo_id"] or "AUTOMATICO")
            if active_job is not None:
                self.repository.finish(owner, active_job, "INTERROMPIDO" if stopped else "ERRO", error)
            self.repository.set_info(owner, estado="PARADO" if stopped else "ERRO", erro=None if stopped else error)
        finally:
            if self._stop.is_set():
                closing_state = "PRONTO" if self._closing_idle else "PARADO"
                self.repository.set_info(owner, estado="ERRO" if self._fault else closing_state, erro=self._fault)
            finished.set()
            heartbeat.join(timeout=1)
            self.repository.release(owner)
