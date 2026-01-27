# ===== app.py (1/5) =====
# app.py
import streamlit as st
import pandas as pd
from io import BytesIO
import datetime as dt
import os
import re
import time
from streamlit_cookies_manager import EncryptedCookieManager
import secrets
import string

# ====== AJUSTES GENERALES ======
st.set_page_config(page_title="Tecnificaciones CBC ", layout="centered")
APP_TITLE = "🏀 Tecnificaciones CBC - Reserva de Sesiones"
ADMIN_QUERY_FLAG = "admin"

# Capacidad por categoría
MAX_POR_CANASTA = 4
CATEG_MINI = "Minibasket"
CATEG_GRANDE = "Canasta grande"

# Enlaces a canales de WhatsApp
CANAL_GENERAL_URL = st.secrets.get("CANAL_GENERAL_URL", "")
CANAL_MINI_URL = st.secrets.get("CANAL_MINI_URL", "")
CANAL_GRANDE_URL = st.secrets.get("CANAL_GRANDE_URL", "")

EQUIPOS_OPCIONES = [
    "— Selecciona —",
    "Benjamín 1ºaño 2017",
    "Benjamín 2ºaño 2016",
    "Alevín 1ºaño 2015",
    "Alevín 2ºaño 2014",
    "Infantil 1ºaño 2013",
    "Infantil 2ºaño 2012",
    "Cadete 1ºaño 2011",
    "Cadete 2ºaño 2010",
    "Junior 1ºaño 2009",
    "Junior 2ºaño 2008",
    "Senior",
    "Otro"
]

# ====== CHEQUEOS DE SECRETS ======
if "gcp_service_account" not in st.secrets:
    st.error("Faltan credenciales de Google en secrets: bloque [gcp_service_account].")
    st.stop()

_SID = st.secrets.get("SHEETS_SPREADSHEET_ID")
_URL = st.secrets.get("SHEETS_SPREADSHEET_URL")
_SID_BLOCK = (st.secrets.get("sheets") or {}).get("sheet_id")

if not (_SID or _URL or _SID_BLOCK):
    st.error("Configura en secrets la hoja: SHEETS_SPREADSHEET_ID o SHEETS_SPREADSHEET_URL (o [sheets].sheet_id).")
    st.stop()

# ====== UTILS ======
def read_secret(key: str, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, default)
        
cookies = EncryptedCookieManager(
    prefix="cbc/",
    password=read_secret("COOKIE_PASSWORD", "CAMBIA_ESTO_EN_SECRETS")
)

if not cookies.ready():
    st.stop()

def to_text(v):
    if v is None:
        return ""
    try:
        import math
        if isinstance(v, float) and math.isnan(v):
            return ""
    except Exception:
        pass
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="ignore")
    return str(v)

def _norm_name(s: str) -> str:
    return " ".join((s or "").split()).casefold()

FAMILIAS_HEADERS = ["codigo","tutor","telefono","email","updated_at"]
HIJOS_HEADERS    = ["codigo","jugador","equipo","canasta","updated_at"]

def _ensure_ws(sh, title: str, headers: list[str], cols: int):
    try:
        ws = sh.worksheet(title)
        h = ws.row_values(1)
        if len(h) < len(headers):
            _retry_gspread(ws.update, f"A1:{chr(64+len(headers))}1", [headers])
        return ws
    except WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=500, cols=cols)
        _retry_gspread(ws.update, f"A1:{chr(64+len(headers))}1", [headers])
        return ws

def _gen_family_code(prefix="CBC-", n=10) -> str:
    # 10 chars base32 friendly (sin 0/O, 1/I)
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    return prefix + "".join(secrets.choice(alphabet) for _ in range(n))

def crear_justificante_admin_pdf(fecha_iso: str, hora: str, record: dict, status_forzado: str = "ok") -> BytesIO:
    f_iso = _norm_fecha_iso(fecha_iso)
    h = _parse_hora_cell(hora)
    datos = {
        "status": status_forzado,  # "ok" para confirmada, "wait" para espera si quisieras
        "fecha_iso": f_iso,
        "fecha_txt": pd.to_datetime(f_iso).strftime("%d/%m/%Y"),
        "hora": h,
        "nombre": to_text(record.get("nombre", "—")),
        "canasta": to_text(record.get("canasta", "—")),
        "equipo": to_text(record.get("equipo", "—")),
        "tutor": to_text(record.get("tutor", "—")),
        "telefono": to_text(record.get("telefono", "—")),
        "email": to_text(record.get("email", "—")),
    }
    return crear_justificante_pdf(datos)
    
def texto_estado_grupo(fecha_iso: str, hora: str, canasta: str) -> tuple[str, str]:
    """
    Devuelve (nivel_streamlit, texto) según el estado real del grupo:
    - CERRADA -> cerrada por admin (no lista de espera)
    - ABIERTA sin plazas -> completa (lista de espera)
    - ABIERTA con plazas -> plazas disponibles
    """
    estado = get_estado_grupo_mem(fecha_iso, hora, canasta)

    if estado == "CERRADA":
        return "error", "⛔ **CERRADA** · no admite reservas"

    libres = plazas_libres_mem(fecha_iso, hora, canasta)

    if libres <= 0:
        return "warning", "🔴 **COMPLETA** → entrarás en *lista de espera*"
    if libres == 1:
        return "warning", "🟡 **Última plaza**"
    return "info", "🟢 **Plazas disponibles**"


def _norm_hora(h: str) -> str:
    h = (h or "").strip()
    if not h:
        return "—"
    if re.fullmatch(r"\d{3,4}", h):
        if len(h) == 3:
            h = "0" + h
        return f"{int(h[:2]):02d}:{int(h[2:]):02d}"
    m = re.match(r'^(\d{1,2})(?::?(\d{1,2}))?$', h)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2) or 0)
        hh = max(0, min(23, hh))
        mm = max(0, min(59, mm))
        return f"{hh:02d}:{mm:02d}"
    # '09:30:00'
    m2 = re.match(r'^(\d{1,2}):(\d{2}):\d{2}$', h)
    if m2:
        return f"{int(m2.group(1)):02d}:{int(m2.group(2)):02d}"
    try:
        return dt.datetime.strptime(h[:5], "%H:%M").strftime("%H:%M")
    except Exception:
        return h

# Acepta '09:30', '9:30', '09h30', '930', '09:30-10:30', '09:30 – 10:30', '09:30:00',
# y objetos time/datetime → '09:30'
_HHMM_RE = re.compile(r'(?:(\d{1,2})[:hH](\d{2}))|(\b\d{3,4}\b)', re.UNICODE)
def _parse_hora_cell(x) -> str:
    if isinstance(x, dt.time):
        return f"{x.hour:02d}:{x.minute:02d}"
    if isinstance(x, dt.datetime):
        return f"{x.hour:02d}:{x.minute:02d}"
    s = str(x or "").strip()
    # primero, si hay patrón HH:MM:SS
    mss = re.match(r'^(\d{1,2}):(\d{2}):\d{2}$', s)
    if mss:
        return f"{int(mss.group(1)):02d}:{int(mss.group(2)):02d}"
    # luego, buscar primera hora válida en el texto
    m = _HHMM_RE.search(s)
    if m:
        if m.group(1) and m.group(2):
            hh = int(m.group(1))
            mm = int(m.group(2))
            return f"{hh:02d}:{mm:02d}"
        if m.group(3):
            raw = m.group(3)
            if len(raw) == 3:
                raw = "0" + raw
            return f"{int(raw[:2]):02d}:{int(raw[2:]):02d}"
    return _norm_hora(s)

# Normaliza fecha: ISO, dd/mm/yyyy, fecha real de Sheets o serial Excel/Sheets
def _norm_fecha_iso(x) -> str:
    if x is None or x == "":
        return ""
    if isinstance(x, (dt.date, dt.datetime)):
        return (x.date() if isinstance(x, dt.datetime) else x).isoformat()
    s = str(x).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", s):
        try:
            d = dt.datetime.strptime(s, "%d/%m/%Y").date()
            return d.isoformat()
        except Exception:
            pass
    try:
        d = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.notna(d):
            return d.date().isoformat()
    except Exception:
        pass
    # Serial Excel/Sheets
    try:
        val = float(s)
        base = dt.date(1899, 12, 30)
        d = base + dt.timedelta(days=int(val))
        return d.isoformat()
    except Exception:
        return s

def hora_mas(h: str, minutos: int) -> str:
    base = _norm_hora(h)
    try:
        t0 = dt.datetime.strptime(base, "%H:%M")
        t1 = t0 + dt.timedelta(minutes=minutos)
        return t1.strftime("%H:%M")
    except Exception:
        return base

# ====== GOOGLE SHEETS ======
import gspread
from gspread.exceptions import WorksheetNotFound, APIError
from google.oauth2.service_account import Credentials

# Usa ambos scopes (Sheets + Drive) en todas las rutas
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

def _gc():
    info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

