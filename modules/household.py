"""Cuentas del hogar: división entre personas, cuotas mensuales y abonos."""
import uuid
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import db
from modules.helpers import (
    safe_str, safe_float, safe_int, parse_money, today_iso,
    add_months, parse_date_cl, month_name_es,
)
from modules.uploads import save_image, serve_image

bp = Blueprint("household", __name__)

SPLIT_TYPES = [
    ("equal", "Partes iguales"),
    ("fixed", "Monto fijo por persona"),
    ("percent", "Porcentaje por persona"),
    ("custom", "Personalizado"),
]


@bp.route("/logo/<path:filename>")
def logo(filename):
    return serve_image(filename)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _split_amounts(total, n):
    """Reparte 'total' en n cuotas enteras (la última absorbe el resto)."""
    if n <= 1:
        return [total]
    base = round(total / n)
    parts = [base] * (n - 1)
    parts.append(round(total - base * (n - 1)))
    return parts


def _create_participants(bill_id, amount, split, person_ids, shares):
    """Crea los participantes de una cuenta con su parte según el tipo de división."""
    valid = [safe_int(p) for p in person_ids if safe_int(p) > 0]
    n = len(valid)
    for i, pid in enumerate(person_ids):
        pid_int = safe_int(pid)
        if pid_int <= 0:
            continue
        share_amt = 0
        share_pct = None
        raw = shares[i] if i < len(shares) else 0
        if split == "equal" and n > 0:
            share_amt = round(amount / n)
        elif split == "fixed":
            share_amt = parse_money(raw)
        elif split == "percent":
            share_pct = safe_float(raw)
            share_amt = round(amount * share_pct / 100)
        else:  # custom
            share_amt = parse_money(raw)
        db.insert("household_bill_participants", {
            "bill_id": bill_id,
            "person_id": pid_int,
            "share_amount": share_amt,
            "share_percent": share_pct,
            "paid_amount": 0,
            "status": "pendiente",
        })


def _bill_collection(bill):
    """Devuelve (por_cobrar, abonado, pendiente) de una cuenta.

    Si tiene participantes, lo que me deben es la suma de sus partes; si no,
    se considera que el monto completo es lo que me deben.
    """
    pc = bill.get("participants_count") or 0
    if pc > 0:
        por_cobrar = bill.get("sum_shares") or 0
        abonado = bill.get("sum_paid") or 0
    else:
        por_cobrar = bill.get("amount") or 0
        abonado = bill.get("collected_amount") or 0
    pendiente = max(0, por_cobrar - abonado)
    return por_cobrar, abonado, pendiente


def _recalc_bill_status(bill_id):
    """Recalcula el estado de la cuenta a partir de abonos/participantes."""
    bill = db.query("""
        SELECT b.*,
               (SELECT COUNT(*) FROM household_bill_participants hbp WHERE hbp.bill_id=b.id) AS participants_count,
               (SELECT COALESCE(SUM(share_amount),0) FROM household_bill_participants hbp WHERE hbp.bill_id=b.id) AS sum_shares,
               (SELECT COALESCE(SUM(paid_amount),0) FROM household_bill_participants hbp WHERE hbp.bill_id=b.id) AS sum_paid
        FROM household_bills b WHERE b.id=?
    """, (bill_id,), one=True)
    if not bill:
        return
    por_cobrar, abonado, pendiente = _bill_collection(bill)
    if por_cobrar > 0 and pendiente <= 0:
        status = "pagada"
    elif abonado > 0:
        status = "parcial"
    else:
        status = bill["status"] if bill["status"] == "vencida" else "pendiente"
    db.update("household_bills", {
        "status": status,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }, "id = ?", (bill_id,))


