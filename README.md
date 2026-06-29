# 💰 Motor Financiero Personal

Aplicación web completa para gestionar tus finanzas personales, pensada para correr **24/7 en una Raspberry Pi** dentro de tu red local. Moderna, responsive, con **modo claro/oscuro**, **emojis** por todos lados y **100% offline** (no depende de ningún CDN).

**App en español · locale chileno (CLP, dd/mm/yyyy).**

---

## ⚠️ Seguridad — léelo primero

**Esta app NO tiene login por diseño.** Es de uso personal y asume que solo tú accedes a tu red local.

👉 **No la expongas directamente a internet.** Para acceder desde fuera de casa usa **Tailscale** (recomendado) o una VPN. La API REST sí usa un token (`X-API-Token`) para integraciones externas.

---

## ✨ Características

- 📊 **Dashboard** con KPIs, **“disponible para gastar este mes”**, gráfico de gastos y evolución de 6 meses; el **cupo disponible** se filtra por tarjeta (muestra disponible **y utilizado**, o la suma de todas) y hay una tarjeta de **deuda total** (tarjetas + créditos) con **tendencia de endeudamiento** (histórico real + proyección de cómo debería ir bajando)
- 🧮 **Plan & escenarios** — ingresa tu sueldo y mira cuánto puedes gastar; **simulador** de compras en cuotas que proyecta los próximos 12 meses con **veredicto por colchón**: ✅ alcanza (≥ $300.000), ⚠️ muy ajustado (entre $0 y $300.000) o ⛔ no alcanza (< $0)
- 🏦 **Bancos, cuentas y tarjetas** — 11 bancos chilenos **precargados** con sus colores; ahora puedes **subir el logo** de cada banco y se ve en tarjetas y créditos
- 💳 **Tarjetas de crédito** con cupos, días de pago, facturación y cuotas
- 📉 **Créditos** (consumo, avances, súper avances, compras en cuotas) con calendario de cuotas y **página “Pagar mi crédito”** que descuenta de tu cuenta
- 💸 **Gastos e ingresos** con categorías, adjuntos, filtros y exportación CSV
- 🤝 **Gastos compartidos** — al crear un gasto puedes repartirlo entre personas (genera **cuentas por cobrar**) o mandarlo a **Cuentas del Hogar**; al marcar que te pagaron, el monto se **suma a tu cuenta**
- 👥 **Personas y deudas** entre amigos/familia, con abonos parciales
- 🏠 **Cuentas del hogar** con **filtro por mes/año**, **con logo** y **cuentas fijas mensuales** (Agua, Luz, Tricot, TAG…): al marcarlas pagadas se **crea automáticamente la del mes siguiente** conservando el historial. Resumen por mes (facturado / por cobrar / abonado / neto), **abonos por mes** (pagos parciales de a poco), división entre participantes y **compras en cuotas**
- 🔁 **Pagos recurrentes** con **logo del proveedor** y opción “me lo devuelven” (cuentas de terceros que pagas tú)
- 🎯 **Presupuestos** por categoría/cuenta/persona/total
- 💯 **Montos con autoformato** — escribes `1234567` y se muestra `1.234.567` al instante
- 📅 **Calendario** financiero unificado · 📈 **Flujo de caja proyectado** que ahora **proyecta también tu ingreso esperado** (sueldo el día de pago, configurable) y se ajusta con los ingresos reales del mes
- 🔔 **Alertas** automáticas · 🔌 **API REST** con token (Telegram, Atajos iOS, Home Assistant)
- 🌗 **Modo claro / oscuro / automático** · 📱 **Responsive** (iPhone y desktop)
- 💾 **Backups** manuales y automatizables
- 🚫 **Sin CDNs** — estilos y librerías incluidos: funciona aunque la Pi esté sin internet

---

## 🚀 Instalación rápida (Raspberry Pi / Linux)

> Guía detallada paso a paso en **[INSTALL_RPI.md](INSTALL_RPI.md)**.

```bash
# 1. Clonar tu repositorio
git clone https://github.com/<tu-usuario>/<tu-repo>.git motor-financiero
cd motor-financiero

# 2. Entorno virtual + dependencias
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. (Opcional) variables de entorno
cp .env.example .env       # edita API_TOKEN si vas a usar la API

# 4. Ejecutar
python app.py
# → abre http://<IP_DE_LA_PI>:5000
```

La base de datos (`database/finance.db`) se crea sola en el primer arranque, con los **bancos chilenos y las categorías ya cargados**.

Para dejarlo corriendo siempre (systemd) y backups automáticos, sigue [INSTALL_RPI.md](INSTALL_RPI.md).

---

## 🔒 Tus datos privados (montos) — no van al repo

Para que **tus montos reales no queden en GitHub**, los datos personales viven fuera del repositorio:

- `database/finance.db` → **gitignored** (tu base de datos con todo).
- `database/seed_personal.py` → **gitignored**. Es una semilla opcional con tus créditos, recurrentes, tarjeta, etc. Si el archivo existe, la app lo carga **una sola vez** al arrancar (usa el flag `settings.personal_seeded`).
- `database/seed_personal.example.py` → **sí** se versiona, pero solo con datos de ejemplo. Es la plantilla.

**Para cargar tus datos en la Raspberry Pi:**

