"""
PLANTILLA de datos personales.

Cómo usar:
  1. Copia este archivo a `database/seed_personal.py`
        cp database/seed_personal.example.py database/seed_personal.py
  2. Edita las listas con tus créditos, recurrentes, etc.
  3. Inicia la app: se cargan una sola vez (flag settings.personal_seeded).

`seed_personal.py` está en .gitignore, así que tus montos reales NO se suben
a GitHub. Este `.example.py` sí se versiona, pero solo con datos de ejemplo.
"""
from datetime import date
from modules.helpers import add_months, parse_date_cl


def _bank_id(conn, name):
    row = conn.execute("SELECT id FROM banks WHERE name=?", (name,)).fetchone()
    return row["id"] if row else None


def _person_id(conn, name):
    row = conn.execute("SELECT id FROM people WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    return conn.execute("INSERT INTO people (name) VALUES (?)", (name,)).lastrowid


def _gen_installments(conn, loan_id, total, paid, amount, first_date, pay_day):
    start = parse_date_cl(first_date) or date.today()
    nxt = None
    for i in range(1, total + 1):
        due = add_months(start, i - 1)
        if pay_day:
            try:
                due = due.replace(day=min(int(pay_day), 28))
            except (ValueError, TypeError):
                pass
        is_paid = i <= paid
        if not is_paid and nxt is None:
            nxt = due.isoformat()
        conn.execute(
            """INSERT INTO loan_installments
               (loan_id, installment_number, amount, due_date, status, paid_amount, paid_date)
               VALUES (?,?,?,?,?,?,?)""",
            (loan_id, i, amount, due.isoformat(),
             "pagada" if is_paid else "pendiente",
             amount if is_paid else 0, due.isoformat() if is_paid else None))
    return nxt


# (name, type, bank, original, cuota, total, paid, first_payment, pay_day, billed_in_card, note)
LOANS = [
    ("Crédito de ejemplo", "consumo", "Banco Falabella", 1000000, 100000, 10, 2, "2026-01-15", 15, False, "Ejemplo"),
]

# (name, amount, fixed)
RECURRING_MINE = [
    ("Suscripción ejemplo", 9990, 1),
]


def load(conn):
    seeded = conn.execute("SELECT value FROM settings WHERE key='personal_seeded'").fetchone()
    if seeded and seeded["value"] == "1":
        return

    for (name, ltype, bank, original, cuota, total, paid, first, payday, billed, note) in LOANS:
        bid = _bank_id(conn, bank)
        pending_inst = max(0, total - paid)
        cur = conn.execute(
            """INSERT INTO loans
               (name, bank_id, billed_in_card, type, original_amount, pending_amount,
                total_installments, paid_installments, pending_installments,
                installment_amount, first_payment_date, payment_day, status, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, bid, 1 if billed else 0, ltype, original, cuota * pending_inst,
             total, paid, pending_inst, cuota, first, payday, "vigente", note))
        nxt = _gen_installments(conn, cur.lastrowid, total, paid, cuota, first, payday)
        conn.execute("UPDATE loans SET next_payment_date=? WHERE id=?", (nxt, cur.lastrowid))

    for (name, amount, fixed) in RECURRING_MINE:
        conn.execute(
            """INSERT INTO recurring_payments (name, amount, amount_is_fixed, frequency, active)
               VALUES (?,?,?,?,1)""", (name, amount, fixed, "monthly"))

    for k, v in (("monthly_income", "0"), ("personal_seeded", "1")):
        if conn.execute("SELECT key FROM settings WHERE key=?", (k,)).fetchone():
            conn.execute("UPDATE settings SET value=? WHERE key=?", (v, k))
        else:
            conn.execute("INSERT INTO settings (key, value) VALUES (?,?)", (k, v))
