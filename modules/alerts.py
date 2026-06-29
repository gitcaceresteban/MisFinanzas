"""Alertas del sistema."""
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import db
from modules.helpers import safe_str, safe_int

bp = Blueprint("alerts", __name__)


@bp.route("/")
def index():
    show_dismissed = request.args.get("dismissed") == "1"
    where = "1=1" if show_dismissed else "dismissed = 0"

    alerts = db.query(f"""
        SELECT * FROM alerts
        WHERE {where}
        ORDER BY severity DESC, created_at DESC
        LIMIT 200
    """)

    # Conteos por severidad
    counts = db.query("""
        SELECT severity, COUNT(*) AS c
        FROM alerts WHERE dismissed = 0
        GROUP BY severity
    """)
    counts_dict = {c["severity"]: c["c"] for c in counts}

    return render_template("alerts.html",
                          alerts=alerts,
                          counts=counts_dict,
                          show_dismissed=show_dismissed)


@bp.route("/generar", methods=["POST"])
def generate():
    """Regenera todas las alertas automáticas en base al estado actual."""
    generated = 0
    today = date.today()

    # Limpiar alertas auto-generadas no dismisseadas
    db.execute("DELETE FROM alerts WHERE dismissed = 0 AND type IN (?, ?, ?, ?, ?, ?, ?, ?)",
               ("low_balance", "low_card_limit", "card_due", "loan_due",
                "person_unpaid", "budget_warn", "budget_over", "household_overdue"))

    # Saldos bajos
    settings = db.query("SELECT value FROM settings WHERE key='low_balance_threshold'",
                        one=True)
    threshold = float(settings["value"]) if settings else 50000
    low_accounts = db.query("""
        SELECT id, name, balance FROM accounts
        WHERE status='activa' AND balance < ? AND balance >= 0
    """, (threshold,))
    for a in low_accounts:
        db.insert("alerts", {
            "type": "low_balance",
            "severity": "warning",
            "title": f"Saldo bajo en {a['name']}",
            "message": f"Saldo actual: ${a['balance']:,.0f}",
            "related_entity_type": "account",
            "related_entity_id": a["id"],
            "action_url": "/cuentas/",
        })
        generated += 1

    # Cupos de tarjeta bajos (< 20% disponible)
    cards = db.query("""
        SELECT id, name, credit_limit, used_amount,
               (credit_limit - used_amount) AS avail
        FROM credit_cards
        WHERE status='activa' AND credit_limit > 0
    """)
    for c in cards:
        if c["credit_limit"] > 0:
            pct = (c["avail"] / c["credit_limit"]) * 100
            if pct < 20:
                db.insert("alerts", {
                    "type": "low_card_limit",
                    "severity": "warning",
                    "title": f"Cupo bajo en {c['name']}",
                    "message": f"Disponible: ${c['avail']:,.0f} ({pct:.1f}%)",
                    "related_entity_type": "card",
                    "related_entity_id": c["id"],
                    "action_url": f"/tarjetas/{c['id']}",
                })
                generated += 1

    # Tarjetas con fecha de pago cerca (próximos 7 días)
    cards_due = db.query("""
        SELECT id, name, payment_day, billed_amount
        FROM credit_cards
        WHERE status='activa' AND payment_day IS NOT NULL
              AND has_billed_debt = 1
    """)
    for c in cards_due:
        if c["payment_day"]:
            try:
                due = date(today.year, today.month, min(c["payment_day"], 28))
                if 0 <= (due - today).days <= 7:
                    db.insert("alerts", {
                        "type": "card_due",
                        "severity": "warning",
                        "title": f"Pago próximo: {c['name']}",
                        "message": f"Vence el {c['payment_day']}/{today.month}",
                        "related_entity_type": "card",
                        "related_entity_id": c["id"],
                        "action_url": f"/tarjetas/{c['id']}",
                    })
                    generated += 1
            except ValueError:
                pass

    # Cuotas de crédito próximas
    loan_dues = db.query("""
        SELECT li.id, li.amount, li.due_date, l.name AS loan_name, l.id AS loan_id
        FROM loan_installments li
        JOIN loans l ON l.id = li.loan_id
        WHERE li.status = 'pendiente'
              AND li.due_date >= date('now')
              AND li.due_date <= date('now', '+7 days')
    """)
    for li in loan_dues:
        db.insert("alerts", {
            "type": "loan_due",
            "severity": "warning",
            "title": f"Cuota próxima: {li['loan_name']}",
            "message": f"${li['amount']:,.0f} - vence {li['due_date']}",
            "related_entity_type": "loan",
            "related_entity_id": li["loan_id"],
            "action_url": f"/creditos/{li['loan_id']}",
        })
        generated += 1

    # Personas con deudas pendientes
    persons_owe = db.query("""
        SELECT pd.id, p.name, pd.pending_amount, pd.direction, pd.expected_date
        FROM person_debts pd
        JOIN people p ON p.id = pd.person_id
        WHERE pd.status IN ('pendiente', 'parcial')
              AND pd.direction = 'they_owe_me'
              AND pd.expected_date IS NOT NULL
              AND pd.expected_date <= date('now')
    """)
    for pd in persons_owe:
        db.insert("alerts", {
            "type": "person_unpaid",
            "severity": "warning",
            "title": f"{pd['name']} tiene deuda vencida",
            "message": f"${pd['pending_amount']:,.0f} - vencía {pd['expected_date']}",
            "related_entity_type": "person_debt",
            "related_entity_id": pd["id"],
            "action_url": f"/personas/",
        })
        generated += 1

    # Presupuestos sobrepasados
    budgets = db.query("""
        SELECT b.*, c.name AS cat_name
        FROM budgets b
        LEFT JOIN categories c ON c.id = b.category_id
        WHERE b.scope = 'category'
              AND b.year = ? AND (b.month = ? OR b.month IS NULL)
    """, (today.year, today.month))
    for b_ in budgets:
        if not b_["category_id"]:
            continue
        r = db.query("""
            SELECT COALESCE(SUM(amount), 0) AS s FROM transactions
            WHERE type='expense' AND status='pagado'
              AND category_id = ?
              AND strftime('%Y-%m', date) = ?
        """, (b_["category_id"], f"{today.year}-{today.month:02d}"), one=True)
        spent = r["s"] if r else 0
        if b_["amount"] > 0:
            pct = (spent / b_["amount"]) * 100
            if pct >= 100:
                db.insert("alerts", {
                    "type": "budget_over",
                    "severity": "error",
                    "title": f"Presupuesto excedido: {b_['cat_name']}",
                    "message": f"Gastado: ${spent:,.0f} de ${b_['amount']:,.0f} ({pct:.1f}%)",
                    "related_entity_type": "budget",
                    "related_entity_id": b_["id"],
                    "action_url": "/presupuestos/",
                })
                generated += 1
            elif pct >= (b_["alert_threshold"] or 80):
                db.insert("alerts", {
                    "type": "budget_warn",
                    "severity": "warning",
                    "title": f"Presupuesto al {pct:.0f}%: {b_['cat_name']}",
                    "message": f"Gastado: ${spent:,.0f} de ${b_['amount']:,.0f}",
                    "related_entity_type": "budget",
                    "related_entity_id": b_["id"],
                    "action_url": "/presupuestos/",
                })
                generated += 1

    # Cuentas del hogar vencidas
    overdue_bills = db.query("""
        SELECT id, name, amount, due_date FROM household_bills
        WHERE status IN ('pendiente', 'parcial')
              AND due_date IS NOT NULL
              AND due_date <= date('now')
    """)
    for b_ in overdue_bills:
        db.insert("alerts", {
            "type": "household_overdue",
            "severity": "warning",
            "title": f"Cuenta del hogar vencida: {b_['name']}",
            "message": f"${b_['amount']:,.0f} - vencía {b_['due_date']}",
            "related_entity_type": "household_bill",
            "related_entity_id": b_["id"],
            "action_url": "/hogar/",
        })
        generated += 1

    flash(f"{generated} alertas generadas", "success")
    return redirect(url_for("alerts.index"))


@bp.route("/<int:alert_id>/leer", methods=["POST"])
def mark_read(alert_id):
    db.update("alerts", {"read": 1}, "id = ?", (alert_id,))
    return redirect(url_for("alerts.index"))


@bp.route("/<int:alert_id>/descartar", methods=["POST"])
def dismiss(alert_id):
    db.update("alerts", {"dismissed": 1, "read": 1}, "id = ?", (alert_id,))
    return redirect(url_for("alerts.index"))


@bp.route("/descartar-todas", methods=["POST"])
def dismiss_all():
    db.execute("UPDATE alerts SET dismissed = 1, read = 1 WHERE dismissed = 0")
    flash("Todas las alertas descartadas", "info")
    return redirect(url_for("alerts.index"))
