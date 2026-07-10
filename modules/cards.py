"""Gestión de tarjetas de crédito y sus cuotas."""
# Se importa con alias porque este módulo define una vista llamada `calendar`
# (ruta /calendario) que, si no, sombrearía al módulo estándar `calendar`.
import calendar as _calendar
from datetime import datetime, date, timedelta
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


# =====================================================================
# Ciclo de facturación y recálculo dinámico del facturado
# =====================================================================
def _clamp_day(year: int, month: int, day: int) -> date:
    """Devuelve date(year, month, min(day, último_día_del_mes))."""
    last = _calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def billing_cycle_bounds(billing_day, ref_date=None):
    """Devuelve (cycle_start, cycle_end) del último ciclo de facturación ya
    cerrado respecto de ``ref_date`` (hoy por defecto).

    - ``cycle_end``: la fecha de cierre (``billing_day``) más reciente que ya
      pasó (o es hoy). Si el día no existe en el mes se usa el último día.
    - ``cycle_start``: el día siguiente al cierre anterior (un mes antes de
      ``cycle_end`` + 1 día).
    - Si ``billing_day`` es None, se usa el mes calendario en curso como
      fallback (no rompe tarjetas sin ese dato configurado).
    """
    ref = ref_date or date.today()
    if not billing_day:
        first = date(ref.year, ref.month, 1)
        last = calendar.monthrange(ref.year, ref.month)[1]
        return first, date(ref.year, ref.month, last)

    close_this = _clamp_day(ref.year, ref.month, billing_day)
    if ref >= close_this:
        cycle_end = close_this
    else:
        prev = add_months(date(ref.year, ref.month, 1), -1)
        cycle_end = _clamp_day(prev.year, prev.month, billing_day)

    prev_m = add_months(date(cycle_end.year, cycle_end.month, 1), -1)
    prev_close = _clamp_day(prev_m.year, prev_m.month, billing_day)
    cycle_start = prev_close + timedelta(days=1)
    return cycle_start, cycle_end


def _billing_close_on_or_after(d: date, billing_day: int) -> date:
    """Primer cierre de facturación (``billing_day``) en o después de ``d``.

    Una compra hecha antes (o el mismo día) del cierre de su mes se factura en
    ese cierre; una compra posterior al cierre se factura el mes siguiente.
    """
    close_this = _clamp_day(d.year, d.month, billing_day)
    if d <= close_this:
        return close_this
    nxt = add_months(date(d.year, d.month, 1), 1)
    return _clamp_day(nxt.year, nxt.month, billing_day)


