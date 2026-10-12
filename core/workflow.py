"""Orquestracao de uma fila planejada, autorizada pela camera na area P01."""

from threading import Event, RLock, Thread
from uuid import uuid4

from core.classifier import ClassificationError, read_product_id
from core.controller import ControllerError
from hardware.device import HardwareError
from storage.queue import QueueError
from vision.qrcode import ArucoNotRegisteredError, CameraError, QRCodeNotFoundError


class Workflow:
    def __init__(self, controller, repository, *, scan_interval=0.1):
        self.controller = controller
        self.repository = repository
        self.scan_interval = scan_interval
        self._lock = RLock()
        self._stop = Event()
        self._worker = None
        self._fault = None
        self.repository.recover()

    def snapshot(self):
        return {"fluxo": self.repository.runtime(), "itens": self.repository.items(),
                "ultimos_finalizados": self.repository.recent(), "area_coleta": self.controller.gripper.pickup_zone}

    def running(self):
        return self.repository.runtime()["ativo"]

    def start(self):
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise QueueError("O fluxo ja esta ativo.")
            self.repository.recover()
            head = self.repository.head()
            if head is None:
                raise QueueError("Escolha os produtos e adicione unidades a fila antes de iniciar.")
            if head["estado"] != "PENDENTE":
                raise QueueError("A cabeca da fila esta interrompida ou com erro. Inspecione o produto e cancele ou tente novamente.")
            if self.controller.state.snapshot()["estado"] in {"ERRO", "PARADO"}:
                raise QueueError("Resete o sistema antes de retomar o fluxo.")
            owner = uuid4().hex
            self.repository.acquire(owner, lease=30)
            try:
                self.controller.connect_components()
                self.controller.ensure_operation_ready()
                if not self.repository.heartbeat(owner):
                    raise QueueError("A fila recebeu uma parada durante a preparacao.")
            except Exception as exc:
                self.repository.set_info(owner, estado="ERRO", erro={"codigo": getattr(exc, "code", "FLOW_ERROR"), "mensagem": str(exc)})
                self.repository.release(owner)
                raise
            self._stop.clear()
            self._fault = None
            self._worker = Thread(target=self._run, args=(owner,), name="inteliesteira-fila", daemon=True)
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
            self.repository.set_info(estado="PRONTO", erro=None, aviso=None)
            return result

    def shutdown(self):
        if self._worker is not None and self._worker.is_alive():
            self.stop()
            self._worker.join(timeout=2)

    def _heartbeat(self, owner, finished):
        while not finished.wait(1):
            try:
                if not self.repository.heartbeat(owner):
                    if not self.repository.runtime()["parada_solicitada"]:
                        self._fault = {"codigo": "QUEUE_OWNERSHIP_LOST", "mensagem": "A orquestracao perdeu a posse da fila."}
                    self._stop.set()
                    self.controller.stop()
                    return
                for _name, device in self.controller._hardware_devices():
                    device.execute("SISTEMA:PING", "HEARTBEAT", timeout=min(0.5, self.controller.command_timeout), retries=0)
            except Exception as exc:
                self._fault = {"codigo": "HEARTBEAT_FAILED", "mensagem": str(exc)}
                self._stop.set()
                self.controller.stop()
                self.repository.set_info(owner, erro=self._fault)
                return

    def _run(self, owner):
        finished = Event()
        heartbeat = Thread(target=self._heartbeat, args=(owner, finished), daemon=True)
        heartbeat.start()
        active_job = None
        try:
            while not self._stop.is_set():
                head = self.repository.head()
                if head is None:
                    self.repository.set_info(owner, estado="CONCLUIDO", esperado=None, detectado=None, aviso=None)
                    break
                if head["estado"] != "PENDENTE":
                    raise QueueError("O proximo item precisa de inspecao antes da retomada.")
                expected = self.controller.products.get(head["produto_id"])
                if expected is None:
                    active_job = head
                    raise QueueError(f"Produto {head['produto_id']} foi excluido ou desativado.")
                if self.repository.runtime().get("area_livre_pendente"):
                    self.repository.set_info(owner, estado="AGUARDANDO_AREA_LIVRE", esperado=head["produto_id"], aviso="Retire o produto anterior da area P01 antes de apresentar a proxima unidade.")
                    if not self.controller.camera.wait_until_clear(timeout=0.5, cancelled=self._stop.is_set):
                        continue
                    self.repository.set_info(owner, area_livre_pendente=False, aviso=None)
                self.repository.set_info(owner, estado="AGUARDANDO_LEITURA", esperado=head["produto_id"])
                try:
                    captured = self.controller.camera.scan_qrcode(timeout=0.5, cancelled=self._stop.is_set)
                    detected_id = read_product_id(captured)
                    detected = self.controller.products.get(detected_id)
                    if detected is None:
                        self.repository.set_info(owner, detectado=detected_id, aviso="Etiqueta de produto desconhecido, excluido ou inativo. Nenhum movimento autorizado.")
                        continue
                    if detected["id"].lower() != expected["id"].lower():
                        self.repository.set_info(owner, detectado=detected["id"], aviso=f"Fora da ordem: apresente {expected['id']} na area P01.")
                        continue
                except QRCodeNotFoundError:
                    self._stop.wait(self.scan_interval)
                    continue
                except (ClassificationError, ArucoNotRegisteredError) as exc:
                    self.repository.set_info(owner, aviso=str(exc))
                    self._stop.wait(self.scan_interval)
                    continue
                if self._stop.is_set():
                    break
                active_job = head
                cycle_id = uuid4().hex[:12]
                self.repository.claim(owner, head["id"], cycle_id)
                self.repository.set_info(owner, estado="PROCESSANDO", detectado=detected["id"], aviso=None)
                self.controller.process_next_product(identified_qr_code=captured, expected_product_id=expected["id"],
                                                     cycle_id=cycle_id, occupancy=self.controller.cycles.destination_counts())
                self.repository.finish(owner, head["id"], "FINALIZADO")
                active_job = None
                self.repository.set_info(owner, area_livre_pendente=True)
        except Exception as exc:
            stopped = self._stop.is_set()
            error = self._fault or {"codigo": getattr(exc, "code", "FLOW_ERROR"), "mensagem": str(exc)}
            if active_job is not None:
                self.repository.finish(owner, active_job["id"], "INTERROMPIDO" if stopped and not self._fault else "ERRO", error)
            self.repository.set_info(owner, estado="PARADO" if stopped and not self._fault else "ERRO", erro=None if stopped and not self._fault else error)
        finally:
            if self._stop.is_set():
                self.repository.set_info(owner, estado="ERRO" if self._fault else "PARADO", erro=self._fault)
            finished.set()
            heartbeat.join(timeout=1)
            self.repository.release(owner)
