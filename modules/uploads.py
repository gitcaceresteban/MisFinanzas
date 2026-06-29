"""Utilidades para subir y servir imágenes (logos de bancos, proveedores)."""
from datetime import datetime
from pathlib import Path
from flask import current_app, send_from_directory, abort
from werkzeug.utils import secure_filename

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif", "svg"}


def _allowed_image(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in IMAGE_EXTENSIONS


def save_image(file_storage, prefix: str = "logo"):
    """Guarda una imagen subida y devuelve el nombre de archivo (o None)."""
    if not file_storage or not file_storage.filename:
        return None
    if not _allowed_image(file_storage.filename):
        return None
    upload_dir = current_app.config["UPLOAD_DIR"]
    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    fn = secure_filename(file_storage.filename)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    final = f"{prefix}_{stamp}_{fn}"
    file_storage.save(Path(upload_dir) / final)
    return final


def serve_image(filename: str):
    """Sirve una imagen del directorio de uploads."""
    upload_dir = current_app.config["UPLOAD_DIR"]
    safe = secure_filename(filename)
    if not safe or not (Path(upload_dir) / safe).exists():
        abort(404)
    return send_from_directory(upload_dir, safe)
