"""Créditos, avances y deudas propias (consumo, avance, súper avance, cuotas)."""
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import db
from modules.helpers import (
    safe_str, safe_float, safe_int, parse_money, parse_date_cl,
    add_months, today_iso
)

bp = Blueprint("loans", __name__)

LOAN_TYPES = [
    ("consumo", "Crédito de consumo"),
    ("automotriz", "Crédito automotriz"),
    ("hipotecario", "Crédito hipotecario"),
    ("avance", "Avance de tarjeta"),
    ("super_avance", "Súper avance (SAV)"),
    ("personal", "Préstamo personal"),
    ("cuotas", "Compra en cuotas"),
    ("otra", "Otra deuda"),
]

LOAN_STATUSES = [
    ("vigente", "Vigente"),
    ("pagada", "Pagada"),
    ("refinanciada", "Refinanciada"),
    ("atrasada", "Atrasada"),
]


def _next_payment_from_installments(loan_id):
    """Devuelve la fecha de la próxima cuota pendiente, o None."""
    row = db.query("""
        SELECT MIN(due_date) AS d FROM loan_installments
        WHERE loan_id = ? AND status != 'pagada'
    """, (loan_id,), one=True)
    return row["d"] if row else None


def _generate_installments(loan_id, total_inst, paid_inst, inst_amount,
                           first_payment_date, payment_day):
    """Crea el calendario de cuotas del crédito (idempotente: borra y recrea)."""
    db.delete("loan_installments", "loan_id = ?", (loan_id,))
    start = parse_date_cl(first_payment_date) or date.today()
    for i in range(1, total_inst + 1):
        due = add_months(start, i - 1)
        if payment_day:
            try:
                due = due.replace(day=min(int(payment_day), 28))
            except (ValueError, TypeError):
                pass
        is_paid = i <= paid_inst
        db.insert("loan_installments", {
            "loan_id": loan_id,
            "installment_number": i,
            "amount": inst_amount,
            "due_date": due.isoformat(),
            "status": "pagada" if is_paid else "pendiente",
            "paid_amount": inst_amount if is_paid else 0,
            "paid_date": due.isoformat() if is_paid else None,
        })


@bp.route("/")
def index():
    loans = db.query("""
        SELECT l.*, b.name AS bank_name, b.color AS bank_color, b.logo_path AS bank_logo,
               cc.name AS card_name
        FROM loans l
        LEFT JOIN banks b ON b.id = l.bank_id
        LEFT JOIN credit_cards cc ON cc.id = l.card_id
        ORDER BY (l.status='vigente') DESC, l.next_payment_date ASC, l.name ASC
    """)
    vigentes = [l for l in loans if l["status"] == "vigente"]
    total_pending = sum(l["pending_amount"] or 0 for l in vigentes)
    total_monthly = sum(l["installment_amount"] or 0 for l in vigentes)
    total_original = sum(l["original_amount"] or 0 for l in loans)
    active_count = len(vigentes)
    return render_template("loans.html",
                          loans=loans,
                          total_pending=total_pending,
                          total_monthly=total_monthly,
                          total_original=total_original,
                          active_count=active_count)


def _read_form():
    """Lee y normaliza los campos del formulario de crédito."""
    original = parse_money(request.form.get("original_amount"))
    total_inst = safe_int(request.form.get("total_installments")) or 1
    paid_inst = safe_int(request.form.get("paid_installments")) or 0
    paid_inst = max(0, min(paid_inst, total_inst))
    inst_amount = parse_money(request.form.get("installment_amount"))
    if not inst_amount and total_inst > 0:
        inst_amount = round(original / total_inst) if original else 0

    pending_inst = max(0, total_inst - paid_inst)
    # El monto pendiente real = valor cuota * cuotas que faltan
    # (puede diferir del monto solicitado, sobre todo en créditos con interés).
    pending = parse_money(request.form.get("pending_amount"))
    if not pending:
        pending = round(inst_amount * pending_inst)

    payment_day = safe_int(request.form.get("payment_day")) or None
    first_pay = safe_str(request.form.get("first_payment_date")) or None

    data = {
        "name": safe_str(request.form.get("name")),
        "entity": safe_str(request.form.get("entity")) or None,
        "bank_id": safe_int(request.form.get("bank_id")) or None,
        "card_id": safe_int(request.form.get("card_id")) or None,
        "billed_in_card": 1 if request.form.get("billed_in_card") else 0,
        "type": safe_str(request.form.get("type")) or "consumo",
        "original_amount": original,
        "pending_amount": pending,
        "total_installments": total_inst,
        "paid_installments": paid_inst,
        "pending_installments": pending_inst,
        "installment_amount": inst_amount,
        "first_payment_date": first_pay,
        "payment_day": payment_day,
        "interest_rate": safe_float(request.form.get("interest_rate")) or None,
        "status": safe_str(request.form.get("status")) or "vigente",
        "notes": safe_str(request.form.get("notes")) or None,
    }
    return data


