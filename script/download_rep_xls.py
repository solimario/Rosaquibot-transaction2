#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download_rep_xls.py
Descarga el reporte C2C (Transferencia de Saldo Interna) de Pretups
usando requests + BeautifulSoup, sin Selenium ni Xvfb.

Reemplaza la versión anterior basada en Selenium.
Interfaz idéntica: mismos argumentos, misma ruta de salida.
transf_int_job.sh no requiere cambios.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Carga cfg/.env del proyecto. override=False: si el shell ya hizo source, no pisa nada.
_ENV_FILE = Path(__file__).resolve().parent.parent / "cfg" / ".env"
if _ENV_FILE.exists():
    load_dotenv(dotenv_path=_ENV_FILE, override=False)

# ============================================================================
# CONFIGURACIÓN
# ============================================================================
ORIGIN    = "https://crl.dacclaro.com.pe"
BASE      = ORIGIN + "/pretups/"
LOGIN_URL = urljoin(BASE, "login.do")

DEBUG          = os.getenv("DEBUG", "").strip().lower() in {"1", "true", "yes", "y"}
TIMEOUT        = int(os.getenv("PRETUPS_TIMEOUT", "60").strip())
CLARO_USER     = os.getenv("CLARO_USER", "").strip()
CLARO_PASS     = os.getenv("CLARO_PASS", "").strip()
OUTPUT_XLS_ENV = os.getenv("OUTPUT_XLS", "").strip()

# Siempre relativo al directorio raíz del proyecto, independiente del CWD de Jenkins
DEBUG_DIR = Path(__file__).resolve().parent.parent / "salida_http_c2c"

XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


# ============================================================================
# UTILIDADES
# ============================================================================
def log(msg: str) -> None:
    print(msg, flush=True)


def dbg(msg: str) -> None:
    if DEBUG:
        print(f"[DEBUG] {msg}", flush=True)


def _save(path: Path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif isinstance(content, (dict, list)):
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.write_text(str(content), encoding="utf-8", errors="replace")


def save_debug(name: str, content) -> None:
    if not DEBUG:
        return
    _save(DEBUG_DIR / name, content)
    dbg(f"Guardado: {DEBUG_DIR / name}")


def save_error(name: str, content) -> None:
    _save(DEBUG_DIR / name, content)
    log(f"   Evidencia guardada: {DEBUG_DIR / name}")


# ============================================================================
# ARGUMENTOS / FECHAS
# ============================================================================
def _validate_ddmmyy(s: str) -> str:
    if not re.fullmatch(r"\d{2}/\d{2}/\d{2}", s):
        raise ValueError(f"Formato inválido: '{s}'. Usa DD/MM/YY (ej. 22/04/26).")
    try:
        datetime.strptime(s, "%d/%m/%y")
    except ValueError:
        raise ValueError(f"Fecha no válida: '{s}'.")
    return s


def get_dates() -> tuple[str, str]:
    parser = argparse.ArgumentParser(description="Descarga reporte C2C vía HTTP.")
    parser.add_argument("--fecha",        help="Fecha única DD/MM/YY (retrocompat)")
    parser.add_argument("--fecha-inicio", help="Fecha inicio DD/MM/YY")
    parser.add_argument("--fecha-fin",    help="Fecha fin DD/MM/YY")
    args = parser.parse_args()

    ini = (args.fecha_inicio or os.getenv("FECHA_INICIO", "")).strip()
    fin = (args.fecha_fin    or os.getenv("FECHA_FIN",    "")).strip()

    if not ini and not fin:
        legacy = (args.fecha or os.getenv("FECHA", "")).strip()
        if legacy:
            v = _validate_ddmmyy(legacy)
            return v, v

    if ini:
        ini = _validate_ddmmyy(ini)
    if fin:
        fin = _validate_ddmmyy(fin)

    if not ini and not fin:
        ayer = (datetime.now() - timedelta(days=1)).strftime("%d/%m/%y")
        return ayer, ayer
    elif ini and not fin:
        return ini, ini
    elif not ini and fin:
        return fin, fin
    return ini, fin


# ============================================================================
# SESSION
# ============================================================================
def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
    })
    return s


