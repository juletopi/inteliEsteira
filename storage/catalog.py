"""Transporte e verificacao do cadastro, preservando os IDs das etiquetas."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from core.classifier import ClassificationError, validate_product_id, validate_state
from storage.database import Database


class CatalogError(ValueError):
    pass


def validate_catalog(document):
    if not isinstance(document, dict) or type(document.get("version")) is not int or document["version"] != 1:
        raise CatalogError("Versao de catalogo invalida: esperado version=1.")
    if document.get("aruco_dictionary") != "DICT_4X4_250":
        raise CatalogError("O catalogo deve usar o dicionario DICT_4X4_250.")
    entries = document.get("products")
    if not isinstance(entries, list) or not entries:
        raise CatalogError("O catalogo deve conter uma lista de produtos nao vazia.")
    products, product_ids, marker_ids = [], set(), set()
    for entry in entries:
        if not isinstance(entry, dict) or not {"produto_id", "uf", "ativo", "aruco_id"} <= entry.keys():
            raise CatalogError("Cada produto deve informar produto_id, uf, ativo e aruco_id.")
        try:
            product_id = validate_product_id(entry["produto_id"])
            state = validate_state(entry["uf"])
        except ClassificationError as exc:
            raise CatalogError(str(exc)) from exc
        if product_id != entry["produto_id"] or state != entry["uf"]:
            raise CatalogError("Use identificadores sem espacos e UFs em maiusculas.")
        if type(entry["ativo"]) is not bool:
            raise CatalogError(f"{product_id}: ativo deve ser booleano.")
        deleted = entry.get("excluido", False)
        if type(deleted) is not bool or deleted and entry["ativo"]:
            raise CatalogError(f"{product_id}: excluido deve ser booleano; produtos excluidos devem estar inativos.")
        marker_id = entry["aruco_id"]
        if marker_id is not None and (type(marker_id) is not int or not 0 <= marker_id <= 249):
            raise CatalogError(f"{product_id}: aruco_id deve ser null ou um inteiro de 0 a 249.")
        if product_id.lower() in product_ids:
            raise CatalogError(f"Produto duplicado no catalogo: {product_id}.")
        if marker_id is not None and marker_id in marker_ids:
            raise CatalogError(f"ID ArUco duplicado no catalogo: {marker_id}.")
        product_ids.add(product_id.lower())
        if marker_id is not None:
            marker_ids.add(marker_id)
        products.append({"produto_id": product_id, "uf": state, "ativo": entry["ativo"],
                         "aruco_id": marker_id, "excluido": deleted})
    return products


def export_catalog(database):
    if not database.path.is_file():
        raise CatalogError(f"Banco nao encontrado: {database.path}")
    with database.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(products)")}
        deleted_column = "p.deleted_at" if "deleted_at" in columns else "NULL AS deleted_at"
        rows = connection.execute(
            f"""SELECT p.product_id, p.state, p.active, a.marker_id, {deleted_column}
               FROM products p LEFT JOIN aruco_markers a ON a.product_id = p.product_id
               ORDER BY p.product_id COLLATE NOCASE"""
        ).fetchall()
    document = {
        "version": 1,
        "aruco_dictionary": "DICT_4X4_250",
        "products": [
            {"produto_id": row["product_id"], "uf": row["state"],
             "ativo": bool(row["active"]), "aruco_id": row["marker_id"],
             **({"excluido": True} if row["deleted_at"] is not None else {})}
            for row in rows
        ],
    }
    validate_catalog(document)
    return document


def import_catalog(database, document):
    products = validate_catalog(document)
    now = datetime.now(timezone.utc).isoformat()
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        for product in products:
            product_id = product["produto_id"]
            existing = connection.execute(
                """SELECT p.product_id, p.state, p.active, p.deleted_at, a.marker_id
                   FROM products p LEFT JOIN aruco_markers a ON a.product_id = p.product_id
                   WHERE p.product_id = ?""", (product_id,)
            ).fetchone()
            if existing is not None:
                if existing["product_id"] != product_id or existing["state"] != product["uf"]:
                    raise CatalogError(f"{product_id}: cadastro local diverge do catalogo. Nenhum produto foi importado.")
                if not product["excluido"] and (existing["deleted_at"] is not None or bool(existing["active"]) != product["ativo"]):
                    raise CatalogError(f"{product_id}: atividade ou exclusao local diverge do catalogo. Nenhum produto foi importado.")
                if existing["marker_id"] is not None and existing["marker_id"] != product["aruco_id"]:
                    raise CatalogError(f"{product_id}: ID ArUco local diverge do catalogo. Nenhum produto foi importado.")
                if product["excluido"] and existing["deleted_at"] is None:
                    connection.execute(
                        "UPDATE products SET active = 0, deleted_at = ?, updated_at = ? WHERE product_id = ?",
                        (now, now, product_id),
                    )
            else:
                connection.execute(
                    """INSERT INTO products (product_id, state, active, created_at, updated_at, deleted_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (product_id, product["uf"], int(product["ativo"]), now, now, now if product["excluido"] else None),
                )
            marker_id = product["aruco_id"]
            if marker_id is not None:
                owner = connection.execute(
                    "SELECT product_id FROM aruco_markers WHERE marker_id = ?", (marker_id,)
                ).fetchone()
                if owner is not None and owner["product_id"] != product_id:
                    raise CatalogError(f"ArUco {marker_id} pertence a {owner['product_id']}. Nenhum produto foi importado.")
                if owner is None:
                    connection.execute(
                        "INSERT INTO aruco_markers (marker_id, product_id) VALUES (?, ?)",
                        (marker_id, product_id),
                    )
    return len(products)


