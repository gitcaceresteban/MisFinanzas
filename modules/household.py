"""Cuentas del hogar: vista por mes, cuentas fijas mensuales y abonos."""
import uuid
import calendar
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
    if n <= 1:
        return [total]
    base = round(total / n)
    parts = [base] * (n - 1)
    parts.append(round(total - base * (n - 1)))
    return parts


def _create_participants(bill_id, amount, split, person_ids, shares):
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
        else:
            share_amt = parse_money(raw)
        db.insert("household_bill_participants", {
            "bill_id": bill_id, "person_id": pid_int,
            "share_amount": share_amt, "share_percent": share_pct,
            "paid_amount": 0, "status": "pendiente",
        })


def _por_cobrar(bill):
    """Lo que me deben: la suma de las partes de los participantes; si no hay
    participantes, el monto completo."""
    if (bill.get("participants_count") or 0) > 0:
        return bill.get("sum_shares") or 0
    return bill.get("amount") or 0


def _clone_bill(src, new_due, status="pendiente"):
    """Crea una copia de una cuenta para otro mes (conservando datos y
    participantes). Se usa para regenerar las cuentas fijas."""
    new_id = db.insert("household_bills", {
        "name": src["name"], "category_id": src["category_id"],
        "amount": src["amount"], "due_date": new_due.isoformat(),
        "paid_by_person_id": src["paid_by_person_id"],
        "paid_from_account_id": src["paid_from_account_id"],
        "split_type": src["split_type"], "status": status,
        "logo_path": src["logo_path"],
        "installments_total": 1, "installment_number": 1, "series_id": None,
        "collected_amount": 0,
        "is_recurring": src["is_recurring"], "recurring_day": src["recurring_day"],
        "notes": src["notes"],
    })
    for p in db.query("SELECT * FROM household_bill_participants WHERE bill_id=?",
                      (src["id"],)):
        db.insert("household_bill_participants", {
            "bill_id": new_id, "person_id": p["person_id"],
            "share_amount": p["share_amount"], "share_percent": p["share_percent"],
            "paid_amount": 0, "status": "pendiente",
        })
    return new_id


def _next_due(due_str, recurring_day):
    base = parse_date_cl(due_str) or date.today()
    nxt = add_months(base, 1)
    day = recurring_day or base.day
    last = calendar.monthrange(nxt.year, nxt.month)[1]
    return nxt.replace(day=min(int(day), last))


