#!/usr/bin/env python3

import sys
import json
import sqlite3
from datetime import datetime

DB_PATH = "/home/caceresteban/Aplicaciones/motor-financiero/database/finance.db"


def normalizar_fecha(fecha):
    if not fecha:
        return datetime.now().strftime("%Y-%m-%d")

    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(fecha, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return datetime.now().strftime("%Y-%m-%d")


def existe(cur, tabla, id_valor):
    if id_valor is None:
        return True

    cur.execute(f"SELECT 1 FROM {tabla} WHERE id = ? LIMIT 1", (id_valor,))
    return cur.fetchone() is not None


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
        monto = float(data.get("Monto", 0))
        tipo = data.get("Tipo", "Gasto")
        descripcion = data.get("Descripción", "")
        category_id = data.get("category_id")
        account_id = data.get("account_id")
        card_id = data.get("card_id")
        metodo_pago = data.get("MetodoPago", "")
        person_id = data.get("person_id")
        estado = data.get("Estado", "Pagado")
        proyecto = data.get("Proyecto", "")
        tags = data.get("ProyectoTags", "")
        notas = data.get("Notas", "")
        transaction_type = data.get("transaction_type", "Normal")
        installments_total = int(data.get("installments_total", 1))
        is_shared = int(data.get("is_shared", 0))
        my_share = float(data.get("my_share", monto))

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

        cur.execute("""
            INSERT INTO transactions (
                date,
                amount,
                type,
                transaction_type,
                category_id,
                description,
                account_id,
                card_id,
                payment_method,
                person_id,
                project,
                tags,
                status,
                origin,
                installments_total,
                notes,
                created_at,
                updated_at,
                is_shared,
                my_share
            )
            VALUES (
                ?,?,?,?,?,?,
                ?,?,?,?,?,?,
                ?,?,?,?,
                datetime('now'),
                datetime('now'),
                ?,?
            )
        """, (
            fecha,
            monto,
            tipo,
            transaction_type,
            category_id,
            descripcion,
            account_id,
            card_id,
            metodo_pago,
            person_id,
            proyecto,
            tags,
            estado,
            "Atajo iPhone",
            installments_total,
            notas,
            is_shared,
            my_share
        ))

        conn.commit()

        transaction_id = cur.lastrowid

        conn.close()

        print(json.dumps({
            "success": True,
            "id": transaction_id,
            "message": f"✅ {descripcion} (${monto:,.0f}) registrado correctamente"
        }, ensure_ascii=False))

    except Exception as e:

        print(json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
