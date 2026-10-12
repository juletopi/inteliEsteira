"""Fila persistente e exclusao mutua entre processos de orquestracao."""

from datetime import datetime, timezone
import json
from time import time


class QueueError(ValueError):
    code = "QUEUE_ERROR"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class QueueRepository:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def _active(row):
        return bool(row["owner"] and row["lease_until"] > time())

    def runtime(self):
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM operation_runtime WHERE id = 1").fetchone()
        return {**json.loads(row["info"]), "ativo": self._active(row), "parada_solicitada": bool(row["stop_requested"])}

    @staticmethod
    def _idle(connection):
        row = connection.execute("SELECT * FROM operation_runtime WHERE id = 1").fetchone()
        if QueueRepository._active(row):
            raise QueueError("Pare o fluxo antes de alterar a fila.")

    def enqueue(self, product_ids):
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._idle(connection)
            pending = connection.execute("SELECT COUNT(*) FROM operation_queue WHERE status NOT IN ('FINALIZADO', 'CANCELADO')").fetchone()[0]
            if pending + len(product_ids) > 100:
                raise QueueError("A fila aceita no maximo 100 unidades pendentes.")
            ids = []
            for product_id in product_ids:
                product = connection.execute(
                    "SELECT product_id FROM products WHERE product_id = ? AND active = 1 AND deleted_at IS NULL", (product_id,)
                ).fetchone()
                if product is None:
                    raise QueueError(f"Produto {product_id} nao esta cadastrado e ativo.")
                stamp = now_iso()
                cursor = connection.execute(
                    "INSERT INTO operation_queue (product_id, created_at, updated_at) VALUES (?, ?, ?)",
                    (product["product_id"], stamp, stamp),
                )
                ids.append(cursor.lastrowid)
        return ids

    @staticmethod
    def _serialize(row):
        return {"id": row["id"], "produto_id": row["product_id"], "estado": row["status"],
                "ciclo_id": row["cycle_id"], "erro": json.loads(row["error"]) if row["error"] else None}

    def items(self):
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM operation_queue WHERE status NOT IN ('FINALIZADO', 'CANCELADO') ORDER BY id").fetchall()
        return [self._serialize(row) for row in rows]

    def head(self):
        items = self.items()
        return items[0] if items else None

    def recent(self):
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM operation_queue WHERE status = 'FINALIZADO' ORDER BY id DESC LIMIT 10").fetchall()
        return [self._serialize(row) for row in rows]

    def edit(self, item_id, action):
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._idle(connection)
            row = connection.execute("SELECT * FROM operation_queue WHERE id = ?", (item_id,)).fetchone()
            if row is None or row["status"] in {"FINALIZADO", "CANCELADO", "PROCESSANDO"}:
                raise QueueError("Item indisponivel para alteracao.")
            if action == "retry" and row["status"] not in {"ERRO", "INTERROMPIDO"}:
                raise QueueError("Apenas itens com erro ou interrompidos podem ser reenfileirados.")
            status = "PENDENTE" if action == "retry" else "CANCELADO"
            connection.execute("UPDATE operation_queue SET status = ?, error = NULL, cycle_id = NULL, updated_at = ? WHERE id = ?",
                               (status, now_iso(), item_id))

    def recover(self):
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            runtime = connection.execute("SELECT * FROM operation_runtime WHERE id = 1").fetchone()
            if self._active(runtime):
                return
            rows = connection.execute("SELECT * FROM operation_queue WHERE status = 'PROCESSANDO'").fetchall()
            interrupted = False
            reconciled = False
            for row in rows:
                cycle = connection.execute("SELECT status FROM cycles WHERE cycle_id = ?", (row["cycle_id"],)).fetchone()
                done = cycle is not None and cycle["status"] == "FINALIZADO"
                interrupted = interrupted or not done
                reconciled = reconciled or done
                error = None if done else json.dumps({"codigo": "PROCESS_RESTARTED", "mensagem": "Operacao interrompida. Inspecione e reposicione o produto antes de tentar novamente."})
                connection.execute("UPDATE operation_queue SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                                   ("FINALIZADO" if done else "INTERROMPIDO", error, now_iso(), row["id"]))
                if not done:
                    connection.execute("UPDATE cycles SET status = 'PARADO', finished_at = ? WHERE cycle_id = ? AND finished_at IS NULL",
                                       (now_iso(), row["cycle_id"]))
            connection.execute("UPDATE operation_runtime SET owner = NULL, lease_until = 0 WHERE id = 1")
            if runtime["owner"] or rows:
                info = json.loads(runtime["info"])
                info.update({"estado": "INTERROMPIDO" if interrupted else "PRONTO",
                             "aviso": "Servidor reiniciado. A retomada exige acao do operador."})
                if reconciled:
                    info["area_livre_pendente"] = True
                connection.execute("UPDATE operation_runtime SET info = ? WHERE id = 1", (json.dumps(info, ensure_ascii=False),))

    def acquire(self, owner, lease=5.0):
        self.recover()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._idle(connection)
            info = json.loads(connection.execute("SELECT info FROM operation_runtime WHERE id = 1").fetchone()[0])
            info.update({"estado": "INICIANDO", "erro": None, "aviso": None})
            connection.execute("UPDATE operation_runtime SET owner = ?, lease_until = ?, stop_requested = 0, info = ? WHERE id = 1",
                               (owner, time() + lease, json.dumps(info, ensure_ascii=False)))

    def heartbeat(self, owner, lease=5.0):
        with self.database.connect() as connection:
            cursor = connection.execute("UPDATE operation_runtime SET lease_until = ? WHERE id = 1 AND owner = ? AND stop_requested = 0",
                                        (time() + lease, owner))
        return bool(cursor.rowcount)

    def set_info(self, owner=None, **changes):
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM operation_runtime WHERE id = 1").fetchone()
            if owner is not None and row["owner"] != owner:
                return
            if owner is None and self._active(row):
                return
            info = json.loads(row["info"])
            info.update(changes)
            connection.execute("UPDATE operation_runtime SET info = ? WHERE id = 1", (json.dumps(info, ensure_ascii=False),))

    def claim(self, owner, item_id, cycle_id):
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            runtime = connection.execute("SELECT * FROM operation_runtime WHERE id = 1").fetchone()
            if runtime["owner"] != owner or not self._active(runtime) or runtime["stop_requested"]:
                raise QueueError("A orquestracao perdeu a posse da fila ou recebeu uma parada.")
            head = connection.execute("SELECT * FROM operation_queue WHERE status NOT IN ('FINALIZADO', 'CANCELADO') ORDER BY id LIMIT 1").fetchone()
            if head is None or head["id"] != item_id or head["status"] != "PENDENTE":
                raise QueueError("A ordem da fila mudou ou o item nao esta pendente.")
            connection.execute("UPDATE operation_queue SET status = 'PROCESSANDO', cycle_id = ?, updated_at = ? WHERE id = ?",
                               (cycle_id, now_iso(), item_id))

    def finish(self, owner, item_id, status, error=None):
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            runtime = connection.execute("SELECT owner FROM operation_runtime WHERE id = 1").fetchone()
            if runtime["owner"] != owner:
                return
            connection.execute("UPDATE operation_queue SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                               (status, json.dumps(error, ensure_ascii=False) if error else None, now_iso(), item_id))

    def request_stop(self):
        with self.database.connect() as connection:
            connection.execute("UPDATE operation_runtime SET stop_requested = 1 WHERE id = 1")

    def release(self, owner):
        with self.database.connect() as connection:
            connection.execute("UPDATE operation_runtime SET owner = NULL, lease_until = 0 WHERE id = 1 AND owner = ?", (owner,))