# ----------------------------------------------------------------------
# Vistas
# ----------------------------------------------------------------------
@bp.route("/")
def index():
    today = date.today()
    ym = safe_str(request.args.get("ym")) or today.strftime("%Y-%m")
    try:
        y, m = map(int, ym.split("-"))
        d0 = date(y, m, 1)
    except (ValueError, AttributeError):
        d0 = date(today.year, today.month, 1)
    y, m = d0.year, d0.month
    ym = f"{y}-{m:02d}"
    label = f"{month_name_es(m)} {y}"
    prev_ym = add_months(d0, -1).strftime("%Y-%m")
    next_ym = add_months(d0, 1).strftime("%Y-%m")

    bills = db.query("""
        SELECT b.*,
               c.name AS category_name, c.color AS category_color, c.icon AS category_icon,
               p.name AS paid_by_name,
               (SELECT COUNT(*) FROM household_bill_participants hbp WHERE hbp.bill_id=b.id) AS participants_count,
               (SELECT COALESCE(SUM(hbp.share_amount),0) FROM household_bill_participants hbp WHERE hbp.bill_id=b.id) AS sum_shares
        FROM household_bills b
        LEFT JOIN categories c ON c.id = b.category_id
        LEFT JOIN people p ON p.id = b.paid_by_person_id
        WHERE strftime('%Y-%m', b.due_date) = ?
        ORDER BY b.name ASC
    """, (ym,))
    for b in bills:
        b["por_cobrar"] = _por_cobrar(b)

    payments = db.query("""
        SELECT hp.*, pe.name AS person_name, a.name AS account_name
        FROM household_payments hp
        LEFT JOIN people pe ON pe.id = hp.person_id
        LEFT JOIN accounts a ON a.id = hp.account_id
        WHERE hp.ym = ?
        ORDER BY hp.date DESC, hp.id DESC
    """, (ym,))

    cargos = sum(b["amount"] or 0 for b in bills)
    por_cobrar = sum(b["por_cobrar"] for b in bills)
    abonado = sum(p["amount"] or 0 for p in payments)
    neto = max(0, por_cobrar - abonado)
    pending_count = sum(1 for b in bills if b["status"] in ("pendiente", "parcial", "vencida"))

    # ¿Hay cuentas fijas (recurrentes) que aún no existen en este mes?
    existing_names = {b["name"] for b in bills}
    templates = db.query("""
        SELECT name FROM household_bills WHERE is_recurring=1
          AND id IN (SELECT MAX(id) FROM household_bills WHERE is_recurring=1 GROUP BY name)
    """)
    missing_fixed = [t["name"] for t in templates if t["name"] not in existing_names]

    people = db.query("SELECT * FROM people WHERE active=1 ORDER BY name")
    accounts = db.query("""SELECT a.*, b.name AS bank_name FROM accounts a
                           LEFT JOIN banks b ON b.id=a.bank_id
                           WHERE a.status='activa' ORDER BY a.name""")

    return render_template("household.html",
                          bills=bills, payments=payments,
                          ym=ym, label=label, prev_ym=prev_ym, next_ym=next_ym,
                          is_current=(ym == today.strftime("%Y-%m")),
                          cargos=cargos, por_cobrar=por_cobrar, abonado=abonado,
                          neto=neto, pending_count=pending_count,
                          missing_fixed=missing_fixed,
                          people=people, accounts=accounts)


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
        is_recurring = 1 if request.form.get("is_recurring") else 0
        n_inst = max(1, safe_int(request.form.get("installments_total")) or 1)
        if is_recurring:
            n_inst = 1  # una cuenta fija es mensual perpetua, no en cuotas

        if not name or amount <= 0:
            flash("Nombre y monto son obligatorios", "error")
            return redirect(url_for("household.create"))

        person_ids = request.form.getlist("participant_ids[]")
        shares = request.form.getlist("participant_shares[]")

        base = parse_date_cl(due_date) if due_date else date.today()
        recurring_day = base.day if (is_recurring and base) else None
        amounts = _split_amounts(amount, n_inst)
        series_id = uuid.uuid4().hex if n_inst > 1 else None
        first_id = None
        first_ym = (base or date.today()).strftime("%Y-%m")

        for i in range(n_inst):
            inst_due = add_months(base, i) if base else None
            inst_name = name if n_inst == 1 else f"{name} (cuota {i+1}/{n_inst})"
            data = {
                "name": inst_name, "category_id": category_id, "amount": amounts[i],
                "due_date": inst_due.isoformat() if inst_due else None,
                "paid_by_person_id": paid_by, "paid_from_account_id": paid_from,
                "split_type": split, "status": "pendiente", "logo_path": logo_file,
                "installments_total": n_inst, "installment_number": i + 1,
                "series_id": series_id, "collected_amount": 0,
                "is_recurring": is_recurring, "recurring_day": recurring_day,
                "notes": notes,
            }
            new_id = db.insert("household_bills", data)
            if first_id is None:
                first_id = new_id
            db.audit("create", "household_bill", new_id, data)
            _create_participants(new_id, amounts[i], split, person_ids, shares)

        if n_inst > 1:
            flash(f"Cuenta creada en {n_inst} cuotas mensuales", "success")
        else:
            flash("Cuenta del hogar registrada" + (" (fija mensual)" if is_recurring else ""), "success")
        return redirect(url_for("household.index", ym=first_ym))

    return render_template("household_form.html", bill=None,
                          categories=categories, people=people,
                          accounts=accounts, split_types=SPLIT_TYPES,
                          participants=[])


