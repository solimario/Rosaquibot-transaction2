# rosaquibot-transf-interna

Robot de descarga, carga y notificación del reporte de **Transferencias Internas** del portal Claro Perú — Pretups.

Descarga el Excel de movimientos por rango de fechas, lo convierte a CSV, lo carga a MySQL y envía un correo con el resumen adjunto a los destinatarios configurados.

---

## Flujo del proceso

```
script/transf_int_job.sh
  ├─ download_rep_xls.py   → Login HTTP + descarga XLS de transferencias por fecha
  ├─ generate_csv.py       → Convierte XLS → CSV depurado
  ├─ MySQL LOAD DATA       → Carga a tabla `transferencia_interna`
  ├─ send_mail.py          → Envía resumen por correo (Gmail SMTP con adjunto CSV)
  └─ sync_onedrive.sh      → (opcional) Sube CSV a SharePoint vía Microsoft Graph API y borra local
```

Si no hay movimientos en el período, se envía un correo de aviso y el proceso termina sin error.

---

## Requisitos

- Python 3.11+
- MySQL client (`mysql` en PATH, con `--local-infile`)
- Cuenta Gmail con **Contraseña de aplicación** habilitada

```bash
pip install -r requirements.txt
```

---

## Configuración

```bash
cp cfg/.env.example cfg/.env
# Completar cfg/.env con credenciales reales
```

### Variables de entorno

| Variable | Descripción | Requerida |
|---|---|---|
| `DB_HOST` | Host del servidor MySQL | Sí |
| `DB_USER` | Usuario MySQL | Sí |
| `DB_PASS` | Contraseña MySQL | Sí |
| `DB_NAME` | Nombre de la base de datos | Sí |
| `CLARO_USER` | Usuario del portal Claro (Pretups) | Sí |
| `CLARO_PASS` | Contraseña del portal Claro | Sí |
| `MAIL_REMITENTE` | Correo Gmail desde el que se envía | Sí |
| `SMTP_APP_PASSWORD` | Contraseña de aplicación Gmail (16 caracteres) | Sí |
| `ONEDRIVE_SYNC` | `true` para activar subida a SharePoint | No (default: false) |
| `SP_TENANT_ID` | Tenant ID de Azure AD | Solo si `ONEDRIVE_SYNC=true` |
| `SP_CLIENT_ID` | Client ID de la App Registration en Azure AD | Solo si `ONEDRIVE_SYNC=true` |
| `SP_CLIENT_SECRET` | Client Secret de la App Registration | Solo si `ONEDRIVE_SYNC=true` |
| `SP_DRIVE_ID` | Drive ID del sitio SharePoint destino | Solo si `ONEDRIVE_SYNC=true` |
| `SP_REMOTE_PATH` | Ruta remota en SharePoint (default: `Rosaquibot/transferencias-internas`) | No |

### Configurar contraseña de aplicación Gmail

1. Ir a [myaccount.google.com](https://myaccount.google.com) → Seguridad
2. Habilitar verificación en dos pasos
3. Generar una **Contraseña de aplicación** (Mail / Linux)
4. Copiar los 16 caracteres al campo `SMTP_APP_PASSWORD`

---

## Ejecución

### Manual (período: ayer)
```bash
source cfg/.env
bash script/transf_int_job.sh
```

### Con fecha específica
```bash
source cfg/.env
FECHA_INICIO=28/04/26 FECHA_FIN=28/04/26 bash script/transf_int_job.sh
```

### Con rango de fechas
```bash
source cfg/.env
FECHA_INICIO=01/04/26 FECHA_FIN=28/04/26 bash script/transf_int_job.sh
```

### Cron (ejemplo diario a las 8 AM, hora Perú)
```cron
0 8 * * * source /home/drosadio/Rosaquibot-transaction2/cfg/.env && bash /home/drosadio/Rosaquibot-transaction2/script/transf_int_job.sh >> /var/log/transf_interna.log 2>&1
```

---

## Estructura del proyecto

```
Rosaquibot-transaction2/
├── cfg/
│   ├── .env                      # Credenciales reales (no commitear)
│   └── .env.example              # Plantilla de variables
├── Data/
│   ├── historico/                # CSVs de transferencias por fecha (generados)
│   └── historico_rym/            # Histórico RYM
├── docs/
│   └── onedrive-sync.md          # Guía de configuración SharePoint (Microsoft Graph API)
├── img/
│   └── logo_rosaqui.jpg          # Logo para el correo HTML
├── script/
│   ├── transf_int_job.sh         # Orquestador principal
│   ├── sync_onedrive.sh          # Sube CSVs a SharePoint vía Graph API y elimina locales
│   ├── download_rep_xls.py       # Descarga XLS via HTTP
│   ├── generate_csv.py           # Convierte XLS → CSV
│   └── send_mail.py              # Envío de correo con adjunto
└── requirements.txt
```

---

## Integración Jenkins

Configurar el Job Jenkins con los parámetros:
- `FECHA_INICIO` (String, formato `DD/MM/YY`, opcional)
- `FECHA_FIN` (String, formato `DD/MM/YY`, opcional)

Si ambos parámetros están vacíos, el script procesa automáticamente el día anterior.

---

## Sincronización con SharePoint (M365)

Los CSV del histórico se suben automáticamente a SharePoint via **Microsoft Graph API** y se eliminan del servidor local para liberar espacio. No requiere rclone — solo credenciales de una App Registration en Azure AD.

### Activar

Agregar en `cfg/.env`:

```bash
ONEDRIVE_SYNC=true
SP_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
SP_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
SP_CLIENT_SECRET=tu_client_secret
SP_DRIVE_ID=b!xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SP_REMOTE_PATH=Rosaquibot/transferencias-internas   # opcional, es el default
```

### Subir el histórico existente por primera vez

```bash
# Sube todo Data/historico y Data/historico_rym, borra locales
bash script/sync_onedrive.sh --full
```

### Estructura en SharePoint

```
SharePoint Drive/
└── Rosaquibot/
    └── transferencias-internas/
        ├── historico/          ← transferencia_interna_YYYYMMDD.csv
        └── historico_rym/      ← mismo formato
```

Ver guía completa de configuración Azure AD y obtención del Drive ID: [`docs/onedrive-sync.md`](docs/onedrive-sync.md)

---

## Notas de seguridad

- `cfg/.env` y `Data/` están en `.gitignore`. **Nunca subir credenciales ni datos de transacciones reales al repositorio.**
- El script usa `flock` para evitar ejecuciones concurrentes.
- El `SP_CLIENT_SECRET` en `cfg/.env` contiene credenciales Azure AD — no commitear.