# ============================================================================
# LOGIN
# ============================================================================
def _extract_js_redirect(html: str) -> str | None:
    m = re.search(r"location\.replace\('([^']+)'\)", html)
    return m.group(1) if m else None


def _extract_frame_by_index(html: str, index: int = 0) -> str:
    soup = BeautifulSoup(html, "html.parser")
    frames = soup.find_all("frame")
    if len(frames) > index:
        return (frames[index].get("src") or "").strip()
    for attr in ("mainFrame", "leftFrame", "menuFrame"):
        f = soup.find("frame", id=attr) or soup.find("frame", attrs={"name": attr})
        if f:
            return (f.get("src") or "").strip()
    return ""


def login(session: requests.Session) -> tuple[str, requests.Response]:
    log("➡️  GET base...")
    r0 = session.get(BASE, timeout=TIMEOUT)
    r0.raise_for_status()
    save_debug("00_base.html", r0.text)

    log("➡️  POST login...")
    payload = {
        "method":   "loadUserDetails",
        "page":     "1",
        "language": "sp_PE",
        "loginID":  CLARO_USER,
        "password": CLARO_PASS,
        "submit1":  "Entrada al sistema",
    }
    save_debug("01_login_payload.json", {**payload, "password": "***REDACTED***"})

    r1 = session.post(
        LOGIN_URL, data=payload,
        headers={"Referer": BASE, "Origin": ORIGIN,
                 "Content-Type": "application/x-www-form-urlencoded"},
        timeout=TIMEOUT,
    )
    r1.raise_for_status()
    save_debug("02_login_response.html", r1.text)

    redirect = _extract_js_redirect(r1.text)
    if not redirect:
        save_error("error_login.html", r1.text)
        raise RuntimeError("Login fallido: no se encontró redirect JS. Ver salida_http_c2c/error_login.html")

    redirect_url = urljoin(ORIGIN, redirect)
    dbg(f"Redirect → {redirect_url}")
    r2 = session.get(redirect_url, timeout=TIMEOUT)
    r2.raise_for_status()
    save_debug("03_homepage.html", r2.text)

    frame_src = _extract_frame_by_index(r2.text, 0)
    if not frame_src:
        save_error("error_no_frame.html", r2.text)
        raise RuntimeError("No se encontró frame[0] en el homepage. Ver salida_http_c2c/error_no_frame.html")

    frame_url = urljoin(str(r2.url), frame_src)
    dbg(f"Frame[0] URL → {frame_url}")
    r3 = session.get(frame_url, timeout=TIMEOUT)
    r3.raise_for_status()
    save_debug("04_frame0_nav.html", r3.text)
    save_debug("session_cookies.json", {c.name: c.value for c in session.cookies})

    return str(r2.url), r3


# ============================================================================
# NAVEGACIÓN AL FORMULARIO C2C
# ============================================================================
def _find_link(html: str, base_url: str, *keywords: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    kw = [k.lower() for k in keywords]

    for a in soup.find_all("a", href=True):
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).lower()
        if all(k in text for k in kw):
            href = a["href"].strip()
            if href and not href.startswith("javascript:void"):
                return href

    for a in soup.find_all("a"):
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).lower()
        if all(k in text for k in kw):
            onclick = a.get("onclick", "")
            m = re.search(r"['\"]([\w./?\-&=]+\.do[^'\"]*)['\"]", onclick)
            if m:
                return m.group(1)
    return None


