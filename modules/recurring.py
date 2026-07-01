"""Pagos recurrentes."""
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import db
from modules.helpers import safe_str, safe_float, safe_int, parse_money, today_iso
from modules.uploads import save_image, serve_image

bp = Blueprint("recurring", __name__)

FREQUENCIES = [
    ("monthly", "Mensual"),
    ("weekly", "Semanal"),
    ("biweekly", "Quincenal"),
    ("yearly", "Anual"),
    ("custom", "Personalizado"),
]


@bp.route("/logo/<path:filename>")
def logo(filename):
    return serve_image(filename)


@bp.route("/")
def index():
    payments = db.query("""
        SELECT r.*, c.name AS category_name, c.color AS category_color, c.icon AS category_icon,
               a.name AS account_name,
               cc.name AS card_name,
               p.name AS person_name
        FROM recurring_payments r
        LEFT JOIN categories c ON c.id = r.category_id
        LEFT JOIN accounts a ON a.id = r.account_id
        LEFT JOIN credit_cards cc ON cc.id = r.card_id
        LEFT JOIN people p ON p.id = r.person_id
        ORDER BY r.active DESC, r.day_of_month ASC, r.name ASC
    """)

    # ¿Qué recurrentes ya se pagaron en el mes en curso? Se determina por la
    # transacción enlazada (recurring_id) del mes actual; así el estado se
    # reinicia solo cada mes.
    ym_now = date.today().strftime("%Y-%m")
    paid_rows = db.query("""
        SELECT recurring_id, MAX(id) AS tx_id
        FROM transactions
        WHERE recurring_id IS NOT NULL AND status='pagado'
              AND strftime('%Y-%m', date) = ?
        GROUP BY recurring_id
    """, (ym_now,))
    paid_map = {r["recurring_id"]: r["tx_id"] for r in paid_rows}
    for p in payments:
        # Compatibilidad: pagos antiguos sin enlace usan last_paid_month.
        p["paid_this_month"] = (p["id"] in paid_map) or (p.get("last_paid_month") == ym_now)
        p["paid_tx_id"] = paid_map.get(p["id"])

    today_day = date.today().day
    active = [p for p in payments if p["active"]]
    total_month = sum(p["amount"] for p in active if p["frequency"] == "monthly")
    upcoming = [p for p in active
                if p["day_of_month"] and p["day_of_month"] >= today_day]
    overdue = [p for p in active
               if p["day_of_month"] and p["day_of_month"] < today_day]

    # Agrupar por grupo (Suscripciones, Teléfono, Servicios, ...)
    groups = {}
    for p in payments:
        g = p["group_name"] or "Sin grupo"
        groups.setdefault(g, {"name": g, "rows": [], "total": 0})
        groups[g]["rows"].append(p)
        if p["active"] and p["frequency"] == "monthly":
            groups[g]["total"] += p["amount"] or 0
    grouped = sorted(groups.values(), key=lambda x: (x["name"] == "Sin grupo", x["name"]))

    # Grupos existentes para el datalist del formulario
    group_names = sorted({p["group_name"] for p in payments if p["group_name"]})

    return render_template("recurring.html",
                          payments=payments,
                          grouped=grouped,
                          group_names=group_names,
                          total_month=total_month,
                          active_count=len(active),
                          upcoming_count=len(upcoming),
                          overdue_count=len(overdue))


@bp.route("/nuevo", methods=["GET", "POST"])
def create():
    categories = db.query("SELECT * FROM categories WHERE active=1 ORDER BY name")
    accounts = db.query("SELECT * FROM accounts WHERE status='activa' ORDER BY name")
    cards = db.query("SELECT * FROM credit_cards WHERE status='activa' ORDER BY name")
    people = db.query("SELECT * FROM people WHERE active=1 ORDER BY name")
    group_names = [r["g"] for r in db.query(
        "SELECT DISTINCT group_name AS g FROM recurring_payments WHERE group_name IS NOT NULL ORDER BY g")]

    if request.method == "POST":
        logo_file = save_image(request.files.get("logo"), prefix="rec")
        data = {
            "name": safe_str(request.form.get("name")),
            "category_id": safe_int(request.form.get("category_id")) or None,
            "amount": parse_money(request.form.get("amount")),
            "amount_is_fixed": 1 if request.form.get("amount_is_fixed") else 0,
            "frequency": safe_str(request.form.get("frequency")) or "monthly",
            "day_of_month": safe_int(request.form.get("day_of_month")) or None,
            "account_id": safe_int(request.form.get("account_id")) or None,
            "card_id": safe_int(request.form.get("card_id")) or None,
            "person_id": safe_int(request.form.get("person_id")) or None,
            "is_reimbursable": 1 if request.form.get("is_reimbursable") else 0,
            "group_name": safe_str(request.form.get("group_name")) or None,
            "logo_path": logo_file,
            "active": 1,
            "start_date": safe_str(request.form.get("start_date")) or None,
            "end_date": safe_str(request.form.get("end_date")) or None,
            "notes": safe_str(request.form.get("notes")) or None,
        }
        if not data["name"]:
            flash("El nombre es obligatorio", "error")
            return redirect(url_for("recurring.create"))
        new_id = db.insert("recurring_payments", data)
        db.audit("create", "recurring_payment", new_id, data)
        flash("Pago recurrente creado", "success")
        return redirect(url_for("recurring.index"))

    return render_template("recurring_form.html", payment=None,
                          categories=categories, accounts=accounts,
                          cards=cards, people=people, group_names=group_names,
                          frequencies=FREQUENCIES)


