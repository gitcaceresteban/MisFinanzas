"""Gestión de personas y deudas entre personas."""
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import db
from modules.helpers import safe_str, safe_float, safe_int, parse_money, today_iso

bp = Blueprint("people", __name__)


@bp.route("/")
def index():
    people = db.query("""
        SELECT p.*,
               COALESCE((SELECT SUM(pending_amount) FROM person_debts
                         WHERE person_id=p.id AND direction='they_owe_me'
                               AND status IN ('pendiente','parcial')), 0) AS they_owe,
               COALESCE((SELECT SUM(pending_amount) FROM person_debts
                         WHERE person_id=p.id AND direction='i_owe_them'
                               AND status IN ('pendiente','parcial')), 0) AS i_owe
        FROM people p
        WHERE p.active = 1
        ORDER BY p.name ASC
    """)
    people = [dict(p) for p in people]
    for p in people:
        p["net"] = (p["they_owe"] or 0) - (p["i_owe"] or 0)
    total_they_owe = sum(p["they_owe"] for p in people)
    total_i_owe = sum(p["i_owe"] for p in people)
    return render_template("people.html",
                           people=people,
                           total_they_owe=total_they_owe,
                           total_i_owe=total_i_owe,
                           net=total_they_owe - total_i_owe)


@bp.route("/nueva", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        data = {
            "name": safe_str(request.form.get("name")),
            "alias": safe_str(request.form.get("alias")) or None,
            "phone": safe_str(request.form.get("phone")) or None,
            "telegram_id": safe_str(request.form.get("telegram_id")) or None,
            "email": safe_str(request.form.get("email")) or None,
            "notes": safe_str(request.form.get("notes")) or None,
        }
        if not data["name"]:
            flash("El nombre es obligatorio", "error")
            return redirect(url_for("people.create"))
        new_id = db.insert("people", data)
        db.audit("create", "person", new_id, data)
        flash("Persona agregada", "success")
        return redirect(url_for("people.detail", person_id=new_id))
    return render_template("people_form.html", person=None)


@bp.route("/<int:person_id>")
def detail(person_id):
    person = db.query("SELECT * FROM people WHERE id = ?", (person_id,), one=True)
    if not person:
        flash("Persona no encontrada", "error")
        return redirect(url_for("people.index"))

    debts = db.query("""
        SELECT pd.*, c.name AS category_name, c.color AS category_color
        FROM person_debts pd
        LEFT JOIN categories c ON c.id = pd.category_id
        WHERE pd.person_id = ?
        ORDER BY pd.status ASC, pd.date DESC
    """, (person_id,))

    they_owe = sum(d["pending_amount"] for d in debts
                   if d["direction"] == "they_owe_me"
                   and d["status"] in ("pendiente", "parcial"))
    i_owe = sum(d["pending_amount"] for d in debts
                if d["direction"] == "i_owe_them"
                and d["status"] in ("pendiente", "parcial"))

    transactions = db.query("""
        SELECT t.*, c.name AS category_name, c.color AS category_color
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.person_id = ?
        ORDER BY t.date DESC
        LIMIT 30
    """, (person_id,))

    payments_history = db.query("""
        SELECT pdp.*, pd.direction, pd.description AS debt_description
        FROM person_debt_payments pdp
        JOIN person_debts pd ON pd.id = pdp.debt_id
        WHERE pd.person_id = ?
        ORDER BY pdp.date DESC
        LIMIT 30
    """, (person_id,))

    categories = db.query("SELECT * FROM categories WHERE active=1 ORDER BY name")
    accounts = db.query("""SELECT a.*, b.name AS bank_name FROM accounts a
                           LEFT JOIN banks b ON b.id=a.bank_id
                           WHERE a.status='activa' ORDER BY a.name""")

    return render_template("people_detail.html",
                           person=person,
                           debts=debts,
                           transactions=transactions,
                           payments_history=payments_history,
                           categories=categories,
                           accounts=accounts,
                           they_owe=they_owe,
                           i_owe=i_owe,
                           net=they_owe - i_owe)


@bp.route("/<int:person_id>/editar", methods=["GET", "POST"])
def edit(person_id):
    person = db.query("SELECT * FROM people WHERE id = ?", (person_id,), one=True)
    if not person:
        flash("Persona no encontrada", "error")
        return redirect(url_for("people.index"))
    if request.method == "POST":
        data = {
            "name": safe_str(request.form.get("name")),
            "alias": safe_str(request.form.get("alias")) or None,
            "phone": safe_str(request.form.get("phone")) or None,
            "telegram_id": safe_str(request.form.get("telegram_id")) or None,
            "email": safe_str(request.form.get("email")) or None,
            "notes": safe_str(request.form.get("notes")) or None,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        db.update("people", data, "id = ?", (person_id,))
        db.audit("update", "person", person_id, data)
        flash("Persona actualizada", "success")
        return redirect(url_for("people.detail", person_id=person_id))
    return render_template("people_form.html", person=person)


@bp.route("/<int:person_id>/eliminar", methods=["POST"])
def remove(person_id):
    db.update("people", {"active": 0}, "id = ?", (person_id,))
    db.audit("delete", "person", person_id)
    flash("Persona desactivada", "info")
    return redirect(url_for("people.index"))


@bp.route("/<int:person_id>/deuda/nueva", methods=["POST"])
def add_debt(person_id):
    """Registrar deuda nueva con esta persona."""
    amount = parse_money(request.form.get("amount"))
    if amount <= 0:
        flash("Monto debe ser mayor a 0", "error")
        return redirect(url_for("people.detail", person_id=person_id))

    data = {
        "person_id": person_id,
        "direction": safe_str(request.form.get("direction")) or "they_owe_me",
        "original_amount": amount,
        "pending_amount": amount,
        "paid_amount": 0,
        "date": safe_str(request.form.get("date")) or today_iso(),
        "expected_date": safe_str(request.form.get("expected_date")) or None,
        "description": safe_str(request.form.get("description")) or None,
        "category_id": safe_int(request.form.get("category_id")) or None,
        "status": "pendiente",
        "notes": safe_str(request.form.get("notes")) or None,
    }
    new_id = db.insert("person_debts", data)
    db.audit("create", "person_debt", new_id, data)
    flash("Deuda registrada", "success")
    return redirect(url_for("people.detail", person_id=person_id))


@bp.route("/deuda/<int:debt_id>/abonar", methods=["POST"])
def add_payment(debt_id):
    """Registrar un abono a una deuda."""
    debt = db.query("SELECT * FROM person_debts WHERE id = ?", (debt_id,), one=True)
    if not debt:
        flash("Deuda no encontrada", "error")
        return redirect(url_for("people.index"))

    amount = parse_money(request.form.get("amount"))
    if amount <= 0:
        flash("Monto del abono debe ser > 0", "error")
        return redirect(url_for("people.detail", person_id=debt["person_id"]))

    # Registrar abono
    db.insert("person_debt_payments", {
        "debt_id": debt_id,
        "amount": amount,
        "date": safe_str(request.form.get("date")) or today_iso(),
        "notes": safe_str(request.form.get("notes")) or None,
    })

    new_paid = (debt["paid_amount"] or 0) + amount
    new_pending = max(0, (debt["original_amount"] or 0) - new_paid)

    if new_pending <= 0:
        new_status = "pagado"
    elif new_paid > 0:
        new_status = "parcial"
    else:
        new_status = "pendiente"

    db.update("person_debts", {
        "paid_amount": new_paid,
        "pending_amount": new_pending,
        "status": new_status,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }, "id = ?", (debt_id,))
    db.audit("payment", "person_debt", debt_id, {"amount": amount,
                                                    "new_pending": new_pending})

    # Si me pagaron y elijo una cuenta, depositar el monto ahí (solo cuando
    # la deuda es a mi favor / me deben).
    account_id = safe_int(request.form.get("account_id")) or None
    deposit_msg = ""
    if account_id and debt["direction"] == "they_owe_me":
        db.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?",
                   (amount, account_id))
        db.insert("transactions", {
            "date": safe_str(request.form.get("date")) or today_iso(),
            "amount": amount, "type": "income", "transaction_type": "normal",
            "description": f"Cobro a {db.query('SELECT name FROM people WHERE id=?', (debt['person_id'],), one=True)['name']}",
            "account_id": account_id, "person_id": debt["person_id"],
            "status": "pagado", "origin": "web",
        })
        deposit_msg = " y depositado en tu cuenta"
    flash(f"Abono de ${amount:,.0f} registrado{deposit_msg}", "success")
    return redirect(url_for("people.detail", person_id=debt["person_id"]))


@bp.route("/deuda/<int:debt_id>/eliminar", methods=["POST"])
def remove_debt(debt_id):
    debt = db.query("SELECT * FROM person_debts WHERE id = ?", (debt_id,), one=True)
    if not debt:
        flash("Deuda no encontrada", "error")
        return redirect(url_for("people.index"))
    person_id = debt["person_id"]
    db.delete("person_debts", "id = ?", (debt_id,))
    db.audit("delete", "person_debt", debt_id)
    flash("Deuda eliminada", "info")
    return redirect(url_for("people.detail", person_id=person_id))


@bp.route("/deuda/<int:debt_id>/cancelar", methods=["POST"])
def cancel_debt(debt_id):
    """Cancelar/condonar una deuda."""
    debt = db.query("SELECT * FROM person_debts WHERE id = ?", (debt_id,), one=True)
    if not debt:
        flash("Deuda no encontrada", "error")
        return redirect(url_for("people.index"))
    db.update("person_debts", {
        "status": "cancelado",
        "pending_amount": 0,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }, "id = ?", (debt_id,))
    db.audit("adjustment", "person_debt", debt_id, {"action": "cancelled"})
    flash("Deuda cancelada", "info")
    return redirect(url_for("people.detail", person_id=debt["person_id"]))