def navigate_to_c2c_form(session: requests.Session, frame_resp: requests.Response) -> requests.Response:
    nav_url = str(frame_resp.url)

    log("➡️  Buscando enlace 'Reporte de canal C2C'...")
    href1 = (
        _find_link(frame_resp.text, nav_url, "reporte de canal", "c2c")
        or _find_link(frame_resp.text, nav_url, "transferencia de saldo interna")
        or _find_link(frame_resp.text, nav_url, "c2c")
    )
    if not href1:
        save_error("error_no_link_menu_c2c.html", frame_resp.text)
        raise RuntimeError("No se encontró el enlace 'Reporte de canal C2C'. Ver salida_http_c2c/error_no_link_menu_c2c.html")

    url1 = urljoin(nav_url, href1)
    dbg(f"Link menú C2C → {url1}")
    r1 = session.get(url1, headers={"Referer": nav_url}, timeout=TIMEOUT)
    r1.raise_for_status()
    save_debug("05_c2c_submenu.html", r1.text)

    log("➡️  Buscando enlace 'Detalles de transferencias C2C'...")
    href2 = (
        _find_link(r1.text, url1, "detalles", "c2c")
        or _find_link(r1.text, url1, "detalles", "transferencia")
        or _find_link(r1.text, url1, "detalles")
    )
    if not href2:
        save_error("error_no_link_detalle_c2c.html", r1.text)
        raise RuntimeError("No se encontró 'Detalles de transferencias C2C'. Ver salida_http_c2c/error_no_link_detalle_c2c.html")

    url2 = urljoin(url1, href2)
    dbg(f"Link detalle C2C → {url2}")
    r2 = session.get(url2, headers={"Referer": url1}, timeout=TIMEOUT)
    r2.raise_for_status()
    save_debug("06_c2c_form.html", r2.text)

    return r2


# ============================================================================
# ENVÍO DEL FORMULARIO C2C
# ============================================================================
def _parse_form(html: str, page_url: str, preferred_name: str | None = None) -> dict:
    soup = BeautifulSoup(html, "lxml")

    form = None
    if preferred_name:
        form = (soup.find("form", {"name": preferred_name})
                or soup.find("form", {"id": preferred_name}))
    if not form:
        form = soup.find("form")
    if not form:
        raise RuntimeError("No se encontró ningún <form> en la página del reporte C2C.")

    action     = form.get("action") or page_url
    method     = (form.get("method") or "POST").upper()
    action_url = urljoin(page_url, action)

    fields: dict[str, str] = {}
    submits: dict[str, str] = {}

    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        itype = (inp.get("type") or "text").lower()
        if itype in {"image", "reset"}:
            continue
        if itype in {"checkbox", "radio"} and not inp.has_attr("checked"):
            continue
        if itype in {"submit", "button"}:
            submits[name] = inp.get("value", "")
            continue
        fields[name] = inp.get("value", "")

    for sel in form.find_all("select"):
        name = sel.get("name")
        if not name:
            continue
        opt = sel.find("option", selected=True) or sel.find("option")
        fields[name] = opt.get("value", "") if opt else ""

    for ta in form.find_all("textarea"):
        name = ta.get("name")
        if name:
            fields[name] = ta.get_text() or ""

    return {
        "action_url": action_url,
        "method":     method,
        "fields":     fields,
        "submits":    submits,
        "form_name":  form.get("name") or form.get("id") or "",
    }