def _open_sheet():
    gc = _gc()
    # Forzamos ID (mejor que URL)
    sheet_id = (
        st.secrets.get("SHEETS_SPREADSHEET_ID")
        or (st.secrets.get("sheets") or {}).get("sheet_id")
        or None
    )
    if not sheet_id:
        st.error("Falta SHEETS_SPREADSHEET_ID en secrets.")
        st.stop()
    try:
        return gc.open_by_key(sheet_id)
    except gspread.exceptions.APIError as e:
        st.error("No puedo abrir la hoja por ID (Google Sheets).")
        st.code(f"""ID: {sheet_id}
Service account: {st.secrets["gcp_service_account"].get("client_email","<sin_client_email>")}
Excepción: {type(e).__name__}""")
        st.info("Si la hoja está en **Unidad compartida**, añade la service account como **miembro de la Unidad** (no solo del archivo).")
        st.stop()

# ---- Cabeceras esperadas en inscripciones / waitlist ----
_EXPECTED_HEADERS = ["timestamp","fecha_iso","hora","nombre","canasta","equipo","tutor","telefono","email"]

# ====== CARGA CACHEADA (TTL=60s) ======
@st.cache_data(ttl=60, show_spinner=False)
def _load_ws_df_cached(sheet_name: str) -> pd.DataFrame:
    """Lee una pestaña y la normaliza (cacheada). Evita 429."""
    sh = _open_sheet()
    ws = sh.worksheet(sheet_name)
    vals = ws.get_all_values()
    if not vals:
        if sheet_name == "sesiones":
            return pd.DataFrame(columns=["fecha_iso","hora","estado","estado_mini","estado_grande"])
        return pd.DataFrame(columns=_EXPECTED_HEADERS)
    headers = [h.strip() for h in vals[0]]
    rows = vals[1:] if len(vals) > 1 else []
    df = pd.DataFrame(rows, columns=headers) if headers else pd.DataFrame()

    def _ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
        for c in _EXPECTED_HEADERS:
            if c not in df.columns:
                df[c] = ""
        return df

    # Normalizaciones por tipo de hoja
    if sheet_name == "sesiones":
        for c in ["fecha_iso","hora","estado","estado_mini","estado_grande"]:
            if c not in df.columns:
                df[c] = ""
        df["fecha_iso"] = df["fecha_iso"].map(_norm_fecha_iso)
        df["hora"] = df["hora"].map(_parse_hora_cell)
        df["estado"] = df["estado"].replace("", "ABIERTA").str.upper()
        df["estado_mini"] = df["estado_mini"].replace("", "ABIERTA").str.upper()
        df["estado_grande"] = df["estado_grande"].replace("", "ABIERTA").str.upper()
    else:
        df = _ensure_cols(df)
        df["fecha_iso"] = df["fecha_iso"].map(_norm_fecha_iso)
        df["hora"] = df["hora"].map(_parse_hora_cell)
        df["canasta"] = df["canasta"].astype(str).str.strip()
    return df

@st.cache_data(ttl=60, show_spinner=False)
def load_all_data():
    """Carga TODO una vez (sesiones, inscripciones, waitlist)."""
    sh = _open_sheet()
    # Asegura que existe 'sesiones' solo si falta (sin tocar si ya existe)
    try:
        ws = sh.worksheet("sesiones")
        # Si la hoja existe pero es antigua (3 cols), asegura headers de 5 cols
        headers = ws.row_values(1)
        if len(headers) < 5:
            ws.update("A1:E1", [["fecha_iso","hora","estado","estado_mini","estado_grande"]])
    except WorksheetNotFound:
        ws = sh.add_worksheet(title="sesiones", rows=100, cols=5)
        ws.update("A1:E1", [["fecha_iso","hora","estado","estado_mini","estado_grande"]])

    sesiones = _load_ws_df_cached("sesiones")
    try:
        ins = _load_ws_df_cached("inscripciones")
    except WorksheetNotFound:
        ins = pd.DataFrame(columns=_EXPECTED_HEADERS)
    try:
        wl = _load_ws_df_cached("waitlist")
    except WorksheetNotFound:
        wl = pd.DataFrame(columns=_EXPECTED_HEADERS)
    return {"sesiones": sesiones, "ins": ins, "wl": wl}

@st.cache_data(ttl=300, show_spinner=False)
def _load_familias_cached() -> pd.DataFrame:
    sh = _open_sheet()
    ws = _ensure_ws(sh, "familias", FAMILIAS_HEADERS, cols=len(FAMILIAS_HEADERS))
    vals = ws.get_all_values()
    if not vals or len(vals) == 1:
        return pd.DataFrame(columns=FAMILIAS_HEADERS)
    df = pd.DataFrame(vals[1:], columns=[h.strip() for h in vals[0]])
    for c in FAMILIAS_HEADERS:
        if c not in df.columns: df[c] = ""
    df["codigo"] = df["codigo"].astype(str).str.strip()
    return df

@st.cache_data(ttl=300, show_spinner=False)
def _load_hijos_cached() -> pd.DataFrame:
    sh = _open_sheet()
    ws = _ensure_ws(sh, "hijos", HIJOS_HEADERS, cols=len(HIJOS_HEADERS))
    vals = ws.get_all_values()
    if not vals or len(vals) == 1:
        return pd.DataFrame(columns=HIJOS_HEADERS)
    df = pd.DataFrame(vals[1:], columns=[h.strip() for h in vals[0]])
    for c in HIJOS_HEADERS:
        if c not in df.columns: df[c] = ""
    df["codigo"] = df["codigo"].astype(str).str.strip()
    return df

def get_familia_por_codigo(codigo: str) -> dict | None:
    cod = (codigo or "").strip().upper()
    if not cod:
        return None
    df = _load_familias_cached()
    m = df[df["codigo"].str.upper() == cod]
    if m.empty:
        return None
    r = m.iloc[-1].to_dict()
    return {
        "codigo": cod,
        "tutor": to_text(r.get("tutor","")),
        "telefono": to_text(r.get("telefono","")),
        "email": to_text(r.get("email","")),
    }

def get_hijos_por_codigo(codigo: str) -> list[dict]:
    cod = (codigo or "").strip().upper()
    if not cod:
        return []
    df = _load_hijos_cached()
    m = df[df["codigo"].str.upper() == cod]
    if m.empty:
        return []
    return m.to_dict("records")

def upsert_familia_y_hijo(codigo: str | None, tutor: str, telefono: str, email: str,
                          jugador: str, equipo: str, canasta: str) -> str:
    sh = _open_sheet()
    ws_fam = _ensure_ws(sh, "familias", FAMILIAS_HEADERS, cols=len(FAMILIAS_HEADERS))
    ws_hij = _ensure_ws(sh, "hijos", HIJOS_HEADERS, cols=len(HIJOS_HEADERS))
    now = dt.datetime.now().isoformat(timespec="seconds")

    tel = (telefono or "").strip()
    if not tel:
        return codigo or ""

    # 1) Si no hay código, intentamos reutilizar uno por teléfono (si ya existe)
    if not codigo:
        df = _load_familias_cached()
        m = df[df["telefono"].astype(str).str.strip() == tel]
        if not m.empty:
            codigo = to_text(m.iloc[-1].get("codigo","")).strip()

    # 2) Si sigue sin haber, generamos uno nuevo
    if not codigo:
        codigo = _gen_family_code()

    codigo = codigo.strip().upper()

    # 3) Upsert familia (por código)
    rows = _retry_gspread(ws_fam.get_all_values)
    if not rows:
        _retry_gspread(ws_fam.update, "A1:E1", [FAMILIAS_HEADERS])
        rows = _retry_gspread(ws_fam.get_all_values)

    updated = False
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 1 and str(row[0]).strip().upper() == codigo:
            _retry_gspread(ws_fam.update, f"A{i}:E{i}", [[codigo, tutor, tel, email, now]])
            updated = True
            break
    if not updated:
        _retry_gspread(ws_fam.append_row, [codigo, tutor, tel, email, now], value_input_option="USER_ENTERED")

    # 4) Upsert hijo (por código + jugador_norm)
    jugador_norm = _norm_name(jugador)
    rows2 = _retry_gspread(ws_hij.get_all_values)
    if not rows2:
        _retry_gspread(ws_hij.update, "A1:E1", [HIJOS_HEADERS])
        rows2 = _retry_gspread(ws_hij.get_all_values)

    done = False
    for i, row in enumerate(rows2[1:], start=2):
        if len(row) >= 2 and str(row[0]).strip().upper() == codigo and _norm_name(row[1]) == jugador_norm:
            _retry_gspread(ws_hij.update, f"A{i}:E{i}", [[codigo, jugador, equipo, canasta, now]])
            done = True
            break
    if not done:
        _retry_gspread(ws_hij.append_row, [codigo, jugador, equipo, canasta, now], value_input_option="USER_ENTERED")

    # invalidar caches
    _load_familias_cached.clear()
    _load_hijos_cached.clear()
    return codigo

