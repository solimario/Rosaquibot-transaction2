# Sincronización de Históricos con SharePoint (Microsoft Graph API)

Guía para subir los CSV del histórico a SharePoint y eliminar los archivos locales, liberando espacio en el servidor. Usa **Microsoft Graph API** con una App Registration en Azure AD — no requiere rclone ni navegador en el servidor.

---

## Tabla de contenido

1. [Arquitectura del flujo](#1-arquitectura-del-flujo)
2. [Crear App Registration en Azure AD](#2-crear-app-registration-en-azure-ad)
3. [Obtener el Drive ID de SharePoint](#3-obtener-el-drive-id-de-sharepoint)
4. [Configurar cfg/.env](#4-configurar-cfgenv)
5. [Uso del script sync_onedrive.sh](#5-uso-del-script-sync_onedrivesh)
6. [Integración con el job principal](#6-integración-con-el-job-principal)
7. [Visualización en Excel Online](#7-visualización-en-excel-online)
8. [Migración a otro servidor](#8-migración-a-otro-servidor)
9. [Verificación y troubleshooting](#9-verificación-y-troubleshooting)

---

## 1. Arquitectura del flujo

```
transf_int_job.sh
  ├─ download_rep_xls.py     → Descarga XLS de Claro Pretups
  ├─ generate_csv.py         → Convierte XLS → CSV
  ├─ MySQL LOAD DATA         → Carga a BD
  ├─ send_mail.py            → Envía correo con adjunto
  ├─ cp → Data/historico/    → Guarda CSV local
  │
  └─ sync_onedrive.sh  (si ONEDRIVE_SYNC=true)
       ├─ GET token  → login.microsoftonline.com (client_credentials)
       ├─ PUT file   → graph.microsoft.com/v1.0/drives/{SP_DRIVE_ID}/root:/{ruta}:/content
       └─ rm local   → Libera espacio en servidor
```

**Resultado:** El CSV queda en SharePoint, accesible desde cualquier navegador con Excel Online.

---

## 2. Crear App Registration en Azure AD

Este proceso se hace **una sola vez**. No requiere navegador en el servidor.

1. Ir a [portal.azure.com](https://portal.azure.com) → **Azure Active Directory** → **Registros de aplicaciones** → **Nueva registración**
2. Nombre: `Rosaquibot-SharePoint` (o cualquier nombre descriptivo)
3. Tipo de cuenta: **Solo cuentas de este directorio organizacional**
4. URI de redirección: dejar vacío → **Registrar**

### Agregar permisos de API

En la app recién creada → **Permisos de API** → **Agregar un permiso** → **Microsoft Graph** → **Permisos de aplicación**:

- `Files.ReadWrite.All` — para subir archivos al Drive

Luego → **Conceder consentimiento de administrador** (requiere rol de Administrador Global o de aplicaciones).

### Crear Client Secret

**Certificados y secretos** → **Nuevo secreto de cliente**:
- Descripción: `rosaquibot-server`
- Expiración: 24 meses (o la que corresponda)
- **Copiar el valor inmediatamente** — no se vuelve a mostrar

### Datos a guardar

| Dato | Dónde encontrarlo |
|---|---|
| `SP_TENANT_ID` | Azure AD → Información general → ID de directorio (inquilino) |
| `SP_CLIENT_ID` | Registro de app → Información general → Id. de aplicación (cliente) |
| `SP_CLIENT_SECRET` | El valor del secreto recién creado |

---

## 3. Obtener el Drive ID de SharePoint

El `SP_DRIVE_ID` identifica el Drive específico dentro de SharePoint donde se guardarán los archivos.

### Opción A — via Microsoft Graph Explorer

1. Ir a [developer.microsoft.com/graph/graph-explorer](https://developer.microsoft.com/en-us/graph/graph-explorer)
2. Iniciar sesión con la cuenta M365 corporativa
3. Ejecutar: `GET https://graph.microsoft.com/v1.0/sites/{hostname}:/sites/{sitename}:/drives`
4. Buscar el `id` del drive deseado (ej. `b!xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`)

### Opción B — via curl desde el servidor (con token ya configurado)

```bash
# Obtener token primero
TOKEN=$(curl -s -X POST \
  "https://login.microsoftonline.com/${SP_TENANT_ID}/oauth2/v2.0/token" \
  -d "client_id=${SP_CLIENT_ID}" \
  -d "client_secret=${SP_CLIENT_SECRET}" \
  -d "scope=https://graph.microsoft.com/.default" \
  -d "grant_type=client_credentials" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Listar drives del sitio
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://graph.microsoft.com/v1.0/sites/{hostname}:/sites/{sitename}:/drives" \
  | python3 -m json.tool | grep '"id"'
```

---

## 4. Configurar cfg/.env

Agregar al final de `cfg/.env`:

```bash
# ============ SharePoint sync ============
ONEDRIVE_SYNC=true
SP_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
SP_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
SP_CLIENT_SECRET=tu_client_secret_aqui
SP_DRIVE_ID=b!xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SP_REMOTE_PATH=Rosaquibot/transferencias-internas   # opcional, es el default
```

---

## 5. Uso del script sync_onedrive.sh

```bash
# Subir TODO el histórico existente (primera vez) y borrar locales
bash script/sync_onedrive.sh --full

# Subir un archivo específico y borrarlo
bash script/sync_onedrive.sh --archivo Data/historico/transferencia_interna_20260428.csv

# Ver ayuda
bash script/sync_onedrive.sh --help
```

En modo integrado (llamado desde `transf_int_job.sh`), el script recibe el archivo via la variable de entorno `ARCHIVO_ONEDRIVE`.

---

## 6. Integración con el job principal

El `transf_int_job.sh` llama automáticamente a `sync_onedrive.sh` al final si `ONEDRIVE_SYNC=true` está en `cfg/.env`. No hay que modificar el cron — el sync ocurre dentro del job.

Si el sync falla, el job **no falla**: el archivo local se conserva y se registra un warning en el log.

---

## 7. Visualización en Excel Online

1. Ir a `portal.office.com` → **SharePoint** → navegar al sitio y carpeta configurada
2. Ir a `Rosaquibot/transferencias-internas/historico/`
3. Hacer clic en cualquier CSV → se abre en **Excel Online**

### Consolidar todos los archivos (Power Query)

1. Crear un nuevo archivo Excel en SharePoint
2. `Datos` → `Obtener datos` → `Desde una carpeta de SharePoint`
3. Seleccionar la carpeta `Rosaquibot/transferencias-internas/historico`
4. Excel combinará todos los CSV en una tabla que se actualiza automáticamente al abrir

---

## 8. Migración a otro servidor

A diferencia de rclone, **no hay ningún archivo de configuración en el servidor** que preservar. Solo hay que copiar las credenciales:

### Checklist de migración

```
[ ] Copiar Rosaquibot-transaction2/ completo (sin Data/ si ya está en SharePoint)
[ ] Copiar cfg/.env con todas las credenciales (incluyendo SP_*)
[ ] Verificar Python 3.11+: python3.11 --version
[ ] Verificar MySQL client: mysql --version
[ ] Verificar curl: curl --version
[ ] Instalar dependencias: pip install -r requirements.txt
[ ] Registrar el cron: crontab -e
[ ] Prueba de subida: bash script/sync_onedrive.sh --archivo <cualquier_csv>
[ ] Ejecución completa: bash script/transf_int_job.sh
```

---

## 9. Verificación y troubleshooting

### Verificar que el token funciona

```bash
source cfg/.env
curl -s -X POST \
  "https://login.microsoftonline.com/${SP_TENANT_ID}/oauth2/v2.0/token" \
  -d "client_id=${SP_CLIENT_ID}" \
  -d "client_secret=${SP_CLIENT_SECRET}" \
  -d "scope=https://graph.microsoft.com/.default" \
  -d "grant_type=client_credentials" \
  | python3 -m json.tool | grep -E '"access_token"|"error"'
```

### Probar subida manual de un archivo

```bash
source cfg/.env
bash script/sync_onedrive.sh --archivo Data/historico/transferencia_interna_20260428.csv
```

### Errores comunes

| Error | Causa | Solución |
|---|---|---|
| `Variable SP_TENANT_ID no definida` | Faltan variables en `.env` | Revisar sección 4 |
| `No se pudo obtener token` | `SP_CLIENT_ID` o `SP_CLIENT_SECRET` incorrectos | Verificar en portal.azure.com |
| `HTTP 403` | App sin permisos `Files.ReadWrite.All` o sin consentimiento de admin | Revisar sección 2 |
| `HTTP 404` | `SP_DRIVE_ID` incorrecto o ruta no existe | Verificar Drive ID con Graph Explorer |
| `HTTP 401` | Client Secret vencido | Crear nuevo secreto en Azure AD |
