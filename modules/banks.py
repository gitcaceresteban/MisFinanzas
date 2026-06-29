"""Gestión de bancos."""
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import db
from modules.helpers import safe_str, safe_int
from modules.uploads import save_image, serve_image

bp = Blueprint("banks", __name__)


@bp.route("/logo/<path:filename>")
def logo(filename):
    return serve_image(filename)


@bp.route("/")
def index():
    banks = db.query("""
        SELECT b.*,
               (SELECT COUNT(*) FROM accounts a WHERE a.bank_id = b.id) AS accounts_count,
               (SELECT COUNT(*) FROM credit_cards c WHERE c.bank_id = b.id) AS cards_count,
               (SELECT COUNT(*) FROM loans l WHERE l.bank_id = b.id) AS loans_count,
               (SELECT COALESCE(SUM(a.balance),0) FROM accounts a WHERE a.bank_id = b.id) AS total_balance
        FROM banks b
        WHERE b.active = 1
        ORDER BY b.is_seeded DESC, b.name ASC
    """)
    return render_template("banks.html", banks=banks)


@bp.route("/nuevo", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        logo_file = save_image(request.files.get("logo"), prefix="bank")
        data = {
            "name": safe_str(request.form.get("name")),
            "country": safe_str(request.form.get("country")) or "CL",
            "color": safe_str(request.form.get("color")) or "#3b82f6",
            "color_secondary": safe_str(request.form.get("color_secondary")) or None,
            "website": safe_str(request.form.get("website")) or None,
            "notes": safe_str(request.form.get("notes")) or None,
            "logo_path": logo_file,
            "is_seeded": 0,
        }
        if not data["name"]:
            flash("El nombre es obligatorio", "error")
            return redirect(url_for("banks.create"))
        new_id = db.insert("banks", data)
        db.audit("create", "bank", new_id, data)
        flash(f"Banco '{data['name']}' agregado", "success")
        return redirect(url_for("banks.index"))
    return render_template("banks_form.html", bank=None)


@bp.route("/<int:bank_id>/editar", methods=["GET", "POST"])
def edit(bank_id):
    bank = db.query("SELECT * FROM banks WHERE id = ?", (bank_id,), one=True)
    if not bank:
        flash("Banco no encontrado", "error")
        return redirect(url_for("banks.index"))

    if request.method == "POST":
        logo_file = save_image(request.files.get("logo"), prefix="bank")
        data = {
            "name": safe_str(request.form.get("name")),
            "country": safe_str(request.form.get("country")) or "CL",
            "color": safe_str(request.form.get("color")) or "#3b82f6",
            "color_secondary": safe_str(request.form.get("color_secondary")) or None,
            "website": safe_str(request.form.get("website")) or None,
            "notes": safe_str(request.form.get("notes")) or None,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        if logo_file:
            data["logo_path"] = logo_file
        db.update("banks", data, "id = ?", (bank_id,))
        db.audit("update", "bank", bank_id, data)
        flash("Banco actualizado", "success")
        return redirect(url_for("banks.index"))

    return render_template("banks_form.html", bank=bank)


@bp.route("/<int:bank_id>/eliminar", methods=["POST"])
def remove(bank_id):
    # Soft delete: solo desactivar para preservar histórico
    db.update("banks", {"active": 0}, "id = ?", (bank_id,))
    db.audit("delete", "bank", bank_id)
    flash("Banco desactivado", "info")
    return redirect(url_for("banks.index"))


@bp.route("/<int:bank_id>/restaurar", methods=["POST"])
def restore(bank_id):
    db.update("banks", {"active": 1}, "id = ?", (bank_id,))
    flash("Banco restaurado", "success")
    return redirect(url_for("banks.index"))