# ===== app.py (2/5) =====
# ====== HELPERS EN MEMORIA ======
def get_sesiones_por_dia_cached() -> dict:
    df = load_all_data()["sesiones"]
    out = {}
    for _, r in df.iterrows():
        f = str(r["fecha_iso"]).strip()
        if not f:
            continue
        item = {
            "fecha_iso": f,
            "hora": _parse_hora_cell(str(r.get("hora","")).strip() or "—"),
            "estado": (str(r.get("estado","ABIERTA")).strip() or "ABIERTA").upper(),
            "estado_mini": (str(r.get("estado_mini","ABIERTA")).strip() or "ABIERTA").upper(),
            "estado_grande": (str(r.get("estado_grande","ABIERTA")).strip() or "ABIERTA").upper(),
        }
        out.setdefault(f, []).append(item)
    return out

def get_sesion_info_mem(fecha_iso: str, hora: str) -> dict:
    df = load_all_data()["sesiones"]
    h = _parse_hora_cell(hora)
    f = _norm_fecha_iso(fecha_iso)
    m = df[(df["fecha_iso"] == f) & (df["hora"] == h)]
    if not m.empty:
        r = m.iloc[0].to_dict()
        return {
            "hora": _parse_hora_cell(r.get("hora","—")),
            "estado": (str(r.get("estado","ABIERTA")) or "ABIERTA").upper(),
            "estado_mini": (str(r.get("estado_mini","ABIERTA")) or "ABIERTA").upper(),
            "estado_grande": (str(r.get("estado_grande","ABIERTA")) or "ABIERTA").upper(),
        }
    return {"hora": h, "estado": "ABIERTA", "estado_mini": "ABIERTA", "estado_grande": "ABIERTA"}

def _inscripciones_mem(fecha_iso: str, hora: str) -> pd.DataFrame:
    dfs = load_all_data()
    f = _norm_fecha_iso(fecha_iso)
    h = _parse_hora_cell(hora)
    ins = dfs["ins"]
    if ins.empty:
        return ins
    return ins[(ins["fecha_iso"] == f) & (ins["hora"] == h)]

def _waitlist_mem(fecha_iso: str, hora: str) -> pd.DataFrame:
    dfs = load_all_data()
    f = _norm_fecha_iso(fecha_iso)
    h = _parse_hora_cell(hora)
    wl = dfs["wl"]
    if wl.empty:
        return wl
    return wl[(wl["fecha_iso"] == f) & (wl["hora"] == h)]

def _match_canasta(valor: str, objetivo: str) -> bool:
    v = (valor or "").strip().lower()
    o = objetivo.strip().lower()
    if o.startswith("mini"):
        return v.startswith("mini")
    if o.startswith("canasta"):
        return v.startswith("canasta")
    return v == o

def get_estado_grupo_mem(fecha_iso: str, hora: str, canasta: str) -> str:
    info = get_sesion_info_mem(fecha_iso, hora)
    # Si global cerrada -> todo cerrado
    if (info.get("estado","ABIERTA") or "ABIERTA").upper() == "CERRADA":
        return "CERRADA"
    # Si el grupo está cerrado -> cerrado
    if _match_canasta(canasta, CATEG_MINI):
        return (info.get("estado_mini","ABIERTA") or "ABIERTA").upper()
    return (info.get("estado_grande","ABIERTA") or "ABIERTA").upper()

def plazas_ocupadas_mem(fecha_iso: str, hora: str, canasta: str) -> int:
    df_ins = _inscripciones_mem(fecha_iso, hora)
    if df_ins.empty:
        return 0
    return sum(1 for _, r in df_ins.iterrows() if _match_canasta(r.get("canasta",""), canasta))

def plazas_libres_mem(fecha_iso: str, hora: str, canasta: str) -> int:
    # Respeta cierre por grupo + global
    if get_estado_grupo_mem(fecha_iso, hora, canasta) == "CERRADA":
        return 0
    return max(0, MAX_POR_CANASTA - plazas_ocupadas_mem(fecha_iso, hora, canasta))

def ya_existe_en_sesion_mem(fecha_iso: str, hora: str, nombre: str) -> str | None:
    nn = _norm_name(nombre)
    for _, r in _inscripciones_mem(fecha_iso, hora).iterrows():
        if _norm_name(r.get("nombre","")) == nn:
            return "inscripciones"
    for _, r in _waitlist_mem(fecha_iso, hora).iterrows():
        if _norm_name(r.get("nombre","")) == nn:
            return "waitlist"
    return None

# ====== ESCRITURAS CON BACKOFF + INVALIDACIÓN DE CACHÉ ======
def _retry_gspread(call, *args, **kwargs):
    last_exc = None
    for i in range(5):
        try:
            return call(*args, **kwargs)
        except APIError as e:
            last_exc = e
            msg = str(e)
            # Backoff ante cuotas o 5xx
            if "429" in msg or "quota" in msg.lower() or "500" in msg or "503" in msg:
                time.sleep(1.5 * (2 ** i))
                continue
            raise
    raise last_exc if last_exc else RuntimeError("Error desconocido en Google Sheets")

def append_row(sheet_name: str, values: list):
    sh = _open_sheet()
    ws = sh.worksheet(sheet_name)
    headers = ws.row_values(1)
    if not headers:
        _retry_gspread(ws.update, "A1:I1", [_EXPECTED_HEADERS])
    _retry_gspread(ws.append_row, values, value_input_option="USER_ENTERED")
    load_all_data.clear()  # invalidar cache para ver el cambio al instante

SESIONES_SHEET = "sesiones"

def upsert_sesion(fecha_iso: str, hora: str, estado: str = "ABIERTA", estado_mini: str = "ABIERTA", estado_grande: str = "ABIERTA"):
    sh = _open_sheet()
    try:
        ws = sh.worksheet(SESIONES_SHEET)
    except WorksheetNotFound:
        ws = sh.add_worksheet(title="sesiones", rows=100, cols=5)
        _retry_gspread(ws.update, "A1:E1", [["fecha_iso","hora","estado","estado_mini","estado_grande"]])

    rows = _retry_gspread(ws.get_all_values)
    if not rows:
        _retry_gspread(ws.update, "A1:E1", [["fecha_iso","hora","estado","estado_mini","estado_grande"]])
        rows = _retry_gspread(ws.get_all_values)

    # Si headers antiguos (3 cols), actualizamos a 5
    if rows and len(rows[0]) < 5:
        _retry_gspread(ws.update, "A1:E1", [["fecha_iso","hora","estado","estado_mini","estado_grande"]])
        rows = _retry_gspread(ws.get_all_values)

    f_iso = _norm_fecha_iso(fecha_iso)
    hora_n = _parse_hora_cell(hora)

    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 2 and _norm_fecha_iso(row[0]) == f_iso and _parse_hora_cell(row[1]) == hora_n:
            _retry_gspread(ws.update, f"A{i}:E{i}", [[f_iso, hora_n, estado.upper(), estado_mini.upper(), estado_grande.upper()]])
            load_all_data.clear()
            return

    _retry_gspread(ws.append_row, [f_iso, hora_n, estado.upper(), estado_mini.upper(), estado_grande.upper()], value_input_option="USER_ENTERED")
    load_all_data.clear()

def delete_sesion(fecha_iso: str, hora: str):
    sh = _open_sheet()
    try:
        ws = sh.worksheet(SESIONES_SHEET)
    except WorksheetNotFound:
        return
    rows = _retry_gspread(ws.get_all_values)
    f_iso = _norm_fecha_iso(fecha_iso)
    hora_n = _parse_hora_cell(hora)
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 2 and _norm_fecha_iso(row[0]) == f_iso and _parse_hora_cell(row[1]) == hora_n:
            _retry_gspread(ws.delete_rows, i)
            load_all_data.clear()
            return

def set_estado_sesion(fecha_iso: str, hora: str, estado: str):
    sh = _open_sheet()
    try:
        ws = sh.worksheet(SESIONES_SHEET)
    except WorksheetNotFound:
        return
    rows = _retry_gspread(ws.get_all_values)
    # headers antiguos -> upgrade
    if rows and len(rows[0]) < 5:
        _retry_gspread(ws.update, "A1:E1", [["fecha_iso","hora","estado","estado_mini","estado_grande"]])
        rows = _retry_gspread(ws.get_all_values)

    f_iso = _norm_fecha_iso(fecha_iso)
    hora_n = _parse_hora_cell(hora)
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 2 and _norm_fecha_iso(row[0]) == f_iso and _parse_hora_cell(row[1]) == hora_n:
            _retry_gspread(ws.update_cell, i, 3, estado.upper())
            load_all_data.clear()
            return

def set_estado_grupo(fecha_iso: str, hora: str, canasta: str, estado: str):
    sh = _open_sheet()
    try:
        ws = sh.worksheet(SESIONES_SHEET)
    except WorksheetNotFound:
        return
    rows = _retry_gspread(ws.get_all_values)
    if not rows:
        return
    # headers antiguos -> upgrade
    if len(rows[0]) < 5:
        _retry_gspread(ws.update, "A1:E1", [["fecha_iso","hora","estado","estado_mini","estado_grande"]])
        rows = _retry_gspread(ws.get_all_values)

    f_iso = _norm_fecha_iso(fecha_iso)
    hora_n = _parse_hora_cell(hora)
    col = 4 if _match_canasta(canasta, CATEG_MINI) else 5  # D mini / E grande
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 2 and _norm_fecha_iso(row[0]) == f_iso and _parse_hora_cell(row[1]) == hora_n:
            _retry_gspread(ws.update_cell, i, col, estado.upper())
            load_all_data.clear()
            return
