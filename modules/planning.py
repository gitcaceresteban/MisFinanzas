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
    """Devuelve compromisos (egresos comprometidos) por mes para el horizonte."""
    keys = _month_keys()
    ym_set = {k[2]: {"loans": 0, "cards": 0, "recurring": 0, "household": 0, "billed": 0}
              for k in keys}

    # Cuotas de créditos pendientes
    for r in db.query("""
        SELECT strftime('%Y-%m', due_date) AS ym, COALESCE(SUM(amount),0) AS t
        FROM loan_installments WHERE status != 'pagada' GROUP BY ym
    """):
        if r["ym"] in ym_set:
            ym_set[r["ym"]]["loans"] += r["t"] or 0

    # Cuotas de tarjetas estimadas
    for r in db.query("""
        SELECT strftime('%Y-%m', estimated_date) AS ym, COALESCE(SUM(amount),0) AS t
        FROM card_installments WHERE status != 'pagada' GROUP BY ym
    """):
        if r["ym"] in ym_set:
            ym_set[r["ym"]]["cards"] += r["t"] or 0

    # Recurrentes mensuales activos (se repiten cada mes).
    # Se excluyen los reembolsables (cuentas de tíos): los pago pero me los
    # devuelven, así que no reducen mi capacidad real de gasto.
    rec_total = db.query("""
        SELECT COALESCE(SUM(amount),0) AS t FROM recurring_payments
        WHERE active=1 AND frequency='monthly' AND is_reimbursable=0
    """, one=True)["t"] or 0
    for k in keys:
        ym_set[k[2]]["recurring"] = rec_total

    # Cuentas del hogar pendientes con vencimiento (mi parte = total − lo que aportan otros)
    for r in db.query("""
        SELECT strftime('%Y-%m', due_date) AS ym, COALESCE(SUM(amount),0) AS t
        FROM household_bills
        WHERE status IN ('pendiente','parcial','vencida') AND due_date IS NOT NULL
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

    income = get_monthly_income()
    months = []
    for (y, m, ym) in keys:
        c = ym_set[ym]
        committed = c["loans"] + c["cards"] + c["recurring"] + c["household"] + c["billed"]
        months.append({
            "ym": ym, "year": y, "month": m,
            "label": f"{month_name_es(m, short=True)} {y}",
            "loans": c["loans"], "cards": c["cards"], "recurring": c["recurring"],
            "household": c["household"], "billed": c["billed"],
            "committed": committed, "income": income,
            "free": income - committed,
        })
    return months


@bp.route("/")
def index():
    months = compute_commitments()
    income = get_monthly_income()
    today = date.today()
    ym = f"{today.year}-{today.month:02d}"

    # Gasto variable ya realizado este mes (gastos normales, sin contar pagos
    # de deuda ni recurrentes ya contabilizados como compromisos).
    spent = db.query("""
        SELECT COALESCE(SUM(amount),0) AS t FROM transactions
        WHERE type='expense' AND status='pagado'
          AND strftime('%Y-%m', date)=?
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
