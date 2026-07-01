"""API REST con autenticación por token.
Pensada para integrarse con Telegram bot, Atajos iOS, Home Assistant.
"""
from datetime import datetime, date
from functools import wraps
from flask import Blueprint, request, jsonify, current_app
from database import db
from modules.helpers import safe_str, safe_float, safe_int, today_iso

bp = Blueprint("api", __name__)


def require_token(f):
    """Decorador: valida X-API-Token header o ?token=..."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-API-Token") or request.args.get("token")
        expected = current_app.config.get("API_TOKEN")
        if not token or not expected or token != expected:
            return jsonify({"error": "Unauthorized", "message": "Token inválido"}), 401
        return f(*args, **kwargs)
    return wrapper


# ============================================
# Health / info
# ============================================
@bp.route("/health")
def health():
    return jsonify({"status": "ok", "service": "finance_api", "version": "1.0.0"})


@bp.route("/info")
@require_token
def info():
    return jsonify({
        "name": "Mis Finanzas · RNRJ",
        "version": "1.0.0",
        "endpoints": [
            "GET  /api/health",
            "GET  /api/dashboard",
            "GET  /api/gastos",
            "POST /api/gastos",
            "GET  /api/gastos/<id>",
            "PUT  /api/gastos/<id>",
            "DELETE /api/gastos/<id>",
            "GET  /api/personas",
            "GET  /api/deudas-personas",
            "POST /api/deudas-personas/<id>/abono",
            "GET  /api/cuentas",
            "GET  /api/tarjetas",
            "GET  /api/pagos-recurrentes",
            "GET  /api/presupuestos",
            "GET  /api/calendario",
            "GET  /api/alertas",
        ],
    })


# ============================================
# Dashboard
# ============================================
@bp.route("/dashboard")
@require_token
def dashboard():
    today = date.today()
    ym_str = today.strftime("%Y-%m")

    accounts_sum = db.query(
        "SELECT COALESCE(SUM(balance),0) AS t FROM accounts WHERE status='activa'",
        one=True
    )

    cards_sum = db.query("""
        SELECT COALESCE(SUM(credit_limit),0) AS lim,
               COALESCE(SUM(used_amount),0) AS used
        FROM credit_cards WHERE status='activa'
    """, one=True)

    month_expense = db.query("""
        SELECT COALESCE(SUM(amount),0) AS t FROM transactions
        WHERE type='expense' AND status='pagado'
              AND strftime('%Y-%m', date) = ?
    """, (ym_str,), one=True)

    month_income = db.query("""
        SELECT COALESCE(SUM(amount),0) AS t FROM transactions
        WHERE type='income' AND status='pagado'
              AND strftime('%Y-%m', date) = ?
    """, (ym_str,), one=True)

    return jsonify({
        "date": today.isoformat(),
        "total_balance": accounts_sum["t"],
        "cards_limit": cards_sum["lim"],
        "cards_used": cards_sum["used"],
        "cards_available": cards_sum["lim"] - cards_sum["used"],
        "month_expense": month_expense["t"],
        "month_income": month_income["t"],
        "month_net": month_income["t"] - month_expense["t"],
    })


# ============================================
# Gastos
# ============================================
@bp.route("/gastos", methods=["GET"])
@require_token
def gastos_list():
    limit = safe_int(request.args.get("limit")) or 50
    rows = db.query(f"""
        SELECT t.*, c.name AS category_name, a.name AS account_name,
               cc.name AS card_name, p.name AS person_name
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        LEFT JOIN accounts a ON a.id = t.account_id
        LEFT JOIN credit_cards cc ON cc.id = t.card_id
        LEFT JOIN people p ON p.id = t.person_id
        ORDER BY t.date DESC, t.id DESC
        LIMIT ?
    """, (limit,))
    return jsonify({"transactions": rows})


@bp.route("/gastos", methods=["POST"])
@require_token
def gastos_create():
    data = request.get_json(silent=True) or {}
    if not data.get("amount"):
        return jsonify({"error": "Monto requerido"}), 400

    tx = {
        "date": data.get("date") or today_iso(),
        "amount": safe_float(data.get("amount")),
        "type": data.get("type") or "expense",
        "transaction_type": data.get("transaction_type") or "normal",
        "category_id": data.get("category_id"),
        "description": data.get("description"),
        "account_id": data.get("account_id"),
        "card_id": data.get("card_id"),
        "person_id": data.get("person_id"),
        "payment_method": data.get("payment_method"),
        "status": data.get("status") or "pagado",
        "origin": data.get("origin") or "api",
        "notes": data.get("notes"),
    }
    new_id = db.insert("transactions", tx)
    db.audit("create", "transaction", new_id, tx, source=tx["origin"])

    # Actualizar saldo
    if tx["account_id"] and tx["status"] == "pagado":
        mult = -1 if tx["type"] == "expense" else 1
        db.execute(
            "UPDATE accounts SET balance = balance + ? WHERE id = ?",
            (tx["amount"] * mult, tx["account_id"])
        )
    if tx["card_id"] and tx["type"] == "expense":
        db.execute(
            "UPDATE credit_cards SET used_amount = used_amount + ? WHERE id = ?",
            (tx["amount"], tx["card_id"])
        )

    return jsonify({"id": new_id, "status": "created"}), 201


@bp.route("/gastos/<int:tx_id>", methods=["GET"])
@require_token
def gastos_get(tx_id):
    row = db.query("SELECT * FROM transactions WHERE id = ?", (tx_id,), one=True)
    if not row:
        return jsonify({"error": "No encontrado"}), 404
    return jsonify(row)


@bp.route("/gastos/<int:tx_id>", methods=["PUT", "PATCH"])
@require_token
def gastos_update(tx_id):
    data = request.get_json(silent=True) or {}
    row = db.query("SELECT * FROM transactions WHERE id = ?", (tx_id,), one=True)
    if not row:
        return jsonify({"error": "No encontrado"}), 404

    allowed = ["date", "amount", "type", "transaction_type", "category_id",
               "description", "account_id", "card_id", "payment_method",
               "person_id", "project", "tags", "status", "notes"]
    update_data = {k: v for k, v in data.items() if k in allowed}
    if not update_data:
        return jsonify({"error": "Nada que actualizar"}), 400
    update_data["updated_at"] = datetime.now().isoformat(timespec="seconds")

    db.update("transactions", update_data, "id = ?", (tx_id,))
    db.audit("update", "transaction", tx_id, update_data, source="api")
    return jsonify({"id": tx_id, "status": "updated"})


@bp.route("/gastos/<int:tx_id>", methods=["DELETE"])
@require_token
def gastos_delete(tx_id):
    row = db.query("SELECT * FROM transactions WHERE id = ?", (tx_id,), one=True)
    if not row:
        return jsonify({"error": "No encontrado"}), 404
    # Revertir saldos
    if row["account_id"] and row["status"] == "pagado":
        mult = 1 if row["type"] == "expense" else -1
        db.execute(
            "UPDATE accounts SET balance = balance + ? WHERE id = ?",
            (row["amount"] * mult, row["account_id"])
        )
    if row["card_id"] and row["type"] == "expense":
        db.execute(
            "UPDATE credit_cards SET used_amount = used_amount - ? WHERE id = ?",
            (row["amount"], row["card_id"])
        )
    db.delete("card_installments", "transaction_id = ?", (tx_id,))
    db.delete("transactions", "id = ?", (tx_id,))
    db.audit("delete", "transaction", tx_id, source="api")
    return jsonify({"id": tx_id, "status": "deleted"})


# ============================================
# Personas / deudas
# ============================================
@bp.route("/personas")
@require_token
def personas_list():
    rows = db.query("""
        SELECT p.*,
               COALESCE((SELECT SUM(pending_amount) FROM person_debts
                         WHERE person_id=p.id AND direction='they_owe_me'
                               AND status IN ('pendiente','parcial')), 0) AS they_owe,
               COALESCE((SELECT SUM(pending_amount) FROM person_debts
                         WHERE person_id=p.id AND direction='i_owe_them'
                               AND status IN ('pendiente','parcial')), 0) AS i_owe
        FROM people p
        WHERE p.active = 1
        ORDER BY p.name
    """)
    return jsonify({"people": rows})


@bp.route("/deudas-personas")
@require_token
def debts_list():
    rows = db.query("""
        SELECT pd.*, p.name AS person_name
        FROM person_debts pd
        JOIN people p ON p.id = pd.person_id
        WHERE pd.status IN ('pendiente','parcial')
        ORDER BY pd.date DESC
    """)
    return jsonify({"debts": rows})


@bp.route("/deudas-personas/<int:debt_id>/abono", methods=["POST"])
@require_token
def debt_payment(debt_id):
    data = request.get_json(silent=True) or {}
    amount = safe_float(data.get("amount"))
    if amount <= 0:
        return jsonify({"error": "Monto inválido"}), 400

    debt = db.query("SELECT * FROM person_debts WHERE id = ?", (debt_id,), one=True)
    if not debt:
        return jsonify({"error": "Deuda no encontrada"}), 404

    db.insert("person_debt_payments", {
        "debt_id": debt_id,
        "amount": amount,
        "date": data.get("date") or today_iso(),
        "notes": data.get("notes"),
    })

    new_paid = (debt["paid_amount"] or 0) + amount
    new_pending = max(0, (debt["original_amount"] or 0) - new_paid)
    new_status = "pagado" if new_pending <= 0 else ("parcial" if new_paid > 0 else "pendiente")

    db.update("person_debts", {
        "paid_amount": new_paid,
        "pending_amount": new_pending,
        "status": new_status,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }, "id = ?", (debt_id,))
    db.audit("payment", "person_debt", debt_id, {"amount": amount}, source="api")
    return jsonify({"id": debt_id, "new_pending": new_pending, "status": new_status})


# ============================================
# Cuentas y tarjetas
# ============================================
@bp.route("/cuentas")
@require_token
def cuentas_list():
    rows = db.query("""
        SELECT a.*, b.name AS bank_name, b.color AS bank_color
        FROM accounts a
        LEFT JOIN banks b ON b.id = a.bank_id
        ORDER BY a.status, a.name
    """)
    return jsonify({"accounts": rows})


@bp.route("/tarjetas")
@require_token
def tarjetas_list():
    rows = db.query("""
        SELECT c.*, b.name AS bank_name, b.color AS bank_color,
               (c.credit_limit - c.used_amount) AS available_limit
        FROM credit_cards c
        LEFT JOIN banks b ON b.id = c.bank_id
        ORDER BY c.status, c.name
    """)
    return jsonify({"cards": rows})


# ============================================
# Recurrentes y presupuestos
# ============================================
@bp.route("/pagos-recurrentes")
@require_token
def recurrentes_list():
    rows = db.query("""
        SELECT r.*, c.name AS category_name
        FROM recurring_payments r
        LEFT JOIN categories c ON c.id = r.category_id
        WHERE r.active = 1
        ORDER BY r.day_of_month, r.name
    """)
    return jsonify({"recurring_payments": rows})


@bp.route("/presupuestos")
@require_token
def presupuestos_list():
    today = date.today()
    year = safe_int(request.args.get("year")) or today.year
    month = safe_int(request.args.get("month")) or today.month

    rows = db.query("""
        SELECT b.*, c.name AS category_name
        FROM budgets b
        LEFT JOIN categories c ON c.id = b.category_id
        WHERE b.year = ? AND (b.month = ? OR b.month IS NULL)
        ORDER BY b.scope, c.name
    """, (year, month))
    return jsonify({"budgets": rows, "year": year, "month": month})


# ============================================
# Calendario y alertas
# ============================================
@bp.route("/calendario")
@require_token
def calendario():
    today = date.today()
    ym_str = today.strftime("%Y-%m")

    cards = db.query("""
        SELECT 'card_payment' AS kind, c.id, c.name AS title, c.payment_day AS day,
               c.billed_amount AS amount
        FROM credit_cards c
        WHERE c.status='activa' AND c.payment_day IS NOT NULL
              AND c.has_billed_debt = 1
    """)

    rec = db.query("""
        SELECT 'recurring' AS kind, r.id, r.name AS title, r.day_of_month AS day,
               r.amount
        FROM recurring_payments r
        WHERE r.active = 1 AND r.day_of_month IS NOT NULL
    """)

    return jsonify({"month": ym_str, "events": list(cards) + list(rec)})


@bp.route("/alertas")
@require_token
def alertas_list():
    rows = db.query("""
        SELECT * FROM alerts
        WHERE dismissed = 0
        ORDER BY severity DESC, created_at DESC
        LIMIT 50
    """)
    return jsonify({"alerts": rows})
