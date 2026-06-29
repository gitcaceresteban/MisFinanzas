"""Flujo de caja proyectado: saldo + ingresos - gastos por día/mes."""
from datetime import date, timedelta
from flask import Blueprint, render_template, request
from database import db
from modules.helpers import safe_int

bp = Blueprint("cashflow", __name__)


@bp.route("/")
def index():
    today = date.today()
    days = safe_int(request.args.get("days")) or 60
    if days > 365:
        days = 365
    if days < 7:
        days = 7

    end_date = today + timedelta(days=days)

    # Saldo inicial: suma de todas las cuentas activas
    accounts_sum = db.query("""
        SELECT COALESCE(SUM(balance), 0) AS total
        FROM accounts WHERE status='activa'
    """, one=True)
    initial_balance = accounts_sum["total"] or 0

    # Inicializar el día actual
    days_data = {}
    cursor = today
    while cursor <= end_date:
        days_data[cursor.isoformat()] = {
            "date": cursor.isoformat(),
            "inflows": 0,
            "outflows": 0,
            "events": [],
        }
        cursor += timedelta(days=1)

    # ---- Egresos proyectados ----

    # 1) Tarjetas con facturado
    cards = db.query("""
        SELECT id, name, payment_day, billed_amount, has_billed_debt
        FROM credit_cards
        WHERE status='activa' AND has_billed_debt=1
              AND payment_day IS NOT NULL
              AND billed_amount > 0
    """)
    for c in cards:
        d_iso = _next_day_with(c["payment_day"], today, end_date)
        if d_iso and d_iso in days_data:
            days_data[d_iso]["outflows"] += c["billed_amount"]
            days_data[d_iso]["events"].append({
                "kind": "card",
                "title": f"Pago tarjeta {c['name']}",
                "amount": -c["billed_amount"],
            })

    # 2) Cuotas de tarjetas estimadas
    inst_card = db.query("""
        SELECT ci.estimated_date, ci.amount, c.name AS card_name
        FROM card_installments ci
        JOIN credit_cards c ON c.id = ci.card_id
        WHERE ci.status != 'pagada'
              AND ci.estimated_date BETWEEN ? AND ?
    """, (today.isoformat(), end_date.isoformat()))
    for ci in inst_card:
        d_iso = ci["estimated_date"]
        if d_iso in days_data:
            days_data[d_iso]["outflows"] += ci["amount"]
            days_data[d_iso]["events"].append({
                "kind": "card_inst",
                "title": f"Cuota {ci['card_name']}",
                "amount": -ci["amount"],
            })

    # 3) Cuotas de créditos
    loan_inst = db.query("""
        SELECT li.due_date, li.amount, l.name AS loan_name
        FROM loan_installments li
        JOIN loans l ON l.id = li.loan_id
        WHERE li.status = 'pendiente'
              AND li.due_date BETWEEN ? AND ?
    """, (today.isoformat(), end_date.isoformat()))
    for li in loan_inst:
        d_iso = li["due_date"]
        if d_iso in days_data:
            days_data[d_iso]["outflows"] += li["amount"]
            days_data[d_iso]["events"].append({
                "kind": "loan",
                "title": f"Cuota {li['loan_name']}",
                "amount": -li["amount"],
            })

    # 4) Recurrentes mensuales activos
    recurring = db.query("""
        SELECT r.*, c.name AS cat_name
        FROM recurring_payments r
        LEFT JOIN categories c ON c.id = r.category_id
        WHERE r.active = 1
              AND r.frequency = 'monthly'
              AND r.day_of_month IS NOT NULL
    """)
    for r in recurring:
        # Iterar mes a mes dentro del rango
        cursor = date(today.year, today.month, 1)
        while cursor <= end_date:
            try:
                event_date = date(cursor.year, cursor.month,
                                  min(r["day_of_month"], 28))
            except ValueError:
                cursor = _add_one_month(cursor)
                continue
            if today <= event_date <= end_date:
                d_iso = event_date.isoformat()
                if d_iso in days_data:
                    days_data[d_iso]["outflows"] += r["amount"]
                    days_data[d_iso]["events"].append({
                        "kind": "recurring",
                        "title": r["name"],
                        "amount": -r["amount"],
                    })
            cursor = _add_one_month(cursor)

    # 5) Cuentas del hogar con fecha de vencimiento
    bills = db.query("""
        SELECT name, amount, due_date FROM household_bills
        WHERE status IN ('pendiente','parcial','vencida')
              AND due_date BETWEEN ? AND ?
    """, (today.isoformat(), end_date.isoformat()))
    for b_ in bills:
        d_iso = b_["due_date"]
        if d_iso in days_data:
            days_data[d_iso]["outflows"] += b_["amount"]
            days_data[d_iso]["events"].append({
                "kind": "household",
                "title": b_["name"],
                "amount": -b_["amount"],
            })

    # 6) Deudas por cobrar (entradas esperadas)
    receivable = db.query("""
        SELECT pd.expected_date, pd.pending_amount, p.name AS person_name
        FROM person_debts pd
        JOIN people p ON p.id = pd.person_id
        WHERE pd.status IN ('pendiente','parcial')
              AND pd.direction = 'they_owe_me'
              AND pd.expected_date BETWEEN ? AND ?
    """, (today.isoformat(), end_date.isoformat()))
    for pd in receivable:
        d_iso = pd["expected_date"]
        if d_iso in days_data:
            days_data[d_iso]["inflows"] += pd["pending_amount"]
            days_data[d_iso]["events"].append({
                "kind": "person_inflow",
                "title": f"{pd['person_name']} (esperado)",
                "amount": pd["pending_amount"],
            })

    # 7) Estimar ingresos recurrentes (basado en histórico)
    # Promedio de ingresos mensuales últimos 3 meses
    avg_income = db.query("""
        SELECT AVG(monthly_total) AS avg_total FROM (
            SELECT strftime('%Y-%m', date) AS m, SUM(amount) AS monthly_total
            FROM transactions
            WHERE type='income' AND status='pagado'
                  AND date >= date('now', '-3 months')
            GROUP BY m
        )
    """, one=True)
    avg_per_month = (avg_income["avg_total"] or 0) if avg_income else 0
    # Proyectar el ingreso promedio al primer día de cada mes futuro
    if avg_per_month > 0:
        cursor = date(today.year, today.month, 1)
        cursor = _add_one_month(cursor)  # comenzar el próximo mes
        while cursor <= end_date:
            d_iso = cursor.isoformat()
            if d_iso in days_data:
                days_data[d_iso]["inflows"] += avg_per_month
                days_data[d_iso]["events"].append({
                    "kind": "income_estimate",
                    "title": "Ingreso estimado (promedio)",
                    "amount": avg_per_month,
                })
            cursor = _add_one_month(cursor)

    # Calcular saldo acumulado
    flow = []
    running = initial_balance
    for d_iso in sorted(days_data.keys()):
        day = days_data[d_iso]
        net = day["inflows"] - day["outflows"]
        running += net
        flow.append({
            "date": d_iso,
            "inflows": day["inflows"],
            "outflows": day["outflows"],
            "net": net,
            "balance": running,
            "events": day["events"],
        })

    min_balance = min((f["balance"] for f in flow), default=initial_balance)
    final_balance = flow[-1]["balance"] if flow else initial_balance

    return render_template("cashflow.html",
                          flow=flow,
                          initial_balance=initial_balance,
                          final_balance=final_balance,
                          min_balance=min_balance,
                          days=days)


def _next_day_with(day_of_month: int, start: date, end: date):
    """Devuelve el próximo día N que esté entre start y end."""
    if not day_of_month:
        return None
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        try:
            candidate = date(cursor.year, cursor.month, min(day_of_month, 28))
            if start <= candidate <= end:
                return candidate.isoformat()
        except ValueError:
            pass
        cursor = _add_one_month(cursor)
    return None


def _add_one_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)
