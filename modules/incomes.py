"""Vista de ingresos: usa la misma tabla transactions pero filtra por type='income'."""
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import db
from modules.helpers import safe_str, safe_int, parse_money, today_iso

bp = Blueprint("incomes", __name__)


@bp.route("/")
def index():
    today = date.today()
    year = safe_int(request.args.get("year")) or today.year
    month = request.args.get("month")
    ym_str = f"{year}-{int(month):02d}" if month else f"{year}-{today.month:02d}"

    incomes = db.query("""
        SELECT t.*, c.name AS category_name, c.color AS category_color,
               c.icon AS category_icon,
               a.name AS account_name, b.color AS bank_color,
               p.name AS person_name
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        LEFT JOIN accounts a ON a.id = t.account_id
        LEFT JOIN banks b ON b.id = a.bank_id
        LEFT JOIN people p ON p.id = t.person_id
        WHERE t.type = 'income'
              AND strftime('%Y-%m', t.date) = ?
        ORDER BY t.date DESC
    """, (ym_str,))

    total = sum(i["amount"] for i in incomes if i["status"] == "pagado")

    # Por categoría
    by_category = db.query("""
        SELECT c.name, c.color, c.icon, SUM(t.amount) AS total
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.type='income' AND t.status='pagado'
              AND strftime('%Y-%m', t.date) = ?
        GROUP BY c.id
        ORDER BY total DESC
    """, (ym_str,))

    # Por mes (últimos 12)
    monthly = db.query("""
        SELECT strftime('%Y-%m', date) AS month,
               SUM(amount) AS total
        FROM transactions
        WHERE type='income' AND status='pagado'
              AND date >= date('now', '-12 months')
        GROUP BY month
        ORDER BY month ASC
    """)

    return render_template("incomes.html",
                          incomes=incomes,
                          total=total,
                          by_category=by_category,
                          monthly=monthly,
                          year=year, month=int(month) if month else today.month)


@bp.route("/nuevo", methods=["GET", "POST"])
def create():
    """Formulario propio para ingresos: más simple que el de gastos
    (sin cuotas, sin gasto compartido, solo cuentas como destino)."""
    categories = db.query("""
        SELECT * FROM categories WHERE active=1 AND kind='income' ORDER BY name
    """)
    accounts = db.query("""
        SELECT a.*, b.name AS bank_name, b.logo_path AS bank_logo
        FROM accounts a LEFT JOIN banks b ON b.id = a.bank_id
        WHERE a.status='activa' ORDER BY a.name
    """)
    people = db.query("SELECT * FROM people WHERE active=1 ORDER BY name")

    if request.method == "POST":
        amount = parse_money(request.form.get("amount"))
        if amount <= 0:
            flash("El monto debe ser mayor a 0", "error")
            return redirect(url_for("incomes.create"))

        data = {
            "date": safe_str(request.form.get("date")) or today_iso(),
            "amount": amount,
            "type": "income",
            "transaction_type": "normal",
            "category_id": safe_int(request.form.get("category_id")) or None,
            "description": safe_str(request.form.get("description")) or None,
            "account_id": safe_int(request.form.get("account_id")) or None,
            "person_id": safe_int(request.form.get("person_id")) or None,
            "status": safe_str(request.form.get("status")) or "pagado",
            "origin": "web",
            "notes": safe_str(request.form.get("notes")) or None,
        }
        new_id = db.insert("transactions", data)
        db.audit("create", "transaction", new_id, data)

        # El ingreso suma al saldo de la cuenta destino
        if data["account_id"] and data["status"] == "pagado":
            db.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?",
                       (amount, data["account_id"]))

        flash("Ingreso registrado", "success")
        return redirect(url_for("incomes.index"))

    return render_template("incomes_form.html",
                          categories=categories,
                          accounts=accounts,
                          people=people)