def _form_context():
    banks = db.query("SELECT * FROM banks WHERE active=1 ORDER BY name")
    cards = db.query("""SELECT c.*, b.name AS bank_name FROM credit_cards c
                        LEFT JOIN banks b ON b.id=c.bank_id
                        WHERE c.status='activa' ORDER BY c.name""")
    return banks, cards


@bp.route("/nuevo", methods=["GET", "POST"])
def create():
    banks, cards = _form_context()
    if request.method == "POST":
        data = _read_form()
        if not data["name"]:
            flash("El nombre es obligatorio", "error")
            return redirect(url_for("loans.create"))

        generate = bool(request.form.get("generate_installments"))
        new_id = db.insert("loans", data)
        db.audit("create", "loan", new_id, data)

        if generate and data["first_payment_date"]:
            _generate_installments(
                new_id, data["total_installments"], data["paid_installments"],
                data["installment_amount"], data["first_payment_date"],
                data["payment_day"])
            db.update("loans",
                      {"next_payment_date": _next_payment_from_installments(new_id)},
                      "id = ?", (new_id,))

        flash("Crédito registrado", "success")
        return redirect(url_for("loans.detail", loan_id=new_id))

    return render_template("loans_form.html", loan=None, banks=banks, cards=cards,
                          types=LOAN_TYPES, statuses=LOAN_STATUSES)


@bp.route("/<int:loan_id>")
def detail(loan_id):
    loan = db.query("""
        SELECT l.*, b.name AS bank_name, b.color AS bank_color, b.logo_path AS bank_logo,
               cc.name AS card_name
        FROM loans l
        LEFT JOIN banks b ON b.id = l.bank_id
        LEFT JOIN credit_cards cc ON cc.id = l.card_id
        WHERE l.id = ?
    """, (loan_id,), one=True)
    if not loan:
        flash("Crédito no encontrado", "error")
        return redirect(url_for("loans.index"))

    installments = db.query("""
        SELECT * FROM loan_installments
        WHERE loan_id = ?
        ORDER BY installment_number
    """, (loan_id,))

    pct = round(
        (loan["paid_installments"] / loan["total_installments"] * 100), 1
    ) if loan["total_installments"] else 0

    next_inst = next((i for i in installments if i["status"] != "pagada"), None)

    return render_template("loans_detail.html",
                          loan=loan,
                          installments=installments,
                          next_inst=next_inst,
                          pct=pct)


@bp.route("/<int:loan_id>/editar", methods=["GET", "POST"])
def edit(loan_id):
    loan = db.query("SELECT * FROM loans WHERE id = ?", (loan_id,), one=True)
    if not loan:
        flash("Crédito no encontrado", "error")
        return redirect(url_for("loans.index"))
    banks, cards = _form_context()

    if request.method == "POST":
        data = _read_form()
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        db.update("loans", data, "id = ?", (loan_id,))
        db.audit("update", "loan", loan_id, data)

        # Regenerar calendario si lo pide
        if request.form.get("generate_installments") and data["first_payment_date"]:
            _generate_installments(
                loan_id, data["total_installments"], data["paid_installments"],
                data["installment_amount"], data["first_payment_date"],
                data["payment_day"])
            db.update("loans",
                      {"next_payment_date": _next_payment_from_installments(loan_id)},
                      "id = ?", (loan_id,))

        flash("Crédito actualizado", "success")
        return redirect(url_for("loans.detail", loan_id=loan_id))

    return render_template("loans_form.html", loan=loan, banks=banks, cards=cards,
                          types=LOAN_TYPES, statuses=LOAN_STATUSES)


