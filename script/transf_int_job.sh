#!/bin/bash
set -euo pipefail
trap 'echo "$(TZ=UTC+5 date) - ❌ Error inesperado en la línea $LINENO. Abortando..."; exit 1' ERR

echo "$(TZ=UTC+5 date) - 🟢 Inicio del proceso de transferencia interna (Grupo-Robot-Transf_int)"

# ============================ BLOQUEO DE EJECUCIÓN ============================
exec 9>/tmp/transf_int.lock
flock -n 9 || { echo "$(TZ=UTC+5 date) - ❌ Ya hay una ejecución en curso"; exit 1; }

# ============================ PARÁMETROS DE FECHA (desde Jenkins) ============================
# FECHA_INICIO y FECHA_FIN en formato DD/MM/YY. Retrocompatible con FECHA.
# Reglas: 1) ambos vacíos→ayer, 2) solo inicio→fin=inicio, 3) solo fin→inicio=fin, 4) ambos→rango

_validate_fecha() {
    local d="$1"
    if ! [[ "$d" =~ ^[0-9]{1,2}/[0-9]{1,2}/[0-9]{2}$ ]]; then
        echo "❌ Fecha inválida: '$d'. Formato esperado: DD/MM/YY"
        exit 1
    fi
}

_ymd_de_fecha() {
    local d="$1"
    IFS=/ read -r DD MM YY <<< "$d"
    [ ${#DD} -eq 1 ] && DD="0$DD"
    [ ${#MM} -eq 1 ] && MM="0$MM"
    [ ${#YY} -eq 2 ] && YY="20$YY"
    echo "${YY}${MM}${DD}"
}

_human_de_fecha() {
    local d="$1"
    IFS=/ read -r DD MM YY <<< "$d"
    [ ${#DD} -eq 1 ] && DD="0$DD"
    [ ${#MM} -eq 1 ] && MM="0$MM"
    [ ${#YY} -eq 2 ] && YY="20$YY"
    echo "${DD}/${MM}/${YY}"
}

# Retrocompat: FECHA antigua alimenta FECHA_INICIO si los nuevos no vienen
FECHA_INICIO="${FECHA_INICIO:-${FECHA:-}}"
FECHA_FIN="${FECHA_FIN:-${FECHA:-}}"

if [ -z "$FECHA_INICIO" ] && [ -z "$FECHA_FIN" ]; then
    FECHA_INI_FORM="$(date -d "yesterday" +%d/%m/%y)"
    FECHA_FIN_FORM="$(date -d "yesterday" +%d/%m/%y)"
elif [ -n "$FECHA_INICIO" ] && [ -z "$FECHA_FIN" ]; then
    _validate_fecha "$FECHA_INICIO"
    FECHA_INI_FORM="$FECHA_INICIO"
    FECHA_FIN_FORM="$FECHA_INICIO"
elif [ -z "$FECHA_INICIO" ] && [ -n "$FECHA_FIN" ]; then
    _validate_fecha "$FECHA_FIN"
    FECHA_INI_FORM="$FECHA_FIN"
    FECHA_FIN_FORM="$FECHA_FIN"
else
    _validate_fecha "$FECHA_INICIO"
    _validate_fecha "$FECHA_FIN"
    FECHA_INI_FORM="$FECHA_INICIO"
    FECHA_FIN_FORM="$FECHA_FIN"
fi

FECHA_INI_YMD="$(_ymd_de_fecha "$FECHA_INI_FORM")"
FECHA_FIN_YMD="$(_ymd_de_fecha "$FECHA_FIN_FORM")"

if [ "$FECHA_INI_YMD" = "$FECHA_FIN_YMD" ]; then
    FECHA_YMD="$FECHA_INI_YMD"
    FECHA_ASUNTO_HUM="$(_human_de_fecha "$FECHA_INI_FORM")"
else
    FECHA_YMD="${FECHA_INI_YMD}_${FECHA_FIN_YMD}"
    FECHA_ASUNTO_HUM="$(_human_de_fecha "$FECHA_INI_FORM") al $(_human_de_fecha "$FECHA_FIN_FORM")"
fi

# ============================ DEFINIR RUTAS ============================
BASE_DIR="/home/drosadio/Rosaquibot-transaction2"
ENV_FILE="$BASE_DIR/cfg/.env"
DESTINO="$BASE_DIR/Data"
OUTPUT_XLS="$DESTINO/test2_${FECHA_YMD}.xls"
OUTPUT_CSV="$DESTINO/test2_${FECHA_YMD}.csv"
SQL_LOAD_FILE="$OUTPUT_CSV"
HISTORICO="$DESTINO/historico"

# ============================ VALIDAR RUTAS/ARCHIVOS ============================
[ -d "$BASE_DIR" ] || { echo "❌ No existe BASE_DIR: $BASE_DIR"; exit 1; }
[ -f "$ENV_FILE" ] || { echo "❌ No se encontró el archivo .env"; exit 1; }
mkdir -p "$DESTINO" "$HISTORICO"

# ============================ CARGAR VARIABLES DE ENTORNO ============================
source "$ENV_FILE"

# ============================ VALIDACIÓN DE VARIABLES CLAVE ============================
for var in CLARO_USER CLARO_PASS DB_HOST DB_USER DB_PASS DB_NAME MAIL_REMITENTE SMTP_APP_PASSWORD; do
    [ -n "${!var:-}" ] || { echo "❌ Variable de entorno $var no está definida"; exit 1; }
done

# ============================ DESCARGA DEL XLS ============================
echo "$(TZ=UTC+5 date) - 🐍 Ejecutando script Python de descarga (${FECHA_INI_FORM} → ${FECHA_FIN_FORM})"
export OUTPUT_XLS
python3.11 "$BASE_DIR/script/download_rep_xls.py" --fecha-inicio "$FECHA_INI_FORM" --fecha-fin "$FECHA_FIN_FORM"

[ -f "$OUTPUT_XLS" ] || { echo "❌ ERROR: No se generó el archivo XLS: $OUTPUT_XLS"; exit 1; }

# ============================ GENERAR CSV DEPURADO ============================
echo "$(TZ=UTC+5 date) - 🔧 Generando CSV depurado"
_T0=$(date +%s)
export OUTPUT_XLS OUTPUT_CSV
python3.11 "$BASE_DIR/script/generate_csv.py"
echo "$(TZ=UTC+5 date) - ✅ CSV generado en $(( $(date +%s) - _T0 ))s"

[ -s "$OUTPUT_CSV" ] || { echo "❌ El archivo CSV no fue generado correctamente: $OUTPUT_CSV"; exit 1; }

# Verificar que haya filas de datos (no solo cabecera)
# Crystal Reports devuelve XLS vacío cuando no hay movimientos — eso es válido, no un error
_filas_datos=$(tail -n +2 "$OUTPUT_CSV" | grep -c . 2>/dev/null || echo 0)
if [ "$_filas_datos" -eq 0 ]; then
    echo "$(TZ=UTC+5 date) - ⚠️  Sin movimientos para el período ${FECHA_ASUNTO_HUM}."
    echo "$(TZ=UTC+5 date) - 📧 Enviando aviso de período sin actividad..."
    MAIL_SIN_DATOS=true \
    MAIL_DESTINATARIOS="diego.rosadio1096@gmail.com,gerencia@rosaqui.com,alonso.guicon@gmail.com,recarga.lm@rosaqui.com" \
    MAIL_ASUNTO="📭 [GRUPO ROSAQUI SAC] Sin movimientos – Transferencias Internas – ${FECHA_ASUNTO_HUM}" \
    MAIL_LOGO="$BASE_DIR/img/logo_rosaqui.jpg" \
    MAIL_JOB_NAME="${JOB_NAME:-Grupo-Robot-Transf_Int}" \
    MAIL_BUILD_TIME="$(TZ=UTC+5 date '+%d/%m/%Y %H:%M')" \
    MAIL_FECHA_PERIODO="${FECHA_ASUNTO_HUM}" \
    python3.11 "$BASE_DIR/script/send_mail.py" || true
    rm -f "$OUTPUT_XLS" "$OUTPUT_CSV"
    echo "$(TZ=UTC+5 date) - 🏁 Proceso finalizado correctamente (sin datos)."
    exit 0
fi
echo "$(TZ=UTC+5 date) - 📊 Filas a procesar: ${_filas_datos}"

# ============================ CARGA DEL CSV A MYSQL ============================
echo "$(TZ=UTC+5 date) - 📤 Cargando CSV a MySQL tabla transferencia_interna"
_T0=$(date +%s)
mysql -h"$DB_HOST" -u"$DB_USER" -p"$DB_PASS" "$DB_NAME" --local-infile=1 -e "
LOAD DATA LOCAL INFILE '$SQL_LOAD_FILE'
IGNORE INTO TABLE transferencia_interna
CHARACTER SET UTF8
FIELDS TERMINATED BY ','
LINES TERMINATED BY '\n'
IGNORE 1 ROWS
(origen_nombre, origen_numero, origen_categoria, destino_nombre, destino_numero, destino_categoria, tipo, producto, monto, fecha, hora);
"
echo "$(TZ=UTC+5 date) - ✅ Carga MySQL completada en $(( $(date +%s) - _T0 ))s"

# ============================ HISTÓRICO Y ENVÍO DE CORREO ============================
echo "$(TZ=UTC+5 date) - 🗂️ Guardando histórico y enviando correo"
_T0=$(date +%s)

ARCHIVO_DESTINO="$HISTORICO/transferencia_interna_${FECHA_YMD}.csv"
cp "$OUTPUT_CSV" "$ARCHIVO_DESTINO"

export MAIL_DESTINATARIOS="diego.rosadio1096@gmail.com,gerencia@rosaqui.com,alonso.guicon@gmail.com,recarga.lm@rosaqui.com"
export MAIL_ADJUNTO="$ARCHIVO_DESTINO"
export MAIL_ASUNTO="📑 [GRUPO ROSAQUI SAC] Resumen Diario – Transferencias Internas – ${FECHA_ASUNTO_HUM}"
export MAIL_LOGO="$BASE_DIR/img/logo_rosaqui.jpg"
export MAIL_JOB_NAME="${JOB_NAME:-Grupo-Robot-Transf_Int}"
export MAIL_BUILD_TIME="$(TZ=UTC+5 date '+%d/%m/%Y %H:%M')"

python3.11 "$BASE_DIR/script/send_mail.py"
echo "$(TZ=UTC+5 date) - ✅ Correo enviado en $(( $(date +%s) - _T0 ))s"

# ============================ SYNC ONEDRIVE (opcional) ============================
if [ "${ONEDRIVE_SYNC:-false}" = "true" ]; then
    echo "$(TZ=UTC+5 date) - ☁️  Sincronizando CSV con OneDrive"
    ARCHIVO_ONEDRIVE="$ARCHIVO_DESTINO" \
    bash "$BASE_DIR/script/sync_onedrive.sh" || echo "$(TZ=UTC+5 date) - ⚠️  OneDrive sync falló — archivo local conservado"
fi

# ============================ LIMPIEZA FINAL ============================
echo "$(TZ=UTC+5 date) - 🧹 Limpiando archivos temporales"
rm -f "$OUTPUT_XLS" "$OUTPUT_CSV"

# ============================ FINAL ============================
echo "$(TZ=UTC+5 date) - 🏁 Proceso finalizado correctamente."
