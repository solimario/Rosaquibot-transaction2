#!/bin/bash
# Sube los CSV del histórico a SharePoint usando Microsoft Graph API.
# No requiere rclone. Credenciales via App Registration en Azure AD.
set -euo pipefail

BASE_DIR="/home/drosadio/Rosaquibot-transaction2"
REMOTE_PATH="${SP_REMOTE_PATH:-Rosaquibot/transferencias-internas}"
HISTORICO="$BASE_DIR/Data/historico"
HISTORICO_RYM="$BASE_DIR/Data/historico_rym"

_uso() {
    echo "Uso: $0 [--full | --archivo <ruta_csv> | --help]"
    echo ""
    echo "  --full              Sube todo Data/historico y Data/historico_rym, borra locales"
    echo "  --archivo <ruta>    Sube un CSV específico y lo borra localmente"
    echo "  (sin args)          Modo integrado: llamado desde transf_int_job.sh con ARCHIVO_ONEDRIVE definido"
    exit 0
}

_log() { echo "$(TZ=UTC+5 date) - $*"; }

_verificar_credenciales() {
    for var in SP_TENANT_ID SP_CLIENT_ID SP_CLIENT_SECRET SP_DRIVE_ID; do
        if [ -z "${!var:-}" ]; then
            _log "❌ Variable $var no definida. Verificar .env"
            exit 1
        fi
    done
}

_get_token() {
    local token
    token=$(curl -s -X POST \
        "https://login.microsoftonline.com/${SP_TENANT_ID}/oauth2/v2.0/token" \
        -d "client_id=${SP_CLIENT_ID}" \
        -d "client_secret=${SP_CLIENT_SECRET}" \
        -d "scope=https://graph.microsoft.com/.default" \
        -d "grant_type=client_credentials" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['access_token'])" 2>/dev/null)

    if [ -z "$token" ]; then
        _log "❌ No se pudo obtener token. Verificar SP_TENANT_ID, SP_CLIENT_ID, SP_CLIENT_SECRET en .env"
        exit 1
    fi
    echo "$token"
}

_subir_archivo() {
    local archivo="$1"
    local carpeta_remota="$2"
    local token="$3"

    if [ ! -f "$archivo" ]; then
        _log "⚠️  Archivo no encontrado: $archivo"
        return 1
    fi

    local nombre
    nombre=$(basename "$archivo")
    local url="https://graph.microsoft.com/v1.0/drives/${SP_DRIVE_ID}/root:/${carpeta_remota}/${nombre}:/content"

    _log "☁️  Subiendo: $nombre → SharePoint/${carpeta_remota}/"
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" -X PUT \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: text/csv" \
        --data-binary "@${archivo}" \
        "$url")

    if [[ "$http_code" =~ ^2 ]]; then
        _log "✅ Subida exitosa: $nombre"
        rm -f "$archivo"
        _log "🗑️  Eliminado local: $archivo"
    else
        _log "❌ Error al subir: $nombre (HTTP $http_code) — archivo local conservado"
        return 1
    fi
}

_subir_carpeta_completa() {
    local local_dir="$1"
    local remote_dir="$2"
    local token="$3"

    if [ ! -d "$local_dir" ]; then
        _log "⚠️  Carpeta no encontrada: $local_dir — saltando"
        return 0
    fi

    local total
    total=$(find "$local_dir" -name "*.csv" | wc -l)

    if [ "$total" -eq 0 ]; then
        _log "ℹ️  Sin archivos CSV en $local_dir"
        return 0
    fi

    _log "📦 Subiendo $total archivos desde $local_dir → SharePoint/${remote_dir}/"
    local errores=0
    while IFS= read -r archivo; do
        _subir_archivo "$archivo" "$remote_dir" "$token" || ((errores++)) || true
    done < <(find "$local_dir" -name "*.csv")

    if [ "$errores" -eq 0 ]; then
        _log "✅ Subida completa de $local_dir"
    else
        _log "⚠️  $errores archivos fallaron — revisar log"
        return 1
    fi
}

# ======================== MAIN ========================

case "${1:-}" in
    --help|-h) _uso ;;

    --full)
        _verificar_credenciales
        _log "🔑 Obteniendo token de Microsoft..."
        TOKEN=$(_get_token)
        _log "✅ Token obtenido"
        _log "🚀 Modo --full: subiendo todo el histórico a SharePoint"
        _subir_carpeta_completa "$HISTORICO"     "${REMOTE_PATH}/historico"     "$TOKEN"
        _subir_carpeta_completa "$HISTORICO_RYM" "${REMOTE_PATH}/historico_rym" "$TOKEN"
        _log "🏁 Sincronización completa finalizada."
        ;;

    --archivo)
        [ -z "${2:-}" ] && { _log "❌ Falta la ruta del archivo. Uso: $0 --archivo <ruta>"; exit 1; }
        _verificar_credenciales
        _log "🔑 Obteniendo token de Microsoft..."
        TOKEN=$(_get_token)
        _log "✅ Token obtenido"
        if [[ "$2" == *historico_rym* ]]; then
            _subir_archivo "$2" "${REMOTE_PATH}/historico_rym" "$TOKEN"
        else
            _subir_archivo "$2" "${REMOTE_PATH}/historico" "$TOKEN"
        fi
        ;;

    "")
        if [ -z "${ARCHIVO_ONEDRIVE:-}" ]; then
            _log "❌ Variable ARCHIVO_ONEDRIVE no definida. Usar --archivo o --full."
            exit 1
        fi
        _verificar_credenciales
        _log "🔑 Obteniendo token de Microsoft..."
        TOKEN=$(_get_token)
        _log "✅ Token obtenido"
        if [[ "$ARCHIVO_ONEDRIVE" == *historico_rym* ]]; then
            _subir_archivo "$ARCHIVO_ONEDRIVE" "${REMOTE_PATH}/historico_rym" "$TOKEN"
        else
            _subir_archivo "$ARCHIVO_ONEDRIVE" "${REMOTE_PATH}/historico" "$TOKEN"
        fi
        ;;

    *) _uso ;;
esac
