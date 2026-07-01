"""
Helpers de conexión y operaciones sobre SQLite.
Diseñado para ser fácilmente reemplazado por PostgreSQL en el futuro.
"""
import sqlite3
import json
from pathlib import Path
from typing import Any, Iterable, Optional
from flask import g, current_app


def get_db() -> sqlite3.Connection:
    """Obtiene la conexión SQLite asociada al request actual."""
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE_PATH"],
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None,  # autocommit modo
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db


def close_db(e=None) -> None:
    """Cierra la conexión al finalizar el request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app) -> None:
    """Crea las tablas si no existen."""
    schema_path = Path(__file__).parent / "schema.sql"
    db_path = Path(app.config["DATABASE_PATH"])
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(app.config["DATABASE_PATH"]) as conn:
        conn.row_factory = sqlite3.Row
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()


# Columnas añadidas después de la versión inicial del esquema.
# Como schema.sql usa CREATE TABLE IF NOT EXISTS, no altera tablas ya creadas;
# esta migración añade columnas que falten de forma idempotente y segura.
MIGRATIONS = [
    # (tabla, columna, definición)
    # Categorías: distinguir si aplican a gastos o ingresos ('expense'/'income')
    ("categories", "kind", "TEXT NOT NULL DEFAULT 'expense'"),
    ("banks", "logo_path", "TEXT"),
    ("credit_cards", "logo_path", "TEXT"),
    ("loans", "payment_day", "INTEGER"),
    ("loans", "card_id", "INTEGER"),
    ("loans", "billed_in_card", "INTEGER NOT NULL DEFAULT 0"),
    ("recurring_payments", "logo_path", "TEXT"),
    ("recurring_payments", "is_reimbursable", "INTEGER NOT NULL DEFAULT 0"),
    ("recurring_payments", "last_paid_month", "TEXT"),
    ("recurring_payments", "group_name", "TEXT"),
    ("transactions", "is_shared", "INTEGER NOT NULL DEFAULT 0"),
    ("transactions", "my_share", "REAL"),
    # Enlaza una transacción con el pago recurrente que la originó (para poder
    # saber qué recurrente se pagó este mes y revertirlo si se cancela).
    ("transactions", "recurring_id", "INTEGER"),
    ("person_debts", "paid_to_account_id", "INTEGER"),
    ("household_bills", "is_recurring", "INTEGER NOT NULL DEFAULT 0"),
    ("household_bills", "recurring_day", "INTEGER"),
    # Cuentas del hogar: logo, compras en cuotas (N cargos mensuales) y abonos
    ("household_bills", "logo_path", "TEXT"),
    ("household_bills", "installments_total", "INTEGER NOT NULL DEFAULT 1"),
    ("household_bills", "installment_number", "INTEGER NOT NULL DEFAULT 1"),
    ("household_bills", "series_id", "TEXT"),
    ("household_bills", "collected_amount", "REAL NOT NULL DEFAULT 0"),
]


def run_migrations(app) -> None:
    """Aplica migraciones de columnas faltantes (idempotente)."""
    import sqlite3
    with sqlite3.connect(app.config["DATABASE_PATH"]) as conn:
        conn.row_factory = sqlite3.Row
        for table, column, ddl in MIGRATIONS:
            try:
                cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
            except sqlite3.OperationalError:
                continue  # la tabla aún no existe
            if column not in cols:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                except sqlite3.OperationalError:
                    pass
        conn.commit()


def query(sql: str, params: Iterable = (), one: bool = False):
    """Ejecuta SELECT y devuelve filas como dicts."""
    db = get_db()
    cur = db.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    if one:
        return dict(rows[0]) if rows else None
    return [dict(r) for r in rows]


def execute(sql: str, params: Iterable = ()) -> int:
    """Ejecuta INSERT/UPDATE/DELETE y devuelve lastrowid o rowcount."""
    db = get_db()
    cur = db.execute(sql, params)
    last_id = cur.lastrowid
    rowcount = cur.rowcount
    cur.close()
    return last_id if last_id else rowcount


def execute_many(sql: str, params_list: list) -> None:
    db = get_db()
    db.executemany(sql, params_list)


def insert(table: str, data: dict) -> int:
    """Insert helper que devuelve el id nuevo."""
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
    return execute(sql, tuple(data.values()))


def update(table: str, data: dict, where: str, where_params: tuple) -> int:
    """Update helper."""
    set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
    sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
    params = tuple(data.values()) + where_params
    return execute(sql, params)


def delete(table: str, where: str, where_params: tuple) -> int:
    sql = f"DELETE FROM {table} WHERE {where}"
    return execute(sql, where_params)


def audit(action: str, entity_type: str, entity_id: Optional[int] = None,
          changes: Optional[dict] = None, source: str = "web") -> None:
    """Registra una entrada en audit_log."""
    try:
        insert("audit_log", {
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "changes_json": json.dumps(changes, ensure_ascii=False, default=str) if changes else None,
            "source": source,
        })
    except Exception:
        # No interrumpir el flujo principal por un fallo de auditoría
        pass


def register(app) -> None:
    """Registra los hooks de teardown."""
    app.teardown_appcontext(close_db)
