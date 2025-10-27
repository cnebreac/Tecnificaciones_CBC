import streamlit as st
import pandas as pd
from io import BytesIO
import datetime as dt
import os
import re

# ====== AJUSTES GENERALES ======
st.set_page_config(page_title="Tecnificaciones CBC ", layout="centered")
APP_TITLE = "🏀 Tecnificaciones CBC - Reserva de Sesiones"
ADMIN_QUERY_FLAG = "admin"

# Capacidad por categoría
MAX_POR_CANASTA = 4
CATEG_MINI = "Minibasket"
CATEG_GRANDE = "Canasta grande"

EQUIPOS_OPCIONES = [
    "— Selecciona —",
    "Escuela 1ºaño 2019",
    "Escuela 2ºaño 2018",
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
    "Otro",
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

def _norm_hora(h: str) -> str:
    h = (h or "").strip()
    if not h:
        return "—"
    m = re.match(r'^(\d{1,2})(?::?(\d{1,2}))?$', h)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2) or 0)
        hh = max(0, min(23, hh))
        mm = max(0, min(59, mm))
        return f"{hh:02d}:{mm:02d}"
    try:
        return dt.datetime.strptime(h[:5], "%H:%M").strftime("%H:%M")
    except Exception:
        return h

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
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def _gc():
    info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

def _open_sheet():
    gc = _gc()
    url = st.secrets.get("SHEETS_SPREADSHEET_URL")
    sid = st.secrets.get("SHEETS_SPREADSHEET_ID") or (st.secrets.get("sheets") or {}).get("sheet_id")
    if url:
        return gc.open_by_url(url)
    elif sid:
        return gc.open_by_key(sid)
    else:
        st.error("Falta SHEETS_SPREADSHEET_URL o SHEETS_SPREADSHEET_ID en secrets.")
        st.stop()

@st.cache_data(ttl=15)
def load_df(sheet_name: str) -> pd.DataFrame:
    sh = _open_sheet()
    ws = sh.worksheet(sheet_name)
    data = ws.get_all_records()
    return pd.DataFrame(data)

def append_row(sheet_name: str, values: list):
    sh = _open_sheet()
    ws = sh.worksheet(sheet_name)
    ws.append_row(values, value_input_option="USER_ENTERED")

# ====== SESIONES ======
SESIONES_SHEET = "sesiones"

def _ensure_ws_sesiones():
    sh = _open_sheet()
    try:
        ws = sh.worksheet(SESIONES_SHEET)
        headers = ws.row_values(1)
        needed = ["fecha_iso", "hora", "estado"]
        if headers != needed:
            ws.resize(rows=max(2, len(ws.get_all_values())), cols=3)
            ws.update("A1:C1", [needed])
    except Exception:
        ws = sh.add_worksheet(title=SESIONES_SHEET, rows=100, cols=3)
        ws.update("A1:C1", [["fecha_iso", "hora", "estado"]])
    return ws

@st.cache_data(ttl=15)
def load_sesiones_df():
    ws = _ensure_ws_sesiones()
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    if df.empty:
        df = pd.DataFrame(columns=["fecha_iso", "hora", "estado"])
    for c in ["fecha_iso", "hora", "estado"]:
        if c not in df.columns:
            df[c] = ""
    df["hora"] = df["hora"].apply(_norm_hora)
    df["estado"] = df["estado"].replace("", "ABIERTA").str.upper()
    return df

def get_sesiones_por_dia():
    df = load_sesiones_df()
    out = {}
    for _, r in df.iterrows():
        f = str(r["fecha_iso"]).strip()
        if not f:
            continue
        item = {
            "fecha_iso": f,
            "hora": _norm_hora(str(r.get("hora", ""))),
            "estado": (str(r.get("estado", "ABIERTA")).strip() or "ABIERTA").upper(),
        }
        out.setdefault(f, []).append(item)
    return out

