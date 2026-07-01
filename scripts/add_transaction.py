#!/usr/bin/env python3
"""
Ingreso de movimientos desde el atajo del iPhone.

Recibe un JSON por STDIN, lo normaliza a los valores que espera la app
(la web usa 'expense'/'income', 'normal', 'pagado', etc.) y lo inserta en la
base de datos, replicando los mismos efectos que el formulario web:

  - Actualiza el saldo de la cuenta (resta gastos, suma ingresos).
  - Suma el gasto al cupo usado de la tarjeta.
  - Si es una compra en cuotas con tarjeta, crea las cuotas futuras.

La ruta de la base de datos se puede configurar con la variable de entorno
FINANCE_DB_PATH; si no, usa la ruta por defecto de la Raspberry.
"""

import os
import sys
import json
import sqlite3
import calendar
from datetime import datetime, date


DB_PATH = os.getenv(
    "FINANCE_DB_PATH",
    "/home/caceresteban/Aplicaciones/motor-financiero/database/finance.db",
)


# ----------------------------------------------------------------------
# Normalización de valores (el atajo/IA manda etiquetas en español)
# ----------------------------------------------------------------------
TYPE_MAP = {
    "gasto": "expense", "expense": "expense",
    "ingreso": "income", "income": "income",
    "transferencia": "transfer", "transfer": "transfer",
}

TXTYPE_MAP = {
    "normal": "normal", "compra normal": "normal",
    "cuotas": "installments", "en cuotas": "installments",
    "compra en cuotas": "installments", "installments": "installments",
    "avance": "cash_advance", "cash_advance": "cash_advance",
    "super avance": "super_advance", "súper avance": "super_advance",
    "super_advance": "super_advance",
    "pago de deuda": "debt_payment", "debt_payment": "debt_payment",
    "comisión/interés": "fee_interest", "comision/interes": "fee_interest",
    "fee_interest": "fee_interest",
    "ajuste manual": "adjustment", "ajuste": "adjustment", "adjustment": "adjustment",
}

STATUS_MAP = {
    "pagado": "pagado", "paid": "pagado",
    "pendiente": "pendiente", "pending": "pendiente",
    "reembolsado": "reembolsado", "anulado": "anulado",
}

# payment_method es texto libre; normalizamos los valores más comunes.
METHOD_MAP = {
    "efectivo": "efectivo", "cash": "efectivo",
    "transferencia": "transferencia", "transfer": "transferencia",
    "debito": "debito", "débito": "debito", "tarjeta débito": "debito",
    "tarjeta debito": "debito",
    "credito": "credito", "crédito": "credito", "tarjeta crédito": "credito",
    "tarjeta credito": "credito",
    "app": "app", "billetera": "app", "app / billetera": "app",
    "otro": "otro",
}


def _norm(value, mapping, default):
    """Normaliza un valor contra un mapa (insensible a mayúsculas/acentos)."""
    if value is None:
        return default
    key = str(value).strip().lower()
    if not key:
        return default
    return mapping.get(key, default)


