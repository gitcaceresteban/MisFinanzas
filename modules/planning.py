"""
Planificación financiera:
  - Ingreso estimado mensual (sueldo + extras).
  - Cuánto puedo gastar este mes (ingreso − compromisos).
  - Proyección de los próximos meses (cuotas, créditos, recurrentes).
  - Simulador de escenarios: '¿qué pasa si compro algo en N cuotas?'.
"""
import json
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import db
from modules.helpers import safe_int, parse_money, month_name_es, add_months

bp = Blueprint("planning", __name__)

HORIZON_MONTHS = 12


def get_setting(key, default=""):
    row = db.query("SELECT value FROM settings WHERE key=?", (key,), one=True)
    return row["value"] if row and row["value"] is not None else default


def set_setting(key, value):
    if db.query("SELECT key FROM settings WHERE key=?", (key,), one=True):
        db.update("settings", {"value": value}, "key=?", (key,))
    else:
        db.insert("settings", {"key": key, "value": value})


def get_monthly_income():
    return parse_money(get_setting("monthly_income", "0"))


def _month_keys(n=HORIZON_MONTHS):
    today = date.today()
    start = date(today.year, today.month, 1)
    keys = []
    for i in range(n):
        d = add_months(start, i)
        keys.append((d.year, d.month, f"{d.year}-{d.month:02d}"))
    return keys


def compute_commitments():
    """Devuelve compromisos (egresos comprometidos) por mes para el horizonte.

    Aplica el 'desfase de sueldo': si te pagan en la segunda mitad del mes
    (income_day >= 15), el sueldo de un mes cubre las obligaciones del mes
    SIGUIENTE (que vencen antes del próximo pago). Por eso cada fila muestra el
    ingreso del mes y las obligaciones que ese ingreso realmente financia.
    """
    # +1 mes de horizonte para poder mirar las obligaciones del mes siguiente.
    keys = _month_keys(HORIZON_MONTHS + 1)
    ym_set = {k[2]: {"loans": 0, "cards": 0, "recurring": 0, "household": 0, "billed": 0}
              for k in keys}

    # Cuotas de créditos (con calendario o sintetizadas si no lo tienen),
    # para considerar TODAS las deudas propias en el horizonte.
    import calendar
    from modules.loans import iter_loan_payments
    h_start = date(keys[0][0], keys[0][1], 1)
    h_end = date(keys[-1][0], keys[-1][1],
                 calendar.monthrange(keys[-1][0], keys[-1][1])[1])
    for ev in iter_loan_payments(h_start, h_end):
        ym = ev["date"].strftime("%Y-%m")
        if ym in ym_set:
            ym_set[ym]["loans"] += ev["amount"]

    # Cuotas de tarjetas estimadas. Se EXCLUYEN las cuotas del ciclo ya cerrado
    # (estimated_date <= cierre de la tarjeta), porque esas ya están contadas en
    # billed_amount → evita el doble conteo.
    from modules.cards import billing_cycle_bounds
    cycle_ends = {}
    for r in db.query("""
        SELECT ci.estimated_date AS est, ci.amount AS amount, ci.card_id AS card_id,
               c.billing_day AS billing_day
        FROM card_installments ci
        JOIN credit_cards c ON c.id = ci.card_id
        WHERE ci.status != 'pagada'
    """):
        cid = r["card_id"]
        if cid not in cycle_ends:
            cycle_ends[cid] = billing_cycle_bounds(r["billing_day"])[1].isoformat()
        if not r["est"] or r["est"] <= cycle_ends[cid]:
            continue  # ya incluida en billed_amount
        ym = r["est"][:7]
        if ym in ym_set:
            ym_set[ym]["cards"] += r["amount"] or 0

    # Recurrentes mensuales activos (se repiten cada mes).
    # Se excluyen los reembolsables (cuentas de tíos): los pago pero me los
    # devuelven, así que no reducen mi capacidad real de gasto.
    rec_total = db.query("""
        SELECT COALESCE(SUM(amount),0) AS t FROM recurring_payments
        WHERE active=1 AND frequency='monthly' AND is_reimbursable=0
    """, one=True)["t"] or 0
    for k in keys:
        ym_set[k[2]]["recurring"] = rec_total

    # Cuentas del hogar pendientes con vencimiento. Solo cuenta MI parte neta =
    # total − lo que aportan/me devuelven los participantes. Así, una cuenta que
    # pago con mi tarjeta pero me reembolsan por completo (participantes cubren el
    # 100%) queda en $0 y no infla mis compromisos.
    for r in db.query("""
        SELECT strftime('%Y-%m', due_date) AS ym,
               COALESCE(SUM(CASE WHEN net > 0 THEN net ELSE 0 END), 0) AS t
        FROM (
            SELECT hb.due_date,
                   hb.amount - COALESCE(
                       (SELECT SUM(share_amount) FROM household_bill_participants
                        WHERE bill_id = hb.id), 0) AS net
            FROM household_bills hb
            WHERE hb.status IN ('pendiente','parcial','vencida')
                  AND hb.due_date IS NOT NULL
        )
        GROUP BY ym
    """):
        if r["ym"] in ym_set:
            ym_set[r["ym"]]["household"] += r["t"] or 0

    # Tarjetas facturadas (a pagar el mes en curso)
    current = keys[0][2]
    billed = db.query("""
        SELECT COALESCE(SUM(billed_amount),0) AS t FROM credit_cards
        WHERE status='activa' AND has_billed_debt=1
    """, one=True)["t"] or 0
    ym_set[current]["billed"] = billed

    # Gasto del ciclo EN CURSO (no facturado): se cierra y paga aprox. el mes
    # próximo, así que se refleja ahí para no subestimar el pago de tarjeta.
    unbilled = db.query("""
        SELECT COALESCE(SUM(unbilled_amount),0) AS t FROM credit_cards
        WHERE status='activa'
    """, one=True)["t"] or 0
    if unbilled and len(keys) > 1:
        ym_set[keys[1][2]]["billed"] += unbilled

    # Desfase de sueldo: si te pagan en la segunda mitad del mes, ese sueldo
    # cubre las obligaciones del mes siguiente.
    income_day = safe_int(get_setting("income_day", "27")) or 27
    offset = 1 if income_day >= 15 else 0

    income = get_monthly_income()
    months = []
    for idx in range(HORIZON_MONTHS):
        (y, m, ym) = keys[idx]
        # Obligaciones que financia el sueldo de este mes (según el desfase).
        src = ym_set[keys[idx + offset][2]]
        committed = (src["loans"] + src["cards"] + src["recurring"]
                     + src["household"] + src["billed"])
        months.append({
            "ym": ym, "year": y, "month": m,
            "label": f"{month_name_es(m, short=True)} {y}",
            "loans": src["loans"], "cards": src["cards"], "recurring": src["recurring"],
            "household": src["household"], "billed": src["billed"],
            "committed": committed, "income": income,
            "free": income - committed,
            "offset": offset,
        })
    return months


