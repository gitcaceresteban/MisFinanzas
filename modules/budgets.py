"""Presupuestos por categoría, cuenta y persona."""
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import db
from modules.helpers import safe_str, safe_float, safe_int, parse_money

bp = Blueprint("budgets", __name__)


@bp.route("/")
def index():
    today = date.today()
    year = safe_int(request.args.get("year")) or today.year
    month = safe_int(request.args.get("month")) or today.month

    budgets = db.query("""
        SELECT b.*,
               c.name AS category_name, c.color AS category_color, c.icon AS category_icon,
               a.name AS account_name,
               p.name AS person_name
        FROM budgets b
        LEFT JOIN categories c ON c.id = b.category_id
        LEFT JOIN accounts a ON a.id = b.account_id
        LEFT JOIN people p ON p.id = b.person_id
        WHERE b.year = ? AND (b.month = ? OR b.month IS NULL)
        ORDER BY b.scope, c.name
    """, (year, month))

    # Para cada presupuesto, calcular el gasto real
    enriched = []
    for b_ in budgets:
        b_ = dict(b_)
        spent = 0
        if b_["scope"] == "category" and b_["category_id"]:
            r = db.query("""
                SELECT COALESCE(SUM(amount), 0) AS s FROM transactions
                WHERE type='expense' AND status='pagado'
                  AND category_id = ?
                  AND strftime('%Y', date) = ?
                  AND strftime('%m', date) = ?
            """, (b_["category_id"], str(year), f"{month:02d}"), one=True)
            spent = r["s"] if r else 0
        elif b_["scope"] == "account" and b_["account_id"]:
            r = db.query("""
                SELECT COALESCE(SUM(amount), 0) AS s FROM transactions
                WHERE type='expense' AND status='pagado'
                  AND account_id = ?
                  AND strftime('%Y', date) = ?
                  AND strftime('%m', date) = ?
            """, (b_["account_id"], str(year), f"{month:02d}"), one=True)
            spent = r["s"] if r else 0
        elif b_["scope"] == "person" and b_["person_id"]:
            r = db.query("""
                SELECT COALESCE(SUM(amount), 0) AS s FROM transactions
                WHERE type='expense' AND status='pagado'
                  AND person_id = ?
                  AND strftime('%Y', date) = ?
                  AND strftime('%m', date) = ?
            """, (b_["person_id"], str(year), f"{month:02d}"), one=True)
            spent = r["s"] if r else 0
        elif b_["scope"] == "global":
            r = db.query("""
                SELECT COALESCE(SUM(amount), 0) AS s FROM transactions
                WHERE type='expense' AND status='pagado'
                  AND strftime('%Y', date) = ?
                  AND strftime('%m', date) = ?
            """, (str(year), f"{month:02d}"), one=True)
            spent = r["s"] if r else 0

        b_["spent"] = spent
        b_["remaining"] = max(0, b_["amount"] - spent)
        b_["pct"] = round((spent / b_["amount"] * 100), 1) if b_["amount"] else 0
        b_["over"] = spent > b_["amount"]
        enriched.append(b_)

    categories = db.query("SELECT * FROM categories WHERE active=1 ORDER BY name")
    accounts = db.query("SELECT * FROM accounts ORDER BY name")
    people = db.query("SELECT * FROM people WHERE active=1 ORDER BY name")

    return render_template("budgets.html",
                          budgets=enriched,
                          categories=categories,
                          accounts=accounts,
                          people=people,
                          year=year, month=month)


@bp.route("/nuevo", methods=["POST"])
def create():
    today = date.today()
    data = {
        "period": safe_str(request.form.get("period")) or "monthly",
        "year": safe_int(request.form.get("year")) or today.year,
        "month": safe_int(request.form.get("month")) or today.month,
        "scope": safe_str(request.form.get("scope")) or "category",
        "category_id": safe_int(request.form.get("category_id")) or None,
        "account_id": safe_int(request.form.get("account_id")) or None,
        "person_id": safe_int(request.form.get("person_id")) or None,
        "amount": parse_money(request.form.get("amount")),
        "alert_threshold": safe_int(request.form.get("alert_threshold")) or 80,
        "notes": safe_str(request.form.get("notes")) or None,
    }
    if data["amount"] <= 0:
        flash("El monto debe ser mayor a 0", "error")
        return redirect(url_for("budgets.index"))
    new_id = db.insert("budgets", data)
    db.audit("create", "budget", new_id, data)
    flash("Presupuesto creado", "success")
    return redirect(url_for("budgets.index"))


@bp.route("/<int:budget_id>/editar", methods=["POST"])
def edit(budget_id):
    data = {
        "amount": parse_money(request.form.get("amount")),
        "alert_threshold": safe_int(request.form.get("alert_threshold")) or 80,
        "notes": safe_str(request.form.get("notes")) or None,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    db.update("budgets", data, "id = ?", (budget_id,))
    db.audit("update", "budget", budget_id, data)
    flash("Presupuesto actualizado", "success")
    return redirect(url_for("budgets.index"))


@bp.route("/<int:budget_id>/eliminar", methods=["POST"])
def remove(budget_id):
    db.delete("budgets", "id = ?", (budget_id,))
    db.audit("delete", "budget", budget_id)
    flash("Presupuesto eliminado", "info")
    return redirect(url_for("budgets.index"))