def submit_c2c_form(
    session: requests.Session,
    form_resp: requests.Response,
    fecha_ini: str,
    fecha_fin: str,
) -> requests.Response:
    page_url = str(form_resp.url)

    soup_raw = BeautifulSoup(form_resp.text, "lxml")
    btn = soup_raw.find(attrs={"name": "c2cTrfRetWid"})
    form_name = None
    if btn:
        parent_form = btn.find_parent("form")
        if parent_form:
            form_name = parent_form.get("name") or parent_form.get("id")

    fi = _parse_form(form_resp.text, page_url, form_name)

    save_debug("07_form_fields_raw.json", {
        "form_name":  fi["form_name"],
        "action_url": fi["action_url"],
        "method":     fi["method"],
        "fields":     fi["fields"],
        "submits":    fi["submits"],
    })

    payload = dict(fi["fields"])
    payload["txnSubType"]      = "ALL"
    payload["transferInOrOut"] = "ALL"
    payload["fromDate"]        = fecha_ini
    payload["toDate"]          = fecha_fin
    # El JS del form ejecuta changeFromCategory() que agrega ALL:ALL dinámicamente
    payload["fromtransferCategoryCode"] = "ALL:ALL"
    payload["userName"]                 = "Todo"
    payload["totransferCategoryCode"]   = "ALL:ALL:ALL"
    payload["touserName"]               = "Todo"

    if "c2cTrfRetWid" in fi["submits"]:
        payload["c2cTrfRetWid"] = fi["submits"]["c2cTrfRetWid"]
    elif btn:
        payload["c2cTrfRetWid"] = btn.get("value", "")

    save_debug("08_submit_payload.json", payload)
    log(f"➡️  {fi['method']} formulario → {fi['action_url']}")

    headers = {
        "Referer":      page_url,
        "Origin":       ORIGIN,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    if fi["method"] == "GET":
        r = session.get(fi["action_url"],  params=payload, headers=headers, timeout=TIMEOUT)
    else:
        r = session.post(fi["action_url"], data=payload,   headers=headers, timeout=TIMEOUT)

    r.raise_for_status()
    save_debug("09_after_submit.html", r.text)
    save_debug("09_after_submit_headers.json", dict(r.headers))
    dbg(f"Submit status={r.status_code}  Content-Type={r.headers.get('Content-Type','')}")

    soup_check = BeautifulSoup(r.text, "html.parser")
    validation_block = soup_check.find("h3")
    if validation_block and "Error de Validación" in validation_block.get_text():
        items = [li.get_text(strip=True) for li in soup_check.find_all("li")]
        errores = "; ".join(items) if items else r.text[1200:1600]
        save_error("error_validacion_servidor.html", r.text)
        raise RuntimeError(f"El servidor rechazó el formulario: {errores}")

    return r


# ============================================================================
# DESCARGA XLS — Crystal Reports HTML5 Viewer
# ============================================================================
def _is_xls(content: bytes, headers: dict) -> bool:
    if content[:8] == XLS_MAGIC:
        return True
    ct = (headers.get("Content-Type") or "").lower()
    cd = (headers.get("Content-Disposition") or "").lower()
    return (
        "vnd.ms-excel"    in ct
        or "application/xls" in ct
        or "octet-stream" in ct
        or "attachment"   in cd
    )


_SKIP_POPUPS = ("faq.do", "webhelp", "help_sp", "logout", "login.do",
                "Channel_User", "localeArr")


def _extract_report_popup_url(html: str, base_url: str) -> str | None:
    for m in re.finditer(r"window\.open\s*\(\s*['\"]([^'\"]+)['\"]", html, re.IGNORECASE):
        url = m.group(1).strip()
        if url and not any(skip in url for skip in _SKIP_POPUPS):
            return urljoin(base_url, url)
    return None


def _try_get_xls(session: requests.Session, url: str, referer: str,
                 label: str = "") -> bytes | None:
    dbg(f"GET {label} → {url}")
    try:
        r = session.get(url, headers={
            "Referer": referer,
            "Accept":  "application/vnd.ms-excel, application/octet-stream, */*",
        }, timeout=120, allow_redirects=True)
        r.raise_for_status()
        if _is_xls(r.content, r.headers):
            return r.content
        slug = re.sub(r"[^a-zA-Z0-9]", "_", url)[-50:]
        save_debug(f"xls_attempt_{slug}.html", r.text[:8000])
        dbg(f"   → no es XLS (ct={r.headers.get('Content-Type','')}, {len(r.content)} bytes)")
    except requests.RequestException as e:
        dbg(f"   → falló: {e}")
    return None


def _try_post_xls(session: requests.Session, url: str, data: dict,
                  referer: str, label: str = "") -> bytes | None:
    dbg(f"POST {label} → {url}")
    try:
        r = session.post(url, data=data, headers={
            "Referer":      referer,
            "Origin":       ORIGIN,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept":       "application/vnd.ms-excel, application/octet-stream, */*",
        }, timeout=120, allow_redirects=True)
        r.raise_for_status()
        if _is_xls(r.content, r.headers):
            return r.content
        slug = re.sub(r"[^a-zA-Z0-9]", "_", url)[-50:]
        save_debug(f"xls_post_{slug}.html", r.text[:8000])
        dbg(f"   → no es XLS (ct={r.headers.get('Content-Type','')}, {len(r.content)} bytes)")
    except requests.RequestException as e:
        dbg(f"   → falló: {e}")
    return None


def _crystal_xls_from_viewer(session: requests.Session,
                              viewer_url: str, viewer_html: str,
                              referer: str) -> bytes | None:
    """
    Exporta XLS desde el Crystal Reports HTML5 Viewer.
    URL construida por el JS del viewer:
        BASE?cmd=export&export_fmt=xls&disposition=attachment&ts=<ms>
    donde BASE = commonAction.do (sin query string).
    """
    import time as _time
    ts = int(_time.time() * 1000)
    base_action = viewer_url.split("?")[0]

    for fmt in ("xls", "xlsx"):
        url = f"{base_action}?cmd=export&export_fmt={fmt}&disposition=attachment&ts={ts}"
        content = _try_get_xls(session, url, referer=viewer_url, label=f"CR fmt={fmt}")
        if content:
            return content

        url = f"{base_action}?method=crystalReport&cmd=export&export_fmt={fmt}&disposition=attachment&ts={ts}"
        content = _try_get_xls(session, url, referer=viewer_url, label=f"CR method+fmt={fmt}")
        if content:
            return content

    for layout in ("", "staticlayout"):
        qs = f"cmd=export&export_fmt=xls&disposition=attachment&ts={ts}"
        if layout:
            qs += f"&staticlayout={layout}"
        content = _try_get_xls(session, f"{base_action}?{qs}",
                                referer=viewer_url, label=f"CR layout={layout or 'default'}")
        if content:
            return content

    for fmt in ("xls", "xlsx"):
        data = {"cmd": "export", "export_fmt": fmt,
                "disposition": "attachment", "ts": str(ts)}
        content = _try_post_xls(session, base_action, data,
                                 referer=viewer_url, label=f"CR POST fmt={fmt}")
        if content:
            return content
        data["method"] = "crystalReport"
        content = _try_post_xls(session, base_action, data,
                                 referer=viewer_url, label=f"CR POST method+fmt={fmt}")
        if content:
            return content

    save_error("crystal_viewer.html", viewer_html)
    return None


def download_xls(
    session: requests.Session,
    submit_resp: requests.Response,
    fecha_ini: str,
    fecha_fin: str,
) -> bytes:
    html = submit_resp.text
    base = str(submit_resp.url)
    hdrs = dict(submit_resp.headers)

    if _is_xls(submit_resp.content, hdrs):
        log("✅ La respuesta al submit es directamente XLS.")
        return submit_resp.content

    crystal_url = _extract_report_popup_url(html, base)
    save_debug("10_popup_url_detectado.json", {"url": crystal_url})

    if crystal_url:
        log(f"➡️  Crystal Reports viewer: {crystal_url}")

        content = _try_get_xls(session, crystal_url, referer=base, label="viewer directo")
        if content:
            log("✅ XLS obtenido del viewer directamente.")
            return content

        try:
            r_viewer = session.get(crystal_url, headers={"Referer": base}, timeout=TIMEOUT)
            r_viewer.raise_for_status()
            save_debug("11_crystal_viewer.html", r_viewer.text)
            save_debug("11_crystal_viewer_headers.json", dict(r_viewer.headers))

            if _is_xls(r_viewer.content, r_viewer.headers):
                log("✅ XLS obtenido del viewer (GET).")
                return r_viewer.content

            content = _crystal_xls_from_viewer(session, crystal_url, r_viewer.text, referer=base)
            if content:
                log("✅ XLS obtenido via Crystal Reports export.")
                return content

        except requests.RequestException as e:
            dbg(f"Error accediendo al viewer: {e}")

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    save_error("error_context.json", {
        "submit_url":     base,
        "submit_status":  submit_resp.status_code,
        "content_type":   submit_resp.headers.get("Content-Type", ""),
        "content_length": len(submit_resp.content),
        "crystal_url":    crystal_url,
        "instruccion": (
            "Abrir Chrome → DevTools → Network. Reproducir el flujo manual. "
            "Filtrar por Content-Disposition:attachment para encontrar el endpoint XLS."
        ),
    })
    save_error("error_last_html.html", html)
    raise RuntimeError(
        f"No se pudo descargar el XLS.\n"
        f"  crystal_url detectado: {crystal_url}\n"
        f"  Ver {DEBUG_DIR}/error_context.json\n"
        f"  Ver {DEBUG_DIR}/crystal_viewer.html  (si existe)"
    )


# ============================================================================
# MAIN
# ============================================================================
def main() -> None:
    if not CLARO_USER or not CLARO_PASS:
        log("❌ CLARO_USER o CLARO_PASS no están definidos.")
        sys.exit(1)

    fecha_ini, fecha_fin = get_dates()
    log(f"📅 Rango de fechas: {fecha_ini} → {fecha_fin}")

    if DEBUG:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        log(f"🐛 Modo DEBUG activado → evidencia en {DEBUG_DIR}/")

    # Ruta de salida compatible con transf_int_job.sh:
    #   - Si OUTPUT_XLS está exportado, escribe ahí directamente.
    #   - Si no, escribe en DOWNLOAD_DIR con el patrón C2cRetWidTransferChannelUserUnion*.xls
    #     que el shell encuentra con find y luego mueve a OUTPUT_XLS.
    if OUTPUT_XLS_ENV:
        out_path = Path(OUTPUT_XLS_ENV)
    else:
        fecha_ymd = datetime.strptime(fecha_ini, "%d/%m/%y").strftime("%Y%m%d")
        if fecha_ini != fecha_fin:
            fecha_fin_ymd = datetime.strptime(fecha_fin, "%d/%m/%y").strftime("%Y%m%d")
            fecha_ymd = f"{fecha_ymd}_{fecha_fin_ymd}"
        out_path = Path("/home/drosadio/Descargas") / f"C2cRetWidTransferChannelUserUnion_{fecha_ymd}.xls"

    log(f"📁 Destino XLS: {out_path}")

    session = build_session()

    try:
        log("🔐 Iniciando sesión...")
        _home_url, frame_resp = login(session)

        log("📂 Navegando al formulario C2C...")
        form_resp = navigate_to_c2c_form(session, frame_resp)

        log("🎛️  Enviando formulario con filtros y fechas...")
        submit_resp = submit_c2c_form(session, form_resp, fecha_ini, fecha_fin)

        log("⬇️  Descargando XLS...")
        xls_content = download_xls(session, submit_resp, fecha_ini, fecha_fin)

        if xls_content[:8] != XLS_MAGIC:
            log(f"⚠️  Firma XLS no reconocida. Bytes: {xls_content[:16].hex()}")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(xls_content)
        log(f"✅ XLS guardado: {out_path} ({len(xls_content):,} bytes)")

    except Exception as exc:
        log(f"❌ Error: {exc}")
        if DEBUG:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
