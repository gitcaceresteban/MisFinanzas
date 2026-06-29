"""
Configuración centralizada de la aplicación.
Carga variables desde .env y expone defaults sensatos.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar .env si existe
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    """Configuración base."""

    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-cambiar-en-produccion")
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"

    # Servidor
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 5000))

    # Base de datos
    DATABASE_PATH = str(BASE_DIR / os.getenv("DATABASE_PATH", "database/finance.db"))

    # API
    API_TOKEN = os.getenv("API_TOKEN", "cambia-este-token")

    # Regional
    LOCALE = os.getenv("LOCALE", "es_CL")
    CURRENCY = os.getenv("CURRENCY", "CLP")
    TIMEZONE = os.getenv("TIMEZONE", "America/Santiago")

    # Directorios
    BACKUP_DIR = BASE_DIR / os.getenv("BACKUP_DIR", "backups")
    UPLOAD_DIR = BASE_DIR / os.getenv("UPLOAD_DIR", "uploads")
    BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", 10))
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", 10))

    # Flask config
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
    JSON_AS_ASCII = False
    JSONIFY_PRETTYPRINT_REGULAR = False
    TEMPLATES_AUTO_RELOAD = DEBUG


# Asegurar que los directorios existan
Config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
Config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
Path(Config.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
