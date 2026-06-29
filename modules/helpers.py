"""
Utilidades transversales: formateo de moneda CLP,
manejo de fechas en formato chileno, etc.
"""
from datetime import datetime, date, timedelta
from typing import Optional, Union
import calendar


# =========================
# Formateo moneda chilena
# =========================
def format_clp(value: Optional[Union[int, float]], with_symbol: bool = True) -> str:
    """Formatea un monto a estilo chileno: $1.234.567"""
    if value is None:
        return "$0" if with_symbol else "0"
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return "$0" if with_symbol else "0"
    sign = "-" if n < 0 else ""
    n = abs(n)
    s = f"{n:,}".replace(",", ".")
    return f"{sign}${s}" if with_symbol else f"{sign}{s}"


def parse_clp(text: str) -> int:
    """Parsea '$1.234.567' -> 1234567"""
    if text is None:
        return 0
    cleaned = str(text).replace("$", "").replace(".", "").replace(",", "").strip()
    if not cleaned or cleaned == "-":
        return 0
    try:
        return int(cleaned)
    except ValueError:
        try:
            return int(float(cleaned))
        except ValueError:
            return 0


def parse_money(value, default: float = 0.0) -> float:
    """
    Parsea montos en formato chileno tolerando el separador de miles con punto.
    Acepta '$1.234.567', '1.234.567', '1234567', '-50.000', '1.234,50'.
    Importante: en Chile el punto es separador de miles, por eso NO se trata
    como decimal. La coma (rara en montos enteros) sí se trata como decimal.
    Úsalo para TODO campo de dinero del formulario (los inputs se autoformatean
    con puntos en el navegador, y Python debe entenderlos igual).
    """
    if value is None:
        return default
    s = str(value).strip()
    if not s:
        return default
    negative = s.startswith("-")
    s = s.replace("$", "").replace(" ", "").replace(" ", "")
    s = s.replace(".", "")        # quitar separador de miles
    s = s.replace(",", ".")       # coma -> punto decimal (por si acaso)
    cleaned = "".join(ch for ch in s if ch.isdigit() or ch == ".")
    if cleaned in ("", ".", "-"):
        return default
    try:
        val = float(cleaned)
    except ValueError:
        return default
    return -val if negative else val


# =========================
# Formateo fechas
# =========================
def format_date_cl(d: Union[str, date, datetime, None],
                   fmt: str = "%d/%m/%Y") -> str:
    """Formatea fecha en estilo chileno dd/mm/yyyy"""
    if d is None or d == "":
        return ""
    if isinstance(d, str):
        try:
            # Intentar varios formatos
            for f in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                     "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    d = datetime.strptime(d, f)
                    break
                except ValueError:
                    continue
            else:
                return str(d)
        except Exception:
            return str(d)
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime(fmt)


def parse_date_cl(s: str) -> Optional[date]:
    """Parsea string a date en cualquier formato común."""
    if not s:
        return None
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def today_iso() -> str:
    return date.today().isoformat()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def month_range(year: int, month: int) -> tuple:
    """Devuelve (primer_dia, ultimo_dia) del mes."""
    first = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    last = date(year, month, last_day)
    return first, last


def current_month_range() -> tuple:
    t = date.today()
    return month_range(t.year, t.month)


def add_months(d: date, months: int) -> date:
    """Suma N meses a una fecha, ajustando el día si es necesario."""
    new_month = d.month - 1 + months
    new_year = d.year + new_month // 12
    new_month = new_month % 12 + 1
    last_day = calendar.monthrange(new_year, new_month)[1]
    new_day = min(d.day, last_day)
    return date(new_year, new_month, new_day)


def days_until(target: Union[str, date, None]) -> Optional[int]:
    """Días desde hoy hasta target (negativo si ya pasó)."""
    if target is None:
        return None
    if isinstance(target, str):
        target = parse_date_cl(target)
    if not target:
        return None
    return (target - date.today()).days