# ===== app.py (3/5) =====
# ====== PDF: JUSTIFICANTE INDIVIDUAL ======
def crear_justificante_pdf(datos: dict) -> BytesIO:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import cm
    from reportlab.lib import colors as _colors

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    x = 2*cm
    y = height - 2*cm

    status_ok = (datos.get("status") == "ok")
    titulo = "Justificante de inscripción" if status_ok else "Justificante - Lista de espera"

    c.setFont("Helvetica-Bold", 16)
    c.drawString(x, y, titulo)
    y -= 0.8*cm
    c.setFont("Helvetica", 11)
    c.drawString(x, y, f"Sesión: {datos.get('fecha_txt','—')}  ·  Hora: {datos.get('hora','—')}")
    y -= 0.5*cm
    c.drawString(x, y, f"Estado: {'CONFIRMADA' if status_ok else 'LISTA DE ESPERA'}")
    y -= 0.8*cm

    c.setFont("Helvetica", 10)
    for label, value in [
        ("Jugador", datos.get("nombre","—")),
        ("Canasta", datos.get("canasta","—")),
        ("Categoría/Equipo", datos.get("equipo","—")),
        ("Tutor", datos.get("tutor","—")),
        ("Teléfono", datos.get("telefono","—")),
        ("Email", datos.get("email","—")),
    ]:
        c.drawString(x, y, f"{label}:")
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x + 4.2*cm, y, value)
        c.setFont("Helvetica", 10)
        y -= 0.6*cm

    y -= 0.4*cm
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(_colors.grey)
    c.drawString(x, y, "Conserve este justificante como comprobante de su reserva.")
    c.setFillColor(_colors.black)

    # ... después del texto de "Conserve este justificante..."
    y -= 0.6*cm
    family_code = to_text(datos.get("family_code","")).strip()
    if family_code:
        c.setFillColor(_colors.black)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x, y, f"Código de familia (para autorrelleno): {family_code}")

    # ------- Canales de WhatsApp en el PDF -------
    y -= 1*cm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, "Canales de comunicación:")
    y -= 0.6*cm
    c.setFont("Helvetica", 10)

    # Canal general
    if CANAL_GENERAL_URL:
        c.drawString(x, y, "General: ")
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(x + 3*cm, y, CANAL_GENERAL_URL)
        y -= 0.5*cm
        c.setFont("Helvetica", 10)

    # Canal por categoría
    canasta_pdf = (datos.get("canasta", "") or "").lower()

    if "mini" in canasta_pdf and CANAL_MINI_URL:
        c.drawString(x, y, "Minibasket: ")
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(x + 3*cm, y, CANAL_MINI_URL)
        y -= 0.5*cm
        c.setFont("Helvetica", 10)
    elif "canasta" in canasta_pdf and CANAL_GRANDE_URL:
        c.drawString(x, y, "Canasta grande: ")
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(x + 3*cm, y, CANAL_GRANDE_URL)
        y -= 0.5*cm
        c.setFont("Helvetica", 10)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf

# ====== PDF: LISTADOS SESIÓN (INSCRIPCIONES + ESPERA) ======
def crear_pdf_sesion(fecha_iso: str, hora: str) -> BytesIO:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import cm

    d = pd.to_datetime(_norm_fecha_iso(fecha_iso)).date()
    hora = _parse_hora_cell(hora)

    lista = _inscripciones_mem(fecha_iso, hora).to_dict("records")
    wl = _waitlist_mem(fecha_iso, hora).to_dict("records")

    ins_mini = [r for r in lista if _match_canasta(r.get("canasta",""), CATEG_MINI)]
    ins_gran = [r for r in lista if _match_canasta(r.get("canasta",""), CATEG_GRANDE)]

    info_s = get_sesion_info_mem(fecha_iso, hora)
    hora_lbl = info_s.get("hora","—")

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    fecha_txt = d.strftime("%A, %d %B %Y").capitalize()
    y = height - 2*cm
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2*cm, y, f"Tecnificación Baloncesto — {fecha_txt} {hora_lbl}")
    y -= 0.8*cm
    c.setFont("Helvetica", 11)
    c.drawString(2*cm, y, f"Capacidad por categoría: {MAX_POR_CANASTA} | Mini: {len(ins_mini)} | Grande: {len(ins_gran)}")
    y -= 1.0*cm

    def fit_text(text, max_chars=35):
        text = to_text(text)
        return text if len(text) <= max_chars else text[:max_chars-1] + "…"

    left = 2.0*cm
    right = width - 2.0*cm
    line = 0.55*cm
    min_margin = 2.0*cm

    def header(title, y):
        c.setFont("Helvetica-Bold", 12)
        c.drawString(left, y, title)
        y -= 0.6*cm
        c.setFont("Helvetica", 10)
        c.drawString(left, y, "#  Nombre (jugador)  |  Canasta  |  Equipo  |  Tutor  |  Teléfono")
        y -= 0.4*cm
        c.line(left, y, right, y)
        y -= 0.4*cm
        return y

    def draw_list(rows, y, start=1):
        if not rows:
            c.setFont("Helvetica", 10)
            c.drawString(left, y, "— Vacío —")
            return y - 0.6*cm
        for i, r in enumerate(rows, start=start):
            if y < min_margin:
                c.showPage()
                y = height - 2*cm
            c.setFont("Helvetica", 10)
            text = f"{i}. {fit_text(r.get('nombre'))} | {fit_text(r.get('canasta'),18)} | {fit_text(r.get('equipo'),22)} | {fit_text(r.get('tutor'),18)} | {fit_text(r.get('telefono'),12)}"
            c.drawString(left, y, text)
            y -= line
        return y

    # Confirmadas
    y = header("Inscripciones confirmadas — Canasta grande", y)
    y = draw_list([r for r in lista if _match_canasta(r.get("canasta",""), CATEG_GRANDE)], y, start=1)
    y -= 0.6*cm
    y = header("Inscripciones confirmadas — Minibasket", y)
    y = draw_list([r for r in lista if _match_canasta(r.get("canasta",""), CATEG_MINI)], y, start=1)

    # Espera
    y -= 0.8*cm
    y = header("Lista de espera — Canasta grande", y)
    y = draw_list([r for r in wl if _match_canasta(r.get("canasta",""), CATEG_GRANDE)], y, start=1)
    y -= 0.6*cm
    y = header("Lista de espera — Minibasket", y)
    y = draw_list([r for r in wl if _match_canasta(r.get("canasta",""), CATEG_MINI)], y, start=1)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf

# ====== ESTADO ======
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

