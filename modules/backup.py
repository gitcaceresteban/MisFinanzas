"""Backups manuales de la base de datos."""
import os
import shutil
from datetime import datetime
from pathlib import Path
from flask import Blueprint, render_template, redirect, url_for, flash, current_app, send_from_directory

bp = Blueprint("backup", __name__)


@bp.route("/")
def index():
    backup_dir = Path(current_app.config["BACKUP_DIR"])
    backup_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(backup_dir.glob("*.db"), reverse=True):
        stat = f.stat()
        files.append({
            "name": f.name,
            "size_kb": round(stat.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
        })
    return render_template("backup.html", backups=files,
                          backup_dir=str(backup_dir))


@bp.route("/crear", methods=["POST"])
def create():
    """Crea un snapshot del SQLite."""
    db_path = Path(current_app.config["DATABASE_PATH"])
    backup_dir = Path(current_app.config["BACKUP_DIR"])
    backup_dir.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        flash("Base de datos no encontrada", "error")
        return redirect(url_for("backup.index"))

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"finance_{stamp}.db"
    try:
        shutil.copy2(db_path, target)
        flash(f"Backup creado: {target.name}", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")

    # Retención
    keep = current_app.config.get("BACKUP_KEEP", 10)
    backups = sorted(backup_dir.glob("finance_*.db"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        try:
            old.unlink()
        except Exception:
            pass

    return redirect(url_for("backup.index"))


@bp.route("/<path:filename>")
def download(filename):
    backup_dir = current_app.config["BACKUP_DIR"]
    return send_from_directory(backup_dir, filename, as_attachment=True)


@bp.route("/<path:filename>/eliminar", methods=["POST"])
def remove(filename):
    backup_dir = Path(current_app.config["BACKUP_DIR"])
    target = backup_dir / filename
    if target.exists() and target.is_file():
        try:
            target.unlink()
            flash(f"Backup eliminado: {filename}", "info")
        except Exception as e:
            flash(f"Error eliminando: {e}", "error")
    return redirect(url_for("backup.index"))
