"""Gestión de tarjetas de crédito y sus cuotas."""
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import db
from modules.helpers import (
    safe_str, safe_float, safe_int, parse_money, parse_date_cl,
    add_months, today_iso
)

bp = Blueprint("cards", __name__)

CARD_STATUSES = [
    ("activa", "Activa"),
    ("bloqueada", "Bloqueada"),
    ("cerrada", "Cerrada"),
]


@bp.route("/")
def index():
    cards = db.query("""
        SELECT c.*, b.name AS bank_name, b.color AS bank_color, b.logo_path AS bank_logo,
               (c.credit_limit - c.used_amount) AS available_limit
        FROM credit_cards c
        LEFT JOIN banks b ON b.id = c.bank_id
        ORDER BY c.status ASC, b.name ASC, c.name ASC
    """)
    total_limit = sum(c["credit_limit"] or 0 for c in cards if c["status"] == "activa")
    total_used = sum(c["used_amount"] or 0 for c in cards if c["status"] == "activa")
    total_available = total_limit - total_used

    return render_template("cards.html", cards=cards,
                           total_limit=total_limit,
                           total_used=total_used,
                           total_available=total_available,
                           statuses=CARD_STATUSES)


@bp.route("/nueva", methods=["GET", "POST"])
def create():
    banks = db.query("SELECT * FROM banks WHERE active=1 ORDER BY name")
    if request.method == "POST":
        data = {
            "bank_id": safe_int(request.form.get("bank_id")) or None,
            "name": safe_str(request.form.get("name")),
            "credit_limit": parse_money(request.form.get("credit_limit")),
            "used_amount": parse_money(request.form.get("used_amount")),
            "billing_day": safe_int(request.form.get("billing_day")) or None,
            "payment_day": safe_int(request.form.get("payment_day")) or None,
            "status": safe_str(request.form.get("status")) or "activa",
            "has_billed_debt": 1 if request.form.get("has_billed_debt") else 0,
            "billed_amount": parse_money(request.form.get("billed_amount")),
            "unbilled_amount": parse_money(request.form.get("unbilled_amount")),
            "color": safe_str(request.form.get("color")) or None,
            "notes": safe_str(request.form.get("notes")) or None,
        }
        if not data["name"]:
            flash("El nombre es obligatorio", "error")
            return redirect(url_for("cards.create"))
        new_id = db.insert("credit_cards", data)
        db.audit("create", "credit_card", new_id, data)
        flash(f"Tarjeta '{data['name']}' creada", "success")
        return redirect(url_for("cards.detail", card_id=new_id))
    return render_template("cards_form.html", card=None, banks=banks,
                           statuses=CARD_STATUSES)


@bp.route("/<int:card_id>")
def detail(card_id):
    card = db.query("""
        SELECT c.*, b.name AS bank_name, b.color AS bank_color, b.logo_path AS bank_logo
        FROM credit_cards c
        LEFT JOIN banks b ON b.id = c.bank_id
        WHERE c.id = ?
    """, (card_id,), one=True)
    if not card:
        flash("Tarjeta no encontrada", "error")
        return redirect(url_for("cards.index"))

    card["available_limit"] = (card["credit_limit"] or 0) - (card["used_amount"] or 0)

    # Cuotas futuras agrupadas por mes
    installments = db.query("""
        SELECT * FROM card_installments
        WHERE card_id = ? AND status != 'pagada'
        ORDER BY estimated_date ASC
    """, (card_id,))

    # Últimas transacciones
    transactions = db.query("""
        SELECT t.*, cat.name AS category_name, cat.color AS category_color
        FROM transactions t
        LEFT JOIN categories cat ON cat.id = t.category_id
        WHERE t.card_id = ?
        ORDER BY t.date DESC, t.id DESC
        LIMIT 25
    """, (card_id,))

    # Cuotas por mes (próximos 12)
    monthly_summary = db.query("""
        SELECT strftime('%Y-%m', estimated_date) AS month,
               COUNT(*) AS count,
               SUM(amount) AS total
        FROM card_installments
        WHERE card_id = ? AND status != 'pagada'
              AND estimated_date >= date('now')
        GROUP BY month
        ORDER BY month ASC
        LIMIT 12
    """, (card_id,))

    return render_template("cards_detail.html", card=card,
                           installments=installments,
                           transactions=transactions,
                           monthly_summary=monthly_summary)


