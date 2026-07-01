"""Gestión de transacciones (gastos, ingresos, etc.)."""
import os
from datetime import datetime, date
from pathlib import Path
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, current_app, send_from_directory, Response)
from werkzeug.utils import secure_filename
from database import db
from modules.helpers import (
    safe_str, safe_float, safe_int, parse_money, today_iso, parse_date_cl,
    icon_emoji
)
from modules.cards import create_installments

bp = Blueprint("transactions", __name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf", "webp", "gif"}

PAYMENT_METHODS = [
    ("efectivo", "Efectivo"),
    ("transferencia", "Transferencia"),
    ("debito", "Tarjeta débito"),
    ("credito", "Tarjeta crédito"),
    ("app", "App / Billetera"),
    ("otro", "Otro"),
]

TRANSACTION_TYPES = [
    ("normal", "Compra normal"),
    ("installments", "Compra en cuotas"),
    ("cash_advance", "Avance"),
    ("super_advance", "Súper avance"),
    ("debt_payment", "Pago de deuda"),
    ("fee_interest", "Comisión/interés"),
    ("adjustment", "Ajuste manual"),
]

STATUSES = [
    ("pagado", "Pagado"),
    ("pendiente", "Pendiente"),
    ("reembolsado", "Reembolsado"),
    ("anulado", "Anulado"),
]


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _categories_json(categories):
    """Serializa las categorías con su tipo (kind) y emoji para que el
    formulario pueda mostrar solo las de gasto o solo las de ingreso."""
    return [{
        "id": c["id"],
        "name": c["name"],
        "kind": (c.get("kind") if isinstance(c, dict) else c["kind"]) or "expense",
        "emoji": icon_emoji(c["icon"]),
    } for c in categories]


def _payment_options():
    """Cuentas y tarjetas (con logo del banco) para el selector unificado."""
    accounts = db.query("""
        SELECT a.*, b.name AS bank_name, b.logo_path AS bank_logo, b.color AS bank_color
        FROM accounts a LEFT JOIN banks b ON b.id = a.bank_id
        WHERE a.status='activa' ORDER BY a.name""")
    cards = db.query("""
        SELECT c.*, b.name AS bank_name, b.logo_path AS bank_logo, b.color AS bank_color
        FROM credit_cards c LEFT JOIN banks b ON b.id = c.bank_id
        WHERE c.status='activa' ORDER BY c.name""")
    return accounts, cards


def _resolve_payment_target(form):
    """Convierte el valor del selector unificado (acc:ID / card:ID) en
    (account_id, card_id). Cae a los campos sueltos si no viene."""
    target = safe_str(form.get("payment_target"))
    if target.startswith("acc:"):
        return safe_int(target[4:]) or None, None
    if target.startswith("card:"):
        return None, safe_int(target[5:]) or None
    # compatibilidad con campos separados
    return (safe_int(form.get("account_id")) or None,
            safe_int(form.get("card_id")) or None)


def _handle_shared(tx_id: int, data: dict) -> str:
    """Procesa un gasto compartido: crea cuentas por cobrar (personas) o una
    cuenta del hogar con sus participantes. Devuelve texto para el flash."""
    if not request.form.get("is_shared"):
        return ""
    mode = safe_str(request.form.get("shared_mode")) or "people"
    pids = request.form.getlist("share_person_id[]")
    amounts = request.form.getlist("share_amount[]")
    participants = []
    total_others = 0
    for i, pid in enumerate(pids):
        pid_int = safe_int(pid)
        amt = parse_money(amounts[i]) if i < len(amounts) else 0
        if pid_int > 0 and amt > 0:
            participants.append((pid_int, amt))
            total_others += amt
    if not participants:
        return ""

    my_share = max(0, (data["amount"] or 0) - total_others)
    db.update("transactions", {"is_shared": 1, "my_share": my_share},
              "id = ?", (tx_id,))

    if mode == "household":
        bill_id = db.insert("household_bills", {
            "name": data.get("description") or "Gasto compartido del hogar",
            "category_id": data.get("category_id"),
            "amount": data["amount"],
            "due_date": data.get("date"),
            "paid_by_person_id": None,           # lo pagué yo
            "paid_from_account_id": data.get("account_id"),
            "status": "pendiente",
            "split_type": "custom",
            "notes": f"Generado desde gasto #{tx_id}",
        })
        for pid_int, amt in participants:
            db.insert("household_bill_participants", {
                "bill_id": bill_id, "person_id": pid_int,
                "share_amount": amt, "paid_amount": 0, "status": "pendiente",
            })
        db.audit("create", "household_bill", bill_id, {"from_tx": tx_id})
        return " · cuenta del hogar creada"
    else:
        for pid_int, amt in participants:
            db.insert("person_debts", {
                "person_id": pid_int,
                "direction": "they_owe_me",
                "original_amount": amt,
                "pending_amount": amt,
                "paid_amount": 0,
                "date": data.get("date"),
                "description": data.get("description") or "Gasto compartido",
                "category_id": data.get("category_id"),
                "related_transaction_id": tx_id,
                "status": "pendiente",
            })
        return f" · {len(participants)} cuenta(s) por cobrar creada(s)"


def _save_attachment(file_storage) -> str:
    if not file_storage or not file_storage.filename:
        return None
    if not _allowed_file(file_storage.filename):
        return None
    upload_dir = current_app.config["UPLOAD_DIR"]
    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    fn = secure_filename(file_storage.filename)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    final = f"{stamp}_{fn}"
    file_storage.save(Path(upload_dir) / final)
    return final


@bp.route("/")
def index():
    # Filtros
    q = safe_str(request.args.get("q"))
    category_id = request.args.get("category_id")
    account_id = request.args.get("account_id")
    card_id = request.args.get("card_id")
    person_id = request.args.get("person_id")
    status = safe_str(request.args.get("status"))
    type_ = safe_str(request.args.get("type"))
    date_from = safe_str(request.args.get("date_from"))
    date_to = safe_str(request.args.get("date_to"))

    where = ["1=1"]
    params = []
    if q:
        where.append("(t.description LIKE ? OR t.notes LIKE ? OR t.tags LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]
    if category_id:
        where.append("t.category_id = ?")
        params.append(category_id)
    if account_id:
        where.append("t.account_id = ?")
        params.append(account_id)
    if card_id:
        where.append("t.card_id = ?")
        params.append(card_id)
    if person_id:
        where.append("t.person_id = ?")
        params.append(person_id)
    if status:
        where.append("t.status = ?")
        params.append(status)
    if type_:
        where.append("t.type = ?")
        params.append(type_)
    if date_from:
        where.append("t.date >= ?")
        params.append(date_from)
    if date_to:
        where.append("t.date <= ?")
        params.append(date_to)

    sql = f"""
        SELECT t.*, c.name AS category_name, c.color AS category_color,
               c.icon AS category_icon,
               a.name AS account_name, b1.color AS account_bank_color,
               cc.name AS card_name, b2.color AS card_bank_color,
               p.name AS person_name
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        LEFT JOIN accounts a ON a.id = t.account_id
        LEFT JOIN banks b1 ON b1.id = a.bank_id
        LEFT JOIN credit_cards cc ON cc.id = t.card_id
        LEFT JOIN banks b2 ON b2.id = cc.bank_id
        LEFT JOIN people p ON p.id = t.person_id
        WHERE {" AND ".join(where)}
        ORDER BY t.date DESC, t.id DESC
        LIMIT 500
    """
    transactions = db.query(sql, tuple(params))

    # Totales
    total_expenses = sum(t["amount"] for t in transactions
                         if t["type"] == "expense" and t["status"] == "pagado")
    total_incomes = sum(t["amount"] for t in transactions
                        if t["type"] == "income" and t["status"] == "pagado")

    categories = db.query("SELECT * FROM categories WHERE active=1 ORDER BY name")
    accounts = db.query("SELECT * FROM accounts ORDER BY name")
    cards = db.query("SELECT * FROM credit_cards ORDER BY name")
    people = db.query("SELECT * FROM people WHERE active=1 ORDER BY name")

    return render_template("transactions.html",
                           transactions=transactions,
                           categories=categories,
                           accounts=accounts,
                           cards=cards,
                           people=people,
                           total_expenses=total_expenses,
                           total_incomes=total_incomes,
                           statuses=STATUSES,
                           filters=request.args)


@bp.route("/nuevo", methods=["GET", "POST"])
def create():
    categories = db.query("SELECT * FROM categories WHERE active=1 ORDER BY name")
    accounts, cards = _payment_options()
    people = db.query("SELECT * FROM people WHERE active=1 ORDER BY name")

    if request.method == "POST":
        attachment = _save_attachment(request.files.get("attachment"))
        account_id, card_id = _resolve_payment_target(request.form)
        # Nº de cuotas: solo aplica si pagas con tarjeta (mínimo 1 = compra normal)
        installments_total = max(1, safe_int(request.form.get("installments_total")) or 1)
        if card_id and installments_total > 1:
            tx_type = "installments"
        else:
            tx_type = safe_str(request.form.get("transaction_type")) or "normal"
        # Método de pago derivado del destino elegido
        if card_id:
            payment_method = "credito"
        elif account_id:
            payment_method = safe_str(request.form.get("payment_method")) or "debito"
        else:
            payment_method = safe_str(request.form.get("payment_method")) or None

        data = {
            "date": safe_str(request.form.get("date")) or today_iso(),
            "amount": parse_money(request.form.get("amount")),
            "type": safe_str(request.form.get("type")) or "expense",
            "transaction_type": tx_type,
            "category_id": safe_int(request.form.get("category_id")) or None,
            "description": safe_str(request.form.get("description")) or None,
            "account_id": account_id,
            "card_id": card_id,
            "payment_method": payment_method,
            "person_id": safe_int(request.form.get("person_id")) or None,
            "project": safe_str(request.form.get("project")) or None,
            "tags": safe_str(request.form.get("tags")) or None,
            "attachment_path": attachment,
            "status": safe_str(request.form.get("status")) or "pagado",
            "origin": "web",
            "installments_total": installments_total if tx_type == "installments" else None,
            "notes": safe_str(request.form.get("notes")) or None,
        }
        new_id = db.insert("transactions", data)
        db.audit("create", "transaction", new_id, data)

        # Si es en cuotas, crear cuotas futuras
        if tx_type == "installments" and data["card_id"] and installments_total > 1:
            card = db.query("SELECT billing_day FROM credit_cards WHERE id=?",
                          (data["card_id"],), one=True)
            create_installments(
                card_id=data["card_id"],
                transaction_id=new_id,
                total_amount=data["amount"],
                total_installments=installments_total,
                start_date=data["date"],
                billing_day=card["billing_day"] if card else None,
            )

        # Si afecta cuenta, actualizar saldo
        if data["account_id"] and data["status"] == "pagado":
            multiplier = -1 if data["type"] == "expense" else 1
            db.execute(
                "UPDATE accounts SET balance = balance + ? WHERE id = ?",
                (data["amount"] * multiplier, data["account_id"])
            )

        # Si es gasto con tarjeta, sumar al cupo usado
        if data["card_id"] and data["type"] == "expense":
            db.execute(
                "UPDATE credit_cards SET used_amount = used_amount + ? WHERE id = ?",
                (data["amount"], data["card_id"])
            )

        # Gasto compartido: crear cuentas por cobrar o cuenta del hogar
        shared_msg = _handle_shared(new_id, data)

        flash("Movimiento registrado" + shared_msg, "success")
        return redirect(url_for("transactions.index"))

    default_type = safe_str(request.args.get("type")) or "expense"
    if default_type not in ("expense", "income", "transfer"):
        default_type = "expense"
    return render_template("transactions_form.html",
                           tx=None,
                           categories=categories,
                           categories_json=_categories_json(categories),
                           default_type=default_type,
                           accounts=accounts,
                           cards=cards,
                           people=people,
                           payment_methods=PAYMENT_METHODS,
                           types=TRANSACTION_TYPES,
                           statuses=STATUSES)


@bp.route("/<int:tx_id>/editar", methods=["GET", "POST"])
def edit(tx_id):
    tx = db.query("SELECT * FROM transactions WHERE id = ?", (tx_id,), one=True)
    if not tx:
        flash("Movimiento no encontrado", "error")
        return redirect(url_for("transactions.index"))

    categories = db.query("SELECT * FROM categories WHERE active=1 ORDER BY name")
    accounts, cards = _payment_options()
    people = db.query("SELECT * FROM people WHERE active=1 ORDER BY name")

    if request.method == "POST":
        attachment = _save_attachment(request.files.get("attachment")) or tx["attachment_path"]
        account_id, card_id = _resolve_payment_target(request.form)
        installments_total = max(1, safe_int(request.form.get("installments_total")) or 1)
        if card_id and installments_total > 1:
            tx_type = "installments"
        else:
            tx_type = safe_str(request.form.get("transaction_type")) or "normal"
        payment_method = "credito" if card_id else (safe_str(request.form.get("payment_method")) or ("debito" if account_id else None))
        data = {
            "date": safe_str(request.form.get("date")) or today_iso(),
            "amount": parse_money(request.form.get("amount")),
            "type": safe_str(request.form.get("type")) or "expense",
            "transaction_type": tx_type,
            "category_id": safe_int(request.form.get("category_id")) or None,
            "description": safe_str(request.form.get("description")) or None,
            "account_id": account_id,
            "card_id": card_id,
            "payment_method": payment_method,
            "person_id": safe_int(request.form.get("person_id")) or None,
            "project": safe_str(request.form.get("project")) or None,
            "tags": safe_str(request.form.get("tags")) or None,
            "attachment_path": attachment,
            "status": safe_str(request.form.get("status")) or "pagado",
            "notes": safe_str(request.form.get("notes")) or None,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        db.update("transactions", data, "id = ?", (tx_id,))
        db.audit("update", "transaction", tx_id, data)
        flash("Movimiento actualizado", "success")
        return redirect(url_for("transactions.index"))

    return render_template("transactions_form.html",
                           tx=tx,
                           categories=categories,
                           categories_json=_categories_json(categories),
                           default_type=tx["type"] or "expense",
                           accounts=accounts,
                           cards=cards,
                           people=people,
                           payment_methods=PAYMENT_METHODS,
                           types=TRANSACTION_TYPES,
                           statuses=STATUSES)


@bp.route("/<int:tx_id>/eliminar", methods=["POST"])
def remove(tx_id):
    tx = db.query("SELECT * FROM transactions WHERE id = ?", (tx_id,), one=True)
    if not tx:
        flash("Movimiento no encontrado", "error")
        return redirect(url_for("transactions.index"))
    # Revertir efectos en cuentas/tarjetas
    if tx["account_id"] and tx["status"] == "pagado":
        multiplier = 1 if tx["type"] == "expense" else -1
        db.execute(
            "UPDATE accounts SET balance = balance + ? WHERE id = ?",
            (tx["amount"] * multiplier, tx["account_id"])
        )
    if tx["card_id"] and tx["type"] == "expense":
        db.execute(
            "UPDATE credit_cards SET used_amount = used_amount - ? WHERE id = ?",
            (tx["amount"], tx["card_id"])
        )
    # Eliminar cuotas asociadas
    db.delete("card_installments", "transaction_id = ?", (tx_id,))
    db.delete("transactions", "id = ?", (tx_id,))
    db.audit("delete", "transaction", tx_id)
    flash("Movimiento eliminado", "info")
    return redirect(url_for("transactions.index"))


@bp.route("/<int:tx_id>/duplicar", methods=["POST"])
def duplicate(tx_id):
    tx = db.query("SELECT * FROM transactions WHERE id = ?", (tx_id,), one=True)
    if not tx:
        flash("Movimiento no encontrado", "error")
        return redirect(url_for("transactions.index"))
    new_data = {k: v for k, v in tx.items()
                if k not in ("id", "created_at", "updated_at")}
    new_data["date"] = today_iso()
    new_id = db.insert("transactions", new_data)
    db.audit("create", "transaction", new_id, {"duplicated_from": tx_id})
    flash("Movimiento duplicado", "success")
    return redirect(url_for("transactions.edit", tx_id=new_id))


@bp.route("/exportar.csv")
def export_csv():
    rows = db.query("""
        SELECT t.id, t.date, t.amount, t.type, t.transaction_type, t.description,
               c.name AS categoria, a.name AS cuenta, cc.name AS tarjeta,
               p.name AS persona, t.payment_method, t.status, t.origin, t.notes
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        LEFT JOIN accounts a ON a.id = t.account_id
        LEFT JOIN credit_cards cc ON cc.id = t.card_id
        LEFT JOIN people p ON p.id = t.person_id
        ORDER BY t.date DESC, t.id DESC
    """)
    headers = ["id", "fecha", "monto", "tipo", "subtipo", "descripcion",
               "categoria", "cuenta", "tarjeta", "persona", "metodo_pago",
               "estado", "origen", "notas"]
    lines = [",".join(headers)]
    for r in rows:
        vals = [str(r.get(k, "") or "").replace(",", " ") for k in
                ["id", "date", "amount", "type", "transaction_type", "description",
                 "categoria", "cuenta", "tarjeta", "persona", "payment_method",
                 "status", "origin", "notes"]]
        lines.append(",".join(vals))
    csv = "\n".join(lines)
    return Response(csv, mimetype="text/csv",
                    headers={"Content-Disposition":
                             "attachment; filename=gastos.csv"})


@bp.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(current_app.config["UPLOAD_DIR"], filename)