```bash
# opción A: copia tu archivo privado (el que te pasé / el de tu PC) a:
#   database/seed_personal.py
# opción B: parte de la plantilla y edítala
cp database/seed_personal.example.py database/seed_personal.py
nano database/seed_personal.py   # edita tus créditos, recurrentes, ingreso, etc.
python app.py                    # se cargan en el primer arranque
```

> ¿Quieres recargar la semilla? Borra `database/finance.db` (o pon `personal_seeded = 0` en Ajustes/BD) y reinicia.

---

## 🎨 Diseño self-contained (sin CDN)

Para que la app funcione **sin depender de internet**, los estilos y librerías están incluidos en el repo:

- **CSS:** Tailwind **precompilado** a un único archivo estático → `static/css/app.css`
- **JS:** Alpine.js, Chart.js y Lucide **vendorizados** → `static/js/vendor/`

No necesitas Node ni npm para *usar* la app. Solo lo necesitas si quieres **cambiar el diseño** y recompilar el CSS:

```bash
npm install            # instala tailwindcss (devDependency)
npm run build:css      # genera static/css/app.css desde static/css/input.css
# o en modo watch mientras editas plantillas:
npm run watch:css
```

> El archivo fuente del diseño es `static/css/input.css` (+ `tailwind.config.js`).
> Los emojis de categorías se mapean en `modules/helpers.py` (`ICON_EMOJI`).

---

## 🗂️ Estructura del proyecto

```
motor-financiero/
├── app.py                 # Flask factory + blueprints
├── config.py              # Configuración (lee .env, con defaults)
├── requirements.txt       # Dependencias Python (Flask)
├── package.json           # Solo para recompilar el CSS (opcional)
├── tailwind.config.js     # Config de Tailwind
├── finance-app.service    # Unit file systemd
├── backup.sh              # Script de backup
├── .env.example
├── database/
│   ├── schema.sql         # Esquema completo (22 tablas)
│   ├── db.py              # Conexión SQLite
│   └── seed.py            # Bancos chilenos + categorías
├── modules/               # Un blueprint por módulo (dashboard, banks, cards…)
│   └── helpers.py         # Formato CLP/fechas + mapa de emojis
├── templates/             # Jinja2 (base, partials, páginas)
├── static/
│   ├── css/
│   │   ├── app.css        # ← CSS compilado que usa la app
│   │   └── input.css      # ← fuente del diseño (Tailwind)
│   └── js/
│       ├── app.js / charts.js / forms.js / theme.js
│       └── vendor/        # alpine, chart.js, lucide (offline)
├── uploads/               # Adjuntos (boletas)
└── backups/               # Snapshots de la BD
```

---

## 🛠️ Stack técnico

- **Backend:** Python 3.11+ · Flask 3
- **DB:** SQLite (WAL + foreign keys)
- **Frontend:** Jinja2 + Tailwind (precompilado) + Alpine.js + Chart.js + Lucide — **todo local, sin CDN**
- **Locale:** es_CL · CLP · dd/mm/yyyy

---

## 🔌 API REST

Todos los endpoints (excepto `/api/health`) requieren token:

```bash
curl -H "X-API-Token: tu_token" http://<IP>:5000/api/dashboard
# o:  http://<IP>:5000/api/dashboard?token=tu_token
```

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/health` | Estado del servicio (sin token) |
| GET | `/api/dashboard` | KPIs principales |
| GET/POST | `/api/gastos` | Listar / crear transacciones |
| GET/PUT/DELETE | `/api/gastos/<id>` | Ver / actualizar / eliminar |
| GET | `/api/personas` | Listar personas |
| GET | `/api/deudas-personas` | Deudas activas |
| POST | `/api/deudas-personas/<id>/abono` | Registrar abono |
| GET | `/api/cuentas` · `/api/tarjetas` | Cuentas / tarjetas |
| GET | `/api/pagos-recurrentes` | Pagos recurrentes |
| GET | `/api/presupuestos` | Presupuestos (`?year=&month=`) |
| GET | `/api/calendario` · `/api/alertas` | Eventos / alertas |

```bash
# Ejemplo: crear gasto desde un Atajo de iOS o Telegram
curl -X POST http://<IP>:5000/api/gastos \
  -H "X-API-Token: tu_token" -H "Content-Type: application/json" \
  -d '{"amount":5000,"description":"Almuerzo","category_id":1,"type":"expense"}'
```

El token se genera solo en el primer arranque. Puedes fijarlo tú en `.env` (`API_TOKEN=`).

---

## 💾 Backups

```bash
# Manual desde la UI:           http://<IP>:5000/backup/
# Automático con cron (3am):    0 3 * * * /ruta/al/proyecto/backup.sh
# Restaurar:                    cp backups/finance_YYYYMMDD_HHMMSS.db database/finance.db
```

---

## 🧪 Variables de entorno (`.env`, opcional)

```
SECRET_KEY=...        # genera con: python -c "import secrets; print(secrets.token_urlsafe(32))"
API_TOKEN=...         # token para la API
HOST=0.0.0.0
PORT=5000
DEBUG=False
DATABASE_PATH=database/finance.db
```

Todas tienen valores por defecto razonables: la app arranca sin `.env`.

---

## 🤝 Integraciones (preparado para)

- **Telegram bot / Atajos de iOS / Home Assistant** → vía `POST /api/gastos`
- **Importación de cartolas** y **"facturas detectadas"** → el campo `origin` de cada transacción identifica la fuente (web/api/telegram/iphone/importado…)

---

Hecho con ❤️ para tener mis finanzas claras. Uso personal.