@bp.route("/")
def index():
    months = compute_commitments()
    income = get_monthly_income()
    today = date.today()
    ym = f"{today.year}-{today.month:02d}"

    # Gasto variable ya realizado este mes que consume el "techo": solo lo que
    # sale de efectivo/débito AHORA (card_id IS NULL). El gasto a crédito NO
    # resta aquí porque ya está representado en committed (billed_amount /
    # cuotas), y contarlo también sería restarlo dos veces. Se excluyen además
    # los pagos de deuda y los recurrentes (ya contabilizados como compromisos).
    spent = db.query("""
        SELECT COALESCE(SUM(amount),0) AS t FROM transactions
        WHERE type='expense' AND status='pagado'
          AND strftime('%Y-%m', date)=?
          AND card_id IS NULL
          AND transaction_type NOT IN ('debt_payment')
          AND (description IS NULL OR description NOT LIKE '[Recurrente]%')
    """, (ym,), one=True)["t"] or 0

    this_month = months[0] if months else None
    ceiling = this_month["free"] if this_month else 0   # techo para gasto variable
    remaining = ceiling - spent

    # Datos para el simulador (JSON)
    sim_data = [{"label": m["label"], "committed": m["committed"], "income": m["income"]}
                for m in months]

    return render_template("planning.html",
                          months=months,
                          income=income,
                          income_day=safe_int(get_setting("income_day", "27")) or 27,
                          this_month=this_month,
                          spent=spent,
                          ceiling=ceiling,
                          remaining=remaining,
                          sim_json=json.dumps(sim_data))


@bp.route("/ingreso", methods=["POST"])
def save_income():
    set_setting("monthly_income", str(int(parse_money(request.form.get("monthly_income")))))
    pay_day = safe_int(request.form.get("income_day"))
    if pay_day:
        set_setting("income_day", str(min(max(pay_day, 1), 31)))
    db.audit("update", "setting", None, {"monthly_income": request.form.get("monthly_income")})
    flash("Ingreso estimado actualizado", "success")
    return redirect(request.form.get("next") or url_for("planning.index"))
