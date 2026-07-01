"""Gestión de cuentas bancarias."""
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import db
from modules.helpers import safe_str, safe_float, safe_int, parse_money

bp = Blueprint("accounts", __name__)

ACCOUNT_TYPES = [
    ("corriente", "Cuenta corriente"),
    ("vista", "Cuenta vista"),
    ("rut", "Cuenta RUT"),
    ("ahorro", "Cuenta de ahorro"),
    ("digital", "Cuenta digital"),
    ("efectivo", "Efectivo"),
    ("otra", "Otra"),
]

ACCOUNT_STATUSES = [
    ("activa", "Activa"),
    ("pausada", "Pausada"),
    ("cerrada", "Cerrada"),
]


@bp.route("/")
def index():
    accounts = db.query("""
        SELECT a.*, b.name AS bank_name, b.color AS bank_color
        FROM accounts a
        LEFT JOIN banks b ON b.id = a.bank_id
        ORDER BY a.status ASC, b.name ASC, a.name ASC
    """)
    total = sum(a["balance"] for a in accounts if a["status"] == "activa")
    return render_template("accounts.html", accounts=accounts,
                          total=total,
                          types=ACCOUNT_TYPES,
                          statuses=ACCOUNT_STATUSES)


@bp.route("/nueva", methods=["GET", "POST"])
def create():
    banks = db.query("SELECT * FROM banks WHERE active=1 ORDER BY name")
    if request.method == "POST":
        data = {
            "bank_id": safe_int(request.form.get("bank_id")) or None,
            "name": safe_str(request.form.get("name")),
            "type": safe_str(request.form.get("type")) or "corriente",
            "currency": safe_str(request.form.get("currency")) or "CLP",
            "balance": parse_money(request.form.get("balance")),
            "credit_line": parse_money(request.form.get("credit_line")),
            "status": safe_str(request.form.get("status")) or "activa",
            "color": safe_str(request.form.get("color")) or None,
            "notes": safe_str(request.form.get("notes")) or None,
        }
        if not data["name"]:
            flash("El nombre es obligatorio", "error")
            return redirect(url_for("accounts.create"))
        new_id = db.insert("accounts", data)
        db.audit("create", "account", new_id, data)
        flash(f"Cuenta '{data['name']}' creada", "success")
        return redirect(url_for("accounts.index"))
    return render_template("accounts_form.html", account=None, banks=banks,
                          types=ACCOUNT_TYPES, statuses=ACCOUNT_STATUSES)


@bp.route("/<int:account_id>")
def detail(account_id):
    """Detalle de una cuenta: saldo + últimos movimientos (gastos e ingresos)."""
    account = db.query("""
        SELECT a.*, b.name AS bank_name, b.color AS bank_color, b.logo_path AS bank_logo
        FROM accounts a
        LEFT JOIN banks b ON b.id = a.bank_id
        WHERE a.id = ?
    """, (account_id,), one=True)
    if not account:
        flash("Cuenta no encontrada", "error")
        return redirect(url_for("accounts.index"))

    transactions = db.query("""
        SELECT t.*, c.name AS category_name, c.color AS category_color,
               c.icon AS category_icon, p.name AS person_name
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        LEFT JOIN people p ON p.id = t.person_id
        WHERE t.account_id = ?
        ORDER BY t.date DESC, t.id DESC
        LIMIT 50
    """, (account_id,))

    # Resumen del mes en curso para esta cuenta
    from datetime import date
    ym = date.today().strftime("%Y-%m")
    month_sums = db.query("""
        SELECT COALESCE(SUM(CASE WHEN type='expense' THEN amount END), 0) AS expenses,
               COALESCE(SUM(CASE WHEN type='income' THEN amount END), 0) AS incomes
        FROM transactions
        WHERE account_id = ? AND status='pagado' AND strftime('%Y-%m', date) = ?
    """, (account_id, ym), one=True)

    return render_template("accounts_detail.html",
                           account=account,
                           transactions=transactions,
                           month_expenses=month_sums["expenses"] or 0,
                           month_incomes=month_sums["incomes"] or 0)


@bp.route("/<int:account_id>/editar", methods=["GET", "POST"])
def edit(account_id):
    account = db.query("SELECT * FROM accounts WHERE id = ?", (account_id,), one=True)
    if not account:
        flash("Cuenta no encontrada", "error")
        return redirect(url_for("accounts.index"))
    banks = db.query("SELECT * FROM banks WHERE active=1 ORDER BY name")

    if request.method == "POST":
        data = {
            "bank_id": safe_int(request.form.get("bank_id")) or None,
            "name": safe_str(request.form.get("name")),
            "type": safe_str(request.form.get("type")) or "corriente",
            "currency": safe_str(request.form.get("currency")) or "CLP",
            "balance": parse_money(request.form.get("balance")),
            "credit_line": parse_money(request.form.get("credit_line")),
            "status": safe_str(request.form.get("status")) or "activa",
            "color": safe_str(request.form.get("color")) or None,
            "notes": safe_str(request.form.get("notes")) or None,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        db.update("accounts", data, "id = ?", (account_id,))
        db.audit("update", "account", account_id, data)
        flash("Cuenta actualizada", "success")
        return redirect(url_for("accounts.index"))

    return render_template("accounts_form.html", account=account, banks=banks,
                          types=ACCOUNT_TYPES, statuses=ACCOUNT_STATUSES)


@bp.route("/<int:account_id>/eliminar", methods=["POST"])
def remove(account_id):
    db.update("accounts", {"status": "cerrada"}, "id = ?", (account_id,))
    db.audit("delete", "account", account_id)
    flash("Cuenta cerrada", "info")
    return redirect(url_for("accounts.index"))


@bp.route("/<int:account_id>/ajustar-saldo", methods=["POST"])
def adjust_balance(account_id):
    """Ajuste manual del saldo, registrando el movimiento."""
    new_balance = parse_money(request.form.get("balance"))
    note = safe_str(request.form.get("note"))
    current = db.query("SELECT balance FROM accounts WHERE id = ?",
                       (account_id,), one=True)
    if not current:
        flash("Cuenta no encontrada", "error")
        return redirect(url_for("accounts.index"))
    diff = new_balance - current["balance"]
    db.update("accounts", {
        "balance": new_balance,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }, "id = ?", (account_id,))
    db.audit("adjustment", "account", account_id, {
        "old_balance": current["balance"],
        "new_balance": new_balance,
        "diff": diff,
        "note": note,
    })
    flash(f"Saldo ajustado (diferencia: {diff:+,.0f})", "success")
    return redirect(url_for("accounts.index"))
