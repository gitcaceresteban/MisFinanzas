"""
Motor Financiero Personal - Aplicación principal Flask.
Diseñada para correr 24/7 en Raspberry Pi en red local.
"""
import os
import sys
from pathlib import Path
from flask import Flask, render_template, redirect, url_for, jsonify

from config import Config
from database import db as database, seed_initial_data
from modules.helpers import (
    format_clp, format_date_cl, status_color,
    month_name_es, day_name_es, days_until, icon_emoji, loan_type_label
)


def create_app() -> Flask:
    """Application factory."""
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(Config)

    # Inicializar base de datos (crea tablas si no existen)
    database.init_db(app)

    # Aplicar migraciones (columnas nuevas en BD ya existentes)
    database.run_migrations(app)

    # Sembrar datos iniciales (bancos chilenos, categorías)
    seed_initial_data(app)

    # Registrar teardown DB
    database.register(app)

    # Filtros Jinja2 personalizados
    app.jinja_env.filters["clp"] = format_clp
    app.jinja_env.filters["fecha"] = format_date_cl
    app.jinja_env.filters["status_color"] = status_color
    app.jinja_env.filters["month_es"] = month_name_es
    app.jinja_env.filters["day_es"] = day_name_es
    app.jinja_env.filters["days_until"] = days_until
    app.jinja_env.filters["emoji"] = icon_emoji
    app.jinja_env.filters["loan_type"] = loan_type_label

    # Inyectar utilidades en todas las plantillas
    @app.context_processor
    def inject_globals():
        from datetime import date, datetime
        return {
            "current_date": date.today(),
            "current_year": date.today().year,
            "current_month": date.today().month,
            # 'today' en ISO (YYYY-MM-DD) para usar como valor por defecto
            # en <input type="date"> de los formularios.
            "today": date.today().isoformat(),
            "app_name": "Motor Financiero",
            "app_version": "1.0.0",
        }

    # Registrar blueprints
    from modules.dashboard import bp as dashboard_bp
    from modules.banks import bp as banks_bp
    from modules.accounts import bp as accounts_bp
    from modules.cards import bp as cards_bp
    from modules.transactions import bp as transactions_bp
    from modules.people import bp as people_bp
    from modules.household import bp as household_bp
    from modules.recurring import bp as recurring_bp
    from modules.budgets import bp as budgets_bp
    from modules.loans import bp as loans_bp
    from modules.incomes import bp as incomes_bp
    from modules.alerts import bp as alerts_bp
    from modules.calendar_view import bp as calendar_bp
    from modules.cashflow import bp as cashflow_bp
    from modules.planning import bp as planning_bp
    from modules.settings import bp as settings_bp
    from modules.backup import bp as backup_bp
    from modules.api import bp as api_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(banks_bp, url_prefix="/bancos")
    app.register_blueprint(accounts_bp, url_prefix="/cuentas")
    app.register_blueprint(cards_bp, url_prefix="/tarjetas")
    app.register_blueprint(transactions_bp, url_prefix="/gastos")
    app.register_blueprint(people_bp, url_prefix="/personas")
    app.register_blueprint(household_bp, url_prefix="/hogar")
    app.register_blueprint(recurring_bp, url_prefix="/recurrentes")
    app.register_blueprint(budgets_bp, url_prefix="/presupuestos")
    app.register_blueprint(loans_bp, url_prefix="/creditos")
    app.register_blueprint(incomes_bp, url_prefix="/ingresos")
    app.register_blueprint(alerts_bp, url_prefix="/alertas")
    app.register_blueprint(calendar_bp, url_prefix="/calendario")
    app.register_blueprint(cashflow_bp, url_prefix="/flujo")
    app.register_blueprint(planning_bp, url_prefix="/plan")
    app.register_blueprint(settings_bp, url_prefix="/ajustes")
    app.register_blueprint(backup_bp, url_prefix="/backup")
    app.register_blueprint(api_bp, url_prefix="/api")

    # Health check
    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "service": "finance_app"})

    # Manejo de errores
    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html",
                               code=404,
                               message="La página que buscas no existe."), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("error.html",
                               code=500,
                               message="Algo salió mal en el servidor."), 500

    return app


if __name__ == "__main__":
    app = create_app()
    print("")
    print("=" * 56)
    print("  Motor Financiero Personal")
    print("=" * 56)
    print(f"  Servidor:  http://{app.config['HOST']}:{app.config['PORT']}")
    print(f"  Base:      {app.config['DATABASE_PATH']}")
    print(f"  Debug:     {app.config['DEBUG']}")
    print("  Detén con: Ctrl+C")
    print("=" * 56)
    print("")
    app.run(
        host=app.config["HOST"],
        port=app.config["PORT"],
        debug=app.config["DEBUG"],
    )
