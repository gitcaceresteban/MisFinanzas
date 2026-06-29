"""Cuentas del hogar y división entre personas."""
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import db
from modules.helpers import safe_str, safe_float, safe_int, parse_money, today_iso

bp = Blueprint("household", __name__)

SPLIT_TYPES = [
    ("equal", "Partes iguales"),
    ("fixed", "Monto fijo por persona"),
    ("percent", "Porcentaje por persona"),
    ("custom", "Personalizado"),
]


@bp.route("/")
def index():
    bills = db.query("""
        SELECT b.*,
               c.name AS category_name, c.color AS category_color, c.icon AS category_icon,
               p.name AS paid_by_name,
               (SELECT COUNT(*) FROM household_bill_participants hbp
                 WHERE hbp.bill_id = b.id) AS participants_count,
               (SELECT COALESCE(SUM(hbp.paid_amount),0)
                  FROM household_bill_participants hbp
                  WHERE hbp.bill_id = b.id) AS total_paid_by_others,
               (SELECT COALESCE(SUM(hbp.share_amount - hbp.paid_amount), 0)
                  FROM household_bill_participants hbp
                  WHERE hbp.bill_id = b.id) AS pending_to_collect
        FROM household_bills b
        LEFT JOIN categories c ON c.id = b.category_id
        LEFT JOIN people p ON p.id = b.paid_by_person_id
        ORDER BY b.status ASC, b.due_date DESC
    """)

    total_paid_by_me = sum(b["amount"] for b in bills
                          if not b["paid_by_person_id"] and b["status"] == "pagada")
    total_pending_amount = sum(b["amount"] for b in bills
                       if b["status"] in ("pendiente", "parcial", "vencida"))
    total_pending_count = sum(1 for b in bills
                       if b["status"] in ("pendiente", "parcial", "vencida"))
    total_to_collect = sum(b["pending_to_collect"] for b in bills
                       if b["status"] in ("pendiente", "parcial", "vencida"))
    # Pagadas este mes
    from datetime import date
    ym = date.today().strftime("%Y-%m")
    total_paid_month = sum(b["amount"] for b in bills
                          if b["status"] == "pagada"
                          and b.get("paid_date") and b["paid_date"].startswith(ym))
    return render_template("household.html", bills=bills,
                          total_paid_by_me=total_paid_by_me,
                          total_pending=total_pending_amount,
                          total_pending_amount=total_pending_amount,
                          total_pending_count=total_pending_count,
                          total_to_collect=total_to_collect,
                          total_paid_month=total_paid_month)


@bp.route("/nueva", methods=["GET", "POST"])
def create():
    categories = db.query("SELECT * FROM categories WHERE active=1 ORDER BY name")
    people = db.query("SELECT * FROM people WHERE active=1 ORDER BY name")
    accounts = db.query("SELECT * FROM accounts WHERE status='activa' ORDER BY name")

    if request.method == "POST":
        data = {
            "name": safe_str(request.form.get("name")),
            "category_id": safe_int(request.form.get("category_id")) or None,
            "amount": parse_money(request.form.get("amount")),
            "due_date": safe_str(request.form.get("due_date")) or None,
            "paid_by_person_id": safe_int(request.form.get("paid_by_person_id")) or None,
            "paid_from_account_id": safe_int(request.form.get("paid_from_account_id")) or None,
            "split_type": safe_str(request.form.get("split_type")) or "equal",
            "status": "pendiente",
            "notes": safe_str(request.form.get("notes")) or None,
        }
        if not data["name"] or data["amount"] <= 0:
            flash("Nombre y monto son obligatorios", "error")
            return redirect(url_for("household.create"))

        new_id = db.insert("household_bills", data)
        db.audit("create", "household_bill", new_id, data)

        # Procesar participantes
        person_ids = request.form.getlist("participant_ids[]")
        shares = request.form.getlist("participant_shares[]")
        split = data["split_type"]
        total_amount = data["amount"]
        n = len([p for p in person_ids if safe_int(p) > 0])
        for i, pid in enumerate(person_ids):
            pid_int = safe_int(pid)
            if pid_int <= 0:
                continue
            share_amt = 0
            share_pct = None
            if split == "equal" and n > 0:
                share_amt = round(total_amount / n)
            elif split == "fixed":
                share_amt = parse_money(shares[i] if i < len(shares) else 0)
            elif split == "percent":
                share_pct = safe_float(shares[i] if i < len(shares) else 0)
                share_amt = round(total_amount * share_pct / 100)
            else:  # custom
                share_amt = parse_money(shares[i] if i < len(shares) else 0)

            db.insert("household_bill_participants", {
                "bill_id": new_id,
                "person_id": pid_int,
                "share_amount": share_amt,
                "share_percent": share_pct,
                "paid_amount": 0,
                "status": "pendiente",
            })
        flash("Cuenta del hogar registrada", "success")
        return redirect(url_for("household.detail", bill_id=new_id))

    return render_template("household_form.html", bill=None,
                          categories=categories, people=people,
                          accounts=accounts, split_types=SPLIT_TYPES,
                          participants=[])


