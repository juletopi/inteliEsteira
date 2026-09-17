"""Repositorios de produtos, ciclos e eventos operacionais."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProductAlreadyExistsError(RuntimeError):
    pass


class ProductRepository:
    def __init__(self, database):
        self.database = database

    def create(self, product_id: str, state: str) -> dict:
        now = _now_iso()
        try:
            with self.database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO products (product_id, state, active, created_at, updated_at)
                    VALUES (?, ?, 1, ?, ?)
                    """,
                    (product_id, state, now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise ProductAlreadyExistsError(
                f"O produto {product_id} ja esta cadastrado."
            ) from exc
        return self.get(product_id, include_inactive=True)

    def get(self, product_id: str, *, include_inactive: bool = False) -> dict | None:
        query = "SELECT * FROM products WHERE product_id = ?"
        parameters: tuple[object, ...] = (product_id,)
        if not include_inactive:
            query += " AND active = 1"

        with self.database.connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        return self._serialize(row) if row else None

    def resolve(self, product_id: str) -> dict | None:
        """Retorna inclusive inativos para a camada de dominio distinguir o erro."""

        return self.get(product_id, include_inactive=True)

    def list(self, *, include_inactive: bool = True) -> list[dict]:
        query = "SELECT * FROM products"
        if not include_inactive:
            query += " WHERE active = 1"
        query += " ORDER BY product_id COLLATE NOCASE"

        with self.database.connect() as connection:
            rows = connection.execute(query).fetchall()
        return [self._serialize(row) for row in rows]

    def update(self, product_id: str, *, state: str, active: bool) -> dict | None:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE products
                SET state = ?, active = ?, updated_at = ?
                WHERE product_id = ?
                """,
                (state, int(active), _now_iso(), product_id),
            )
        if cursor.rowcount == 0:
            return None
        return self.get(product_id, include_inactive=True)

    def deactivate(self, product_id: str) -> dict | None:
        product = self.get(product_id, include_inactive=True)
        if product is None:
            return None
        return self.update(product_id, state=product["uf"], active=False)

    @staticmethod
    def _serialize(row) -> dict:
        return {
            "id": row["product_id"],
            "uf": row["state"],
            "ativo": bool(row["active"]),
            "criado_em": row["created_at"],
            "atualizado_em": row["updated_at"],
        }


class CycleRepository:
    def __init__(self, database):
        self.database = database

    def start(self, cycle_id: str, qr_code: str) -> dict:
        started_at = _now_iso()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO cycles (cycle_id, status, qr_code, started_at)
                VALUES (?, 'AGUARDANDO_OBJETO', ?, ?)
                """,
                (cycle_id, qr_code, started_at),
            )
        self.add_event(cycle_id, "CICLO_INICIADO")
        return self.get(cycle_id)

    def set_route(
        self,
        cycle_id: str,
        *,
        product_id: str,
        state: str,
        macroregion: str,
        destination: str,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE cycles
                SET product_id = ?, state = ?, macroregion = ?, destination = ?,
                    status = 'DESTINO_DEFINIDO'
                WHERE cycle_id = ?
                """,
                (product_id, state, macroregion, destination, cycle_id),
            )

    def set_qr_code(self, cycle_id: str, qr_code: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE cycles SET qr_code = ? WHERE cycle_id = ?",
                (qr_code, cycle_id),
            )

    def set_status(self, cycle_id: str, status: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE cycles SET status = ? WHERE cycle_id = ?",
                (status, cycle_id),
            )

    def complete(self, cycle_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE cycles
                SET status = 'FINALIZADO', finished_at = ?
                WHERE cycle_id = ?
                """,
                (_now_iso(), cycle_id),
            )
        self.add_event(cycle_id, "CICLO_FINALIZADO")

    def fail(self, cycle_id: str, code: str, message: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE cycles
                SET status = 'ERRO', error_code = ?, error_message = ?, finished_at = ?
                WHERE cycle_id = ?
                """,
                (code, message, _now_iso(), cycle_id),
            )
        self.add_event(cycle_id, "ERRO", {"codigo": code, "mensagem": message})

    def stop(self, cycle_id: str) -> None:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE cycles
                SET status = 'PARADO', finished_at = ?
                WHERE cycle_id = ? AND finished_at IS NULL
                """,
                (_now_iso(), cycle_id),
            )
        if cursor.rowcount > 0:
            self.add_event(cycle_id, "CICLO_PARADO")

    def add_event(self, cycle_id: str, event_type: str, payload=None) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO cycle_events (cycle_id, event_type, payload, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    cycle_id,
                    event_type,
                    json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")),
                    _now_iso(),
                ),
            )

    def get(self, cycle_id: str, *, include_events: bool = False) -> dict | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM cycles WHERE cycle_id = ?",
                (cycle_id,),
            ).fetchone()
            if row is None:
                return None
            result = self._serialize(row)
            if include_events:
                events = connection.execute(
                    """
                    SELECT event_type, payload, created_at
                    FROM cycle_events
                    WHERE cycle_id = ?
                    ORDER BY id
                    """,
                    (cycle_id,),
                ).fetchall()
                result["eventos"] = [
                    {
                        "tipo": event["event_type"],
                        "dados": json.loads(event["payload"]),
                        "criado_em": event["created_at"],
                    }
                    for event in events
                ]
        return result

    def list_recent(self, limit: int = 100) -> list[dict]:
        safe_limit = max(1, min(int(limit), 500))
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM cycles ORDER BY started_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [self._serialize(row) for row in rows]

    def count_completed(self) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM cycles WHERE status = 'FINALIZADO'"
            ).fetchone()
        return int(row["total"])

    @staticmethod
    def _serialize(row) -> dict:
        return {
            "id": row["cycle_id"],
            "produto_id": row["product_id"],
            "uf": row["state"],
            "macroregiao": row["macroregion"],
            "destino": row["destination"],
            "estado": row["status"],
            "qr_code": row["qr_code"],
            "erro": (
                {
                    "codigo": row["error_code"],
                    "mensagem": row["error_message"],
                }
                if row["error_code"]
                else None
            ),
            "iniciado_em": row["started_at"],
            "finalizado_em": row["finished_at"],
        }
