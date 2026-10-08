"""Repositorios de produtos, ciclos e eventos operacionais."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProductAlreadyExistsError(RuntimeError):
    pass


class ArucoMarkersExhaustedError(RuntimeError):
    pass


class ArucoMarkerConflictError(RuntimeError):
    pass


class ProductNotRegisteredError(RuntimeError):
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
            with self.database.connect() as connection:
                existing = connection.execute(
                    "SELECT deleted_at FROM products WHERE product_id = ?", (product_id,)
                ).fetchone()
            if existing is not None and existing["deleted_at"] is not None:
                raise ProductAlreadyExistsError(
                    f"O identificador {product_id} pertence a um produto excluido e permanece reservado."
                ) from exc
            raise ProductAlreadyExistsError(
                f"O produto {product_id} ja esta cadastrado."
            ) from exc
        return self.get(product_id, include_inactive=True)

    def get(self, product_id: str, *, include_inactive: bool = False) -> dict | None:
        query = """
            SELECT products.*, aruco_markers.marker_id AS aruco_id
            FROM products
            LEFT JOIN aruco_markers ON aruco_markers.product_id = products.product_id
            WHERE products.product_id = ?
              AND products.deleted_at IS NULL
        """
        parameters: tuple[object, ...] = (product_id,)
        if not include_inactive:
            query += " AND products.active = 1"

        with self.database.connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        return self._serialize(row) if row else None

    def resolve(self, product_id: str) -> dict | None:
        """Retorna inclusive inativos para a camada de dominio distinguir o erro."""

        return self.get(product_id, include_inactive=True)

    def list(self, *, include_inactive: bool = True) -> list[dict]:
        query = """
            SELECT products.*, aruco_markers.marker_id AS aruco_id
            FROM products
            LEFT JOIN aruco_markers ON aruco_markers.product_id = products.product_id
        """
        query += " WHERE products.deleted_at IS NULL"
        if not include_inactive:
            query += " AND products.active = 1"
        query += " ORDER BY products.product_id COLLATE NOCASE"

        with self.database.connect() as connection:
            rows = connection.execute(query).fetchall()
        return [self._serialize(row) for row in rows]

    def resolve_aruco(self, marker_id: int) -> dict | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT products.*, aruco_markers.marker_id AS aruco_id
                FROM aruco_markers
                JOIN products ON products.product_id = aruco_markers.product_id
                WHERE aruco_markers.marker_id = ? AND products.deleted_at IS NULL
                """,
                (marker_id,),
            ).fetchone()
        return self._serialize(row) if row else None

    def ensure_aruco(self, product_id: str, *, marker_id: int | None = None) -> dict | None:
        try:
            return self.ensure_aruco_batch([{"produto_id": product_id, "aruco_id": marker_id}])[0]
        except ProductNotRegisteredError:
            return None

    def ensure_aruco_batch(self, requests: list[dict]) -> list[dict]:
        """Registra o lote em uma transacao, reservando IDs explicitos primeiro."""
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            products = {}
            for item in sorted(requests, key=lambda value: value.get("aruco_id") is None):
                product = self._ensure_aruco(connection, item["produto_id"], item.get("aruco_id"))
                products[item["produto_id"].lower()] = product
            return [products[item["produto_id"].lower()] for item in requests]

    def _ensure_aruco(self, connection, product_id, marker_id):
        if marker_id is not None and (type(marker_id) is not int or not 0 <= marker_id <= 249):
            raise ValueError("O ID ArUco deve ser um inteiro entre 0 e 249.")
        row = connection.execute(
            """SELECT products.*, aruco_markers.marker_id AS aruco_id
               FROM products LEFT JOIN aruco_markers ON aruco_markers.product_id = products.product_id
               WHERE products.product_id = ? AND products.deleted_at IS NULL""", (product_id,)
        ).fetchone()
        if row is None:
            raise ProductNotRegisteredError(f"Produto {product_id} nao encontrado.")
        product = self._serialize(row)
        if product["aruco_id"] is not None:
            if marker_id is not None and marker_id != product["aruco_id"]:
                raise ArucoMarkerConflictError(
                    f"O produto {product['id']} ja usa o ArUco {product['aruco_id']}. "
                    "O vinculo existente foi preservado."
                )
            return product
        if marker_id is None:
            used = {row["marker_id"] for row in connection.execute("SELECT marker_id FROM aruco_markers")}
            marker_id = next((value for value in range(250) if value not in used), None)
            if marker_id is None:
                raise ArucoMarkersExhaustedError("Todos os 250 marcadores ArUco estao em uso.")
        else:
            owner = connection.execute(
                "SELECT product_id FROM aruco_markers WHERE marker_id = ?", (marker_id,)
            ).fetchone()
            if owner is not None:
                raise ArucoMarkerConflictError(f"O ArUco {marker_id} ja pertence ao produto {owner['product_id']}.")
        connection.execute(
            "INSERT INTO aruco_markers (marker_id, product_id) VALUES (?, ?)", (marker_id, product["id"])
        )
        product["aruco_id"] = marker_id
        return product

    def update(self, product_id: str, *, state: str, active: bool) -> dict | None:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE products
                SET state = ?, active = ?, updated_at = ?
                WHERE product_id = ? AND deleted_at IS NULL
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

    def delete(self, product_id: str) -> bool:
        """Retira do catalogo sem perder historico nem reciclar etiquetas antigas."""
        now = _now_iso()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """UPDATE products SET active = 0, deleted_at = ?, updated_at = ?
                   WHERE product_id = ? AND deleted_at IS NULL""", (now, now, product_id)
            )
        return cursor.rowcount > 0

    @staticmethod
    def _serialize(row) -> dict:
        return {
            "id": row["product_id"],
            "uf": row["state"],
            "ativo": bool(row["active"]),
            "aruco_id": row["aruco_id"],
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