@bp.route("/<int:loan_id>/eliminar", methods=["POST"])
def remove(loan_id):
    db.delete("loans", "id = ?", (loan_id,))
    db.audit("delete", "loan", loan_id)
    flash("Crédito eliminado", "info")
    return redirect(url_for("loans.index"))


@bp.route("/<int:loan_id>/pagar", methods=["GET"])
def pay_page(loan_id):
    """Página tipo 'Pagar mi crédito': muestra la próxima cuota a pagar."""
    loan = db.query("""
        SELECT l.*, b.name AS bank_name, b.color AS bank_color, b.logo_path AS bank_logo
        FROM loans l LEFT JOIN banks b ON b.id = l.bank_id
        WHERE l.id = ?
    """, (loan_id,), one=True)
    if not loan:
        flash("Crédito no encontrado", "error")
        return redirect(url_for("loans.index"))

    next_inst = db.query("""
        SELECT * FROM loan_installments
        WHERE loan_id = ? AND status != 'pagada'
        ORDER BY installment_number ASC LIMIT 1
    """, (loan_id,), one=True)

    accounts = db.query("""SELECT a.*, b.name AS bank_name FROM accounts a
                           LEFT JOIN banks b ON b.id=a.bank_id
                           WHERE a.status='activa' ORDER BY a.balance DESC""")

    return render_template("loans_pay.html", loan=loan, inst=next_inst,
                          accounts=accounts)


@bp.route("/cuota/<int:inst_id>/pagar", methods=["POST"])
def pay_installment(inst_id):
    inst = db.query("SELECT * FROM loan_installments WHERE id = ?",
                    (inst_id,), one=True)
    if not inst:
        flash("Cuota no encontrada", "error")
        return redirect(url_for("loans.index"))

    account_id = safe_int(request.form.get("account_id")) or None
    db.update("loan_installments", {
        "status": "pagada",
        "paid_amount": inst["amount"],
        "paid_date": safe_str(request.form.get("date")) or today_iso(),
    }, "id = ?", (inst_id,))

    loan = db.query("SELECT * FROM loans WHERE id = ?", (inst["loan_id"],), one=True)
    # Recontar cuotas pagadas/pendientes desde la tabla (más robusto)
    counts = db.query("""
        SELECT
          SUM(CASE WHEN status='pagada' THEN 1 ELSE 0 END) AS paid,
          SUM(CASE WHEN status!='pagada' THEN 1 ELSE 0 END) AS pending,
          COALESCE(SUM(CASE WHEN status!='pagada' THEN amount ELSE 0 END),0) AS pending_amount
        FROM loan_installments WHERE loan_id = ?
    """, (loan["id"],), one=True)
    new_paid = counts["paid"] or 0
    new_pending = counts["pending"] or 0
    new_pending_amount = counts["pending_amount"] or 0
    new_status = "pagada" if new_pending == 0 else loan["status"]

    db.update("loans", {
        "paid_installments": new_paid,
        "pending_installments": new_pending,
        "pending_amount": new_pending_amount,
        "next_payment_date": _next_payment_from_installments(loan["id"]),
        "status": new_status,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }, "id = ?", (loan["id"],))

    # Descontar de la cuenta elegida (registrando un gasto)
    if account_id:
        db.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?",
                   (inst["amount"], account_id))
        db.insert("transactions", {
            "date": today_iso(),
            "amount": inst["amount"],
            "type": "expense",
            "transaction_type": "debt_payment",
            "description": f"Cuota {inst['installment_number']} · {loan['name']}",
            "account_id": account_id,
            "status": "pagado",
            "origin": "web",
        })

    # Si el crédito se factura en una tarjeta, al pagar la cuota se libera
    # cupo: bajamos el "usado" de la tarjeta (puedes ajustarlo manualmente
    # después si el banco muestra otro cupo por capital + intereses).
    if loan["card_id"]:
        db.execute(
            "UPDATE credit_cards SET used_amount = MAX(0, used_amount - ?) WHERE id = ?",
            (inst["amount"], loan["card_id"]))

    db.audit("payment", "loan_installment", inst_id,
             {"amount": inst["amount"], "account_id": account_id})
    flash(f"Cuota {inst['installment_number']} pagada", "success")
    return redirect(url_for("loans.detail", loan_id=loan["id"]))