# ====== ADMIN O USUARIO ======
params = st.query_params
show_admin_login = params.get(ADMIN_QUERY_FLAG, ["0"])
show_admin_login = (isinstance(show_admin_login, list) and (show_admin_login[0] == "1")) or (show_admin_login == "1")
# ===== app.py (4/5) =====
if show_admin_login:
    # ====== SOLO ADMIN ======
    st.title("🛠️ Panel de administración")

    if not st.session_state.is_admin:
        pwd_input = st.text_input("Contraseña de administrador", type="password")
        admin_secret = read_secret("ADMIN_PASS")
        if st.button("Entrar"):
            if admin_secret and pwd_input == admin_secret:
                st.session_state.is_admin = True
                st.success("Acceso concedido. Recargando…")
                st.rerun()
            else:
                st.error("Contraseña incorrecta.")
    else:
        # 🔄 Botón de refresco SOLO visible a admin autenticada (por si se quiere forzar)
        with st.sidebar:
            if st.button("🔄 Refrescar datos (limpiar caché)"):
                st.cache_data.clear()
                load_all_data.clear()
                st.success("Caché limpiada.")

        dfs = load_all_data()
        df_ses_all = dfs["sesiones"].copy()
        
        # Aviso si está vacío, pero NO bloquea el resto del panel
        if df_ses_all.empty:
            st.info("Aún no hay sesiones creadas.")
        
        # ===== Tabla de inscripciones / espera por sesión (solo si hay sesiones) =====
        if not df_ses_all.empty:
            df_ses_listables = df_ses_all[df_ses_all["estado"].isin(["ABIERTA", "CERRADA"])].copy()
        
            if df_ses_listables.empty:
                st.info("No hay sesiones en estado ABIERTA o CERRADA.")
            else:
                try:
                    df_ses_listables["__f"] = pd.to_datetime(df_ses_listables["fecha_iso"])
                    df_ses_listables = df_ses_listables.sort_values(["__f","hora"]).drop(columns="__f")
                except Exception:
                    pass
        
                fechas_horas = list(dict.fromkeys([
                    (r["fecha_iso"], _parse_hora_cell(r["hora"]))
                    for _, r in df_ses_listables.iterrows()
                ]))
        
                opciones = {
                    (f, h): f"{dt.datetime.strptime(f,'%Y-%m-%d').strftime('%d/%m/%Y')}  ·  {h}  ·  GLOBAL: {get_sesion_info_mem(f,h).get('estado','—')} | MINI: {get_sesion_info_mem(f,h).get('estado_mini','—')} | GRANDE: {get_sesion_info_mem(f,h).get('estado_grande','—')}"
                    for (f, h) in fechas_horas
                }
        
                f_h_admin = st.selectbox(
                    "Selecciona sesión (fecha + hora)",
                    options=fechas_horas,
                    format_func=lambda t: opciones.get(t, f"{t[0]} · {t[1]}")
                )
        
                f_sel, h_sel = f_h_admin
                ins_f = _inscripciones_mem(f_sel, h_sel).to_dict("records")
                wl_f = _waitlist_mem(f_sel, h_sel).to_dict("records")
                df_show = pd.DataFrame(ins_f)
                df_wl = pd.DataFrame(wl_f)
        
                st.write("**Inscripciones:**")
                st.dataframe(df_show if not df_show.empty else pd.DataFrame(columns=["—"]), use_container_width=True)
        
                st.write("**Lista de espera:**")
                st.dataframe(df_wl if not df_wl.empty else pd.DataFrame(columns=["—"]), use_container_width=True)
        
                if st.button("🧾 Generar PDF (inscripciones + lista de espera)"):
                    try:
                        pdf = crear_pdf_sesion(f_sel, h_sel)
                        st.download_button(
                            label="Descargar PDF",
                            data=pdf,
                            file_name=f"sesion_{f_sel}_{_parse_hora_cell(h_sel)}.pdf",
                            mime="application/pdf"
                        )
                    except ModuleNotFoundError:
                        st.error("Falta el paquete 'reportlab'. Añádelo a requirements.txt (línea: reportlab).")
        
                st.divider()
                st.subheader("🧾 Justificante individual (Admin)")
                # (tu bloque de justificante individual aquí, tal cual)
        
        # ==========================
        # 🗓️ GESTIÓN DE SESIONES (SIEMPRE VISIBLE)
        # ==========================
        st.divider()
        st.subheader("🗓️ Gestión de sesiones")
        
        # --- 1) AÑADIR SESIÓN (GLOBAL ABIERTA) ---
        with st.form("form_add_sesion_admin", clear_on_submit=True):
            c1, c2 = st.columns([1, 1])
            with c1:
                fecha_nueva = st.date_input("Fecha", value=dt.date.today())
            with c2:
                hora_nueva = st.text_input("Hora (HH:MM)", value="09:30")
        
            submitted = st.form_submit_button("➕ Añadir sesión (GLOBAL ABIERTA)")
            if submitted:
                f_iso = _norm_fecha_iso(fecha_nueva)
                upsert_sesion(
                    f_iso,
                    hora_nueva,
                    estado="ABIERTA",
                    estado_mini="ABIERTA",
                    estado_grande="ABIERTA"
                )
                st.success(f"Sesión {f_iso} {_parse_hora_cell(hora_nueva)} añadida/actualizada (GLOBAL ABIERTA).")
                st.rerun()
        
        # --- Tabla + eliminar sesión (solo si hay sesiones) ---
        df_ses = load_all_data()["sesiones"].copy()
        if df_ses.empty:
            st.info("No hay sesiones creadas todavía.")
        else:
            try:
                df_ses["__f"] = pd.to_datetime(df_ses["fecha_iso"])
                df_ses["hora"] = df_ses["hora"].apply(_parse_hora_cell)
                df_ses = df_ses.sort_values(["__f","hora"]).drop(columns="__f")
            except Exception:
                pass
        
            st.dataframe(df_ses, use_container_width=True)
        
            st.markdown("#### 🗑️ Eliminar sesión")
        
            opciones_ses = [(r["fecha_iso"], _parse_hora_cell(r["hora"])) for _, r in df_ses.iterrows()]
            opciones_ses = list(dict.fromkeys(opciones_ses))
        
            fdel, hdel = st.selectbox(
                "Selecciona sesión a eliminar",
                options=opciones_ses,
                format_func=lambda t: f"{dt.datetime.strptime(t[0],'%Y-%m-%d').strftime('%d/%m/%Y')} · {_parse_hora_cell(t[1])}",
                key="sel_delete_session"
            )
        
            if st.button("🗑️ Eliminar sesión (GLOBAL)", use_container_width=True):
                delete_sesion(fdel, hdel)
                st.warning(f"Sesión {fdel} {hdel} eliminada.")
                st.rerun()
        
        # ==========================
        # ⚡ ACCIÓN RÁPIDA (solo si hay sesiones)
        # ==========================
        st.divider()
        st.subheader("⚡ Acción rápida")
        
        df_ses2 = load_all_data()["sesiones"].copy()
        if df_ses2.empty:
            st.info("No hay sesiones para modificar.")
        else:
            # (tu bloque de acción rápida tal cual)
            try:
                df_ses2["__f"] = pd.to_datetime(df_ses2["fecha_iso"])
                df_ses2["hora"] = df_ses2["hora"].apply(_parse_hora_cell)
                df_ses2 = df_ses2.sort_values(["__f","hora"]).drop(columns="__f")
            except Exception:
                pass
        
            opciones = [(r["fecha_iso"], _parse_hora_cell(r["hora"])) for _, r in df_ses2.iterrows()]
            opciones = list(dict.fromkeys(opciones))
        
            fsel, hsel = st.selectbox(
                "Selecciona sesión",
                options=opciones,
                format_func=lambda t: f"{dt.datetime.strptime(t[0],'%Y-%m-%d').strftime('%d/%m/%Y')} · {_parse_hora_cell(t[1])}",
                key="sel_action_session"
            )
        
            # Estados actuales (para mostrar acciones solo si aplican)
            info = get_sesion_info_mem(fsel, hsel)
            estado_global = (info.get("estado","ABIERTA") or "ABIERTA").upper()
            estado_mini = (info.get("estado_mini","ABIERTA") or "ABIERTA").upper()
            estado_grande = (info.get("estado_grande","ABIERTA") or "ABIERTA").upper()
        
            # Opciones base (siempre disponibles)
            acciones = [
                "— Selecciona —",
                "Cerrar solo Minibasket",
                "Cerrar solo Canasta grande",
                "Cerrar sesión completa (GLOBAL)",
            ]
        
            # Opciones de reabrir SOLO si hace falta
            if estado_global == "CERRADA":
                acciones.append("Reabrir sesión completa (GLOBAL)")
            if estado_mini == "CERRADA":
                acciones.append("Reabrir solo Minibasket")
            if estado_grande == "CERRADA":
                acciones.append("Reabrir solo Canasta grande")
        
            accion = st.selectbox(
                "Elige acción",
                options=acciones,
                index=0,
                key="sel_action"
            )
        
            colA, colB = st.columns([1, 2])
            with colA:
                aplicar = st.button("✅ Aplicar", use_container_width=True)
            with colB:
                st.caption("Cerrar GLOBAL bloquea ambos grupos. Reabrir un grupo pone GLOBAL ABIERTA para que tenga efecto.")
        
            if aplicar:
                if accion == "— Selecciona —":
                    st.warning("Selecciona una acción primero.")
        
                elif accion == "Cerrar solo Minibasket":
                    set_estado_grupo(fsel, hsel, CATEG_MINI, "CERRADA")
                    st.warning("Minibasket CERRADA.")
                    st.rerun()
        
                elif accion == "Cerrar solo Canasta grande":
                    set_estado_grupo(fsel, hsel, CATEG_GRANDE, "CERRADA")
                    st.warning("Canasta grande CERRADA.")
                    st.rerun()
        
                elif accion == "Cerrar sesión completa (GLOBAL)":
                    set_estado_sesion(fsel, hsel, "CERRADA")
                    st.warning("Sesión cerrada (GLOBAL).")
                    st.rerun()
        
                elif accion == "Reabrir sesión completa (GLOBAL)":
                    set_estado_sesion(fsel, hsel, "ABIERTA")
                    st.success("Sesión ABIERTA (GLOBAL).")
                    st.rerun()
        
                elif accion == "Reabrir solo Minibasket":
                    set_estado_sesion(fsel, hsel, "ABIERTA")  # por si global estaba cerrada
                    set_estado_grupo(fsel, hsel, CATEG_MINI, "ABIERTA")
                    st.success("Minibasket ABIERTA.")
                    st.rerun()
        
                elif accion == "Reabrir solo Canasta grande":
                    set_estado_sesion(fsel, hsel, "ABIERTA")
                    set_estado_grupo(fsel, hsel, CATEG_GRANDE, "ABIERTA")
                    st.success("Canasta grande ABIERTA.")
                    st.rerun()
        

