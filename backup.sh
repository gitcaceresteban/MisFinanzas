#!/bin/bash
# ============================================
# Motor Financiero - Backup automatizado
# Uso: agregar a crontab para corrida diaria
#   0 3 * * * /home/pi/motor-financiero/backup.sh
# ============================================

set -e

# --- Configuración (ajusta APP_DIR a la ruta donde clonaste el repo) ---
APP_DIR="/home/pi/motor-financiero"
DB_FILE="${APP_DIR}/database/finance.db"
BACKUP_DIR="${APP_DIR}/backups"
KEEP_DAYS=30  # eliminar backups más antiguos que esto

# --- Crear directorio si no existe ---
mkdir -p "$BACKUP_DIR"

# --- Verificar que existe la BD ---
if [ ! -f "$DB_FILE" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Base de datos no encontrada en $DB_FILE"
    exit 1
fi

# --- Crear snapshot ---
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
TARGET="${BACKUP_DIR}/finance_${TIMESTAMP}.db"

# Usar el comando .backup de SQLite (más seguro que cp con BD en uso)
if command -v sqlite3 &> /dev/null; then
    sqlite3 "$DB_FILE" ".backup '$TARGET'"
else
    # Fallback a cp
    cp "$DB_FILE" "$TARGET"
fi

SIZE=$(du -h "$TARGET" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ Backup creado: finance_${TIMESTAMP}.db ($SIZE)"

# --- Limpieza de backups antiguos ---
DELETED=$(find "$BACKUP_DIR" -name "finance_*.db" -type f -mtime +$KEEP_DAYS | wc -l)
find "$BACKUP_DIR" -name "finance_*.db" -type f -mtime +$KEEP_DAYS -delete

if [ "$DELETED" -gt 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🗑️  Eliminados $DELETED backups con más de $KEEP_DAYS días"
fi

# --- Resumen ---
TOTAL_BACKUPS=$(ls -1 "$BACKUP_DIR"/finance_*.db 2>/dev/null | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 📊 Total: $TOTAL_BACKUPS backups, $TOTAL_SIZE"

exit 0