def verify_catalog(database, document, *, require_aruco=False):
    expected = validate_catalog(document)
    actual = {p["produto_id"]: p for p in validate_catalog(export_catalog(database))}
    for product in expected:
        product_id = product["produto_id"]
        if actual.get(product_id) != product:
            raise CatalogError(f"{product_id}: cadastro ou ID ArUco diverge do catalogo salvo.")
        if require_aruco and product["ativo"] and product["aruco_id"] is None:
            raise CatalogError(f"{product_id}: falta vincular o ArUco antes de usar as etiquetas na apresentacao.")
    return len(expected)


def backup_database(database, destination):
    destination = Path(destination)
    if not database.path.is_file():
        raise CatalogError(f"Banco nao encontrado: {database.path}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Reserva o destino sem sobrescrever um backup anterior.
    with destination.open("xb"):
        pass
    try:
        source = sqlite3.connect(database.path.as_uri() + "?mode=ro", uri=True)
        try:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
    except Exception:
        destination.unlink()
        raise


def main(argv=None):
    from config import DATABASE_PATH

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("export", "import", "verify", "backup"))
    parser.add_argument("file", type=Path, help="Catalogo JSON ou destino do backup SQLite.")
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    parser.add_argument("--require-aruco", action="store_true", help="Verificar ArUco de todos os produtos ativos.")
    args = parser.parse_args(argv)
    database = Database(args.database)
    try:
        if args.command == "export":
            document = export_catalog(database)
            args.file.parent.mkdir(parents=True, exist_ok=True)
            with args.file.open("x", encoding="utf-8") as output:
                json.dump(document, output, ensure_ascii=False, indent=2)
                output.write("\n")
            print(f"Catalogo exportado: {args.file.resolve()}")
        elif args.command == "backup":
            backup_database(database, args.file)
            print(f"Backup criado: {args.file.resolve()}")
        else:
            with args.file.open(encoding="utf-8-sig") as source:
                document = json.load(source)
            validate_catalog(document)
            if args.command == "import":
                database.initialize()
                count = import_catalog(database, document)
                print(f"{count} produtos importados com seus IDs originais; exclusoes aplicadas conforme o catalogo.")
            else:
                count = verify_catalog(database, document, require_aruco=args.require_aruco)
                print(f"OK: {count} produtos conferidos (identificador, UF, atividade e ID ArUco).")
        print(f"Banco: {database.path}")
    except (CatalogError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        parser.exit(1, f"Erro: {exc}\n")


if __name__ == "__main__":
    main()
