"""Configuración general del sistema."""
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import db
from modules.helpers import safe_str, parse_money

bp = Blueprint("settings", __name__)


@bp.route("/")
def index():
    settings_rows = db.query("SELECT * FROM settings ORDER BY key")
    settings = {s["key"]: s["value"] for s in settings_rows}

    categories = db.query("""
        SELECT c.*,
               (SELECT COUNT(*) FROM transactions t WHERE t.category_id = c.id) AS tx_count
        FROM categories c
        WHERE c.active = 1
        ORDER BY c.sort_order, c.name
    """)

    return render_template("settings.html",
                          settings=settings,
                          categories=categories)


@bp.route("/guardar", methods=["POST"])
def save():
    """Guarda configuración key/value."""
    for k, v in request.form.items():
        if k.startswith("setting_"):
            key = k.replace("setting_", "")
            existing = db.query("SELECT key FROM settings WHERE key = ?",
                                (key,), one=True)
            if existing:
                db.update("settings", {
                    "value": v,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }, "key = ?", (key,))
            else:
                db.insert("settings", {"key": key, "value": v})
    flash("Configuración guardada", "success")
    return redirect(url_for("settings.index"))


# ---------- Categorías ----------
@bp.route("/categoria/nueva", methods=["POST"])
def category_create():
    data = {
        "name": safe_str(request.form.get("name")),
        "color": safe_str(request.form.get("color")) or "#64748b",
        "icon": safe_str(request.form.get("icon")) or "tag",
        "monthly_budget": parse_money(request.form.get("monthly_budget")),
    }
    if not data["name"]:
        flash("Nombre requerido", "error")
        return redirect(url_for("settings.index"))
    new_id = db.insert("categories", data)
    db.audit("create", "category", new_id, data)
    flash("Categoría creada", "success")
    return redirect(url_for("settings.index"))


@bp.route("/categoria/<int:cat_id>/editar", methods=["POST"])
def category_edit(cat_id):
    data = {
        "name": safe_str(request.form.get("name")),
        "color": safe_str(request.form.get("color")) or "#64748b",
        "icon": safe_str(request.form.get("icon")) or "tag",
        "monthly_budget": parse_money(request.form.get("monthly_budget")),
    }
    db.update("categories", data, "id = ?", (cat_id,))
    db.audit("update", "category", cat_id, data)
    flash("Categoría actualizada", "success")
    return redirect(url_for("settings.index"))


@bp.route("/categoria/<int:cat_id>/eliminar", methods=["POST"])
def category_remove(cat_id):
    db.update("categories", {"active": 0}, "id = ?", (cat_id,))
    db.audit("delete", "category", cat_id)
    flash("Categoría desactivada", "info")
    return redirect(url_for("settings.index"))