@bp.route("/<int:bill_id>")
def detail(bill_id):
    bill = db.query("""
        SELECT b.*, c.name AS category_name, c.color AS category_color,
               p.name AS paid_by_name
        FROM household_bills b
        LEFT JOIN categories c ON c.id = b.category_id
        LEFT JOIN people p ON p.id = b.paid_by_person_id
        WHERE b.id = ?
    """, (bill_id,), one=True)
    if not bill:
        flash("Cuenta no encontrada", "error")
        return redirect(url_for("household.index"))

    participants = db.query("""
        SELECT hbp.*, pe.name AS person_name
        FROM household_bill_participants hbp
        JOIN people pe ON pe.id = hbp.person_id
        WHERE hbp.bill_id = ?
        ORDER BY pe.name
    """, (bill_id,))

    accounts = db.query("""SELECT a.*, b.name AS bank_name FROM accounts a
                           LEFT JOIN banks b ON b.id=a.bank_id
                           WHERE a.status='activa' ORDER BY a.name""")

    bill = dict(bill)
    bill["amount_collected"] = sum(p["paid_amount"] or 0 for p in participants)
    bill["pending_to_collect"] = sum(
        max(0, (p["share_amount"] or 0) - (p["paid_amount"] or 0)) for p in participants)
    bill["amount_paid_by_me"] = bill["amount"] if not bill["paid_by_person_id"] else 0

    return render_template("household_detail.html", bill=bill,
                          participants=participants, accounts=accounts)