@bp.route("/<int:bill_id>")
def detail(bill_id):
    bill = db.query("""
        SELECT b.*, c.name AS category_name, c.color AS category_color, p.name AS paid_by_name
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
        WHERE hbp.bill_id = ? ORDER BY pe.name
    """, (bill_id,))

    series = []
    if bill.get("series_id"):
        series = db.query("""
            SELECT id, name, amount, due_date, status, installment_number
            FROM household_bills WHERE series_id = ? ORDER BY installment_number
        """, (bill["series_id"],))

    bill = dict(bill)
    bill["participants_count"] = len(participants)
    bill["sum_shares"] = sum(p["share_amount"] or 0 for p in participants)
    bill["por_cobrar"] = _por_cobrar(bill)
    bill["amount_paid_by_me"] = bill["amount"] if not bill["paid_by_person_id"] else 0

    return render_template("household_detail.html", bill=bill,
                          participants=participants, series=series)


@bp.route("/<int:bill_id>/editar", methods=["GET", "POST"])
def edit(bill_id):
    bill = db.query("SELECT * FROM household_bills WHERE id = ?", (bill_id,), one=True)
    if not bill:
        flash("Cuenta no encontrada", "error")
        return redirect(url_for("household.index"))
    categories = db.query("SELECT * FROM categories WHERE active=1 ORDER BY name")
    people = db.query("SELECT * FROM people WHERE active=1 ORDER BY name")
    accounts = db.query("SELECT * FROM accounts ORDER BY name")
    participants = db.query("SELECT * FROM household_bill_participants WHERE bill_id = ?",
                            (bill_id,))

    if request.method == "POST":
        logo_file = save_image(request.files.get("logo"), prefix="hogar")
        amount = parse_money(request.form.get("amount"))
        split = safe_str(request.form.get("split_type")) or "equal"
        due_date = safe_str(request.form.get("due_date")) or None
        is_recurring = 1 if request.form.get("is_recurring") else 0
        base = parse_date_cl(due_date)
        data = {
            "name": safe_str(request.form.get("name")),
            "category_id": safe_int(request.form.get("category_id")) or None,
            "amount": amount, "due_date": due_date,
            "paid_by_person_id": safe_int(request.form.get("paid_by_person_id")) or None,
            "paid_from_account_id": safe_int(request.form.get("paid_from_account_id")) or None,
            "split_type": split, "is_recurring": is_recurring,
            "recurring_day": (base.day if (is_recurring and base) else None),
            "notes": safe_str(request.form.get("notes")) or None,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        if logo_file:
            data["logo_path"] = logo_file
        db.update("household_bills", data, "id = ?", (bill_id,))
        db.audit("update", "household_bill", bill_id, data)

        db.delete("household_bill_participants", "bill_id = ?", (bill_id,))
        person_ids = request.form.getlist("participant_ids[]")
        shares = request.form.getlist("participant_shares[]")
        _create_participants(bill_id, amount, split, person_ids, shares)
        flash("Cuenta actualizada", "success")
        return redirect(url_for("household.detail", bill_id=bill_id))

    return render_template("household_form.html", bill=bill,
                          categories=categories, people=people,
                          accounts=accounts, split_types=SPLIT_TYPES,
                          participants=participants)


@bp.route("/<int:bill_id>/marcar-pagada", methods=["POST"])
def mark_paid(bill_id):
    """Marca como pagada (se queda en su mes) y, si es fija, crea la del mes
    siguiente automáticamente (conservando historial y abonos del mes)."""
    bill = db.query("SELECT * FROM household_bills WHERE id = ?", (bill_id,), one=True)
    if not bill:
        flash("Cuenta no encontrada", "error")
        return redirect(url_for("household.index"))
    db.update("household_bills", {
        "status": "pagada", "paid_date": today_iso(),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }, "id = ?", (bill_id,))
    db.audit("payment", "household_bill", bill_id)

    msg = "Cuenta marcada como pagada"
    if bill["is_recurring"]:
        nxt = _next_due(bill["due_date"], bill["recurring_day"])
        nxt_ym = nxt.strftime("%Y-%m")
        dup = db.query("""SELECT id FROM household_bills
                          WHERE name=? AND strftime('%Y-%m', due_date)=?""",
                       (bill["name"], nxt_ym), one=True)
        if not dup:
            _clone_bill(bill, nxt, "pendiente")
            msg += f" · se creó “{bill['name']}” para {month_name_es(nxt.month)} {nxt.year}"

    bill_ym = (parse_date_cl(bill["due_date"]) or date.today()).strftime("%Y-%m")
    flash(msg, "success")
    return redirect(url_for("household.index", ym=bill_ym))


@bp.route("/generar-fijas", methods=["POST"])
def generate_fixed():
    """Crea las cuentas fijas (recurrentes) que falten en el mes indicado."""
    ym = safe_str(request.form.get("ym"))
    try:
        y, m = map(int, ym.split("-"))
    except (ValueError, AttributeError):
        flash("Mes inválido", "error")
        return redirect(url_for("household.index"))

    templates = db.query("""
        SELECT * FROM household_bills WHERE is_recurring=1
          AND id IN (SELECT MAX(id) FROM household_bills WHERE is_recurring=1 GROUP BY name)
    """)
    existing = {r["name"] for r in db.query(
        "SELECT name FROM household_bills WHERE strftime('%Y-%m', due_date)=?", (ym,))}
    created = 0
    for t in templates:
        if t["name"] in existing:
            continue
        day = t["recurring_day"] or (parse_date_cl(t["due_date"]).day if t["due_date"] else 5)
        last = calendar.monthrange(y, m)[1]
        due = date(y, m, min(int(day), last))
        _clone_bill(t, due, "pendiente")
        created += 1
    flash(f"{created} cuenta(s) fija(s) generada(s)" if created
          else "No hay cuentas fijas nuevas para este mes", "success" if created else "info")
    return redirect(url_for("household.index", ym=ym))


@bp.route("/abono", methods=["POST"])
def add_abono():
    """Registra un abono a nivel de MES (pagos parciales de a poco)."""
    ym = safe_str(request.form.get("ym"))
    amount = parse_money(request.form.get("amount"))
    the_date = safe_str(request.form.get("date")) or today_iso()
    person_id = safe_int(request.form.get("person_id")) or None
    account_id = safe_int(request.form.get("account_id")) or None
    notes = safe_str(request.form.get("notes")) or None

    if not ym:
        d = parse_date_cl(the_date) or date.today()
        ym = f"{d.year}-{d.month:02d}"
    if amount <= 0:
        flash("El monto del abono debe ser mayor a 0", "error")
        return redirect(url_for("household.index", ym=ym))

    tx_id = None
    if account_id:
        db.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?",
                   (amount, account_id))
        tx_id = db.insert("transactions", {
            "date": the_date, "amount": amount, "type": "income",
            "transaction_type": "normal", "description": "Abono cuenta del hogar",
            "account_id": account_id, "person_id": person_id,
            "status": "pagado", "origin": "web",
        })

    new_id = db.insert("household_payments", {
        "ym": ym, "person_id": person_id, "amount": amount,
        "date": the_date, "account_id": account_id, "tx_id": tx_id, "notes": notes,
    })
    db.audit("payment", "household_payment", new_id, {"amount": amount, "ym": ym})
    flash(f"Abono de ${amount:,.0f} registrado".replace(",", "."), "success")
    return redirect(url_for("household.index", ym=ym))


