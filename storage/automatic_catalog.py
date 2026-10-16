"""Persistencia automatica do catalogo JSON; SQLite conserva fila e historico.

Cada cadastro publica o JSON por substituicao atomica. Uma assinatura pendente
no mesmo commit SQLite permite recuperar uma falha de escrita sem perder dados.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, RLock

from storage.catalog import export_catalog, validate_catalog


class CatalogPersistenceError(RuntimeError):
    pass


_locks = {}
_locks_guard = Lock()


def fingerprint(document):
    products = validate_catalog(document, allow_empty=True)
    products.sort(key=lambda p: p["produto_id"].lower())
    return hashlib.sha256(json.dumps(products, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class AutomaticCatalog:
    def __init__(self, database, path):
        self.database = database
        self.path = Path(path).resolve()
        with _locks_guard:
            self._lock = _locks.setdefault(os.path.normcase(str(self.path)), RLock())

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.with_suffix(self.path.suffix + ".lock").open("a+b") as handle:
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    handle.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def initialize(self):
        with self.database.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS catalog_persistence (
                id INTEGER PRIMARY KEY CHECK (id = 1), published_hash TEXT, pending_hash TEXT)""")
            connection.execute("INSERT OR IGNORE INTO catalog_persistence(id) VALUES(1)")
        self.synchronize()
        self.database.catalog_store = self

    def _snapshot(self, connection=None):
        return export_catalog(self.database, allow_empty=True, connection=connection)

    def _read_file(self):
        try:
            with self.path.open(encoding="utf-8-sig") as source:
                document = json.load(source)
            validate_catalog(document, allow_empty=True)
            return document
        except FileNotFoundError:
            return None
        except (ValueError, OSError) as exc:
            raise CatalogPersistenceError(f"Nao foi possivel ler o cadastro em {self.path}: {exc}. O arquivo foi preservado.") from exc

    def _publish(self, document):
        temporary = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                    prefix=".catalog-", suffix=".tmp", delete=False) as target:
                temporary = Path(target.name)
                json.dump(document, target, ensure_ascii=False, indent=2)
                target.write("\n")
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.path)
            with self.database.connect() as connection:
                connection.execute("UPDATE catalog_persistence SET published_hash = ?, pending_hash = NULL WHERE id=1",
                                   (fingerprint(document),))
        except OSError as exc:
            raise CatalogPersistenceError(f"Nao foi possivel salvar {self.path}. Os dados foram preservados no banco local e a gravacao sera retomada ao abrir a aplicacao.") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _merge(self, incoming, *, prefer_local):
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for product in validate_catalog(incoming, allow_empty=True):
                product_id, marker = product["produto_id"], product["aruco_id"]
                row = connection.execute("""SELECT p.product_id, p.state, p.active, p.deleted_at, a.marker_id
                    FROM products p LEFT JOIN aruco_markers a ON a.product_id=p.product_id
                    WHERE p.product_id=?""", (product_id,)).fetchone()
                if row is None:
                    connection.execute("""INSERT INTO products(product_id,state,active,created_at,updated_at,deleted_at)
                        VALUES(?,?,?,?,?,?)""", (product_id, product["uf"], int(product["ativo"]), now, now,
                                                 now if product["excluido"] else None))
                else:
                    if row["product_id"] != product_id or (row["marker_id"] is not None and row["marker_id"] != marker):
                        raise CatalogPersistenceError(f"{product_id}: o ID ArUco do JSON diverge do cadastro local. Os dados foram preservados.")
                    # Nunca ressuscita exclusoes locais ou troca etiquetas existentes.
                    if row["deleted_at"] is None and (not prefer_local or product["excluido"]):
                        connection.execute("UPDATE products SET state=?,active=?,deleted_at=?,updated_at=? WHERE product_id=?",
                                           (row["state"] if prefer_local else product["uf"], int(product["ativo"]),
                                            now if product["excluido"] else None, now, product_id))
                if marker is not None:
                    owner = connection.execute("SELECT product_id FROM aruco_markers WHERE marker_id=?", (marker,)).fetchone()
                    if owner is not None and owner["product_id"] != product_id:
                        raise CatalogPersistenceError(f"ArUco {marker} pertence a outro produto no banco local. Os dados foram preservados.")
                    if owner is None:
                        connection.execute("INSERT INTO aruco_markers(marker_id,product_id) VALUES(?,?)", (marker, product_id))
            document = self._snapshot(connection)
            connection.execute("UPDATE catalog_persistence SET pending_hash=? WHERE id=1", (fingerprint(document),))

    def _synchronize(self):
        incoming = self._read_file()
        document = self._snapshot()
        local_hash = fingerprint(document)
        file_hash = fingerprint(incoming) if incoming is not None else None
        with self.database.connect() as connection:
            state = connection.execute("SELECT published_hash,pending_hash FROM catalog_persistence WHERE id=1").fetchone()
        published, pending = state["published_hash"], state["pending_hash"]
        if pending:
            if local_hash != pending or (file_hash not in {None, published, pending}):
                raise CatalogPersistenceError("O JSON e o cadastro local mudaram ao mesmo tempo. Ambos foram preservados para evitar perda de dados.")
            self._publish(document)
            return
        if incoming is not None and file_hash != published:
            if published and local_hash not in {published, file_hash}:
                raise CatalogPersistenceError("O JSON e o cadastro local divergem. Ambos foram preservados para evitar perda de dados.")
            self._merge(incoming, prefer_local=published is None and bool(document["products"]))
            document = self._snapshot()
        elif file_hash == local_hash == published:
            return
        self._publish(document)

    def synchronize(self):
        with self.locked():
            self._synchronize()

    @contextmanager
    def change(self):
        with self.locked():
            self._synchronize()
            with self.database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                document = self._snapshot(connection)
                connection.execute("UPDATE catalog_persistence SET pending_hash=? WHERE id=1", (fingerprint(document),))
            self._publish(document)
