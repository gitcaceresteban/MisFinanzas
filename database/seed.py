"""
Datos iniciales: bancos chilenos con sus colores corporativos
y categorías comunes.
Se ejecuta solo si la tabla está vacía (idempotente).
"""
import sqlite3
import secrets
from pathlib import Path


# Bancos chilenos con sus paletas corporativas
CHILEAN_BANKS = [
    {
        "name": "Banco Falabella",
        "color": "#00803F",
        "color_secondary": "#FFFFFF",
        "website": "https://www.bancofalabella.cl",
        "notes": "Verde corporativo Falabella",
    },
    {
        "name": "Banco Santander",
        "color": "#EC0000",
        "color_secondary": "#FFFFFF",
        "website": "https://www.santander.cl",
        "notes": "Rojo Santander",
    },
    {
        "name": "Banco de Chile",
        "color": "#003DA5",
        "color_secondary": "#F4B223",
        "website": "https://www.bancochile.cl",
        "notes": "Azul y dorado Banco de Chile",
    },
    {
        "name": "Cencosud Scotiabank",
        "color": "#EC111A",
        "color_secondary": "#1A1A1A",
        "website": "https://www.cencosudscotiabank.cl",
        "notes": "Tarjeta Cencosud / Jumbo / Easy / Paris",
    },
    {
        "name": "Scotiabank",
        "color": "#EC111A",
        "color_secondary": "#FFFFFF",
        "website": "https://www.scotiabank.cl",
        "notes": "Rojo Scotiabank",
    },
    {
        "name": "Banco BICE",
        "color": "#003C71",
        "color_secondary": "#C8A951",
        "website": "https://www.bice.cl",
        "notes": "Azul corporativo BICE",
    },
    {
        "name": "Banco Itaú",
        "color": "#EC7000",
        "color_secondary": "#003087",
        "website": "https://www.itau.cl",
        "notes": "Naranjo y azul Itaú",
    },
    {
        "name": "Mercado Pago",
        "color": "#00B1EA",
        "color_secondary": "#FFE600",
        "website": "https://www.mercadopago.cl",
        "notes": "Celeste y amarillo Mercado Libre",
    },
    {
        "name": "BancoEstado",
        "color": "#E30613",
        "color_secondary": "#003DA5",
        "website": "https://www.bancoestado.cl",
        "notes": "Banco del Estado de Chile - incluye CuentaRUT",
    },
    {
        "name": "Coopeuch",
        "color": "#E30613",
        "color_secondary": "#FFFFFF",
        "website": "https://www.coopeuch.cl",
        "notes": "Cooperativa Coopeuch",
    },
    {
        "name": "Tenpo",
        "color": "#7B68EE",
        "color_secondary": "#1A1A1A",
        "website": "https://www.tenpo.cl",
        "notes": "Cuenta digital Tenpo",
    },
]


# Categorías por defecto
DEFAULT_CATEGORIES = [
    {"name": "Comida", "color": "#f97316", "icon": "utensils"},
    {"name": "Transporte", "color": "#06b6d4", "icon": "car"},
    {"name": "Universidad", "color": "#8b5cf6", "icon": "graduation-cap"},
    {"name": "Salud", "color": "#ef4444", "icon": "heart-pulse"},
    {"name": "Casa", "color": "#84cc16", "icon": "home"},
    {"name": "Servicios básicos", "color": "#facc15", "icon": "zap"},
    {"name": "Internet", "color": "#3b82f6", "icon": "wifi"},
    {"name": "Suscripciones", "color": "#a855f7", "icon": "credit-card"},
    {"name": "Mascotas", "color": "#d97706", "icon": "paw-print"},
    {"name": "Deporte", "color": "#10b981", "icon": "dumbbell"},
    {"name": "Ropa", "color": "#ec4899", "icon": "shirt"},
    {"name": "Tecnología", "color": "#6366f1", "icon": "laptop"},
    {"name": "Auto", "color": "#0ea5e9", "icon": "car"},
    {"name": "Viajes", "color": "#14b8a6", "icon": "plane"},
    {"name": "Regalos", "color": "#f43f5e", "icon": "gift"},
    {"name": "Entretenimiento", "color": "#fb7185", "icon": "tv"},
    {"name": "Deudas", "color": "#dc2626", "icon": "trending-down"},
    {"name": "Ahorro", "color": "#16a34a", "icon": "piggy-bank"},
    {"name": "Ingresos", "color": "#22c55e", "icon": "trending-up"},
    {"name": "Otros", "color": "#64748b", "icon": "more-horizontal"},
]


def seed_initial_data(app) -> None:
    """Inserta datos iniciales solo si las tablas están vacías."""
    db_path = app.config["DATABASE_PATH"]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        # Usuario admin (sin auth, solo para FK futura)
        cur = conn.execute("SELECT COUNT(*) as c FROM users")
        if cur.fetchone()["c"] == 0:
            api_token = app.config.get("API_TOKEN") or secrets.token_urlsafe(32)
            conn.execute(
                "INSERT INTO users (username, display_name, api_token) VALUES (?, ?, ?)",
                ("admin", "Esteban", api_token),
            )

        # Bancos
        cur = conn.execute("SELECT COUNT(*) as c FROM banks")
        if cur.fetchone()["c"] == 0:
            for b in CHILEAN_BANKS:
                conn.execute(
                    """INSERT INTO banks (name, country, color, color_secondary,
                       website, notes, is_seeded)
                       VALUES (?, 'CL', ?, ?, ?, ?, 1)""",
                    (b["name"], b["color"], b.get("color_secondary"),
                     b.get("website"), b.get("notes")),
                )

        # Categorías
        cur = conn.execute("SELECT COUNT(*) as c FROM categories")
        if cur.fetchone()["c"] == 0:
            for i, c in enumerate(DEFAULT_CATEGORIES):
                conn.execute(
                    """INSERT INTO categories (name, color, icon, sort_order)
                       VALUES (?, ?, ?, ?)""",
                    (c["name"], c["color"], c["icon"], i),
                )

        # Settings por defecto
        cur = conn.execute("SELECT COUNT(*) as c FROM settings")
        if cur.fetchone()["c"] == 0:
            defaults = {
                "theme": "auto",  # auto, light, dark
                "currency": "CLP",
                "date_format": "dd/mm/yyyy",
                "first_day_of_month": "1",
                "low_balance_threshold": "50000",
                "low_card_limit_pct": "20",
                "budget_warn_pct": "80",
                "app_version": "1.0.0",
            }
            for k, v in defaults.items():
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)", (k, v)
                )

        conn.commit()

        # Datos personales privados (opcional). El archivo seed_personal.py
        # está en .gitignore para que tus montos reales no queden en el repo.
        try:
            from database import seed_personal
            seed_personal.load(conn)
            conn.commit()
        except ImportError:
            pass
        except Exception as e:  # no romper el arranque por un fallo de seed personal
            print(f"[seed_personal] aviso: {e}")
    finally:
        conn.close()