@bp.route("/abono/<int:payment_id>/eliminar", methods=["POST"])
def delete_abono(payment_id):
    pay = db.query("SELECT * FROM household_payments WHERE id = ?", (payment_id,), one=True)
    if not pay:
        flash("Abono no encontrado", "error")
        return redirect(url_for("household.index"))
    if pay["account_id"]:
        db.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?",
                   (pay["amount"], pay["account_id"]))
    if pay["tx_id"]:
        db.delete("transactions", "id = ?", (pay["tx_id"],))
    db.delete("household_payments", "id = ?", (payment_id,))
    db.audit("delete", "household_payment", payment_id)
    flash("Abono eliminado", "info")
    return redirect(url_for("household.index", ym=pay["ym"]))


@bp.route("/<int:bill_id>/eliminar", methods=["POST"])
def remove(bill_id):
    bill = db.query("SELECT due_date FROM household_bills WHERE id=?", (bill_id,), one=True)
    ym = (parse_date_cl(bill["due_date"]).strftime("%Y-%m")
          if bill and bill["due_date"] else None)
    db.delete("household_bills", "id = ?", (bill_id,))
    db.audit("delete", "household_bill", bill_id)
    flash("Cuenta eliminada", "info")
    return redirect(url_for("household.index", ym=ym) if ym else url_for("household.index"))