# ----------------------------------------------------------------------
# Vistas
# ----------------------------------------------------------------------
@bp.route("/")
def index():
    bills = db.query("""
        SELECT b.*,
               c.name AS category_name, c.color AS category_color, c.icon AS category_icon,
               p.name AS paid_by_name,
               (SELECT COUNT(*) FROM household_bill_participants hbp
                 WHERE hbp.bill_id = b.id) AS participants_count,
               (SELECT COALESCE(SUM(hbp.share_amount),0) FROM household_bill_participants hbp
                 WHERE hbp.bill_id = b.id) AS sum_shares,
               (SELECT COALESCE(SUM(hbp.paid_amount),0) FROM household_bill_participants hbp
                 WHERE hbp.bill_id = b.id) AS sum_paid
        FROM household_bills b
        LEFT JOIN categories c ON c.id = b.category_id
        LEFT JOIN people p ON p.id = b.paid_by_person_id
        ORDER BY b.due_date ASC, b.name ASC
    """)

    # Enriquecer cada cuenta con su cobro y agrupar por mes
    groups = {}
    for b in bills:
        por_cobrar, abonado, pendiente = _bill_collection(b)
        b["por_cobrar"] = por_cobrar
        b["abonado"] = abonado
        b["pendiente"] = pendiente

        if b.get("due_date"):
            d = parse_date_cl(b["due_date"])
            if d:
                key = f"{d.year}-{d.month:02d}"
                label = f"{month_name_es(d.month)} {d.year}"
                sort_key = key
            else:
                key, label, sort_key = "sin-fecha", "Sin fecha", "9999-99"
        else:
            key, label, sort_key = "sin-fecha", "Sin fecha", "9999-99"

        g = groups.setdefault(key, {
            "key": key, "label": label, "sort": sort_key, "bills": [],
            "cargos": 0, "por_cobrar": 0, "abonado": 0, "neto": 0,
            "pending_count": 0,
        })
        g["bills"].append(b)
        g["cargos"] += b["amount"] or 0
        g["por_cobrar"] += por_cobrar
        g["abonado"] += abonado
        g["neto"] += pendiente
        if b["status"] in ("pendiente", "parcial", "vencida"):
            g["pending_count"] += 1

    grouped = sorted(groups.values(), key=lambda x: x["sort"])

    # Totales globales (cards superiores)
    total_pending_amount = sum(b["amount"] for b in bills
                       if b["status"] in ("pendiente", "parcial", "vencida"))
    total_pending_count = sum(1 for b in bills
                       if b["status"] in ("pendiente", "parcial", "vencida"))
    total_to_collect = sum(b["pendiente"] for b in bills)
    ym = date.today().strftime("%Y-%m")
    total_paid_month = sum(b["amount"] for b in bills
                          if b["status"] == "pagada"
                          and b.get("paid_date") and b["paid_date"].startswith(ym))

    return render_template("household.html", bills=bills, grouped=grouped,
                          current_ym=ym,
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
        logo_file = save_image(request.files.get("logo"), prefix="hogar")
        name = safe_str(request.form.get("name"))
        amount = parse_money(request.form.get("amount"))
        category_id = safe_int(request.form.get("category_id")) or None
        due_date = safe_str(request.form.get("due_date")) or None
        paid_by = safe_int(request.form.get("paid_by_person_id")) or None
        paid_from = safe_int(request.form.get("paid_from_account_id")) or None
        split = safe_str(request.form.get("split_type")) or "equal"
        notes = safe_str(request.form.get("notes")) or None
        n_inst = max(1, safe_int(request.form.get("installments_total")) or 1)

        if not name or amount <= 0:
            flash("Nombre y monto son obligatorios", "error")
            return redirect(url_for("household.create"))

        person_ids = request.form.getlist("participant_ids[]")
        shares = request.form.getlist("participant_shares[]")

        base = parse_date_cl(due_date) if due_date else date.today()
        amounts = _split_amounts(amount, n_inst)
        series_id = uuid.uuid4().hex if n_inst > 1 else None
        first_id = None

        for i in range(n_inst):
            inst_due = add_months(base, i) if base else None
            inst_name = name if n_inst == 1 else f"{name} (cuota {i+1}/{n_inst})"
            data = {
                "name": inst_name,
                "category_id": category_id,
                "amount": amounts[i],
                "due_date": inst_due.isoformat() if inst_due else None,
                "paid_by_person_id": paid_by,
                "paid_from_account_id": paid_from,
                "split_type": split,
                "status": "pendiente",
                "logo_path": logo_file,
                "installments_total": n_inst,
                "installment_number": i + 1,
                "series_id": series_id,
                "collected_amount": 0,
                "notes": notes,
            }
            new_id = db.insert("household_bills", data)
            if first_id is None:
                first_id = new_id
            db.audit("create", "household_bill", new_id, data)
            _create_participants(new_id, amounts[i], split, person_ids, shares)

        if n_inst > 1:
            flash(f"Cuenta creada en {n_inst} cuotas mensuales", "success")
            return redirect(url_for("household.index"))
        flash("Cuenta del hogar registrada", "success")
        return redirect(url_for("household.detail", bill_id=first_id))

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

    payments = db.query("""
        SELECT hp.*, pe.name AS person_name, a.name AS account_name
        FROM household_bill_payments hp
        LEFT JOIN people pe ON pe.id = hp.person_id
        LEFT JOIN accounts a ON a.id = hp.account_id
        WHERE hp.bill_id = ?
        ORDER BY hp.date DESC, hp.id DESC
    """, (bill_id,))

    accounts = db.query("""SELECT a.*, b.name AS bank_name FROM accounts a
                           LEFT JOIN banks b ON b.id=a.bank_id
                           WHERE a.status='activa' ORDER BY a.name""")

    # Otras cuotas de la misma compra (serie)
    series = []
    if bill.get("series_id"):
        series = db.query("""
            SELECT id, name, amount, due_date, status, installment_number
            FROM household_bills WHERE series_id = ? ORDER BY installment_number
        """, (bill["series_id"],))

    bill = dict(bill)
    bill["participants_count"] = len(participants)
    bill["sum_shares"] = sum(p["share_amount"] or 0 for p in participants)
    bill["sum_paid"] = sum(p["paid_amount"] or 0 for p in participants)
    por_cobrar, abonado, pendiente = _bill_collection(bill)
    bill["por_cobrar"] = por_cobrar
    bill["abonado"] = abonado
    bill["pendiente"] = pendiente
    bill["amount_paid_by_me"] = bill["amount"] if not bill["paid_by_person_id"] else 0

    return render_template("household_detail.html", bill=bill,
                          participants=participants, accounts=accounts,
                          payments=payments, series=series)


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
        logo_file = save_image(request.files.get("logo"), prefix="hogar")
        amount = parse_money(request.form.get("amount"))
        split = safe_str(request.form.get("split_type")) or "equal"
        data = {
            "name": safe_str(request.form.get("name")),
            "category_id": safe_int(request.form.get("category_id")) or None,
            "amount": amount,
            "due_date": safe_str(request.form.get("due_date")) or None,
            "paid_by_person_id": safe_int(request.form.get("paid_by_person_id")) or None,
            "paid_from_account_id": safe_int(request.form.get("paid_from_account_id")) or None,
            "split_type": split,
            "notes": safe_str(request.form.get("notes")) or None,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        if logo_file:
            data["logo_path"] = logo_file
        db.update("household_bills", data, "id = ?", (bill_id,))
        db.audit("update", "household_bill", bill_id, data)

        # Recrear participantes
        db.delete("household_bill_participants", "bill_id = ?", (bill_id,))
        person_ids = request.form.getlist("participant_ids[]")
        shares = request.form.getlist("participant_shares[]")
        _create_participants(bill_id, amount, split, person_ids, shares)
        _recalc_bill_status(bill_id)
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
            "collected_amount": 0,
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


def _apply_abono(bill_id, amount, the_date, account_id, participant_id=None, person_id=None):
    """Registra un abono: historial, participante (si aplica), cuenta y estado."""
    if amount <= 0:
        return
    # Si abona un participante, sumar a su pagado
    if participant_id:
        part = db.query("SELECT * FROM household_bill_participants WHERE id=?",
                        (participant_id,), one=True)
        if part:
            new_paid = (part["paid_amount"] or 0) + amount
            if new_paid >= (part["share_amount"] or 0):
                p_status = "pagado"
            elif new_paid > 0:
                p_status = "parcial"
            else:
                p_status = "pendiente"
            db.update("household_bill_participants",
                      {"paid_amount": new_paid, "status": p_status},
                      "id = ?", (participant_id,))
            person_id = person_id or part["person_id"]

    # Acumulado a nivel de cuenta (fuente única para cuentas sin participantes)
    db.execute("UPDATE household_bills SET collected_amount = COALESCE(collected_amount,0) + ? WHERE id = ?",
               (amount, bill_id))

    # Historial del abono
    db.insert("household_bill_payments", {
        "bill_id": bill_id,
        "participant_id": participant_id,
        "person_id": person_id,
        "amount": amount,
        "date": the_date,
        "account_id": account_id,
        "notes": None,
    })

    # Si me lo depositan en una cuenta, sumarlo al saldo + registrar ingreso
    if account_id:
        db.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?",
                   (amount, account_id))
        db.insert("transactions", {
            "date": the_date, "amount": amount, "type": "income",
            "transaction_type": "normal",
            "description": "Abono cuenta del hogar",
            "account_id": account_id, "person_id": person_id,
            "status": "pagado", "origin": "web",
        })

    db.audit("payment", "household_bill", bill_id, {"amount": amount})
    _recalc_bill_status(bill_id)


@bp.route("/participante/<int:participant_id>/abonar", methods=["POST"])
def participant_payment(participant_id):
    """Registrar abono de un participante."""
    p = db.query("SELECT * FROM household_bill_participants WHERE id = ?",
                 (participant_id,), one=True)
    if not p:
        flash("Participante no encontrado", "error")
        return redirect(url_for("household.index"))
    amount = parse_money(request.form.get("amount"))
    the_date = safe_str(request.form.get("date")) or today_iso()
    account_id = safe_int(request.form.get("account_id")) or None
    _apply_abono(p["bill_id"], amount, the_date, account_id,
                 participant_id=participant_id, person_id=p["person_id"])
    flash(f"Abono de ${amount:,.0f} registrado".replace(",", "."), "success")
    return redirect(url_for("household.detail", bill_id=p["bill_id"]))


@bp.route("/<int:bill_id>/abonar", methods=["POST"])
def bill_payment(bill_id):
    """Registrar un abono directamente sobre la cuenta (sin elegir participante)."""
    bill = db.query("SELECT * FROM household_bills WHERE id = ?", (bill_id,), one=True)
    if not bill:
        flash("Cuenta no encontrada", "error")
        return redirect(url_for("household.index"))
    amount = parse_money(request.form.get("amount"))
    the_date = safe_str(request.form.get("date")) or today_iso()
    account_id = safe_int(request.form.get("account_id")) or None
    person_id = safe_int(request.form.get("person_id")) or None

    # Si hay un único participante, atribuir el abono a él automáticamente.
    participant_id = None
    parts = db.query("SELECT * FROM household_bill_participants WHERE bill_id=?", (bill_id,))
    if person_id:
        match = next((x for x in parts if x["person_id"] == person_id), None)
        if match:
            participant_id = match["id"]
    elif len(parts) == 1:
        participant_id = parts[0]["id"]
        person_id = parts[0]["person_id"]

    _apply_abono(bill_id, amount, the_date, account_id,
                 participant_id=participant_id, person_id=person_id)
    flash(f"Abono de ${amount:,.0f} registrado".replace(",", "."), "success")
    return redirect(url_for("household.detail", bill_id=bill_id))


@bp.route("/<int:bill_id>/eliminar", methods=["POST"])
def remove(bill_id):
    db.delete("household_bills", "id = ?", (bill_id,))
    db.audit("delete", "household_bill", bill_id)
    flash("Cuenta eliminada", "info")
    return redirect(url_for("household.index"))
