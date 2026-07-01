#!/usr/bin/env python3
import sqlite3
import json

DB_PATH = "/home/caceresteban/Aplicaciones/motor-financiero/database/finance.db"

def fetch_all(cur, query):
    cur.execute(query)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

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

print(json.dumps(data, ensure_ascii=False))


