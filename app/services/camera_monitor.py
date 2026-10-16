"""Observacao da camera sem autorizar coleta ou registrar producao."""

from copy import deepcopy
from datetime import datetime, timezone
from threading import Event, RLock, Thread
from time import monotonic

from core.classifier import ClassificationError
from core.controller import SystemBusyError
from vision.aruco import CameraError


class CameraMonitor:
    def __init__(self, controller, workflow, *, interval=0.4):
        self.controller = controller
        self.workflow = workflow
        self.interval = max(0.1, float(interval))
        self._lock = RLock()
        self._stop = Event()
        self._worker = None
        self._last_seen = 0.0
        self._snapshot = {"estado": "AGUARDANDO", "produto": None, "erro": None,
                          "observado_em": None, "somente_observacao": True}

    def snapshot(self):
        if self.workflow.running():
            return {"estado": "OPERACAO", "produto": None, "erro": None,
                    "observado_em": None, "somente_observacao": True}
        with self._lock:
            return deepcopy(self._snapshot)

    def observe_once(self):
        if self.workflow.running():
            raise SystemBusyError("O fluxo automatico esta usando a camera.")
        try:
            decision = self.controller.identify_camera_frame()
        except SystemBusyError:
            raise
        except (CameraError, ClassificationError) as exc:
            with self._lock:
                if exc.code == "ARUCO_NOT_FOUND" and self._snapshot["estado"] == "IDENTIFICADO" and monotonic() - self._last_seen < 1.5:
                    self._snapshot["visivel"] = False
                else:
                    self._snapshot = {"estado": "SEM_ARUCO" if exc.code == "ARUCO_NOT_FOUND" else "ERRO",
                                      "produto": None, "erro": {"codigo": exc.code, "mensagem": exc.message},
                                      "observado_em": datetime.now(timezone.utc).isoformat(), "somente_observacao": True}
            raise
        with self._lock:
            self._last_seen = monotonic()
            self._snapshot = {"estado": "IDENTIFICADO", **decision.as_dict(), "erro": None,
                              "observado_em": datetime.now(timezone.utc).isoformat(), "somente_observacao": True, "visivel": True}
        return decision

    def start(self):
        if getattr(self.controller.camera, "mode", None) != "opencv":
            return
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = Thread(target=self._run, name="inteliesteira-camera", daemon=True)
        self._worker.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.observe_once()
            except (SystemBusyError, CameraError, ClassificationError):
                pass
            except Exception:
                # Falhas inesperadas nao podem deixar uma identificacao antiga visivel.
                with self._lock:
                    self._snapshot = {"estado": "ERRO", "produto": None,
                                      "erro": {"codigo": "CAMERA_MONITOR_ERROR", "mensagem": "Falha no monitor da camera."},
                                      "observado_em": datetime.now(timezone.utc).isoformat(), "somente_observacao": True}
            self._stop.wait(self.interval)

    def shutdown(self):
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=3)