def get_sesion_info(fecha_iso: str, hora: str):
    hora = _norm_hora(hora)
    df = load_sesiones_df()
    if not df.empty:
        m = df[(df["fecha_iso"] == fecha_iso) & (df["hora"] == hora)]
        if not m.empty:
            r = m.iloc[0].to_dict()
            return {"hora": r.get("hora", "—"), "estado": r.get("estado", "ABIERTA")}
    return {"hora": hora, "estado": "ABIERTA"}

def upsert_sesion(fecha_iso, hora, estado="ABIERTA"):
    ws = _ensure_ws_sesiones()
    rows = ws.get_all_values()
    if not rows:
        ws.update("A1:C1", [["fecha_iso", "hora", "estado"]])
        rows = ws.get_all_values()
    hora = _norm_hora(hora)
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 2 and row[0].strip() == fecha_iso and _norm_hora(row[1]) == hora:
            ws.update(f"A{i}:C{i}", [[fecha_iso, hora, estado.upper()]])
            return
    ws.append_row([fecha_iso, hora, estado.upper()], value_input_option="USER_ENTERED")

def delete_sesion(fecha_iso, hora):
    ws = _ensure_ws_sesiones()
    rows = ws.get_all_values()
    hora = _norm_hora(hora)
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 2 and row[0].strip() == fecha_iso and _norm_hora(row[1]) == hora:
            ws.delete_rows(i)
            return

def set_estado_sesion(fecha_iso, hora, estado):
    ws = _ensure_ws_sesiones()
    rows = ws.get_all_values()
    hora = _norm_hora(hora)
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 2 and row[0].strip() == fecha_iso and _norm_hora(row[1]) == hora:
            ws.update_cell(i, 3, estado.upper())
            return

# ====== INSCRIPCIONES Y WAITLIST ======
def get_inscripciones_por_sesion(fecha_iso, hora):
    df = load_df("inscripciones")
    if df.empty:
        return []
    df["hora"] = df["hora"].apply(_norm_hora)
    hora = _norm_hora(hora)
    return df[(df["fecha_iso"] == fecha_iso) & (df["hora"] == hora)].to_dict("records")

def get_waitlist_por_sesion(fecha_iso, hora):
    df = load_df("waitlist")
    if df.empty:
        return []
    df["hora"] = df["hora"].apply(_norm_hora)
    hora = _norm_hora(hora)
    return df[(df["fecha_iso"] == fecha_iso) & (df["hora"] == hora)].to_dict("records")

def _match_canasta(valor, objetivo):
    v = (valor or "").strip().lower()
    o = objetivo.strip().lower()
    if o.startswith("mini"):
        return v.startswith("mini")
    if o.startswith("canasta"):
        return v.startswith("canasta")
    return v == o

def plazas_ocupadas(fecha_iso, hora, canasta):
    ins = get_inscripciones_por_sesion(fecha_iso, hora)
    return sum(1 for r in ins if _match_canasta(r.get("canasta", ""), canasta))

def plazas_libres(fecha_iso, hora, canasta):
    if get_sesion_info(fecha_iso, hora).get("estado", "ABIERTA").upper() == "CERRADA":
        return 0
    return max(0, MAX_POR_CANASTA - plazas_ocupadas(fecha_iso, hora, canasta))

def ya_existe_en_sesion(fecha_iso, hora, nombre):
    nn = _norm_name(nombre)
    for r in get_inscripciones_por_sesion(fecha_iso, hora):
        if _norm_name(r.get("nombre", "")) == nn:
            return "inscripciones"
    for r in get_waitlist_por_sesion(fecha_iso, hora):
        if _norm_name(r.get("nombre", "")) == nn:
            return "waitlist"
    return None

