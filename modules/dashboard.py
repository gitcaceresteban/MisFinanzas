"""Dashboard principal: vista resumen de todo."""
from datetime import date, datetime
from flask import Blueprint, render_template, request
from database import db
from modules.helpers import safe_int, add_months, month_name_es
from modules.planning import compute_commitments, get_monthly_income

bp = Blueprint("dashboard", __name__)


def compute_debt_trend(months_fwd=12):
    """Endeudamiento total (tarjetas + créditos), tendencia y proyección.

    - Guarda un snapshot mensual del total para construir el histórico real.
    - Proyecta cómo debería ir bajando según el calendario de cuotas
      (cuotas de créditos + cuotas de tarjetas), sin asumir nuevas compras.
    """
    today = date.today()
    ym = f"{today.year}-{today.month:02d}"

    cards_debt = db.query("""
        SELECT COALESCE(SUM(used_amount),0) AS t FROM credit_cards WHERE status='activa'
    """, one=True)["t"] or 0
    loans_debt = db.query("""
        SELECT COALESCE(SUM(pending_amount),0) AS t FROM loans WHERE status='vigente'
    """, one=True)["t"] or 0
    total = cards_debt + loans_debt

    # Snapshot del mes en curso (upsert)
    existing = db.query("SELECT id FROM debt_snapshots WHERE ym=?", (ym,), one=True)
    if existing:
        db.update("debt_snapshots", {
            "cards_debt": cards_debt, "loans_debt": loans_debt, "total_debt": total,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }, "id = ?", (existing["id"],))
    else:
        db.insert("debt_snapshots", {
            "ym": ym, "cards_debt": cards_debt,
            "loans_debt": loans_debt, "total_debt": total,
        })

    # Histórico real (snapshots hasta el mes actual)
    snaps = db.query("""
        SELECT ym, total_debt FROM debt_snapshots
        WHERE ym <= ? ORDER BY ym ASC LIMIT 12
    """, (ym,))

    # Reducción mensual programada (cuotas pendientes por mes futuro)
    reduce_by_month = {}
    for r in db.query("""
        SELECT strftime('%Y-%m', due_date) AS m, COALESCE(SUM(amount),0) AS t
        FROM loan_installments WHERE status != 'pagada' GROUP BY m
    """):
        if r["m"]:
            reduce_by_month[r["m"]] = reduce_by_month.get(r["m"], 0) + (r["t"] or 0)
    for r in db.query("""
        SELECT strftime('%Y-%m', estimated_date) AS m, COALESCE(SUM(amount),0) AS t
        FROM card_installments WHERE status != 'pagada' GROUP BY m
    """):
        if r["m"]:
            reduce_by_month[r["m"]] = reduce_by_month.get(r["m"], 0) + (r["t"] or 0)

    # Serie para el gráfico: histórico real + proyección
    labels, real, projected = [], [], []
    for s in snaps:
        labels.append(s["ym"])
        real.append(round(s["total_debt"]))
        projected.append(None)
    # punto de unión: el mes actual también es el inicio de la proyección
    if projected:
        projected[-1] = round(total)

    running = total
    start = date(today.year, today.month, 1)
    for i in range(1, months_fwd + 1):
        d = add_months(start, i)
        key = f"{d.year}-{d.month:02d}"
        running = max(0, running - reduce_by_month.get(key, 0))
        labels.append(key)
        real.append(None)
        projected.append(round(running))

    proj_end = running
    proj_drop = max(0, total - proj_end)
    proj_end_label = f"{month_name_es(add_months(start, months_fwd).month, short=True)} {add_months(start, months_fwd).year}"

    # Dirección de la tendencia
    direction, delta_prev = "flat", None
    if len(snaps) >= 2:
        delta_prev = snaps[-1]["total_debt"] - snaps[-2]["total_debt"]
        direction = "up" if delta_prev > 0 else ("down" if delta_prev < 0 else "flat")
    elif proj_drop > 0:
        direction = "down"

    return {
        "cards_debt": cards_debt, "loans_debt": loans_debt, "total": total,
        "direction": direction, "delta_prev": delta_prev,
        "labels": labels, "real": real, "projected": projected,
        "proj_end": proj_end, "proj_drop": proj_drop, "proj_end_label": proj_end_label,
        "has_schedule": bool(reduce_by_month),
    }


