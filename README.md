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
  └─ send_mail.py          → Envía resumen por correo (Gmail SMTP con adjunto CSV)
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
├── img/
│   └── logo_rosaqui.jpg          # Logo para el correo HTML
├── script/
│   ├── transf_int_job.sh         # Orquestador principal
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

## Notas de seguridad

- `cfg/.env` y `Data/` están en `.gitignore`. **Nunca subir credenciales ni datos de transacciones reales al repositorio.**
- El script usa `flock` para evitar ejecuciones concurrentes.