@bp.route("/<int:payment_id>/editar", methods=["GET", "POST"])
def edit(payment_id):
    payment = db.query("SELECT * FROM recurring_payments WHERE id = ?",
                       (payment_id,), one=True)
    if not payment:
        flash("Pago no encontrado", "error")
        return redirect(url_for("recurring.index"))

    categories = db.query("SELECT * FROM categories WHERE active=1 ORDER BY name")
    accounts = db.query("SELECT * FROM accounts ORDER BY name")
    cards = db.query("SELECT * FROM credit_cards ORDER BY name")
    people = db.query("SELECT * FROM people WHERE active=1 ORDER BY name")
    group_names = [r["g"] for r in db.query(
        "SELECT DISTINCT group_name AS g FROM recurring_payments WHERE group_name IS NOT NULL ORDER BY g")]

    if request.method == "POST":
        logo_file = save_image(request.files.get("logo"), prefix="rec")
        data = {
            "name": safe_str(request.form.get("name")),
            "category_id": safe_int(request.form.get("category_id")) or None,
            "amount": parse_money(request.form.get("amount")),
            "amount_is_fixed": 1 if request.form.get("amount_is_fixed") else 0,
            "frequency": safe_str(request.form.get("frequency")) or "monthly",
            "day_of_month": safe_int(request.form.get("day_of_month")) or None,
            "account_id": safe_int(request.form.get("account_id")) or None,
            "card_id": safe_int(request.form.get("card_id")) or None,
            "person_id": safe_int(request.form.get("person_id")) or None,
            "is_reimbursable": 1 if request.form.get("is_reimbursable") else 0,
            "group_name": safe_str(request.form.get("group_name")) or None,
            "active": 1 if request.form.get("active") else 0,
            "start_date": safe_str(request.form.get("start_date")) or None,
            "end_date": safe_str(request.form.get("end_date")) or None,
            "notes": safe_str(request.form.get("notes")) or None,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        if logo_file:
            data["logo_path"] = logo_file
        db.update("recurring_payments", data, "id = ?", (payment_id,))
        db.audit("update", "recurring_payment", payment_id, data)
        flash("Pago actualizado", "success")
        return redirect(url_for("recurring.index"))

    return render_template("recurring_form.html", payment=payment,
                          categories=categories, accounts=accounts,
                          cards=cards, people=people, group_names=group_names,
                          frequencies=FREQUENCIES)


@bp.route("/<int:payment_id>/toggle", methods=["POST"])
def toggle(payment_id):
    p = db.query("SELECT active FROM recurring_payments WHERE id = ?",
                 (payment_id,), one=True)
    if not p:
        return redirect(url_for("recurring.index"))
    db.update("recurring_payments",
              {"active": 0 if p["active"] else 1},
              "id = ?", (payment_id,))
    flash("Estado actualizado", "info")
    return redirect(url_for("recurring.index"))


@bp.route("/<int:payment_id>/registrar-pago", methods=["POST"])
def register_payment(payment_id):
    """Crea una transacción de gasto basada en este pago recurrente."""
    p = db.query("SELECT * FROM recurring_payments WHERE id = ?",
                 (payment_id,), one=True)
    if not p:
        flash("Pago no encontrado", "error")
        return redirect(url_for("recurring.index"))

    the_date = safe_str(request.form.get("date")) or today_iso()
    ym = the_date[:7]
    # Evita marcar dos veces el mismo mes (doble descuento por error).
    already = db.query("""
        SELECT id FROM transactions
        WHERE recurring_id = ? AND status='pagado'
              AND strftime('%Y-%m', date) = ?
    """, (payment_id, ym), one=True)
    if already:
        flash(f"'{p['name']}' ya está marcado como pagado este mes", "info")
        return redirect(url_for("recurring.index"))

    amount = parse_money(request.form.get("amount")) or p["amount"]
    tx_data = {
        "date": the_date,
        "amount": amount,
        "type": "expense",
        "transaction_type": "normal",
        "category_id": p["category_id"],
        "description": f"[Recurrente] {p['name']}",
        "account_id": p["account_id"],
        "card_id": p["card_id"],
        "person_id": p["person_id"],
        "status": "pagado",
        "origin": "web",
        "recurring_id": payment_id,
    }
    new_tx = db.insert("transactions", tx_data)
    db.audit("create", "transaction", new_tx,
              {**tx_data, "from_recurring": payment_id})
    if p["account_id"]:
        db.execute(
            "UPDATE accounts SET balance = balance - ? WHERE id = ?",
            (amount, p["account_id"])
        )
    if p["card_id"]:
        db.execute(
            "UPDATE credit_cards SET used_amount = used_amount + ? WHERE id = ?",
            (amount, p["card_id"])
        )

    # Si es reembolsable (ej. cuenta de un tío que yo pago), generar una
    # cuenta por cobrar para que esa persona me devuelva el monto.
    if p["is_reimbursable"] and p["person_id"]:
        db.insert("person_debts", {
            "person_id": p["person_id"],
            "direction": "they_owe_me",
            "original_amount": amount,
            "pending_amount": amount,
            "paid_amount": 0,
            "date": tx_data["date"],
            "description": f"{p['name']} (pago recurrente)",
            "related_transaction_id": new_tx,
            "status": "pendiente",
        })

    db.update("recurring_payments", {"last_paid_month": ym}, "id = ?", (payment_id,))
    flash("Pago registrado" + (" · cuenta por cobrar creada" if (p["is_reimbursable"] and p["person_id"]) else ""), "success")
    return redirect(url_for("recurring.index"))


@bp.route("/<int:payment_id>/cancelar-pago", methods=["POST"])
def cancel_payment(payment_id):
    """Revierte el pago del mes en curso: elimina la transacción, devuelve el
    saldo a la cuenta (o el cupo a la tarjeta) y quita la cuenta por cobrar
    asociada si aún no tiene abonos. Útil si se marcó por error."""
    p = db.query("SELECT * FROM recurring_payments WHERE id = ?",
                 (payment_id,), one=True)
    if not p:
        flash("Pago no encontrado", "error")
        return redirect(url_for("recurring.index"))

    ym = date.today().strftime("%Y-%m")
    tx = db.query("""
        SELECT * FROM transactions
        WHERE recurring_id = ? AND status='pagado'
              AND strftime('%Y-%m', date) = ?
        ORDER BY id DESC LIMIT 1
    """, (payment_id, ym), one=True)

    if not tx:
        # No hay transacción enlazada (p. ej. pago antiguo): solo limpiar marca.
        if p.get("last_paid_month") == ym:
            db.update("recurring_payments", {"last_paid_month": None},
                      "id = ?", (payment_id,))
            flash("Pago desmarcado", "info")
        else:
            flash("Este pago no está marcado como pagado este mes", "info")
        return redirect(url_for("recurring.index"))

    # Revertir el efecto en la cuenta / tarjeta
    if tx["account_id"]:
        db.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?",
                   (tx["amount"], tx["account_id"]))
    if tx["card_id"]:
        db.execute("UPDATE credit_cards SET used_amount = used_amount - ? WHERE id = ?",
                   (tx["amount"], tx["card_id"]))

    # Quitar la cuenta por cobrar generada si sigue intacta (sin abonos)
    if p["is_reimbursable"] and p["person_id"]:
        db.delete("person_debts",
                  "related_transaction_id = ? AND paid_amount = 0",
                  (tx["id"],))

    db.delete("transactions", "id = ?", (tx["id"],))
    db.audit("delete", "transaction", tx["id"], {"cancel_recurring": payment_id})

    # Si el último mes pagado era este, limpiar la marca
    if p.get("last_paid_month") == ym:
        db.update("recurring_payments", {"last_paid_month": None},
                  "id = ?", (payment_id,))

    flash(f"Pago de '{p['name']}' cancelado · saldo devuelto", "success")
    return redirect(url_for("recurring.index"))


@bp.route("/<int:payment_id>/eliminar", methods=["POST"])
def remove(payment_id):
    db.delete("recurring_payments", "id = ?", (payment_id,))
    db.audit("delete", "recurring_payment", payment_id)
    flash("Pago recurrente eliminado", "info")
    return redirect(url_for("recurring.index"))
