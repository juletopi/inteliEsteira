"""Operacao automatica: HC-SR04, coleta, identificacao e termino da esteira."""

from threading import Event, RLock, Thread
from uuid import uuid4

from core.controller import ControllerError
from hardware.device import HardwareError
from storage.queue import QueueError
from vision.aruco import CameraError


class Workflow:
    def __init__(self, controller, repository, *, scan_interval=0.1, presence_distance=10, presence_stable_ms=3000,
                 profile_provider=None, auto_sync_neutral=False):
        if not 2 <= presence_distance <= 100 or presence_stable_ms not in {3000, 4000, 5000}:
            raise ValueError("HC-SR04: configure distancia de 2 a 100 cm e estabilidade de 3000, 4000 ou 5000 ms.")
        self.controller = controller
        self.repository = repository
        self.scan_interval = scan_interval
        self.presence_distance = presence_distance
        self.presence_stable_ms = presence_stable_ms
        self.profile_provider = profile_provider
        self.auto_sync_neutral = auto_sync_neutral
        self._lock = RLock()
        self._stop = Event()
        self._prepared = Event()
        # Dispositivo caiu sem unidade em andamento: refaz a preparacao em vez de parar.
        self._reconnect = Event()
        self._sensor_warning = None
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
        sensor = self.sensor.snapshot()
        sensor["conectado"] = self.controller.gripper.arduino.is_connected()
        if not sensor["conectado"]:
            sensor.update(presente=None, distancia_cm=None, recebido_em=None)
        if info["ativo"] and info.get("ciclo_id") and state["ciclo_id"] == info["ciclo_id"]:
            info["estado"] = state["estado"]
        profile = self.profile_provider() if self.profile_provider else None
        return {"modo": "automatico", "fluxo": info, "itens": self.repository.automatic_items(),
                "sensor": sensor, "area_coleta": self.controller.gripper.pickup_zone,
                "perfil_garra": ({"versao": profile["version"], "origem": profile["source"],
                                  "passos_pegar": len(profile["pickup"]), "passos_entregar": len(profile["delivery"]),
                                  "sensor_limite_cm": profile["sensor"]["distance_cm"]}
                                 if profile else None),
                "area_leitura": "E01", "proxima_caixa_liberada": bool(info["ativo"] and info.get("estado") == "AGUARDANDO_SENSOR")}

    def running(self):
        return self.repository.runtime()["ativo"]

    def start(self, *, at_boot=False):
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise QueueError("O fluxo automatico ja esta ativo.")
            self.repository.recover()
            # Na inicializacao, uma parada limpa do operador (sem unidade pendente) nao
            # impede o rearme; ERRO e INTERROMPIDO podem ter deixado um cubo na esteira.
            blocked = {"ERRO", "INTERROMPIDO"} if at_boot else {"ERRO", "INTERROMPIDO", "PARADO"}
            if self.repository.runtime().get("estado") in blocked:
                raise QueueError("Inspecione o cubo e resete a operacao antes de rearmar o sensor.")
            if self.controller.state.snapshot()["estado"] in {"ERRO", "PARADO"}:
                raise QueueError("Resete o sistema antes de retomar o fluxo.")
            profile = self.profile_provider() if self.profile_provider else None
            if profile and not profile["sensor"]["enabled"]:
                raise QueueError("O fluxo coletivo depende do HC-SR04. Ative o sensor no perfil salvo pelo calibrador.")
            owner = uuid4().hex
            self.repository.acquire(owner, lease=30)
            self._stop.clear()
            self._prepared.clear()
            self._reconnect.clear()
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

    def _heartbeat(self, owner, finished, max_misses=3):
        # Um PING atrasado (Wi-Fi do EV3, camera ocupando a CPU) nao derruba o
        # fluxo; so falhas consecutivas ou conexao perdida interrompem.
        misses = {}
        while not finished.wait(1):
            try:
                if not self.repository.heartbeat(owner):
                    if not self.repository.runtime()["parada_solicitada"]:
                        raise QueueError("A operacao perdeu a posse da fila.")
                    self._stop.set()
                    self.controller.stop()
                    return
                if self._prepared.is_set():
                    for name, device in self.controller._hardware_devices():
                        try:
                            device.execute("SISTEMA:PING", "HEARTBEAT", timeout=self.controller.command_timeout, retries=0)
                            misses[name] = 0
                        except HardwareError:
                            misses[name] = misses.get(name, 0) + 1
                            if not device.is_connected() or misses[name] >= max_misses:
                                if self.repository.runtime().get("ciclo_id") is None:
                                    # Ocioso, sem cubo em movimento: reconecta e rearma sozinho.
                                    misses.clear()
                                    self._prepared.clear()
                                    self._reconnect.set()
                                    break
                                raise
            except Exception as exc:
                self._fault = {"codigo": "HEARTBEAT_FAILED", "mensagem": str(exc)}
                self._stop.set()
                self.controller.stop()
                return

    def _prepare(self, owner):
        while not self._stop.is_set():
            try:
                self.controller.connect_components()
                self.controller.reset()
                if self.auto_sync_neutral:
                    self.controller.ensure_neutral_reference()
                self.controller.ensure_operation_ready()
                self.controller.require_gripper_ready()
                self._arm_sensor()
                self._prepared.set()
                self.repository.set_info(owner, erro=None, aviso=None, ciclo_id=None)
                return True
            except (ControllerError, HardwareError, CameraError) as exc:
                self.repository.set_info(owner, estado="AGUARDANDO_CONEXAO", aviso=str(exc), ciclo_id=None)
                self._stop.wait(2)
        return False

    def _arm_sensor(self):
        """Mede o fundo, avisa se ele esta dentro do limite e rearma a deteccao."""
        profile = self.profile_provider() if self.profile_provider else None
        sensor_config = profile["sensor"] if profile else {
            "distance_cm": self.presence_distance, "stable_ms": self.presence_stable_ms,
        }
        limit = sensor_config["distance_cm"]
        try:
            reading = self.controller.read_presence_distance()
        except HardwareError:
            reading = None  # Firmware anterior sem PRESENCA:LEITURA.
        median = reading["mediana_cm"] if reading else -1
        self._sensor_warning = (
            f"O HC-SR04 está lendo {median} cm com o limite em {limit} cm. Se a área de coleta estiver vazia, "
            f"o fundo está perto demais e o sensor ficará preso em 'cubo detectado': reduza a distância do "
            f"sensor no calibrador para no máximo {max(2, median - 3)} cm."
        ) if 2 <= median <= limit + 2 else None
        # Reconfigurar o HC-SR04 reinicia a confirmacao de presenca no Arduino.
        # Limpe tambem o estado em cache para que um novo SENSOR:PRESENTE gere
        # uma borda, mesmo se a leitura anterior ainda estiver marcada como presente.
        self.sensor.reset()
        self.controller.gripper.arduino.execute(
            f"PRESENCA:CONFIGURAR:{limit}:{sensor_config['stable_ms']}", "PRESENCA",
            timeout=self.controller.command_timeout, retries=self.controller.command_retries,
        )

    def _run(self, owner):
        finished = Event()
        heartbeat = Thread(target=self._heartbeat, args=(owner, finished), daemon=True)
        heartbeat.start()
        active_job = None
        try:
            cursor = self.sensor.snapshot()["sequencia"]
            waiting_cancelled = lambda: self._stop.is_set() or self._reconnect.is_set()
            while not self._stop.is_set():
                if self._reconnect.is_set():
                    self._reconnect.clear()
                    self.repository.set_info(owner, estado="AGUARDANDO_CONEXAO", ciclo_id=None,
                                             aviso="Dispositivo sem resposta; reconectando automaticamente.")
                    # Bordas ocorridas sem os dispositivos prontos nao autorizam coleta.
                    cursor = self.sensor.snapshot()["sequencia"]
                if not self._prepared.is_set() and not self._prepare(owner):
                    return
                if self._reconnect.is_set():
                    continue
                self.repository.set_info(owner, estado="AGUARDANDO_SENSOR", ciclo_id=None, detectado=None,
                                         aviso=self._sensor_warning)
                present = self.sensor.wait_present(cursor, timeout=0.5, cancelled=waiting_cancelled)
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
                profile = self.profile_provider() if self.profile_provider else None
                if profile and not profile["repeat"]:
                    self.repository.set_info(owner, estado="PRONTO", ciclo_id=None, detectado=None,
                                             aviso="Ciclo único concluído; inicie novamente para processar outra caixa.")
                    break
                # Bordas ocorridas durante a operacao nao autorizam outra coleta. Rearmar
                # o sensor faz um cubo colocado durante o movimento gerar uma borda nova.
                try:
                    self._arm_sensor()
                except HardwareError:
                    self._prepared.clear()
                    self._reconnect.set()
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
