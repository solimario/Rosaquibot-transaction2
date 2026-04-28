import smtplib
import socket
import os
import re
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage


class _SMTPv4(smtplib.SMTP):
    """Fuerza IPv4 — el servidor no tiene ruta IPv6 a smtp.gmail.com."""
    def _get_socket(self, host, port, timeout):
        af, _, _, _, addr = socket.getaddrinfo(
            host, port, socket.AF_INET, socket.SOCK_STREAM)[0]
        s = socket.socket(af, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(addr)
        return s


# ==================== VARIABLES ENTORNO ====================
smtp_server  = "smtp.gmail.com"
smtp_port    = 587
smtp_timeout = 30

sender_email        = os.environ.get("MAIL_REMITENTE", "")
app_password        = os.environ.get("SMTP_APP_PASSWORD", "")
receiver_emails_raw = os.environ.get("MAIL_DESTINATARIOS", "")
file_path           = os.environ.get("MAIL_ADJUNTO", "")
subject             = os.environ.get("MAIL_ASUNTO", "📎 Reporte")
logo_path           = os.environ.get("MAIL_LOGO", "")
job_name            = os.environ.get("MAIL_JOB_NAME", "")
build_time          = os.environ.get("MAIL_BUILD_TIME", "")

sin_datos = os.environ.get("MAIL_SIN_DATOS", "").strip().lower() in {"1", "true"}

if not sender_email or not app_password or not receiver_emails_raw:
    print("❌ Faltan variables requeridas.")
    exit(1)
if not sin_datos and not file_path:
    print("❌ Faltan variables requeridas.")
    exit(1)
if not sin_datos and not os.path.isfile(file_path):
    print(f"❌ Archivo adjunto no encontrado: {file_path}")
    exit(1)
if logo_path and not os.path.isfile(logo_path):
    print(f"⚠️ Logo no encontrado: {logo_path}. Se omitirá.")
    logo_path = ""

destinatarios = [c.strip() for c in receiver_emails_raw.split(",") if c.strip()]
if not destinatarios:
    print("❌ Lista de destinatarios vacía.")
    exit(1)

# ──────────────────────────────────────────────────────────────
# MODO SIN DATOS — aviso breve, sin adjunto, sin tablas
# ──────────────────────────────────────────────────────────────
if sin_datos:
    _fecha_aviso = os.environ.get("MAIL_FECHA_PERIODO", "el período indicado")
    _logo_tag = ('<img src="cid:logo_rosaqui" style="width:100%;max-width:600px;display:block;"/>'
                 if logo_path else "")
    _job_line = ""
    if job_name or build_time:
        parts = []
        if job_name:   parts.append(f"Job: <strong>{job_name}</strong>")
        if build_time: parts.append(f"Ejecutado: <strong>{build_time}</strong>")
        _job_line = (" · ".join(parts))

    _html_aviso = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#F4F6F8;font-family:Arial,Helvetica,sans-serif;">
  <div style="max-width:560px;margin:20px auto;background:#FFFFFF;border-radius:6px;
              box-shadow:0 2px 8px rgba(0,0,0,.12);overflow:hidden;">
    {_logo_tag}
    <div style="padding:24px 28px;">
      <h2 style="color:#1565C0;margin:0 0 2px">Grupo Rosaqui S.A.C.</h2>
      <p style="font-size:11px;color:#999;margin:0 0 20px">{_job_line}</p>
      <div style="background:#FFF8E1;border-left:5px solid #FF8F00;
                  padding:16px 20px;border-radius:0 6px 6px 0;">
        <p style="font-size:16px;font-weight:bold;color:#E65100;margin:0 0 8px">
          📭 Sin movimientos — {_fecha_aviso}
        </p>
        <p style="font-size:13px;color:#555;margin:0 0 6px">
          No se registraron transferencias internas para este período.
        </p>
        <p style="font-size:13px;color:#555;margin:0">
          El proceso finalizó correctamente. No hay datos que cargar ni reportar.
        </p>
      </div>
      <div style="border-top:1px solid #E0E0E0;margin:20px 0 10px;font-size:0">&nbsp;</div>
      <p style="font-size:11px;color:#bbb;margin:0">
        Grupo Rosaqui S.A.C. · Tecnología e Innovación ·
        Mensaje generado automáticamente, por favor no responder.
      </p>
    </div>
  </div>
</body>
</html>"""

    _msg = MIMEMultipart("related")
    _msg["Subject"] = subject
    _msg["From"]    = sender_email
    _msg["To"]      = ", ".join(destinatarios)
    _alt = MIMEMultipart("alternative")
    _msg.attach(_alt)
    _alt.attach(MIMEText(_html_aviso, "html"))
    if logo_path:
        with open(logo_path, "rb") as _img:
            _logo = MIMEImage(_img.read())
            _logo.add_header("Content-ID", "<logo_rosaqui>")
            _msg.attach(_logo)
    try:
        with _SMTPv4(smtp_server, smtp_port, timeout=smtp_timeout) as _srv:
            _srv.starttls()
            _srv.login(sender_email, app_password)
            _srv.sendmail(sender_email, destinatarios, _msg.as_string())
        print(f"✅ Aviso 'sin datos' enviado a: {', '.join(destinatarios)}")
    except Exception as _e:
        print(f"❌ Error al enviar aviso: {_e}")
        exit(1)
    exit(0)

# ==================== LECTURA — todos los productos ====================
df = pd.read_csv(file_path)
df.columns = df.columns.str.strip()
for col in ['tipo', 'origen_categoria', 'destino_categoria', 'origen_nombre', 'destino_nombre']:
    df[col] = df[col].astype(str).str.strip()
df['monto']   = pd.to_numeric(df['monto'], errors='coerce').fillna(0)
df['producto'] = df['producto'].astype(str).str.upper().str.strip()

cat_dac      = ["DAC Distribuidor Nacional"]
cat_subdac   = ["SubDAC Dist Nacional"]
cat_vendedor = ["Vendedor Dist Nacional", "Vendedor Master Dist Nacional"]
cat_bodega   = ["Bodega Dist Nacional", "PDV MOVIL Dist Nacional", "PDV WEB Dist Nacional"]

# ==================== HELPERS DE AGREGACIÓN ====================
def _agg(tipo, ocat, dcat, key_col):
    mask = pd.Series(True, index=df.index)
    if tipo:  mask &= df['tipo'] == tipo
    if ocat:  mask &= df['origen_categoria'].isin(ocat)
    if dcat:  mask &= df['destino_categoria'].isin(dcat)
    return df.loc[mask].groupby(key_col)['monto'].sum()


# ==================== TABLA BODEGAS DETALLE ====================
_bt = _agg('Transferencia', None,       cat_bodega, 'destino_nombre').rename('Recibido')
_ba = _agg('Anulacion',     cat_bodega, None,       'origen_nombre').rename('Devuelto')
df_bod = pd.concat([_bt, _ba], axis=1).fillna(0).astype(int)
df_bod['Ventas netas'] = df_bod['Recibido'] - df_bod['Devuelto']
df_bod.index.name = 'Nombre'
df_bod = df_bod.reset_index().sort_values('Ventas netas', ascending=False)

# ==================== RESUMEN GENERAL ====================
total_transf = int(df_bod['Recibido'].sum())
total_anul   = int(df_bod['Devuelto'].sum())
neto         = total_transf - total_anul
n_bodegas    = int(df_bod[df_bod['Ventas netas'] > 0]['Nombre'].nunique())

# ==================== CASCADA: datos por nivel ====================
# DAC
dac_to_vend = int(_agg('Transferencia', cat_dac, cat_vendedor, 'origen_nombre').sum())
dac_to_sub  = int(_agg('Transferencia', cat_dac, cat_subdac,   'origen_nombre').sum())
dac_to_bod  = int(_agg('Transferencia', cat_dac, cat_bodega,   'origen_nombre').sum())
dac_recibio = int(_agg('Anulacion', None, cat_dac, 'destino_nombre').sum())
dac_nombres = df[df['origen_categoria'].isin(cat_dac)]['origen_nombre'].unique().tolist()
dac_nombre  = dac_nombres[0] if dac_nombres else "DAC"

# SubDAC (solo si tiene actividad)
sub_to_vend  = int(_agg('Transferencia', cat_subdac, cat_vendedor, 'origen_nombre').sum())
sub_to_bod   = int(_agg('Transferencia', cat_subdac, cat_bodega,   'origen_nombre').sum())
sub_recibido = int(_agg('Transferencia', cat_dac,    cat_subdac,   'destino_nombre').sum())
sub_activo   = (sub_recibido + sub_to_vend + sub_to_bod) > 0

# Vendedores — ranking por lo enviado a bodegas
vend_dist = _agg('Transferencia', cat_vendedor, cat_bodega, 'origen_nombre').sort_values(ascending=False)
n_vendedores = int(vend_dist[vend_dist > 0].count())

# ==================== MÉTRICAS HORARIAS ====================
df_bh = df[
    (df['tipo'] == 'Transferencia') &
    (df['destino_categoria'].isin(cat_bodega))
].copy()

if not df_bh.empty:
    df_bh['hora_int'] = df_bh['Hora'].str.split(':').str[0].astype(int)
    hourly = (df_bh.groupby('hora_int')
                   .agg(txn=('monto', 'count'), monto=('monto', 'sum'))
                   .reset_index().sort_values('hora_int'))
    total_bh_txn  = len(df_bh)
    txn_ppal      = len(df_bh[df_bh['hora_int'].between(10, 17)])
    pct_ppal      = round(txn_ppal / total_bh_txn * 100)
    peak_idx      = int(hourly['txn'].idxmax())
    peak_hour     = int(hourly.loc[peak_idx, 'hora_int'])
    peak_txn      = int(hourly.loc[peak_idx, 'txn'])
    avg_ticket    = int(df_bh['monto'].mean())
    hora_max_disp = int(hourly['hora_int'].max())
else:
    hourly = None
    total_bh_txn = pct_ppal = peak_hour = peak_txn = avg_ticket = hora_max_disp = 0

# ==================== DETECCIÓN DE FECHA ====================
archivo_nombre = os.path.basename(file_path)
fecha_str = "No especificada"
match = re.search(r'(\d{8})(?:_(\d{8}))?', archivo_nombre)
if match:
    d1 = f"{match.group(1)[6:]}/{match.group(1)[4:6]}/{match.group(1)[:4]}"
    fecha_str = d1
    if match.group(2):
        d2 = f"{match.group(2)[6:]}/{match.group(2)[4:6]}/{match.group(2)[:4]}"
        fecha_str = f"{d1} al {d2}"

# ==================== HTML HELPERS ====================
C_BLUE   = "#1565C0"
C_GREEN  = "#2E7D32"
C_AMBER  = "#E65100"
C_PURPLE = "#7B1FA2"
C_RED    = "#C62828"
C_TOTAL  = "#E3F2FD"
C_ROW_A  = "#F9FAFB"
C_ROW_B  = "#FFFFFF"


def _fmt(val):
    n = int(val)
    return f"S/ {n:,}"


def summary_card(label, value, color=C_BLUE, subtitle=""):
    sub = f"<div style='font-size:10px;color:#999;margin-top:1px'>{subtitle}</div>" if subtitle else ""
    return (
        f"<div style='display:inline-block;background:#F0F4FF;border-left:4px solid {color};"
        f"padding:10px 16px;margin:4px 8px 4px 0;border-radius:4px;min-width:130px'>"
        f"<div style='font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.5px'>{label}</div>"
        f"<div style='font-size:18px;font-weight:bold;color:{color};margin-top:2px'>{_fmt(value)}</div>"
        f"{sub}</div>"
    )


def html_table(dataframe, title, descripcion):
    if dataframe.empty:
        return (f"<h4 style='color:{C_BLUE};margin:18px 0 4px'>{title}</h4>"
                f"<p style='font-size:12px;color:#999'>Sin datos para este período.</p>")
    cols   = dataframe.columns.tolist()
    totals = {c: dataframe[c].sum() if c != 'Nombre' else 'TOTAL' for c in cols}
    tdb  = "padding:5px 10px;border:1px solid #E0E0E0;"
    tdn  = tdb + "text-align:right;"
    tdt  = "padding:6px 10px;border:1px solid #BDBDBD;font-weight:bold;"
    tdtn = tdt + "text-align:right;"
    html = (f"<h4 style='color:{C_BLUE};margin:18px 0 4px'>{title}</h4>"
            f"<p style='font-size:11px;color:#777;margin-bottom:6px'>{descripcion}</p>"
            f"<table style='border-collapse:collapse;font-size:12px;width:100%;max-width:680px'>"
            f"<thead><tr style='background:{C_BLUE};color:#FFF'>")
    for col in cols:
        al = "left" if col == "Nombre" else "right"
        html += f"<th style='padding:7px 10px;border:1px solid #0D47A1;text-align:{al}'>{col}</th>"
    html += "</tr></thead><tbody>"
    for i, (_, row) in enumerate(dataframe.iterrows()):
        bg = C_ROW_A if i % 2 == 0 else C_ROW_B
        html += f"<tr style='background:{bg}'>"
        for col, val in row.items():
            html += (f"<td style='{tdb}'>{val}</td>" if col == 'Nombre'
                     else f"<td style='{tdn}'>{_fmt(val)}</td>")
        html += "</tr>"
    html += f"<tr style='background:{C_TOTAL}'>"
    for col in cols:
        val = totals[col]
        html += (f"<td style='{tdt}'>TOTAL</td>" if col == 'Nombre'
                 else f"<td style='{tdtn}'>{_fmt(val)}</td>")
    html += "</tr></tbody></table>"
    return html


# ──────────────────────────────────────────────────────────────
# REC 2+4 — Tarjetas actividad horaria
# ──────────────────────────────────────────────────────────────
def html_activity_cards(peak_h, peak_t, pct, avg_t, total_t):
    if total_t == 0:
        return ""
    def _card(bg, border, label, big, small):
        return (
            f"<div style='display:inline-block;background:{bg};border-left:4px solid {border};"
            f"padding:10px 16px;margin:4px 8px 4px 0;border-radius:4px;min-width:130px'>"
            f"<div style='font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.5px'>{label}</div>"
            f"<div style='font-size:20px;font-weight:bold;color:{border};margin-top:2px'>{big}</div>"
            f"<div style='font-size:10px;color:#999;margin-top:1px'>{small}</div></div>"
        )
    return (
        "<div style='margin:8px 0 16px'>"
        + _card("#FFF8E1", C_AMBER,  "⏰ Hora pico",      f"{peak_h:02d}:00h", f"{peak_t} transacciones")
        + _card("#E8F5E9", C_GREEN,  "🕙 10h – 18h",      f"{pct}%",           "de la actividad")
        + _card("#F3E5F5", C_PURPLE, "💳 Ticket promedio", _fmt(avg_t),         "por transacción")
        + "</div>"
    )


# ──────────────────────────────────────────────────────────────
# REC 1 — Gráfico de barras horizontales por hora
# ──────────────────────────────────────────────────────────────
def html_hourly_chart(hourly_df, peak_h, hora_max):
    if hourly_df is None or hourly_df.empty:
        return ""
    BAR_MAX  = 220
    max_txn  = int(hourly_df['txn'].max())
    hdata    = {int(r['hora_int']): (int(r['txn']), int(r['monto']))
                for _, r in hourly_df.iterrows()}
    html = (
        f"<h4 style='color:{C_BLUE};margin:18px 0 2px'>📊 Actividad por hora · Transferencias a Bodegas</h4>"
        "<p style='font-size:11px;color:#777;margin:0 0 8px'>Número de transacciones por hora (todos los productos)</p>"
        "<table style='border-collapse:collapse;font-size:11px'>"
    )
    for h in range(6, max(hora_max + 1, 22)):
        txn, monto = hdata.get(h, (0, 0))
        bar_px  = int(txn / max_txn * BAR_MAX) if max_txn > 0 and txn > 0 else 0
        is_peak = (h == peak_h)
        b_col   = C_AMBER if is_peak else (C_BLUE if txn > 0 else "#E0E0E0")
        l_col   = C_AMBER if is_peak else "#444"
        w       = "bold" if is_peak else "normal"
        lbl     = "  ★ pico" if is_peak else ""
        html += (
            f"<tr>"
            f"<td style='width:30px;text-align:right;padding:2px 7px 2px 0;color:#666;"
            f"white-space:nowrap;font-weight:{w}'>{h:02d}h</td>"
            f"<td style='padding:2px 0;width:{BAR_MAX}px'>"
            f"<table style='border-collapse:collapse;width:{BAR_MAX}px'>"
            f"<tr style='height:13px'>"
            f"<td style='width:{bar_px}px;background:{b_col}'></td>"
            f"<td style='background:#EEF2FF'></td>"
            f"</tr></table></td>"
            f"<td style='padding:2px 0 2px 8px;color:{l_col};white-space:nowrap;font-weight:{w}'>"
            f"<strong>{txn}</strong> txn · {_fmt(monto)}{lbl}</td>"
            f"</tr>"
        )
    html += "</table>"
    top2     = hourly_df.nlargest(2, 'txn')['hora_int'].tolist()
    top2_str = " y ".join(f"<strong>{int(h):02d}h</strong>" for h in sorted(top2))
    html += (
        f"<p style='font-size:11px;color:#555;margin:8px 0 0;background:#FFF8E1;"
        f"padding:6px 10px;border-left:3px solid {C_AMBER};display:inline-block'>"
        f"🔑 Horas más activas: {top2_str} · "
        f"Pico: <strong>{peak_h:02d}:00h</strong> — "
        f"<strong>{int(hourly_df.loc[hourly_df['txn'].idxmax(),'txn'])} txn</strong></p><br>"
    )
    return html


# ──────────────────────────────────────────────────────────────
# REC 3 — Top 5 bodegas con mini-barra
# ──────────────────────────────────────────────────────────────
def html_top5_bodegas(df_full, n=5):
    top = df_full[df_full['Recibido'] > 0].head(n).copy()
    if top.empty:
        return ""
    BAR_MAX = 160
    max_t   = int(top['Recibido'].max())
    html = (
        f"<h4 style='color:{C_BLUE};margin:18px 0 2px'>🏆 Top {n} Bodegas del día</h4>"
        "<p style='font-size:11px;color:#777;margin:0 0 8px'>"
        "Por saldo recibido (todos los productos) · barra proporcional al mayor</p>"
        "<table style='border-collapse:collapse;font-size:12px;width:100%;max-width:600px'>"
        f"<tr style='background:{C_BLUE};color:#FFF'>"
        "<th style='padding:7px 10px;text-align:left'>#</th>"
        "<th style='padding:7px 10px;text-align:left'>Bodega</th>"
        f"<th style='padding:7px 10px;text-align:left;min-width:{BAR_MAX+20}px'>Saldo recibido</th>"
        "<th style='padding:7px 10px;text-align:right'>Ventas netas</th></tr>"
    )
    for rank, (_, row) in enumerate(top.iterrows(), start=1):
        t      = int(row['Recibido'])
        neto_v = int(row['Ventas netas'])
        bar_px = int(t / max_t * BAR_MAX) if max_t > 0 else 0
        bg     = C_ROW_A if rank % 2 == 1 else C_ROW_B
        nc     = C_GREEN if neto_v >= 0 else C_RED
        medal  = ("🥇" if rank == 1 else "🥈" if rank == 2
                  else "🥉" if rank == 3 else str(rank))
        html += (
            f"<tr style='background:{bg}'>"
            f"<td style='padding:6px 8px;text-align:center;font-size:14px'>{medal}</td>"
            f"<td style='padding:6px 10px;max-width:160px'>{row['Nombre']}</td>"
            f"<td style='padding:4px 10px'>"
            f"<table style='border-collapse:collapse;margin-bottom:2px'>"
            f"<tr style='height:11px'>"
            f"<td style='width:{bar_px}px;background:{C_BLUE}'></td>"
            f"<td style='width:{BAR_MAX - bar_px}px;background:#EEF2FF'></td>"
            f"</tr></table>"
            f"<span style='font-size:11px;color:#333'>{_fmt(t)}</span></td>"
            f"<td style='padding:6px 10px;text-align:right;font-weight:bold;color:{nc}'>"
            f"{_fmt(neto_v)}</td></tr>"
        )
    html += "</table><br>"
    return html


# ──────────────────────────────────────────────────────────────
# PROPUESTA A — Flujo en cascada visual (reemplaza DAC+SubDAC+Vendedores)
# ──────────────────────────────────────────────────────────────
def _cascade_box(color, bg, icon, title, subtitle, lines):
    """Caja de un nivel de la cascada."""
    body = "".join(
        f"<tr><td style='padding:2px 0;font-size:12px;color:#444'>{line}</td></tr>"
        for line in lines
    )
    return (
        f"<table style='border-collapse:collapse;width:100%;max-width:580px;"
        f"background:{bg};border-left:5px solid {color};border-radius:0 6px 6px 0;margin-bottom:0'>"
        f"<tr><td style='padding:10px 14px'>"
        f"<div style='font-size:13px;font-weight:bold;color:{color};margin-bottom:6px'>"
        f"{icon} {title}"
        f"<span style='font-size:11px;font-weight:normal;color:#888;margin-left:8px'>{subtitle}</span>"
        f"</div>"
        f"<table style='border-collapse:collapse'>{body}</table>"
        f"</td></tr></table>"
    )


def _arrow(color):
    return (f"<div style='text-align:left;padding-left:28px;margin:0;line-height:1;"
            f"font-size:22px;color:{color}'>↓</div>")


def html_cascade(dac_nom, dac_to_v, dac_to_s, dac_to_b, dac_recv,
                 sub_activo, sub_recv, sub_to_v, sub_to_b,
                 vend_series, n_vend,
                 total_bodegas, neto_bodegas, n_bodegas_activas):

    # ── NIVEL DAC ──
    dac_lines = []
    if dac_to_v:  dac_lines.append(f"📤 Envió a Vendedores: <strong>{_fmt(dac_to_v)}</strong>")
    if dac_to_s:  dac_lines.append(f"📤 Envió a SubDAC: <strong>{_fmt(dac_to_s)}</strong>")
    if dac_to_b:  dac_lines.append(f"📤 Envió a Bodegas: <strong>{_fmt(dac_to_b)}</strong>")
    if dac_recv:  dac_lines.append(f"🔄 Recibió devoluciones / recaudación: <strong>{_fmt(dac_recv)}</strong>")
    box_dac = _cascade_box(C_BLUE, "#EFF6FF", "📦", "DAC", dac_nom, dac_lines)

    # ── NIVEL SubDAC (solo si hubo actividad) ──
    box_sub = ""
    arr_sub = ""
    if sub_activo:
        sub_lines = []
        if sub_recv:   sub_lines.append(f"📥 Recibió del DAC: <strong>{_fmt(sub_recv)}</strong>")
        if sub_to_v:   sub_lines.append(f"📤 Envió a Vendedores: <strong>{_fmt(sub_to_v)}</strong>")
        if sub_to_b:   sub_lines.append(f"📤 Envió a Bodegas: <strong>{_fmt(sub_to_b)}</strong>")
        box_sub = _cascade_box("#6A1B9A", "#F3E5F5", "🔗", "SubDAC", "", sub_lines)
        arr_sub = _arrow("#6A1B9A")

    # ── NIVEL VENDEDORES (ranking con mini-barras) ──
    vend_activos = vend_series[vend_series > 0]
    BAR_V = 140
    max_v = int(vend_activos.max()) if not vend_activos.empty else 1
    vend_rows = ""
    for nombre, monto_v in vend_activos.head(6).items():
        bar_px = int(int(monto_v) / max_v * BAR_V)
        vend_rows += (
            f"<tr><td style='padding:2px 6px 2px 0;font-size:11px;color:#444;white-space:nowrap;"
            f"max-width:140px;overflow:hidden'>{nombre}</td>"
            f"<td style='padding:2px 4px'>"
            f"<table style='border-collapse:collapse'><tr style='height:10px'>"
            f"<td style='width:{bar_px}px;background:{C_GREEN}'></td>"
            f"<td style='width:{BAR_V - bar_px}px;background:#C8E6C9'></td>"
            f"</tr></table></td>"
            f"<td style='padding:2px 0 2px 6px;font-size:11px;color:#333;white-space:nowrap'>"
            f"{_fmt(int(monto_v))}</td></tr>"
        )
    if len(vend_activos) > 6:
        resto = int(vend_activos.iloc[6:].sum())
        vend_rows += (
            f"<tr><td colspan='3' style='font-size:10px;color:#999;padding-top:3px'>"
            f"+ {len(vend_activos)-6} más · {_fmt(resto)}</td></tr>"
        )
    vend_inner = (
        f"<table style='border-collapse:collapse;margin-top:4px'>{vend_rows}</table>"
        if vend_rows else "<span style='color:#aaa;font-size:11px'>Sin distribuciones este día</span>"
    )
    vend_subtitle = f"{n_vend} activos" if n_vend else ""
    box_vend = (
        f"<table style='border-collapse:collapse;width:100%;max-width:580px;"
        f"background:#F1F8E9;border-left:5px solid {C_GREEN};border-radius:0 6px 6px 0'>"
        f"<tr><td style='padding:10px 14px'>"
        f"<div style='font-size:13px;font-weight:bold;color:{C_GREEN};margin-bottom:6px'>"
        f"🤝 Vendedores"
        f"<span style='font-size:11px;font-weight:normal;color:#888;margin-left:8px'>{vend_subtitle}</span>"
        f"</div>"
        f"<p style='font-size:11px;color:#777;margin:0 0 6px'>Saldo distribuido a Bodegas</p>"
        f"{vend_inner}"
        f"</td></tr></table>"
    )

    # ── NIVEL BODEGAS (resumen) ──
    bod_lines = [
        f"📥 Total recibido: <strong>{_fmt(total_bodegas)}</strong>",
        f"✅ Ventas netas: <strong>{_fmt(neto_bodegas)}</strong>",
        f"🏪 Bodegas con actividad: <strong>{n_bodegas_activas}</strong>",
    ]
    box_bod = _cascade_box(C_AMBER, "#FFF8E1", "🏪", "Bodegas", "", bod_lines)

    return (
        f"<h4 style='color:{C_BLUE};margin:20px 0 8px'>🔀 Flujo de distribución del día</h4>"
        f"<p style='font-size:11px;color:#777;margin:0 0 10px'>"
        f"Cadena completa: DAC → Vendedores → Bodegas (todos los productos)</p>"
        + box_dac
        + _arrow(C_BLUE)
        + (box_sub + arr_sub if sub_activo else "")
        + box_vend
        + _arrow(C_GREEN)
        + box_bod
        + "<br>"
    )


# ==================== GENERAR SECCIONES HTML ====================
cards = (
    summary_card("Total recibido",  total_transf, C_BLUE,   "por bodegas")
  + summary_card("Total devuelto",  total_anul,   C_RED,    "anulaciones")
  + summary_card("Ventas netas",    neto,  C_GREEN if neto >= 0 else C_RED, "")
  + (f"<div style='display:inline-block;background:#F0F4FF;border-left:4px solid {C_PURPLE};"
     f"padding:10px 16px;margin:4px 8px 4px 0;border-radius:4px;min-width:130px'>"
     f"<div style='font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.5px'>Bodegas activas</div>"
     f"<div style='font-size:18px;font-weight:bold;color:{C_PURPLE};margin-top:2px'>{n_bodegas}</div>"
     f"</div>")
)

activity_cards = html_activity_cards(peak_hour, peak_txn, pct_ppal, avg_ticket, total_bh_txn)
chart_horas    = html_hourly_chart(hourly, peak_hour, hora_max_disp)
top5_html      = html_top5_bodegas(df_bod)
cascade_html   = html_cascade(
    dac_nom=dac_nombre,
    dac_to_v=dac_to_vend, dac_to_s=dac_to_sub, dac_to_b=dac_to_bod, dac_recv=dac_recibio,
    sub_activo=sub_activo, sub_recv=sub_recibido, sub_to_v=sub_to_vend, sub_to_b=sub_to_bod,
    vend_series=vend_dist, n_vend=n_vendedores,
    total_bodegas=total_transf, neto_bodegas=neto, n_bodegas_activas=n_bodegas,
)
html_bod_detalle = html_table(
    df_bod, "🏪 Bodegas — detalle completo",
    "Saldo recibido, devoluciones y ventas netas por bodega (todos los productos)."
)

logo_tag = ('<img src="cid:logo_rosaqui" style="width:100%;max-width:600px;display:block;" />'
            if logo_path else "")

# Línea de job/tiempo solo si vienen las variables
job_line = ""
if job_name or build_time:
    parts = []
    if job_name:   parts.append(f"Job: <strong>{job_name}</strong>")
    if build_time: parts.append(f"Ejecutado: <strong>{build_time}</strong>")
    job_line = (f"<p style='font-size:11px;color:#888;margin:2px 0 0;"
                f"background:#F5F5F5;padding:4px 8px;border-radius:3px;display:inline-block'>"
                + " · ".join(parts) + "</p>")

# ==================== CUERPO DEL CORREO ====================
html_body = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#F4F6F8;font-family:Arial,Helvetica,sans-serif;">
  <div style="max-width:680px;margin:20px auto;background:#FFFFFF;border-radius:6px;
              box-shadow:0 2px 8px rgba(0,0,0,.12);overflow:hidden;">

    {logo_tag}

    <div style="padding:24px 28px;">
      <h2 style="color:{C_BLUE};margin:0 0 2px">Grupo Rosaqui S.A.C.</h2>
      <p style="color:#555;font-size:13px;margin:0 0 4px">
        Resumen de transferencias internas · <strong>{fecha_str}</strong>
      </p>
      {job_line}

      <p style="font-size:13px;color:#333;margin:14px 0 10px">
        Estimado equipo, a continuación el resumen del movimiento de saldo
        (Prepago + Recaudación) del período indicado.
      </p>

      <div style="margin-bottom:4px">{cards}</div>
      {activity_cards}

      {chart_horas}

      {top5_html}

      {cascade_html}

      <div style="border-top:1px solid #E0E0E0;margin:20px 0 4px;font-size:0">&nbsp;</div>

      {html_bod_detalle}

      <div style="border-top:1px solid #E0E0E0;margin:24px 0 12px;font-size:0">&nbsp;</div>
      <p style="font-size:11px;color:#999;margin:0">
        Grupo Rosaqui S.A.C. · Tecnología e Innovación ·
        Mensaje generado automáticamente, por favor no responder.
      </p>
    </div>
  </div>
</body>
</html>"""

# ==================== CONSTRUIR MENSAJE ====================
message            = MIMEMultipart("related")
message["Subject"] = subject
message["From"]    = sender_email
message["To"]      = ", ".join(destinatarios)

msg_alt = MIMEMultipart("alternative")
message.attach(msg_alt)
msg_alt.attach(MIMEText(html_body, "html"))

with open(file_path, "rb") as f:
    part = MIMEApplication(f.read(), Name=archivo_nombre)
    part['Content-Disposition'] = f'attachment; filename="{archivo_nombre}"'
    message.attach(part)

if logo_path:
    with open(logo_path, "rb") as img:
        logo = MIMEImage(img.read())
        logo.add_header('Content-ID', '<logo_rosaqui>')
        message.attach(logo)

# ==================== ENVÍO ====================
try:
    with _SMTPv4(smtp_server, smtp_port, timeout=smtp_timeout) as server:
        server.starttls()
        server.login(sender_email, app_password)
        server.sendmail(sender_email, destinatarios, message.as_string())
    print(f"✅ Correo enviado a: {', '.join(destinatarios)}")
except Exception as e:
    print(f"❌ Error al enviar correo: {e}")
    exit(1)