# =========================
# Status helpers
# =========================
STATUS_COLORS = {
    "pagado": "green",
    "pendiente": "yellow",
    "parcial": "blue",
    "vencido": "red",
    "vencida": "red",
    "atrasada": "red",
    "anulado": "gray",
    "cancelado": "gray",
    "reembolsado": "blue",
    "activa": "green",
    "cerrada": "gray",
    "pausada": "yellow",
    "vigente": "green",
    "refinanciada": "blue",
    "bloqueada": "red",
    "facturada": "yellow",
}


def status_color(status: Optional[str]) -> str:
    return STATUS_COLORS.get((status or "").lower(), "gray")


# =========================
# Emojis (diseño)
# =========================
# Mapea los nombres de iconos guardados en BD (estilo Lucide) a emojis,
# para darle vida visual a la app sin depender de librerías de iconos.
ICON_EMOJI = {
    "utensils": "🍽️", "car": "🚗", "graduation-cap": "🎓", "heart-pulse": "🩺",
    "home": "🏠", "zap": "⚡", "wifi": "📶", "credit-card": "💳", "paw-print": "🐾",
    "dumbbell": "🏋️", "shirt": "👕", "laptop": "💻", "plane": "✈️", "gift": "🎁",
    "tv": "📺", "trending-down": "📉", "piggy-bank": "🐷", "trending-up": "📈",
    "more-horizontal": "📦", "tag": "🏷️", "shopping-cart": "🛒", "coffee": "☕",
    "fuel": "⛽", "bus": "🚌", "book": "📚", "music": "🎵", "film": "🎬",
    "phone": "📱", "droplet": "💧", "flame": "🔥", "wrench": "🔧", "briefcase": "💼",
    "dollar-sign": "💵", "banknote": "💵", "wallet": "👛", "building-2": "🏦",
    "landmark": "🏛️", "users": "👥", "repeat": "🔁", "calendar": "📅", "bell": "🔔",
    "target": "🎯", "activity": "📊", "pie-chart": "📊", "baby": "👶", "scissors": "✂️",
    "smartphone": "📱", "gamepad-2": "🎮", "plug": "🔌", "bike": "🚲", "train": "🚆",
    "sparkles": "✨", "star": "⭐", "umbrella": "☂️", "shield": "🛡️", "leaf": "🌿",
    # iconos típicos de estados vacíos / secciones
    "inbox": "📭", "list": "📋", "folder": "📁", "package": "📦", "clock": "🕐",
    "alert-triangle": "⚠️", "alert-circle": "🔔", "check-circle": "✅", "x-circle": "⛔",
    "file-text": "📄", "database": "💾", "settings": "⚙️", "user": "👤", "user-plus": "🧑‍🤝‍🧑",
}


LOAN_TYPE_LABELS = {
    "consumo": "Consumo", "automotriz": "Automotriz", "hipotecario": "Hipotecario",
    "avance": "Avance", "super_avance": "Súper avance", "personal": "Préstamo",
    "cuotas": "En cuotas", "otra": "Otra",
}


def loan_type_label(code: Optional[str]) -> str:
    return LOAN_TYPE_LABELS.get((code or "").lower(), (code or "").replace("_", " ").title())


def icon_emoji(name: Optional[str], default: str = "🏷️") -> str:
    """Devuelve el emoji asociado a un nombre de icono. Si ya es un emoji, lo respeta."""
    if not name:
        return default
    name = str(name).strip()
    # Si el valor guardado ya es un emoji (no ascii), úsalo tal cual.
    if name and not name.replace("-", "").replace("_", "").isascii():
        return name
    return ICON_EMOJI.get(name.lower(), default)


# =========================
# Spanish helpers
# =========================
MONTH_NAMES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]
MONTH_ABBR_ES = [
    "", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
    "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"
]
DAY_NAMES_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DAY_ABBR_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def month_name_es(m: int, short: bool = False) -> str:
    if short:
        return MONTH_ABBR_ES[m] if 1 <= m <= 12 else ""
    return MONTH_NAMES_ES[m] if 1 <= m <= 12 else ""


def day_name_es(d: date, short: bool = False) -> str:
    idx = d.weekday()
    return DAY_ABBR_ES[idx] if short else DAY_NAMES_ES[idx]


def safe_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_str(value, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()