def parse_money(value, default=0.0):
    """Parsea montos tolerando formato chileno ('$1.234.567', '1.234.567')."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return default
    negative = s.startswith("-")
    s = s.replace("$", "").replace(" ", "")
    s = s.replace(".", "")   # separador de miles en Chile
    s = s.replace(",", ".")  # coma -> decimal, por si acaso
    cleaned = "".join(ch for ch in s if ch.isdigit() or ch == ".")
    if cleaned in ("", ".", "-"):
        return default
    try:
        val = float(cleaned)
    except ValueError:
        return default
    return -val if negative else val


def normalizar_fecha(fecha):
    if not fecha:
        return datetime.now().strftime("%Y-%m-%d")
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(fecha), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return datetime.now().strftime("%Y-%m-%d")


def add_months(d, months):
    """Suma N meses a una fecha ajustando el día al último válido del mes."""
    new_month = d.month - 1 + months
    new_year = d.year + new_month // 12
    new_month = new_month % 12 + 1
    last_day = calendar.monthrange(new_year, new_month)[1]
    return date(new_year, new_month, min(d.day, last_day))


def existe(cur, tabla, id_valor):
    if id_valor is None:
        return True
    cur.execute(f"SELECT 1 FROM {tabla} WHERE id = ? LIMIT 1", (id_valor,))
    return cur.fetchone() is not None


def _column_names(cur, tabla):
    cur.execute(f"PRAGMA table_info({tabla})")
    return [r[1] for r in cur.fetchall()]


def crear_cuotas(cur, card_id, transaction_id, total_amount, total_inst, start_iso):
    """Crea las cuotas futuras de una compra en cuotas y actualiza el resumen
    de la tarjeta (replica modules/cards.py::create_installments)."""
    if total_inst < 1:
        return
    amount_per = round(total_amount / total_inst)
    start = datetime.strptime(start_iso, "%Y-%m-%d").date()

    # Día de facturación de la tarjeta (para estimar la fecha de cada cuota)
    cur.execute("SELECT billing_day FROM credit_cards WHERE id = ?", (card_id,))
    row = cur.fetchone()
    billing_day = row[0] if row else None

    for i in range(1, total_inst + 1):
        est = add_months(start, i)
        if billing_day:
            try:
                est = est.replace(day=min(int(billing_day), 28))
            except ValueError:
                pass
        cur.execute(
            """INSERT INTO card_installments
               (card_id, transaction_id, installment_number, total_installments,
                amount, estimated_date, status)
               VALUES (?, ?, ?, ?, ?, ?, 'pendiente')""",
            (card_id, transaction_id, i, total_inst, amount_per, est.isoformat()),
        )

    cur.execute(
        """SELECT COUNT(*), COALESCE(SUM(amount), 0)
           FROM card_installments WHERE card_id = ? AND status != 'pagada'""",
        (card_id,),
    )
    count, total = cur.fetchone()
    cur.execute(
        "UPDATE credit_cards SET future_installments_amount = ?, pending_installments = ? WHERE id = ?",
        (total or 0, count or 0, card_id),
    )


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({
            "success": False,
            "error": "No llegó ningún JSON por STDIN"
        }, ensure_ascii=False))
        return

    try:
        data = json.loads(raw)

        fecha = normalizar_fecha(data.get("Fecha"))
        monto = parse_money(data.get("Monto", 0))
        tipo = _norm(data.get("Tipo"), TYPE_MAP, "expense")
        transaction_type = _norm(data.get("transaction_type"), TXTYPE_MAP, "normal")
        estado = _norm(data.get("Estado"), STATUS_MAP, "pagado")

        descripcion = (data.get("Descripción") or data.get("Descripcion") or "") or None
        category_id = data.get("category_id")
        account_id = data.get("account_id")
        card_id = data.get("card_id")
        person_id = data.get("person_id")
        proyecto = (data.get("Proyecto") or "") or None
        tags = (data.get("ProyectoTags") or data.get("Tags") or "") or None
        notas = (data.get("Notas") or "") or None

        try:
            installments_total = int(data.get("installments_total", 1) or 1)
        except (TypeError, ValueError):
            installments_total = 1
        installments_total = max(1, installments_total)

        is_shared = int(data.get("is_shared", 0) or 0)
        my_share = parse_money(data.get("my_share", monto))

        if monto <= 0:
            raise Exception("El monto debe ser mayor a 0")

        # Método de pago derivado del destino (igual que la web)
        if card_id:
            payment_method = "credito"
        elif account_id:
            payment_method = _norm(data.get("MetodoPago"), METHOD_MAP, "debito")
        else:
            payment_method = _norm(data.get("MetodoPago"), METHOD_MAP, None)

        # Si paga con tarjeta y son 2+ cuotas, es una compra en cuotas
        if card_id and installments_total > 1:
            transaction_type = "installments"

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        if not existe(cur, "categories", category_id):
            raise Exception(f"category_id {category_id} no existe")
        if not existe(cur, "accounts", account_id):
            raise Exception(f"account_id {account_id} no existe")
        if not existe(cur, "credit_cards", card_id):
            raise Exception(f"card_id {card_id} no existe")
        if not existe(cur, "people", person_id):
            raise Exception(f"person_id {person_id} no existe")

        cols = _column_names(cur, "transactions")
        has_shared = "is_shared" in cols and "my_share" in cols

        base_cols = [
            "date", "amount", "type", "transaction_type", "category_id",
            "description", "account_id", "card_id", "payment_method", "person_id",
            "project", "tags", "status", "origin", "installments_total", "notes",
            "created_at", "updated_at",
        ]
        base_vals = [
            fecha, monto, tipo, transaction_type, category_id,
            descripcion, account_id, card_id, payment_method, person_id,
            proyecto, tags, estado, "iphone",
            installments_total if transaction_type == "installments" else None,
            notas,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ]
        if has_shared:
            base_cols += ["is_shared", "my_share"]
            base_vals += [is_shared, my_share]

        placeholders = ", ".join(["?"] * len(base_cols))
        cur.execute(
            f"INSERT INTO transactions ({', '.join(base_cols)}) VALUES ({placeholders})",
            base_vals,
        )
        transaction_id = cur.lastrowid

        # Efecto en el saldo de la cuenta (solo si está pagado)
        if account_id and estado == "pagado":
            multiplier = -1 if tipo == "expense" else 1
            cur.execute(
                "UPDATE accounts SET balance = balance + ? WHERE id = ?",
                (monto * multiplier, account_id),
            )

        # Efecto en el cupo usado de la tarjeta (gastos)
        if card_id and tipo == "expense":
            cur.execute(
                "UPDATE credit_cards SET used_amount = used_amount + ? WHERE id = ?",
                (monto, card_id),
            )

        # Compra en cuotas con tarjeta -> crear cuotas futuras
        if transaction_type == "installments" and card_id and installments_total > 1:
            crear_cuotas(cur, card_id, transaction_id, monto,
                         installments_total, fecha)

        conn.commit()
        conn.close()

        print(json.dumps({
            "success": True,
            "id": transaction_id,
            "type": tipo,
            "message": f"✅ {descripcion or 'Movimiento'} (${monto:,.0f}) registrado correctamente"
        }, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