# ====== PDF JUSTIFICANTE ======
def crear_justificante_pdf(datos):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import cm
    from reportlab.lib import colors

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    x = 2*cm
    y = height - 2*cm

    status_ok = datos.get("status") == "ok"
    titulo = "Justificante de inscripción" if status_ok else "Justificante - Lista de espera"
    c.setFont("Helvetica-Bold", 16)
    c.drawString(x, y, titulo)
    y -= 0.8*cm
    c.setFont("Helvetica", 11)
    c.drawString(x, y, f"Sesión: {datos.get('fecha_txt')}  ·  Hora: {datos.get('hora')}")
    y -= 0.5*cm
    c.drawString(x, y, f"Estado: {'CONFIRMADA' if status_ok else 'LISTA DE ESPERA'}")
    y -= 0.8*cm
    c.setFont("Helvetica", 10)
    for label, value in [
        ("Jugador", datos.get("nombre")),
        ("Canasta", datos.get("canasta")),
        ("Categoría/Equipo", datos.get("equipo")),
        ("Tutor", datos.get("tutor")),
        ("Teléfono", datos.get("telefono")),
        ("Email", datos.get("email")),
    ]:
        c.drawString(x, y, f"{label}:")
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x + 4.2*cm, y, value)
        c.setFont("Helvetica", 10)
        y -= 0.6*cm
    y -= 0.4*cm
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(colors.grey)
    c.drawString(x, y, "Conserve este justificante como comprobante de su reserva.")
    c.showPage()
    c.save()
    buf.seek(0)
    return buf

# ====== ESTADO ADMIN ======
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

# ====== MODO ADMIN ======
params = st.query_params
show_admin_login = params.get(ADMIN_QUERY_FLAG, ["0"])
show_admin_login = (isinstance(show_admin_login, list) and (show_admin_login[0] == "1")) or (show_admin_login == "1")

# === ADMIN ===
if show_admin_login:
    st.title("🛠️ Panel de administración")
    if not st.session_state.is_admin:
        pwd_input = st.text_input("Contraseña de administrador", type="password")
        if st.button("Entrar"):
            if pwd_input == read_secret("ADMIN_PASS"):
                st.session_state.is_admin = True
                st.success("Acceso concedido. Recargando…")
                st.rerun()
            else:
                st.error("Contraseña incorrecta.")
    else:
        # Gestión de sesiones
        st.subheader("➕ Añadir o actualizar sesión")
        with st.form("add_sesion", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            with col1:
                f = st.date_input("Fecha", dt.date.today())
            with col2:
                h = st.text_input("Hora (HH:MM)", "09:30")
            with col3:
                e = st.selectbox("Estado", ["ABIERTA", "CERRADA"])
            if st.form_submit_button("Guardar"):
                upsert_sesion(f.isoformat(), h, e)
                st.success("Sesión guardada")
                st.cache_data.clear()
                st.rerun()

        df_ses = load_sesiones_df()
        if not df_ses.empty:
            df_ses["hora"] = df_ses["hora"].apply(_norm_hora)
            st.dataframe(df_ses, use_container_width=True)
else:
    # === USUARIO ===
    st.title(APP_TITLE)

    SESIONES_DIA = get_sesiones_por_dia()
    today = dt.date.today()

    try:
        from streamlit_calendar import calendar
        events = []
        for f, sesiones in SESIONES_DIA.items():
            fecha_dt = dt.date.fromisoformat(f)

            # Color general por día
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
                        mm = plazas_libres(f, s["hora"], CATEG_MINI)
                        gg = plazas_libres(f, s["hora"], CATEG_GRANDE)
                        if mm > 0 or gg > 0:
                            full_all = False
                        if mm <= 0 or gg <= 0:
                            any_full = True
                    color = "#dc3545" if full_all else "#ffc107" if any_full else "#28a745"

            # Fondo por día
            events.append({"title": "", "start": f, "end": f, "display": "background", "backgroundColor": color})

            # 🔹 Una línea por sesión con rango horario
            for s in sorted(sesiones, key=lambda x: _norm_hora(x["hora"])):
                h_ini = _norm_hora(s["hora"])
                h_fin = hora_mas(h_ini, 60)
                label = f"{h_ini}–{h_fin}"
                events.append({"title": label, "start": f, "end": f, "display": "auto"})

        cal = calendar(
            events=events,
            options={"initialView": "dayGridMonth", "height": 600, "locale": "es", "firstDay": 1},
            key="cal",
        )
    except Exception:
        st.warning("No se pudo cargar el calendario (falta streamlit_calendar).")