@bp.route("/<int:card_id>/editar", methods=["GET", "POST"])
def edit(card_id):
    card = db.query("SELECT * FROM credit_cards WHERE id = ?", (card_id,), one=True)
    if not card:
        flash("Tarjeta no encontrada", "error")
        return redirect(url_for("cards.index"))
    banks = db.query("SELECT * FROM banks WHERE active=1 ORDER BY name")

    if request.method == "POST":
        data = {
            "bank_id": safe_int(request.form.get("bank_id")) or None,
            "name": safe_str(request.form.get("name")),
            "credit_limit": parse_money(request.form.get("credit_limit")),
            "used_amount": parse_money(request.form.get("used_amount")),
            "billing_day": safe_int(request.form.get("billing_day")) or None,
            "payment_day": safe_int(request.form.get("payment_day")) or None,
            "status": safe_str(request.form.get("status")) or "activa",
            "has_billed_debt": 1 if request.form.get("has_billed_debt") else 0,
            "billed_amount": parse_money(request.form.get("billed_amount")),
            "unbilled_amount": parse_money(request.form.get("unbilled_amount")),
            "color": safe_str(request.form.get("color")) or None,
            "notes": safe_str(request.form.get("notes")) or None,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        db.update("credit_cards", data, "id = ?", (card_id,))
        db.audit("update", "credit_card", card_id, data)
        flash("Tarjeta actualizada", "success")
        return redirect(url_for("cards.detail", card_id=card_id))

    return render_template("cards_form.html", card=card, banks=banks,
                           statuses=CARD_STATUSES)


@bp.route("/<int:card_id>/eliminar", methods=["POST"])
def remove(card_id):
    db.update("credit_cards", {"status": "cerrada"}, "id = ?", (card_id,))
    db.audit("delete", "credit_card", card_id)
    flash("Tarjeta cerrada", "info")
    return redirect(url_for("cards.index"))


@bp.route("/cuotas/<int:installment_id>/marcar-pagada", methods=["POST"])
def mark_installment_paid(installment_id):
    inst = db.query("SELECT * FROM card_installments WHERE id = ?",
                    (installment_id,), one=True)
    if not inst:
        flash("Cuota no encontrada", "error")
        return redirect(url_for("cards.index"))
    db.update("card_installments", {"status": "pagada"}, "id = ?", (installment_id,))
    db.audit("payment", "card_installment", installment_id)
    flash("Cuota marcada como pagada", "success")
    return redirect(url_for("cards.detail", card_id=inst["card_id"]))


@bp.route("/cuotas/<int:installment_id>/marcar-facturada", methods=["POST"])
def mark_installment_billed(installment_id):
    inst = db.query("SELECT * FROM card_installments WHERE id = ?",
                    (installment_id,), one=True)
    if not inst:
        flash("Cuota no encontrada", "error")
        return redirect(url_for("cards.index"))
    db.update("card_installments", {"status": "facturada"}, "id = ?", (installment_id,))
    flash("Cuota marcada como facturada", "info")
    return redirect(url_for("cards.detail", card_id=inst["card_id"]))


@bp.route("/calendario")
def calendar():
    """Vista de calendario de tarjetas: cuánto se cargará en cada mes."""
    summary = db.query("""
        SELECT strftime('%Y-%m', ci.estimated_date) AS month,
               c.name AS card_name,
               c.id AS card_id,
               b.name AS bank_name,
               b.color AS bank_color,
               COUNT(*) AS count,
               SUM(ci.amount) AS total
        FROM card_installments ci
        JOIN credit_cards c ON c.id = ci.card_id
        LEFT JOIN banks b ON b.id = c.bank_id
        WHERE ci.status != 'pagada' AND ci.estimated_date >= date('now', '-1 month')
        GROUP BY month, c.id
        ORDER BY month ASC, b.name ASC
        LIMIT 200
    """)

    # Agrupar por mes
    by_month = {}
    for row in summary:
        m = row["month"]
        if m not in by_month:
            by_month[m] = {"month": m, "total": 0, "cards": []}
        by_month[m]["cards"].append(row)
        by_month[m]["total"] += row["total"] or 0

    months_list = sorted(by_month.values(), key=lambda x: x["month"])
    return render_template("cards_calendar.html", months=months_list)


def create_installments(card_id: int, transaction_id: int, total_amount: float,
                        total_installments: int, start_date: str,
                        billing_day: int = None) -> None:
    """Crea automáticamente las cuotas futuras de una compra en cuotas."""
    if total_installments < 1:
        return
    amount_per = round(total_amount / total_installments)
    start = parse_date_cl(start_date) or date.today()

    for i in range(1, total_installments + 1):
        est_date = add_months(start, i)
        if billing_day:
            try:
                est_date = est_date.replace(day=min(billing_day, 28))
            except ValueError:
                pass
        db.insert("card_installments", {
            "card_id": card_id,
            "transaction_id": transaction_id,
            "installment_number": i,
            "total_installments": total_installments,
            "amount": amount_per,
            "estimated_date": est_date.isoformat(),
            "status": "pendiente",
        })

    # Actualizar resumen de la tarjeta
    pending = db.query("""
        SELECT COUNT(*) as c, COALESCE(SUM(amount),0) as t
        FROM card_installments
        WHERE card_id = ? AND status != 'pagada'
    """, (card_id,), one=True)
    db.update("credit_cards", {
        "future_installments_amount": pending["t"],
        "pending_installments": pending["c"],
    }, "id = ?", (card_id,))
