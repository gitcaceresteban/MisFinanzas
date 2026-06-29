"""Calendario financiero unificado: muestra todos los eventos por mes."""
import calendar
from datetime import date
from flask import Blueprint, render_template, request
from database import db
from modules.helpers import safe_int, month_name_es

bp = Blueprint("calendar", __name__)


@bp.route("/")
def index():
    today = date.today()
    year = safe_int(request.args.get("year")) or today.year
    month = safe_int(request.args.get("month")) or today.month

    # Asegurar mes válido
    if month < 1:
        month = 12
        year -= 1
    if month > 12:
        month = 1
        year += 1

    ym_str = f"{year}-{month:02d}"
    last_day = calendar.monthrange(year, month)[1]

    # Construir matriz del mes (semanas)
    cal = calendar.Calendar(firstweekday=0)  # 0 = lunes
    month_matrix = list(cal.monthdayscalendar(year, month))

    # Eventos por día
    events_by_day = {d: [] for d in range(1, last_day + 1)}

    # 1) Tarjetas con día de pago
    cards = db.query("""
        SELECT c.id, c.name, c.payment_day, c.billed_amount, c.has_billed_debt,
               b.color AS color
        FROM credit_cards c
        LEFT JOIN banks b ON b.id = c.bank_id
        WHERE c.status='activa' AND c.payment_day IS NOT NULL
    """)
    for c in cards:
        d = c["payment_day"]
        if d and 1 <= d <= last_day:
            events_by_day[d].append({
                "kind": "card_payment",
                "icon": "credit-card",
                "color": c["color"] or "#ef4444",
                "title": f"Pago {c['name']}",
                "amount": c["billed_amount"] if c["has_billed_debt"] else 0,
                "url": f"/tarjetas/{c['id']}",
            })

    # 2) Cuotas estimadas de tarjetas
    card_inst = db.query("""
        SELECT ci.*, c.name AS card_name, b.color AS color
        FROM card_installments ci
        JOIN credit_cards c ON c.id = ci.card_id
        LEFT JOIN banks b ON b.id = c.bank_id
        WHERE ci.status != 'pagada'
              AND strftime('%Y-%m', ci.estimated_date) = ?
    """, (ym_str,))
    for ci in card_inst:
        try:
            d = int(ci["estimated_date"][8:10])
            events_by_day[d].append({
                "kind": "card_installment",
                "icon": "layers",
                "color": ci["color"] or "#06b6d4",
                "title": f"Cuota {ci['card_name']}",
                "amount": ci["amount"],
                "url": f"/tarjetas/{ci['card_id']}",
            })
        except (ValueError, IndexError):
            pass

    # 3) Cuotas de créditos
    loan_inst = db.query("""
        SELECT li.*, l.name AS loan_name, b.color AS color
        FROM loan_installments li
        JOIN loans l ON l.id = li.loan_id
        LEFT JOIN banks b ON b.id = l.bank_id
        WHERE li.status = 'pendiente'
              AND strftime('%Y-%m', li.due_date) = ?
    """, (ym_str,))
    for li in loan_inst:
        try:
            d = int(li["due_date"][8:10])
            events_by_day[d].append({
                "kind": "loan_installment",
                "icon": "trending-down",
                "color": li["color"] or "#8b5cf6",
                "title": f"Cuota {li['loan_name']}",
                "amount": li["amount"],
                "url": f"/creditos/{li['loan_id']}",
            })
        except (ValueError, IndexError):
            pass

    # 4) Recurrentes mensuales
    recurring = db.query("""
        SELECT r.*, c.color AS cat_color
        FROM recurring_payments r
        LEFT JOIN categories c ON c.id = r.category_id
        WHERE r.active = 1 AND r.frequency = 'monthly'
              AND r.day_of_month IS NOT NULL
    """)
    for r in recurring:
        d = r["day_of_month"]
        if d and 1 <= d <= last_day:
            events_by_day[d].append({
                "kind": "recurring",
                "icon": "repeat",
                "color": r["cat_color"] or "#f97316",
                "title": r["name"],
                "amount": r["amount"],
                "url": "/recurrentes/",
            })

    # 5) Cuentas del hogar
    bills = db.query("""
        SELECT * FROM household_bills
        WHERE due_date IS NOT NULL
              AND strftime('%Y-%m', due_date) = ?
              AND status IN ('pendiente', 'parcial', 'vencida')
    """, (ym_str,))
    for b_ in bills:
        try:
            d = int(b_["due_date"][8:10])
            events_by_day[d].append({
                "kind": "household_bill",
                "icon": "home",
                "color": "#84cc16",
                "title": b_["name"],
                "amount": b_["amount"],
                "url": "/hogar/",
            })
        except (ValueError, IndexError):
            pass

    # 6) Deudas con personas (esperadas)
    debts = db.query("""
        SELECT pd.*, p.name AS person_name
        FROM person_debts pd
        JOIN people p ON p.id = pd.person_id
        WHERE pd.expected_date IS NOT NULL
              AND strftime('%Y-%m', pd.expected_date) = ?
              AND pd.status IN ('pendiente', 'parcial')
    """, (ym_str,))
    for pd in debts:
        try:
            d = int(pd["expected_date"][8:10])
            events_by_day[d].append({
                "kind": "person_debt",
                "icon": "users",
                "color": "#ec4899",
                "title": f"{pd['person_name']}",
                "amount": pd["pending_amount"],
                "url": "/personas/",
            })
        except (ValueError, IndexError):
            pass

    # Total del mes
    total_events = sum(len(evs) for evs in events_by_day.values())
    total_amount = sum(
        sum((e["amount"] or 0) for e in evs)
        for evs in events_by_day.values()
    )

    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12
    next_year = year if month < 12 else year + 1
    next_month = month + 1 if month < 12 else 1

    return render_template("calendar.html",
                          year=year, month=month,
                          month_name=month_name_es(month),
                          month_matrix=month_matrix,
                          events_by_day=events_by_day,
                          today=today,
                          total_events=total_events,
                          total_amount=total_amount,
                          prev_year=prev_year, prev_month=prev_month,
                          next_year=next_year, next_month=next_month)