# ===== app.py (PANEL USUARIO ACTUALIZADO) =====
else:
    # ====== SOLO USUARIO NORMAL ======
    st.title(APP_TITLE)

    st.markdown("""
**Bienvenid@ a las Tecnificaciones CBC**  
Entrenamientos de alto enfoque en grupos muy reducidos para maximizar el aprendizaje de cada jugador/a.

**Cómo funcionan**  
- Cada sesión se divide en **dos grupos**: **Minibasket** y **Canasta Grande**.  
- **Máximo 4 jugadores por grupo** (hasta 8 por sesión).  
- Trabajo **individualizado** en: manejo de balón, finalizaciones, tiro, lectura de juego, toma de decisiones, fundamentos defensivos y coordinación.
- Sesiones de **1 hora**. 
- **Precio: 20€ (en efectivo el día de la sesión)**
""")

    # 🔔 Canal general en la portada
    if CANAL_GENERAL_URL:
        st.info(
            "📢 **Canal general de Tecnificaciones CBC**\n\n"
            f"[Pulsa aquí para unirte al canal general de WhatsApp]({CANAL_GENERAL_URL})"
        )

    with st.expander("ℹ️ Cómo usar esta web", expanded=False):
        st.markdown("""
1. Revisa el **calendario** y elige una fecha con plazas disponibles.  
2. Selecciona la **Canasta** (Minibasket / Canasta Grande) y tu **Categoría/Equipo**.  
3. Rellena los **datos del jugador y del tutor** y pulsa **Reservar**.  
4. Si la categoría está llena, entrarás **automáticamente en lista de espera***.  
5. Tras una reserva correcta, podrás **descargar tu justificante en PDF**.

\\* Si alguien cancela o hay ajustes, podrás pasar a **plaza confirmada**.
        """)

    st.divider()

    # Refrescar sesiones (agrupadas por día) – en memoria / cacheado
    SESIONES_DIA = get_sesiones_por_dia_cached()
    today = dt.date.today()

    # Días con alguna sesión ABIERTA en el futuro (GLOBAL ABIERTA)
    fechas_disponibles = sorted([
        f for f, sesiones in SESIONES_DIA.items()
        if pd.to_datetime(f).date() >= today and any(s["estado"] == "ABIERTA" for s in sesiones)
    ])

    # Calendario
    fecha_seleccionada = None
    try:
        from streamlit_calendar import calendar

        events = []
        for f, sesiones in SESIONES_DIA.items():
            fecha_dt = pd.to_datetime(f).date()

            # Color agregado por día (estado/ocupación) — usa plazas libres ya respetando cierres por grupo
            if fecha_dt < today:
                color = "#dc3545"
            else:
                any_abierta = any(s["estado"] == "ABIERTA" for s in sesiones)
                if not any_abierta:
                    color = "#fd7e14"
                else:
                    full_all = True
                    any_full = False
                    for s in sesiones:
                        mm = plazas_libres_mem(f, s["hora"], CATEG_MINI)
                        gg = plazas_libres_mem(f, s["hora"], CATEG_GRANDE)
                        if mm > 0 or gg > 0:
                            full_all = False
                        if mm <= 0 or gg <= 0:
                            any_full = True
                    color = "#dc3545" if full_all else "#ffc107" if any_full else "#28a745"

            if fecha_dt != today:
                events.append({"title": "", "start": f, "end": f, "display": "background", "backgroundColor": color})

            for s in sorted(sesiones, key=lambda x: _parse_hora_cell(x["hora"])):
                h_ini = _parse_hora_cell(s["hora"])
                h_fin = hora_mas(h_ini, 60)
                label = f"{h_ini}–{h_fin}"
                events.append({"title": label, "start": f, "end": f, "display": "auto"})

        custom_css = """
        .fc-daygrid-day.fc-day-today { background-color: transparent !important; }
        .fc-daygrid-day.fc-day-today .fc-daygrid-day-number {
            border: 2px solid navy;
            border-radius: 50%;
            padding: 2px 6px;
            background-color: #ffffff;
            color: navy !important;
            font-weight: bold;
        }
        .fc-toolbar-title::first-letter { text-transform: uppercase; }
        """

        cal = calendar(
            events=events,
            options={"initialView": "dayGridMonth", "height": 600, "locale": "es", "firstDay": 1},
            custom_css=custom_css,
            key="cal_user",
        )

        if cal and cal.get("clickedEvent"):
            fclicked = cal["clickedEvent"].get("start")[:10]
            if fclicked in SESIONES_DIA and pd.to_datetime(fclicked).date() >= today:
                if any(s["estado"] == "ABIERTA" for s in SESIONES_DIA.get(fclicked, [])):
                    fecha_seleccionada = fclicked
    except Exception:
        pass

    st.caption("🟥 Pasada/sin plazas · 🟧 Cerrada · 🟨 Una categoría llena · 🟩 Plazas en ambas")

    # Select de fechas abiertas
    if not fecha_seleccionada:
        st.subheader("📅 Selecciona fecha")
        if fechas_disponibles:
            etiqueta = {f: f"{pd.to_datetime(f).strftime('%d/%m/%Y')}" for f in fechas_disponibles}
            fecha_seleccionada = st.selectbox(
                "Fechas con sesión",
                options=fechas_disponibles,
                format_func=lambda f: etiqueta[f],
                key="sel_fecha_user"
            )
        else:
            st.info("De momento no hay fechas futuras disponibles.")
            st.stop()

    # Selector de HORA para la fecha elegida (GLOBAL ABIERTA)
    sesiones_del_dia = [s for s in SESIONES_DIA.get(fecha_seleccionada, []) if s["estado"] == "ABIERTA"]
    if not sesiones_del_dia:
        st.warning("Ese día no tiene sesiones abiertas.")
        st.stop()

    horas_ops = sorted({_parse_hora_cell(s["hora"]) for s in sesiones_del_dia})
    hora_seleccionada = st.selectbox("⏰ Elige la hora", options=horas_ops, key="sel_hora_user")

    # Bloque de reserva para la sesión (fecha+hora)
    fkey = _norm_fecha_iso(fecha_seleccionada)
    hkey = _parse_hora_cell(hora_seleccionada)
    info_s = get_sesion_info_mem(fkey, hkey)
    hora_sesion = info_s.get("hora", "—")
    estado_sesion = info_s.get("estado", "ABIERTA").upper()

    st.write(f"### Sesión del **{pd.to_datetime(fkey).strftime('%d/%m/%Y')}** de **{hora_sesion} a {hora_mas(hora_sesion, 60)}**")

    if estado_sesion == "CERRADA":
        st.warning("Esta sesión está **CERRADA**: no admite más reservas en ninguna categoría.")
        st.stop()

    lvl_m, txt_m = texto_estado_grupo(fkey, hkey, CATEG_MINI)
    lvl_g, txt_g = texto_estado_grupo(fkey, hkey, CATEG_GRANDE)

    getattr(st, lvl_m)(f"**{CATEG_MINI}:** {txt_m}")
    getattr(st, lvl_g)(f"**{CATEG_GRANDE}:** {txt_g}")

    with st.expander("ℹ️ **IMPORTANTE para confirmar la reserva**", expanded=False):
        st.markdown("""
Si **después de pulsar “Reservar”** no aparece el botón **“⬇️ Descargar justificante (PDF)”**, la **reserva NO se ha completado**.  
Revisa los campos obligatorios o vuelve a intentarlo.  
*(En **lista de espera** también se genera justificante, identificado como “Lista de espera”.)*
        """)

    # =========== Formulario + Tarjeta de éxito ===========
    placeholder = st.empty()
    ok_flag = f"ok_{fkey}_{hkey}"
    ok_data_key = f"ok_data_{fkey}_{hkey}"
    celebrate_key = f"celebrate_{fkey}_{hkey}"

    # ------------------------------------------------------------------
    # ✅ 1) TARJETA DE ÉXITO (si ya reservó)
    # ------------------------------------------------------------------
    if st.session_state.get(ok_flag):
        data = st.session_state.get(ok_data_key, {})

        with placeholder.container():
            if data.get("status") == "ok":
                st.success("✅ Inscripción realizada correctamente")
            else:
                st.info("ℹ️ Te hemos añadido a la lista de espera")

            if data.get("family_code"):
                st.info(
                    f"🔐 **Tu código de familia:** `{data.get('family_code')}`\n\n"
                    "Guárdalo: te servirá para autorrellenar próximas veces."
                )

            canasta_data = (data.get("canasta", "") or "").lower()
            if "mini" in canasta_data and CANAL_MINI_URL:
                st.info(
                    "🏀 **Canal exclusivo de MINIBASKET**\n"
                    f"[Únete aquí para recibir avisos y la encuesta de esta categoría]({CANAL_MINI_URL})"
                )
            elif "canasta" in canasta_data and CANAL_GRANDE_URL:
                st.info(
                    "⛹️ **Canal exclusivo de CANASTA GRANDE**\n"
                    f"[Únete aquí para recibir avisos y la encuesta de esta categoría]({CANAL_GRANDE_URL})"
                )

            st.markdown("#### Resumen")
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Jugador:** {data.get('nombre','—')}")
                st.write(f"**Canasta:** {data.get('canasta','—')}")
                st.write(f"**Categoría/Equipo:** {data.get('equipo','—')}")
            with col2:
                st.write(f"**Tutor:** {data.get('tutor','—')}")
                st.write(f"**Tel.:** {data.get('telefono','—')}")
                st.write(f"**Email:** {data.get('email','—')}")

            st.divider()
            pdf = crear_justificante_pdf(data)
            st.download_button(
                label="⬇️ Descargar justificante (PDF)",
                data=pdf,
                file_name=(
                    f"justificante_{data.get('fecha_iso','')}_"
                    f"{_norm_name(data.get('nombre','')).replace(' ','_')}_"
                    f"{_parse_hora_cell(data.get('hora','')).replace(':','')}.pdf"
                ),
                mime="application/pdf",
                key=f"dl_btn_{fkey}_{hkey}"
            )

            if st.button("Hacer otra reserva", key=f"otra_{fkey}_{hkey}"):
                st.session_state.pop(ok_flag, None)
                st.session_state.pop(ok_data_key, None)
                st.session_state.pop(f"hijos_{fkey}_{hkey}", None)
                st.rerun()

        # ✅ 2) CELEBRACIÓN
        if st.session_state.pop(celebrate_key, False) and data.get("status") == "ok":
            st.toast("✅ Inscripción realizada correctamente", icon="✅")
            st.balloons()

    # ------------------------------------------------------------------
    # ✅ 3) PESTAÑAS (si NO hay ok_flag)
    # ------------------------------------------------------------------
    else:
        # ✅ IMPORTANTE: esto debe estar FUERA de las tabs (lo usan ambas pestañas)
        codigo_cookie = (cookies.get("family_code") or "").strip()

        # ✅ Orden dinámico: por defecto MANUAL, salvo si hay cookie -> AUTO primero
        if codigo_cookie:
            tab_auto, tab_manual = st.tabs(["🔐 Autorrellenar con código", "✍️ Rellenar manualmente"])
        else:
            tab_manual, tab_auto = st.tabs(["✍️ Rellenar manualmente", "🔐 Autorrellenar con código"])

        
        # ==========================================================
        # TAB 1: AUTORELLENAR + RESERVA RÁPIDA
        # ==========================================================
        with tab_auto:
            st.markdown("### 🔐 Autorrellenar")
            codigo_familia = st.text_input(
                "Código de familia",
                value=codigo_cookie,
                key=f"family_code_{fkey}_{hkey}",
                placeholder="Ej: CBC-7F3KQ9P2..."
            )
        
            # ✅ define esto ANTES de usarlo
            hijos_cargados = st.session_state.get(f"hijos_{fkey}_{hkey}", [])
            fam_valida_o_hijos_cargados = bool(hijos_cargados)  # lo que realmente quieres controlar
            # (si quieres también considerar "código escrito", puedes usar: bool(codigo_familia.strip()) )
        
            col_use, col_forget = st.columns([3, 1], vertical_alignment="center")
        
            with col_use:
                # Mostrar checkbox solo si NO hay cookie guardada y ya hay datos cargados (o lo que tú decidas)
                mostrar_recordar = (not bool(codigo_cookie)) and bool(fam_valida_o_hijos_cargados)
                if mostrar_recordar:
                    recordar_dispositivo = st.checkbox("Guardar este código en este dispositivo", value=False)
                else:
                    recordar_dispositivo = False
        
                # Normaliza
                cookie_norm = (codigo_cookie or "").strip().upper()
                input_norm  = (codigo_familia or "").strip().upper()
                
                # Mostrar "Usar este código" solo cuando:
                # - NO hay cookie, o
                # - el usuario ha escrito un código distinto al guardado (y no está vacío)
                show_usar = (not cookie_norm) or (input_norm and input_norm != cookie_norm)
                
                # (opcional) Mensajito si hay cookie y no se está intentando cambiar
                if cookie_norm and (not input_norm or input_norm == cookie_norm):
                    st.caption("✅ Ya estás usando el código guardado en este dispositivo.")
                
                if show_usar:
                    if st.button(
                        "Usar este código",
                        key=f"autofill_btn_{fkey}_{hkey}",
                        use_container_width=True
                    ):
                        fam = get_familia_por_codigo(codigo_familia)
                        if not fam:
                            st.error("Código no válido (o no encontrado).")
                        else:
                            hijos = get_hijos_por_codigo(fam["codigo"])
                            st.session_state[f"padre_{fkey}_{hkey}"] = fam.get("tutor", "")
                            st.session_state[f"telefono_{fkey}_{hkey}"] = fam.get("telefono", "")
                            st.session_state[f"email_{fkey}_{hkey}"] = fam.get("email", "")
                            st.session_state[f"hijos_{fkey}_{hkey}"] = hijos or []
                
                            st.success("Datos cargados.")
                            st.rerun()

            with col_forget:
                if codigo_cookie:
                    st.markdown(
                        """
                        <style>
                        .forget-link {
                            text-align: right;
                            margin-top: 34px; /* alinea verticalmente con el botón */
                        }
                        .forget-link button {
                            background: none !important;
                            border: none !important;
                            padding: 0 !important;
                            margin: 0 !important;
                            color: #1f77b4 !important;
                            text-decoration: underline;
                            font-size: 0.85rem;
                            font-weight: 400;
                            cursor: pointer;
                            box-shadow: none !important;
                        }
                        .forget-link button:hover {
                            opacity: 0.8;
                        }
                        </style>
                        """,
                        unsafe_allow_html=True
                    )
        
                    st.markdown("<div class='forget-link'>", unsafe_allow_html=True)
                    if st.button(
                        "Olvidar este código",
                        key=f"forget_{fkey}_{hkey}",
                        help="Eliminar el código guardado en este dispositivo"
                    ):
                        cookies["family_code"] = ""
                        cookies.save()
                        st.session_state.pop(f"hijos_{fkey}_{hkey}", None)
                        st.session_state.pop(f"autofilled_{fkey}_{hkey}", None)
                        st.success("Código eliminado de este dispositivo.")
                        st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)
            # Autocarga si ya hay cookie (sin pulsar botón)
            if codigo_cookie and not st.session_state.get(f"autofilled_{fkey}_{hkey}", False):
                fam = get_familia_por_codigo(codigo_cookie)
                if fam:
                    hijos = get_hijos_por_codigo(codigo_cookie)
                    st.session_state[f"padre_{fkey}_{hkey}"] = fam.get("tutor", "")
                    st.session_state[f"telefono_{fkey}_{hkey}"] = fam.get("telefono", "")
                    st.session_state[f"email_{fkey}_{hkey}"] = fam.get("email", "")
                    st.session_state[f"hijos_{fkey}_{hkey}"] = hijos or []
                    st.session_state[f"autofilled_{fkey}_{hkey}"] = True
        

            # ==========================
            # ⚡ RESERVA RÁPIDA
            # ==========================
            hijos_cargados = st.session_state.get(f"hijos_{fkey}_{hkey}", [])
            if hijos_cargados:
                def _fmt_h(r):
                    return f"{to_text(r.get('jugador','—'))} · {to_text(r.get('equipo','—'))} · {to_text(r.get('canasta','—'))}"

                sel_h = st.selectbox(
                    "Selecciona jugador guardado",
                    options=hijos_cargados,
                    format_func=_fmt_h,
                    key=f"selh_{fkey}_{hkey}"
                )

                if st.button("⚡ Reservar con este jugador", key=f"reserveh_{fkey}_{hkey}", use_container_width=True):
                    nombre_h = to_text(sel_h.get("jugador", "")).strip()
                    equipo_h = to_text(sel_h.get("equipo", "")).strip()
                    canasta_h = to_text(sel_h.get("canasta", "")).strip()

                    # --- Datos tutor (de session_state ya autorrellenados por el código) ---
                    tutor_h = to_text(st.session_state.get(f"padre_{fkey}_{hkey}", "")).strip() or "—"
                    telefono_h = to_text(st.session_state.get(f"telefono_{fkey}_{hkey}", "")).strip()
                    email_h = to_text(st.session_state.get(f"email_{fkey}_{hkey}", "")).strip() or "—"

                    if not nombre_h:
                        st.error("No se pudo leer el nombre del jugador guardado.")
                        st.stop()

                    if not telefono_h or (not str(telefono_h).isdigit()):
                        st.error("Falta un teléfono válido guardado para esta familia. Pulsa 'Autorrellenar con código' y revisa los datos.")
                        st.stop()

                    canasta_h_low = canasta_h.lower()
                    if "mini" in canasta_h_low:
                        canasta_final = CATEG_MINI
                    elif "canasta" in canasta_h_low or "grande" in canasta_h_low:
                        canasta_final = CATEG_GRANDE
                    else:
                        st.error("El jugador guardado no tiene canasta válida (Minibasket / Canasta grande).")
                        st.stop()

                    info_tmp = get_sesion_info_mem(fkey, hkey)
                    estado_global = (info_tmp.get("estado", "ABIERTA") or "ABIERTA").upper()
                    if estado_global == "CERRADA":
                        st.error("Esta sesión está CERRADA (GLOBAL).")
                        st.stop()

                    if get_estado_grupo_mem(fkey, hkey, canasta_final) == "CERRADA":
                        st.error(f"{canasta_final} está CERRADA para esta sesión. Reserva desde el formulario eligiendo la otra canasta.")
                        st.stop()

                    ya = ya_existe_en_sesion_mem(fkey, hkey, nombre_h)
                    if ya == "inscripciones":
                        st.error("❌ Este jugador ya está inscrito en esta sesión.")
                        st.stop()
                    if ya == "waitlist":
                        st.warning("ℹ️ Este jugador ya está en lista de espera para esta sesión.")
                        st.stop()
                    
                    equipo_val = equipo_h or "—"
                    # ✅ Si el usuario marcó "Recordar", guardamos el código SOLO ahora (al reservar)
                    # Preferimos el código del input si está, si no el cookie actual, y si no el del padre cargado
                    cod_para_recordar = (codigo_familia or "").strip() or codigo_cookie
                    cod_para_recordar = cod_para_recordar.upper().strip()
                    
                    if recordar_dispositivo and cod_para_recordar:
                        cookies["family_code"] = cod_para_recordar
                        cookies.save()
                    
                    row = [
                        dt.datetime.now().isoformat(timespec="seconds"),
                        fkey, hora_sesion, nombre_h, canasta_final,
                        equipo_val, tutor_h, telefono_h, email_h
                    ]
                    

                    libres_cat = plazas_libres_mem(fkey, hkey, canasta_final)
                    if libres_cat <= 0:
                        append_row("waitlist", row)
                        st.session_state[ok_flag] = True
                        st.session_state[ok_data_key] = {
                            "status": "wait",
                            "fecha_iso": fkey,
                            "fecha_txt": pd.to_datetime(fkey).strftime("%d/%m/%Y"),
                            "hora": hora_sesion,
                            "nombre": nombre_h,
                            "canasta": canasta_final,
                            "equipo": equipo_val,
                            "tutor": tutor_h,
                            "telefono": telefono_h,
                            "email": email_h,
                        }
                        st.rerun()
                    else:
                        append_row("inscripciones", row)
                        st.session_state[ok_flag] = True
                        st.session_state[ok_data_key] = {
                            "status": "ok",
                            "fecha_iso": fkey,
                            "fecha_txt": pd.to_datetime(fkey).strftime("%d/%m/%Y"),
                            "hora": hora_sesion,
                            "nombre": nombre_h,
                            "canasta": canasta_final,
                            "equipo": equipo_val,
                            "tutor": tutor_h,
                            "telefono": telefono_h,
                            "email": email_h,
                        }
                        st.session_state[celebrate_key] = True
                        st.rerun()
            else:
                st.info("Si tienes un código válido, usa 'Usar este código' para ver tus jugadores guardados.")

        # ==========================================================
        # TAB 2: FORMULARIO MANUAL
        # ==========================================================
        with tab_manual:
            # ✅ CLAVE: NO uses placeholder.form aquí
            with st.form(f"form_{fkey}_{hkey}", clear_on_submit=False):
                st.write("📝 Información del jugador")
                nombre = st.text_input("Nombre y apellidos del jugador", key=f"nombre_{fkey}_{hkey}")

                opciones_canasta = []
                if get_estado_grupo_mem(fkey, hkey, CATEG_MINI) == "ABIERTA":
                    opciones_canasta.append(CATEG_MINI)
                if get_estado_grupo_mem(fkey, hkey, CATEG_GRANDE) == "ABIERTA":
                    opciones_canasta.append(CATEG_GRANDE)

                canasta = st.radio("Canasta", opciones_canasta, key=f"canasta_{fkey}_{hkey}")
                err_canasta = st.empty()

                if canasta == CATEG_MINI:
                    st.caption("ℹ️ Para **Minibasket** solo se permiten categorías **Benjamín** y **Alevín**.")
                elif canasta == CATEG_GRANDE:
                    st.caption("ℹ️ Para **Canasta grande** solo se permiten categorías **Infantil**, **Cadete** y **Junior**.")

                equipo_sel = st.selectbox("Categoría / Equipo", EQUIPOS_OPCIONES, index=0, key=f"equipo_sel_{fkey}_{hkey}")
                equipo_otro = st.text_input("Especifica la categoría/equipo", key=f"equipo_otro_{fkey}_{hkey}") if equipo_sel == "Otro" else ""

                if equipo_sel and equipo_sel not in ("— Selecciona —", "Otro"):
                    equipo_val = equipo_sel
                else:
                    equipo_val = (equipo_otro or "").strip()

                err_equipo = st.empty()

                padre = st.text_input("Nombre del padre/madre/tutor", key=f"padre_{fkey}_{hkey}")

                telefono = st.text_input(
                    "Teléfono de contacto del tutor (solo números)",
                    key=f"telefono_{fkey}_{hkey}",
                    max_chars=9,
                    placeholder="Ej: 612345678"
                )
                err_telefono = st.empty()

                email = st.text_input("Email", key=f"email_{fkey}_{hkey}")

                st.caption("Tras pulsar **Reservar**, debe aparecer el botón **“⬇️ Descargar justificante (PDF)”**. Si no aparece, la reserva no se ha completado.")
                guardar_familia = st.checkbox(
                    "💾 Guardar estos datos para próximas reservas (con código de familia)",
                    value=True,
                    key=f"savefam_{fkey}_{hkey}"
                )

                enviar = st.form_submit_button("Reservar")

                if enviar:
                    err_canasta.empty()
                    err_equipo.empty()
                    err_telefono.empty()

                    hay_error = False

                    if not nombre:
                        st.error("Por favor, rellena el **nombre del jugador**.")
                        hay_error = True

                    if not telefono:
                        err_telefono.error("El teléfono es obligatorio.")
                        hay_error = True
                    elif not telefono.isdigit():
                        err_telefono.error("El teléfono solo puede contener números (sin espacios ni guiones).")
                        hay_error = True

                    if not equipo_val:
                        err_equipo.error("La categoría/equipo es obligatoria.")
                        hay_error = True
                    else:
                        ev = equipo_val.lower()
                        if canasta == CATEG_MINI and equipo_sel != "Otro":
                            if not (ev.startswith("benjamín") or ev.startswith("benjamin") or ev.startswith("alevín") or ev.startswith("alevin")):
                                err_canasta.error("Para Minibasket solo se permiten categorías Benjamín o Alevín.")
                                hay_error = True
                        if canasta == CATEG_GRANDE and equipo_sel != "Otro":
                            if not (ev.startswith("infantil") or ev.startswith("cadete") or ev.startswith("junior")):
                                err_canasta.error("Para Canasta grande solo se permiten Infantil, Cadete o Junior.")
                                hay_error = True

                    if get_estado_grupo_mem(fkey, hkey, canasta) == "CERRADA":
                        err_canasta.error(f"⚠️ {canasta} está **CERRADA** para esta sesión. Elige la otra canasta.")
                        hay_error = True

                    if not hay_error:
                        ya = ya_existe_en_sesion_mem(fkey, hkey, nombre)
                        if ya == "inscripciones":
                            st.error("❌ Este jugador ya está inscrito en esta sesión.")
                        elif ya == "waitlist":
                            st.warning("ℹ️ Este jugador ya está en lista de espera para esta sesión.")
                        else:
                            libres_cat = plazas_libres_mem(fkey, hkey, canasta)

                            row = [
                                dt.datetime.now().isoformat(timespec="seconds"),
                                fkey, hora_sesion, nombre, canasta,
                                (equipo_val or ""), (padre or ""), telefono, (email or "")
                            ]

                            family_code = ""
                            if guardar_familia:
                                cod_in = codigo_cookie.strip() if codigo_cookie else ""
                                family_code = upsert_familia_y_hijo(
                                    cod_in if cod_in else None,
                                    (padre or ""), telefono, (email or ""),
                                    nombre, (equipo_val or ""), canasta
                                )
                                if family_code:
                                    cookies["family_code"] = family_code
                                    cookies.save()

                            if libres_cat <= 0:
                                append_row("waitlist", row)
                                st.session_state[ok_flag] = True
                                st.session_state[ok_data_key] = {
                                    "status": "wait",
                                    "fecha_iso": fkey,
                                    "fecha_txt": pd.to_datetime(fkey).strftime("%d/%m/%Y"),
                                    "hora": hora_sesion,
                                    "nombre": nombre,
                                    "canasta": canasta,
                                    "equipo": (equipo_val or "—"),
                                    "tutor": (padre or "—"),
                                    "telefono": telefono,
                                    "email": (email or "—"),
                                    "family_code": family_code,
                                }
                                st.rerun()
                            else:
                                append_row("inscripciones", row)
                                st.session_state[ok_flag] = True
                                st.session_state[ok_data_key] = {
                                    "status": "ok",
                                    "fecha_iso": fkey,
                                    "fecha_txt": pd.to_datetime(fkey).strftime("%d/%m/%Y"),
                                    "hora": hora_sesion,
                                    "nombre": nombre,
                                    "canasta": canasta,
                                    "equipo": (equipo_val or "—"),
                                    "tutor": (padre or "—"),
                                    "telefono": telefono,
                                    "email": (email or "—"),
                                    "family_code": family_code,
                                }
                                st.session_state[celebrate_key] = True
                                st.rerun()
