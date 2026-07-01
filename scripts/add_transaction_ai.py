#!/usr/bin/env python3

import os
import sys
import json
import sqlite3
import subprocess
from datetime import datetime
from openai import OpenAI

BASE_DIR = "/home/caceresteban/Aplicaciones/motor-financiero"
DB_PATH = f"{BASE_DIR}/database/finance.db"
ADD_SCRIPT = f"{BASE_DIR}/scripts/add_transaction.py"

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def get_api_key():
    key = os.getenv("OPENAI_API_KEY")
    if key:
        return key.strip()

    key_path = os.path.expanduser("~/.openai_api_key")
    if os.path.exists(key_path):
        with open(key_path, "r", encoding="utf-8") as f:
            return f.read().strip()

    raise RuntimeError("No encontré OPENAI_API_KEY ni ~/.openai_api_key")


def fetch_all(cur, query):
    cur.execute(query)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_options():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    data = {
        "categories": fetch_all(cur, """
            SELECT id, name
            FROM categories
            WHERE active = 1
            ORDER BY name
        """),
        "accounts": fetch_all(cur, """
            SELECT id, name, type, status
            FROM accounts
            WHERE status = 'activa'
            ORDER BY name
        """),
        "credit_cards": fetch_all(cur, """
            SELECT id, name, status
            FROM credit_cards
            WHERE status = 'activa'
            ORDER BY name
        """),
        "people": fetch_all(cur, """
            SELECT id, name, alias
            FROM people
            WHERE active = 1
            ORDER BY name
        """)
    }

    conn.close()
    return data


def build_prompt(texto_gasto, opciones):
    hoy = datetime.now().strftime("%d-%m-%Y")

    return f"""
A partir del siguiente texto de gasto y del JSON de opciones actuales de mi base de datos, extrae y estandariza la información para crear un movimiento financiero.

Debes responder SOLO con un JSON válido, sin markdown, sin explicación y sin texto adicional.

FECHA DE HOY:
{hoy}

TEXTO DEL GASTO:
{texto_gasto}

OPCIONES ACTUALES DE LA BASE DE DATOS:
{json.dumps(opciones, ensure_ascii=False)}

Formato obligatorio:
{{
  "Fecha": "DD-MM-YYYY",
  "Monto": 0,
  "Tipo": "",
  "Descripción": "",
  "category_id": null,
  "account_id": null,
  "card_id": null,
  "MetodoPago": "",
  "person_id": null,
  "Estado": "",
  "Proyecto": "",
  "ProyectoTags": "",
  "Notas": "",
  "transaction_type": "",
  "installments_total": 1,
  "is_shared": 0,
  "my_share": 0
}}

Reglas:
- Fecha: usar la fecha de hoy si no se indica otra.
- Monto: entero en CLP, sin puntos ni símbolo $.
- Tipo: solo "Gasto", "Ingreso" o "Transferencia". Por defecto "Gasto".
- Descripción: breve y clara.
- category_id: elegir solo un ID existente en categories.
- Si no hay categoría clara, usar la categoría "Otros".
- account_id: usar solo si paga con cuenta corriente, débito, efectivo o transferencia desde cuenta.
- card_id: usar solo si paga con tarjeta de crédito.
- Si usa tarjeta de crédito, account_id debe ser null.
- Si usa cuenta, débito o efectivo, card_id debe ser null.
- person_id: usar solo si hay división, deuda o pago relacionado con una persona.
- Estado: por defecto "Pagado".
- Proyecto y ProyectoTags: dejar "" si no se identifican.
- transaction_type: por defecto "Normal".
- installments_total: si menciona cuotas, usar ese número; si no, 1.
- is_shared: 1 si hay división con otra persona; si no, 0.
- my_share: si no se divide, igual al Monto. Si se divide en partes iguales entre 2, usar la mitad.
- No inventes IDs.
"""


def call_openai(prompt):
    client = OpenAI(api_key=get_api_key())

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "Eres un extractor financiero. Respondes únicamente JSON válido."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        response_format={"type": "json_object"},
        temperature=0
    )

    content = response.choices[0].message.content
    return json.loads(content)


def insert_transaction(data):
    json_text = json.dumps(data, ensure_ascii=False)

    result = subprocess.run(
        ["python3", ADD_SCRIPT],
        input=json_text,
        text=True,
        capture_output=True
    )

    if result.stdout.strip():
        return json.loads(result.stdout.strip())

    return {
        "success": False,
        "error": result.stderr.strip() or "add_transaction.py no devolvió respuesta"
    }


def main():
    texto_gasto = sys.stdin.read().strip()

    if not texto_gasto:
        print(json.dumps({
            "success": False,
            "error": "No llegó texto del gasto por STDIN"
        }, ensure_ascii=False))
        return

    try:
        opciones = get_options()
        prompt = build_prompt(texto_gasto, opciones)
        data = call_openai(prompt)
        result = insert_transaction(data)

        if result.get("success"):
            result["ai_json"] = data

        print(json.dumps(result, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
