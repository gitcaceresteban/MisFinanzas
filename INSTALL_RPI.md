# 🍓 Instalación en Raspberry Pi

Guía paso a paso para instalar el Motor Financiero Personal en una Raspberry Pi 5 (también funciona en RPi 4 o cualquier Linux).

---

## 📋 Requisitos

- Raspberry Pi con Raspbian/Raspberry Pi OS (64-bit recomendado)
- Python 3.11 o superior
- ~100MB de espacio en disco
- Acceso SSH a la RPi (o teclado/monitor)

---

## 1️⃣ Preparar el sistema

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git
```

Verifica la versión de Python:
```bash
python3 --version
# debe ser >= 3.11
```

---

## 2️⃣ Copiar los archivos

### Opción A: con git (recomendado)

Si tienes el repo en GitHub:
```bash
cd /home/pi
git clone https://github.com/tu-usuario/motor-financiero.git
cd motor-financiero
```

### Opción B: con scp desde tu Mac

Desde tu Mac (estando en la carpeta `motor-financiero` extraída):
```bash
scp -r motor-financiero pi@<IP_DE_LA_PI>:/home/pi/
```

### Opción C: con USB
Copia la carpeta a un pendrive y luego:
```bash
cp -r /media/pi/USB/motor-financiero /home/pi/
```

---

## 3️⃣ Crear entorno virtual

```bash
cd /home/pi/motor-financiero

# Crear venv
python3 -m venv venv

# Activar
source venv/bin/activate

# Instalar dependencias
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 4️⃣ Configurar variables de entorno

```bash
cp .env.example .env
nano .env
```

**Importante:** cambia estos valores:

```env
SECRET_KEY=                # genera con: python -c "import secrets; print(secrets.token_urlsafe(32))"
API_TOKEN=                 # otro token random distinto para la API
```

Genera tokens random con:
```bash
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(32))"
python3 -c "import secrets; print('API_TOKEN=' + secrets.token_urlsafe(32))"
```

Luego pega los valores en `.env`.

---

## 5️⃣ Primera ejecución (modo manual)

```bash
# Asegúrate de tener el venv activo
source venv/bin/activate

python app.py
```

Deberías ver:
```
* Running on http://0.0.0.0:5000
* Press CTRL+C to quit
```

Desde tu Mac/celular abre:
```
http://<IP_DE_LA_PI>:5000
```

Si todo se ve bien (dashboard, bancos cargados, etc), detén con `Ctrl+C` y continúa con systemd.

---

## 6️⃣ Configurar como servicio systemd (auto-start)

El servicio inicia automáticamente al arrancar la RPi y se reinicia si falla.

```bash
# Editar el path correcto en el unit file (si tu usuario no es 'pi')
nano finance-app.service
# Verifica que User=pi y WorkingDirectory=/home/pi/motor-financiero coincidan con tu sistema

# Copiar a systemd
sudo cp finance-app.service /etc/systemd/system/

# Recargar systemd
sudo systemctl daemon-reload

# Habilitar al boot
sudo systemctl enable finance-app

# Iniciar ahora
sudo systemctl start finance-app

# Verificar estado
sudo systemctl status finance-app
```

Si todo va bien deberías ver `Active: active (running)` en verde.

### Logs en tiempo real

```bash
sudo journalctl -u finance-app -f
```

### Reiniciar

```bash
sudo systemctl restart finance-app
```

### Detener

```bash
sudo systemctl stop finance-app
```

---

## 7️⃣ Configurar backups automáticos

```bash
# Dar permisos de ejecución
chmod +x /home/pi/motor-financiero/backup.sh

# Probar manualmente
/home/pi/motor-financiero/backup.sh

# Programar diariamente a las 3am
crontab -e
```

Agregar al final:
```
0 3 * * * /home/pi/motor-financiero/backup.sh >> /home/pi/motor-financiero/backups/backup.log 2>&1
```

Los backups se guardan en `backups/` con timestamp. Se mantienen los últimos 30 días automáticamente (configurable en `backup.sh`).

---

## 8️⃣ Acceso remoto con Tailscale (recomendado)

Si quieres acceder a tu Motor Financiero desde fuera de casa de forma segura:

```bash
# Si no tienes Tailscale instalado
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Luego en cualquier dispositivo con Tailscale instalado puedes acceder a:
```
http://<IP_TAILSCALE_DE_LA_PI>:5000
```

**⚠️ Nunca expongas la app directamente a internet sin VPN.** No tiene login por diseño (es de uso personal).

---

## 9️⃣ Acceso desde tu celular

Para usar la app en el celular como si fuera nativa:

1. Abre en el navegador Safari/Chrome: `http://<IP>:5000`
2. Comparte → "Añadir a la pantalla de inicio"
3. Tendrás un ícono en la home como si fuera app nativa

La app es responsive y funciona perfecto en móvil.

---

## 🔟 Verificación final

Lista de chequeo:

- [ ] Dashboard carga en `http://<IP>:5000`
- [ ] Bancos chilenos están precargados en `/bancos/`
- [ ] Puedes crear una cuenta de prueba en `/cuentas/nueva`
- [ ] El servicio systemd está `active (running)`
- [ ] El backup manual funciona en `/backup/`
- [ ] El API responde: `curl http://<IP>:5000/api/health` devuelve `{"status":"ok",...}`
- [ ] Backup script funciona: `./backup.sh`
- [ ] (Opcional) Acceso vía Tailscale funciona

---

## 🐛 Troubleshooting

### "Address already in use" en puerto 5000
Algo más está usando el puerto. Verifica:
```bash
sudo lsof -i :5000
# O cambia el puerto en .env: PORT=8080
```

### El servicio no arranca después de reboot
```bash
sudo systemctl status finance-app
sudo journalctl -u finance-app -n 50
```
Suele ser problema de permisos. Verifica que el usuario configurado en el `.service` exista y tenga acceso a la carpeta.

### Error de permisos en /home/pi/motor-financiero
```bash
sudo chown -R pi:pi /home/pi/motor-financiero
chmod -R 755 /home/pi/motor-financiero
```

### La BD no se crea en el primer arranque
```bash
cd /home/pi/motor-financiero
source venv/bin/activate
python -c "
from app import create_app
from database import init_db
from database.seed import seed_initial_data
app = create_app()
with app.app_context():
    init_db(app)
    seed_initial_data(app)
print('BD lista')
"
```

### Quiero resetear todo
```bash
sudo systemctl stop finance-app
cd /home/pi/motor-financiero
mv database/finance.db database/finance.db.OLD
sudo systemctl start finance-app
# Se creará una nueva BD vacía con seed
```

---

## 🎯 Próximos pasos

Una vez todo funcionando:

1. Agrega tus bancos y cuentas reales
2. Registra tus tarjetas de crédito con cupos y fechas de pago
3. Crea categorías personalizadas en `/ajustes/`
4. Importa tus créditos vigentes
5. Configura presupuestos mensuales
6. (Avanzado) Crea un bot de Telegram que use el API

¡Listo para usar! 💰