def recompute_card_billing(card_id: int) -> None:
    """Recalcula facturado/no facturado/cuotas de una tarjeta desde las tablas
    (patrón 'recount from table', igual que create_installments y loans).

    Deja consistentes las 5 columnas caché que leen dashboard, alerts,
    calendar, planning, cashflow y api:
      - billed_amount: lo que hay que pagar en el próximo vencimiento
        (cuotas del ciclo cerrado + compras normales del ciclo cerrado que
        aún no se han pagado).
      - unbilled_amount: compras normales del ciclo EN CURSO (aún no cerrado).
      - future_installments_amount / pending_installments: cuotas posteriores
        al ciclo cerrado.
      - has_billed_debt: 1 si billed_amount > 0.
    """
    card = db.query("SELECT * FROM credit_cards WHERE id = ?", (card_id,), one=True)
    if not card:
        return
    cycle_start, cycle_end = billing_cycle_bounds(card.get("billing_day"))
    paid_until = card.get("billed_paid_until")  # 'YYYY-MM-DD' o None
    cs, ce = cycle_start.isoformat(), cycle_end.isoformat()
    today = date.today().isoformat()

    # Cuotas facturadas: no pagadas con cierre estimado hasta el fin del ciclo.
    billed_inst = db.query("""
        SELECT COALESCE(SUM(amount), 0) AS t FROM card_installments
        WHERE card_id = ? AND status != 'pagada' AND estimated_date <= ?
    """, (card_id, ce), one=True)["t"] or 0

    # Compras normales del ciclo cerrado (excluye cuotas y pagos de facturado).
    # 'date > paid_until' evita recontar un ciclo ya pagado.
    billed_normal = db.query("""
        SELECT COALESCE(SUM(amount), 0) AS t FROM transactions
        WHERE card_id = ? AND type = 'expense' AND status = 'pagado'
              AND COALESCE(transaction_type, 'normal') NOT IN ('installments', 'debt_payment')
              AND date BETWEEN ? AND ?
              AND date > COALESCE(?, '0000-01-01')
    """, (card_id, cs, ce, paid_until), one=True)["t"] or 0

    billed = billed_inst + billed_normal

    # No facturado: compras normales del ciclo en curso (tras el cierre, hasta hoy).
    unbilled = db.query("""
        SELECT COALESCE(SUM(amount), 0) AS t FROM transactions
        WHERE card_id = ? AND type = 'expense' AND status = 'pagado'
              AND COALESCE(transaction_type, 'normal') NOT IN ('installments', 'debt_payment')
              AND date > ? AND date <= ?
    """, (card_id, ce, today), one=True)["t"] or 0

    # Cuotas futuras: posteriores al ciclo cerrado.
    fut = db.query("""
        SELECT COUNT(*) AS c, COALESCE(SUM(amount), 0) AS t FROM card_installments
        WHERE card_id = ? AND status != 'pagada' AND estimated_date > ?
    """, (card_id, ce), one=True)

    db.update("credit_cards", {
        "billed_amount": billed,
        "unbilled_amount": unbilled,
        "future_installments_amount": fut["t"] or 0,
        "pending_installments": fut["c"] or 0,
        "has_billed_debt": 1 if billed > 0 else 0,
    }, "id = ?", (card_id,))


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
        # billed_amount / unbilled_amount / has_billed_debt ya NO se piden a mano:
        # se calculan solos desde transacciones y cuotas (recompute_card_billing).
        data = {
            "bank_id": safe_int(request.form.get("bank_id")) or None,
            "name": safe_str(request.form.get("name")),
            "credit_limit": parse_money(request.form.get("credit_limit")),
            "used_amount": parse_money(request.form.get("used_amount")),
            "billing_day": safe_int(request.form.get("billing_day")) or None,
            "payment_day": safe_int(request.form.get("payment_day")) or None,
            "status": safe_str(request.form.get("status")) or "activa",
            "color": safe_str(request.form.get("color")) or None,
            "notes": safe_str(request.form.get("notes")) or None,
        }
        if not data["name"]:
            flash("El nombre es obligatorio", "error")
            return redirect(url_for("cards.create"))
        new_id = db.insert("credit_cards", data)
        recompute_card_billing(new_id)
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
        # billed_amount / unbilled_amount / has_billed_debt se recalculan solos.
        data = {
            "bank_id": safe_int(request.form.get("bank_id")) or None,
            "name": safe_str(request.form.get("name")),
            "credit_limit": parse_money(request.form.get("credit_limit")),
            "used_amount": parse_money(request.form.get("used_amount")),
            "billing_day": safe_int(request.form.get("billing_day")) or None,
            "payment_day": safe_int(request.form.get("payment_day")) or None,
            "status": safe_str(request.form.get("status")) or "activa",
            "color": safe_str(request.form.get("color")) or None,
            "notes": safe_str(request.form.get("notes")) or None,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        db.update("credit_cards", data, "id = ?", (card_id,))
        # El día de facturación puede haber cambiado → recalcular facturado.
        recompute_card_billing(card_id)
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
    recompute_card_billing(inst["card_id"])
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
    recompute_card_billing(inst["card_id"])
    flash("Cuota marcada como facturada", "info")
    return redirect(url_for("cards.detail", card_id=inst["card_id"]))


@bp.route("/<int:card_id>/pagar", methods=["GET"])
def pay_page(card_id):
    """Página 'Pagar el facturado': muestra el facturado recién recalculado y
    el detalle (cuotas + compras normales) que lo componen, para comparar
    contra la cartola del banco."""
    recompute_card_billing(card_id)
    card = db.query("""
        SELECT c.*, b.name AS bank_name, b.color AS bank_color, b.logo_path AS bank_logo
        FROM credit_cards c LEFT JOIN banks b ON b.id = c.bank_id
        WHERE c.id = ?
    """, (card_id,), one=True)
    if not card:
        flash("Tarjeta no encontrada", "error")
        return redirect(url_for("cards.index"))

    cycle_start, cycle_end = billing_cycle_bounds(card.get("billing_day"))
    cs, ce = cycle_start.isoformat(), cycle_end.isoformat()

    installments = db.query("""
        SELECT * FROM card_installments
        WHERE card_id = ? AND status != 'pagada' AND estimated_date <= ?
        ORDER BY estimated_date ASC
    """, (card_id, ce))

    transactions = db.query("""
        SELECT t.*, cat.name AS category_name
        FROM transactions t
        LEFT JOIN categories cat ON cat.id = t.category_id
        WHERE t.card_id = ? AND t.type = 'expense' AND t.status = 'pagado'
              AND COALESCE(t.transaction_type, 'normal') NOT IN ('installments', 'debt_payment')
              AND t.date BETWEEN ? AND ?
              AND t.date > COALESCE(?, '0000-01-01')
        ORDER BY t.date ASC
    """, (card_id, cs, ce, card.get("billed_paid_until")))

    accounts = db.query("""SELECT a.*, b.name AS bank_name FROM accounts a
                           LEFT JOIN banks b ON b.id = a.bank_id
                           WHERE a.status='activa' ORDER BY a.balance DESC""")

    return render_template("cards_pay.html", card=card,
                           cycle_start=cycle_start, cycle_end=cycle_end,
                           installments=installments, transactions=transactions,
                           accounts=accounts)


@bp.route("/<int:card_id>/pagar", methods=["POST"])
def pay_billed(card_id):
    """Registra el pago del facturado de una tarjeta (mirror de loans_pay)."""
    card = db.query("SELECT * FROM credit_cards WHERE id = ?", (card_id,), one=True)
    if not card:
        flash("Tarjeta no encontrada", "error")
        return redirect(url_for("cards.index"))

    recompute_card_billing(card_id)
    card = db.query("SELECT * FROM credit_cards WHERE id = ?", (card_id,), one=True)
    cycle_start, cycle_end = billing_cycle_bounds(card.get("billing_day"))
    ce = cycle_end.isoformat()

    billed = card["billed_amount"] or 0
    if billed <= 0:
        flash("Esta tarjeta no tiene facturado por pagar", "info")
        return redirect(url_for("cards.detail", card_id=card_id))

    account_id = safe_int(request.form.get("account_id")) or None
    the_date = safe_str(request.form.get("date")) or today_iso()
    amount = parse_money(request.form.get("amount")) or billed
    if amount <= 0:
        flash("El monto a pagar debe ser mayor a 0", "error")
        return redirect(url_for("cards.pay_page", card_id=card_id))

    # Pago completo (con tolerancia de $1): marca las cuotas del ciclo como
    # pagadas y recuerda hasta qué cierre se pagó para no recontar las compras
    # normales de ese ciclo.
    full = amount >= (billed - 1)
    if full:
        db.execute("""
            UPDATE card_installments SET status = 'pagada'
            WHERE card_id = ? AND status != 'pagada' AND estimated_date <= ?
        """, (card_id, ce))
        db.update("credit_cards", {"billed_paid_until": ce}, "id = ?", (card_id,))

    # Baja el cupo usado por el monto pagado.
    db.execute("UPDATE credit_cards SET used_amount = MAX(0, used_amount - ?) WHERE id = ?",
               (amount, card_id))

    # Si se eligió cuenta: descuenta saldo y registra la transacción de pago.
    if account_id:
        db.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?",
                   (amount, account_id))
        db.insert("transactions", {
            "date": the_date,
            "amount": amount,
            "type": "expense",
            "transaction_type": "debt_payment",
            "card_id": card_id,
            "description": f"Pago facturado {card['name']}",
            "account_id": account_id,
            "status": "pagado",
            "origin": "web",
        })

    recompute_card_billing(card_id)
    db.audit("payment", "credit_card_billing", card_id,
             {"amount": amount, "account_id": account_id, "full": full})
    flash(f"Facturado pagado · ${amount:,.0f}", "success")
    return redirect(url_for("cards.detail", card_id=card_id))


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
    """Crea automáticamente las cuotas futuras de una compra en cuotas.

    La cuota 1 se ubica en el primer cierre de facturación en o después de la
    compra (así una compra hecha antes del cierre de este mes cae en el ciclo
    que cierra este mes, no el próximo), y las siguientes van mes a mes. Si la
    tarjeta no tiene día de facturación, se aproxima con la fecha de compra.
    """
    if total_installments < 1:
        return
    amount_per = round(total_amount / total_installments)
    start = parse_date_cl(start_date) or date.today()
    first_close = _billing_close_on_or_after(start, billing_day) if billing_day else None

    for i in range(1, total_installments + 1):
        if first_close:
            est_date = add_months(first_close, i - 1)
        else:
            est_date = add_months(start, i)
        db.insert("card_installments", {
            "card_id": card_id,
            "transaction_id": transaction_id,
            "installment_number": i,
            "total_installments": total_installments,
            "amount": amount_per,
            "estimated_date": est_date.isoformat(),
            "status": "pendiente",
        })

    # Recalcular facturado / cuotas de la tarjeta desde la tabla.
    recompute_card_billing(card_id)