@bp.route("/")
def index():
    today = date.today()
    year = safe_int(request.args.get("year")) or today.year
    month = safe_int(request.args.get("month")) or today.month
    ym_str = f"{year}-{month:02d}"

    # ----- Totales generales -----
    accounts = db.query("""
        SELECT a.*, b.color AS bank_color, b.name AS bank_name
        FROM accounts a
        LEFT JOIN banks b ON b.id = a.bank_id
        WHERE a.status = 'activa'
        ORDER BY a.balance DESC
    """)
    total_balance = sum(a["balance"] for a in accounts)

    cards = db.query("""
        SELECT c.*, b.color AS bank_color, b.name AS bank_name,
               (c.credit_limit - c.used_amount) AS available_limit
        FROM credit_cards c
        LEFT JOIN banks b ON b.id = c.bank_id
        WHERE c.status = 'activa'
        ORDER BY c.used_amount DESC
    """)
    total_cards_limit = sum(c["credit_limit"] or 0 for c in cards)
    total_cards_used = sum(c["used_amount"] or 0 for c in cards)
    total_cards_available = total_cards_limit - total_cards_used
    total_future_installments = sum(c["future_installments_amount"] or 0 for c in cards)

    # ----- Gastos del mes -----
    month_expenses = db.query("""
        SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS count
        FROM transactions
        WHERE type='expense' AND status='pagado'
              AND strftime('%Y-%m', date) = ?
    """, (ym_str,), one=True)
    month_total_expense = month_expenses["total"] or 0
    month_count_tx = month_expenses["count"] or 0

    # ----- Ingresos del mes -----
    month_incomes = db.query("""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM transactions
        WHERE type='income' AND status='pagado'
              AND strftime('%Y-%m', date) = ?
    """, (ym_str,), one=True)
    month_total_income = month_incomes["total"] or 0

    # ----- Saldo del mes -----
    month_balance = month_total_income - month_total_expense

    # ----- Gastos por categoría (mes actual) -----
    expenses_by_category = db.query("""
        SELECT c.name, c.color, c.icon,
               COALESCE(SUM(t.amount), 0) AS total
        FROM categories c
        LEFT JOIN transactions t ON t.category_id = c.id
              AND t.type='expense' AND t.status='pagado'
              AND strftime('%Y-%m', t.date) = ?
        WHERE c.active = 1
        GROUP BY c.id
        HAVING total > 0
        ORDER BY total DESC
        LIMIT 10
    """, (ym_str,))

    # ----- Evolución últimos 6 meses -----
    monthly_evolution = db.query("""
        SELECT strftime('%Y-%m', date) AS month,
               SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) AS expenses,
               SUM(CASE WHEN type='income' THEN amount ELSE 0 END) AS incomes
        FROM transactions
        WHERE status='pagado'
              AND date >= date('now', '-6 months')
        GROUP BY month
        ORDER BY month ASC
    """)

    # ----- Deudas con personas -----
    they_owe_me = db.query("""
        SELECT COALESCE(SUM(pending_amount), 0) AS total
        FROM person_debts
        WHERE direction='they_owe_me' AND status IN ('pendiente', 'parcial')
    """, one=True)["total"] or 0

    i_owe_them = db.query("""
        SELECT COALESCE(SUM(pending_amount), 0) AS total
        FROM person_debts
        WHERE direction='i_owe_them' AND status IN ('pendiente', 'parcial')
    """, one=True)["total"] or 0

    # Por cobrar también incluye lo pendiente de cuentas del hogar
    household_receivable = db.query("""
        SELECT COALESCE(SUM(share_amount - paid_amount), 0) AS total
        FROM household_bill_participants WHERE status != 'pagado'
    """, one=True)["total"] or 0
    they_owe_me_total = they_owe_me + household_receivable

    # ----- Créditos / loans -----
    loans_summary = db.query("""
        SELECT COALESCE(SUM(pending_amount), 0) AS pending,
               COALESCE(SUM(installment_amount), 0) AS monthly,
               COUNT(*) AS count
        FROM loans WHERE status = 'vigente'
    """, one=True)

    # ----- Cuentas del hogar pendientes -----
    household_pending = db.query("""
        SELECT COUNT(*) AS count,
               COALESCE(SUM(amount), 0) AS total
        FROM household_bills
        WHERE status IN ('pendiente', 'parcial', 'vencida')
    """, one=True)

    # ----- Próximos vencimientos -----
    upcoming = []

    # Tarjetas próximas a vencer este mes
    upcoming_cards = db.query("""
        SELECT c.id, c.name, c.payment_day, b.name AS bank, b.color AS color,
               c.billed_amount AS amount, 'card' AS kind
        FROM credit_cards c
        LEFT JOIN banks b ON b.id = c.bank_id
        WHERE c.status = 'activa'
              AND c.payment_day IS NOT NULL
              AND c.payment_day >= ?
              AND c.has_billed_debt = 1
        ORDER BY c.payment_day ASC
        LIMIT 5
    """, (today.day,))
    for c in upcoming_cards:
        upcoming.append({
            "kind": "card",
            "title": f"Tarjeta {c['name']}",
            "amount": c["amount"],
            "day": c["payment_day"],
            "color": c["color"] or "#3b82f6",
        })

    # Próximas cuotas de créditos
    upcoming_loans = db.query("""
        SELECT li.*, l.name AS loan_name, b.color AS color
        FROM loan_installments li
        JOIN loans l ON l.id = li.loan_id
        LEFT JOIN banks b ON b.id = l.bank_id
        WHERE li.status = 'pendiente'
              AND li.due_date >= date('now')
              AND li.due_date <= date('now', '+30 days')
        ORDER BY li.due_date ASC
        LIMIT 5
    """)
    for li in upcoming_loans:
        upcoming.append({
            "kind": "loan",
            "title": f"Cuota {li['loan_name']}",
            "amount": li["amount"],
            "date": li["due_date"],
            "color": li["color"] or "#8b5cf6",
        })

    # Próximos recurrentes
    upcoming_rec = db.query("""
        SELECT r.*, c.color AS cat_color
        FROM recurring_payments r
        LEFT JOIN categories c ON c.id = r.category_id
        WHERE r.active = 1
              AND r.day_of_month IS NOT NULL
              AND r.day_of_month >= ?
        ORDER BY r.day_of_month ASC
        LIMIT 5
    """, (today.day,))
    for r in upcoming_rec:
        upcoming.append({
            "kind": "recurring",
            "title": r["name"],
            "amount": r["amount"],
            "day": r["day_of_month"],
            "color": r["cat_color"] or "#f97316",
        })

    # ----- Últimas transacciones -----
    last_transactions = db.query("""
        SELECT t.*, c.name AS category_name, c.color AS category_color,
               c.icon AS category_icon, a.name AS account_name,
               cc.name AS card_name
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        LEFT JOIN accounts a ON a.id = t.account_id
        LEFT JOIN credit_cards cc ON cc.id = t.card_id
        ORDER BY t.date DESC, t.id DESC
        LIMIT 8
    """)

    # ----- Alertas activas -----
    alerts = db.query("""
        SELECT * FROM alerts
        WHERE dismissed = 0
        ORDER BY severity DESC, created_at DESC
        LIMIT 6
    """)

    # ----- Presupuestos del mes -----
    budgets_this_month = db.query("""
        SELECT b.*, c.name AS category_name, c.color AS category_color, c.icon AS category_icon
        FROM budgets b
        LEFT JOIN categories c ON c.id = b.category_id
        WHERE b.year = ? AND (b.month = ? OR b.month IS NULL)
              AND b.scope = 'category'
        ORDER BY b.amount DESC
        LIMIT 5
    """, (year, month))

    enriched_budgets = []
    for b_ in budgets_this_month:
        b_ = dict(b_)
        if b_["category_id"]:
            r = db.query("""
                SELECT COALESCE(SUM(amount), 0) AS s FROM transactions
                WHERE type='expense' AND status='pagado'
                  AND category_id = ?
                  AND strftime('%Y-%m', date) = ?
            """, (b_["category_id"], ym_str), one=True)
            spent = r["s"] if r else 0
            b_["spent"] = spent
            b_["pct"] = round((spent / b_["amount"] * 100), 1) if b_["amount"] else 0
            b_["over"] = spent > b_["amount"]
            enriched_budgets.append(b_)

    # ----- Plan del mes (ingreso vs compromisos) -----
    monthly_income = get_monthly_income()
    months_plan = compute_commitments()
    this_month_plan = months_plan[0] if months_plan else None
    spend_ceiling = this_month_plan["free"] if this_month_plan else 0
    variable_spent = db.query("""
        SELECT COALESCE(SUM(amount),0) AS t FROM transactions
        WHERE type='expense' AND status='pagado'
          AND strftime('%Y-%m', date)=?
          AND transaction_type NOT IN ('debt_payment')
          AND (description IS NULL OR description NOT LIKE '[Recurrente]%')
    """, (ym_str,), one=True)["t"] or 0
    spend_remaining = spend_ceiling - variable_spent

    # ----- Endeudamiento total y tendencia -----
    debt = compute_debt_trend()

    return render_template(
        "dashboard.html",
        year=year, month=month,
        accounts=accounts,
        cards=cards,
        debt=debt,
        total_debt=debt["total"],
        monthly_income=monthly_income,
        this_month_plan=this_month_plan,
        spend_ceiling=spend_ceiling,
        variable_spent=variable_spent,
        spend_remaining=spend_remaining,
        they_owe_me_total=they_owe_me_total,
        household_receivable=household_receivable,
        total_balance=total_balance,
        total_cards_limit=total_cards_limit,
        total_cards_used=total_cards_used,
        total_cards_available=total_cards_available,
        total_future_installments=total_future_installments,
        month_total_expense=month_total_expense,
        month_total_income=month_total_income,
        month_balance=month_balance,
        month_count_tx=month_count_tx,
        expenses_by_category=expenses_by_category,
        monthly_evolution=monthly_evolution,
        they_owe_me=they_owe_me,
        i_owe_them=i_owe_them,
        loans_summary=loans_summary,
        household_pending=household_pending,
        upcoming=upcoming[:8],
        last_transactions=last_transactions,
        alerts=alerts,
        budgets=enriched_budgets,
    )
