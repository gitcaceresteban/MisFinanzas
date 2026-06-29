"""Vista de ingresos: usa la misma tabla transactions pero filtra por type='income'."""
from datetime import date
from flask import Blueprint, render_template, request
from database import db
from modules.helpers import safe_str, safe_int

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