@bp.route("/<int:bill_id>/editar", methods=["GET", "POST"])
def edit(bill_id):
    bill = db.query("SELECT * FROM household_bills WHERE id = ?", (bill_id,), one=True)
    if not bill:
        flash("Cuenta no encontrada", "error")
        return redirect(url_for("household.index"))
    categories = db.query("SELECT * FROM categories WHERE active=1 ORDER BY name")
    people = db.query("SELECT * FROM people WHERE active=1 ORDER BY name")
    accounts = db.query("SELECT * FROM accounts ORDER BY name")
    participants = db.query("""
        SELECT * FROM household_bill_participants WHERE bill_id = ?
    """, (bill_id,))

    if request.method == "POST":
        data = {
            "name": safe_str(request.form.get("name")),
            "category_id": safe_int(request.form.get("category_id")) or None,
            "amount": parse_money(request.form.get("amount")),
            "due_date": safe_str(request.form.get("due_date")) or None,
            "paid_by_person_id": safe_int(request.form.get("paid_by_person_id")) or None,
            "paid_from_account_id": safe_int(request.form.get("paid_from_account_id")) or None,
            "split_type": safe_str(request.form.get("split_type")) or "equal",
            "notes": safe_str(request.form.get("notes")) or None,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        db.update("household_bills", data, "id = ?", (bill_id,))
        db.audit("update", "household_bill", bill_id, data)

        # Recrear participantes
        db.delete("household_bill_participants", "bill_id = ?", (bill_id,))
        person_ids = request.form.getlist("participant_ids[]")
        shares = request.form.getlist("participant_shares[]")
        split = data["split_type"]
        n = len([p for p in person_ids if safe_int(p) > 0])
        for i, pid in enumerate(person_ids):
            pid_int = safe_int(pid)
            if pid_int <= 0:
                continue
            share_amt = 0
            share_pct = None
            if split == "equal" and n > 0:
                share_amt = round(data["amount"] / n)
            elif split == "fixed":
                share_amt = parse_money(shares[i] if i < len(shares) else 0)
            elif split == "percent":
                share_pct = safe_float(shares[i] if i < len(shares) else 0)
                share_amt = round(data["amount"] * share_pct / 100)
            else:
                share_amt = parse_money(shares[i] if i < len(shares) else 0)
            db.insert("household_bill_participants", {
                "bill_id": bill_id,
                "person_id": pid_int,
                "share_amount": share_amt,
                "share_percent": share_pct,
                "paid_amount": 0,
                "status": "pendiente",
            })
        flash("Cuenta actualizada", "success")
        return redirect(url_for("household.detail", bill_id=bill_id))

    return render_template("household_form.html", bill=bill,
                          categories=categories, people=people,
                          accounts=accounts, split_types=SPLIT_TYPES,
                          participants=participants)


@bp.route("/<int:bill_id>/marcar-pagada", methods=["POST"])
def mark_paid(bill_id):
    bill = db.query("SELECT * FROM household_bills WHERE id = ?", (bill_id,), one=True)
    if not bill:
        flash("Cuenta no encontrada", "error")
        return redirect(url_for("household.index"))
    db.audit("payment", "household_bill", bill_id)

    if bill["is_recurring"]:
        # Cuenta recurrente: avanza al próximo mes (siempre la misma, vence el día N)
        from datetime import date
        from modules.helpers import add_months, parse_date_cl
        base = parse_date_cl(bill["due_date"]) or date.today()
        nxt = add_months(base, 1)
        day = bill["recurring_day"] or 5
        try:
            nxt = nxt.replace(day=min(int(day), 28))
        except (ValueError, TypeError):
            pass
        db.update("household_bills", {
            "status": "pendiente",
            "due_date": nxt.isoformat(),
            "paid_date": None,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }, "id = ?", (bill_id,))
        db.update("household_bill_participants",
                  {"paid_amount": 0, "status": "pendiente"}, "bill_id = ?", (bill_id,))
        flash(f"Pagada. Próximo vencimiento: {nxt.strftime('%d/%m/%Y')}", "success")
    else:
        db.update("household_bills", {
            "status": "pagada",
            "paid_date": today_iso(),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }, "id = ?", (bill_id,))
        flash("Cuenta marcada como pagada", "success")
    return redirect(url_for("household.detail", bill_id=bill_id))


@bp.route("/participante/<int:participant_id>/abonar", methods=["POST"])
def participant_payment(participant_id):
    """Registrar abono de un participante."""
    p = db.query("SELECT * FROM household_bill_participants WHERE id = ?",
                 (participant_id,), one=True)
    if not p:
        flash("Participante no encontrado", "error")
        return redirect(url_for("household.index"))
    amount = parse_money(request.form.get("amount"))
    new_paid = (p["paid_amount"] or 0) + amount
    if new_paid >= p["share_amount"]:
        new_status = "pagado"
    elif new_paid > 0:
        new_status = "parcial"
    else:
        new_status = "pendiente"
    db.update("household_bill_participants", {
        "paid_amount": new_paid,
        "status": new_status,
    }, "id = ?", (participant_id,))
    db.audit("payment", "household_bill_participant", participant_id,
              {"amount": amount})

    # Si me lo depositan en una cuenta, sumarlo al saldo
    account_id = safe_int(request.form.get("account_id")) or None
    if account_id and amount > 0:
        db.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?",
                   (amount, account_id))
        db.insert("transactions", {
            "date": today_iso(), "amount": amount, "type": "income",
            "transaction_type": "normal",
            "description": "Aporte cuenta del hogar",
            "account_id": account_id, "person_id": p["person_id"],
            "status": "pagado", "origin": "web",
        })

    # Recalcular estado global de la cuenta
    all_p = db.query("""
        SELECT status FROM household_bill_participants WHERE bill_id = ?
    """, (p["bill_id"],))
    if all(x["status"] == "pagado" for x in all_p):
        bill_status = "pagada"
    elif any(x["status"] in ("parcial", "pagado") for x in all_p):
        bill_status = "parcial"
    else:
        bill_status = "pendiente"
    db.update("household_bills", {"status": bill_status}, "id = ?", (p["bill_id"],))

    flash(f"Abono de ${amount:,.0f} registrado", "success")
    return redirect(url_for("household.detail", bill_id=p["bill_id"]))


@bp.route("/<int:bill_id>/eliminar", methods=["POST"])
def remove(bill_id):
    db.delete("household_bills", "id = ?", (bill_id,))
    db.audit("delete", "household_bill", bill_id)
    flash("Cuenta eliminada", "info")
    return redirect(url_for("household.index"))
