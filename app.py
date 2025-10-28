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
    """Acepta '9', '9:3', '09:30', '1130' -> '09:00', '09:03', '09:30', '11:30'."""
    h = (h or "").strip()
    if not h:
        return "—"
    # Permitir "1130" => 11:30
    if re.fullmatch(r"\d{3,4}", h):
        if len(h) == 3:
            h = "0" + h  # e.g., 930 -> 0930
        return f"{int(h[:2]):02d}:{int(h[2:]):02d}"
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
    headers = ws.row_values(1)
    if not headers:
        ws.update("A1:I1", [["timestamp","fecha_iso","hora","nombre","canasta","equipo","tutor","telefono","email"]])
    ws.append_row(values, value_input_option="USER_ENTERED")

# ====== SESIONES (en Google Sheets) ======
SESIONES_SHEET = "sesiones"  # pestaña para gestionar sesiones

def _ensure_ws_sesiones():
    """Garantiza que exista la pestaña 'sesiones' con cabeceras básicas (fecha_iso, hora, estado)."""
    sh = _open_sheet()
    try:
        ws = sh.worksheet(SESIONES_SHEET)
        headers = ws.row_values(1)
        needed = ["fecha_iso","hora","estado"]
        if headers != needed:
            ws.resize(rows=max(2, len(ws.get_all_values())), cols=3)
            ws.update("A1:C1", [needed])
    except Exception:
        ws = sh.add_worksheet(title=SESIONES_SHEET, rows=100, cols=3)
        ws.update("A1:C1", [["fecha_iso","hora","estado"]])
    return ws

@st.cache_data(ttl=15)
def load_sesiones_df() -> pd.DataFrame:
    ws = _ensure_ws_sesiones()
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    if df.empty:
        df = pd.DataFrame(columns=["fecha_iso","hora","estado"])
    for c in ["fecha_iso","hora","estado"]:
        if c not in df.columns: df[c] = ""
    df["hora"] = df["hora"].apply(_norm_hora)
    df["estado"] = df["estado"].replace("", "ABIERTA").str.upper()
    return df

def get_sesiones_por_dia() -> dict:
    """
    Devuelve {fecha_iso: [ {fecha_iso, hora, estado}, ... ]} (todas las sesiones de ese día).
    """
    df = load_sesiones_df()
    out = {}
    for _, r in df.iterrows():
        f = str(r["fecha_iso"]).strip()
        if not f:
            continue
        item = {
            "fecha_iso": f,
            "hora": _norm_hora(str(r.get("hora","")).strip() or "—"),
            "estado": (str(r.get("estado","ABIERTA")).strip() or "ABIERTA").upper()
        }
        out.setdefault(f, []).append(item)
    return out

def get_sesion_info(fecha_iso: str, hora: str) -> dict:
    """
    Devuelve {'hora','estado'} de la sesión exacta (fecha+hora).
    Si no existe, estado=ABIERTA por defecto.
    """
    hora = _norm_hora(hora)
    df = load_sesiones_df()
    if not df.empty:
        m = df[(df["fecha_iso"] == fecha_iso) & (df["hora"] == hora)]
        if not m.empty:
            r = m.iloc[0].to_dict()
            return {"hora": _norm_hora(r.get("hora","—")),
                    "estado": (str(r.get("estado","ABIERTA")) or "ABIERTA").upper()}
    return {"hora": _norm_hora(hora or "—"), "estado": "ABIERTA"}

def upsert_sesion(fecha_iso: str, hora: str, estado: str = "ABIERTA"):
    ws = _ensure_ws_sesiones()
    rows = ws.get_all_values()
    if not rows:
        ws.update("A1:C1", [["fecha_iso","hora","estado"]])
        rows = ws.get_all_values()
    hora = _norm_hora(hora)
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 2 and (row[0] or "").strip() == fecha_iso and _norm_hora(row[1]) == hora:
            ws.update(f"A{i}:C{i}", [[fecha_iso, hora, estado.upper()]])
            return
    ws.append_row([fecha_iso, hora, estado.upper()], value_input_option="USER_ENTERED")

def delete_sesion(fecha_iso: str, hora: str):
    ws = _ensure_ws_sesiones()
    rows = ws.get_all_values()
    if not rows: return
    hora = _norm_hora(hora)
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 2 and (row[0] or "").strip() == fecha_iso and _norm_hora(row[1]) == hora:
            ws.delete_rows(i)
            return

def set_estado_sesion(fecha_iso: str, hora: str, estado: str):
    ws = _ensure_ws_sesiones()
    rows = ws.get_all_values()
    if not rows: return
    hora = _norm_hora(hora)
    for i, row in enumerate(rows[1:], start=2):
        if len(row) >= 2 and (row[0] or "").strip() == fecha_iso and _norm_hora(row[1]) == hora:
            ws.update_cell(i, 3, estado.upper())
            return

# ====== LECTURA DE INSCRIPCIONES/WAITLIST POR SESIÓN ======
def _ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    need = ["timestamp","fecha_iso","hora","nombre","canasta","equipo","tutor","telefono","email"]
    for c in need:
        if c not in df.columns:
            df[c] = ""
    return df

def get_inscripciones_por_sesion(fecha_iso: str, hora: str) -> list:
    df = load_df("inscripciones")
    if df.empty:
        return []
    df = _ensure_cols(df)
    df["hora"] = df["hora"].apply(_norm_hora)
    hora = _norm_hora(hora)
    m = df[(df["fecha_iso"] == fecha_iso) & (df["hora"] == hora)]
    return m.to_dict("records")

def get_waitlist_por_sesion(fecha_iso: str, hora: str) -> list:
    df = load_df("waitlist")
    if df.empty:
        return []
    df = _ensure_cols(df)
    df["hora"] = df["hora"].apply(_norm_hora)
    hora = _norm_hora(hora)
    m = df[(df["fecha_iso"] == fecha_iso) & (df["hora"] == hora)]
    return m.to_dict("records")

# ====== CAPACIDAD, DUPLICADOS ======
def _match_canasta(valor: str, objetivo: str) -> bool:
    v = (valor or "").strip().lower()
    o = objetivo.strip().lower()
    if o.startswith("mini"):
        return v.startswith("mini")
    if o.startswith("canasta"):
        return v.startswith("canasta")
    return v == o

def plazas_ocupadas(fecha_iso: str, hora: str, canasta: str) -> int:
    ins = get_inscripciones_por_sesion(fecha_iso, hora)
    return sum(1 for r in ins if _match_canasta(r.get("canasta",""), canasta))

def plazas_libres(fecha_iso: str, hora: str, canasta: str) -> int:
    if get_sesion_info(fecha_iso, hora).get("estado","ABIERTA").upper() == "CERRADA":
        return 0
    return max(0, MAX_POR_CANASTA - plazas_ocupadas(fecha_iso, hora, canasta))

def ya_existe_en_sesion(fecha_iso: str, hora: str, nombre: str) -> str | None:
    nn = _norm_name(nombre)
    for r in get_inscripciones_por_sesion(fecha_iso, hora):
        if _norm_name(r.get("nombre","")) == nn:
            return "inscripciones"
    for r in get_waitlist_por_sesion(fecha_iso, hora):
        if _norm_name(r.get("nombre","")) == nn:
            return "waitlist"
    return None

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
    filas = [
        ("Jugador", datos.get("nombre","—")),
        ("Canasta", datos.get("canasta","—")),
        ("Categoría/Equipo", datos.get("equipo","—")),
        ("Tutor", datos.get("tutor","—")),
        ("Teléfono", datos.get("telefono","—")),
        ("Email", datos.get("email","—")),
    ]
    for label, value in filas:
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

    c.showPage()
    c.save()
    buf.seek(0)
    return buf

# ====== PDF: LISTADOS SESIÓN (INSCRIPCIONES + ESPERA) ======
def crear_pdf_sesion(fecha_iso: str, hora: str) -> BytesIO:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import cm
    from reportlab.pdfbase.pdfmetrics import stringWidth

    d = dt.date.fromisoformat(fecha_iso)
    hora = _norm_hora(hora)

    lista = get_inscripciones_por_sesion(fecha_iso, hora)
    wl    = get_waitlist_por_sesion(fecha_iso, hora)

    ins_mini = [r for r in lista if _match_canasta(r.get("canasta",""), CATEG_MINI)]
    ins_gran = [r for r in lista if _match_canasta(r.get("canasta",""), CATEG_GRANDE)]
    wl_mini  = [r for r in wl if _match_canasta(r.get("canasta",""), CATEG_MINI)]
    wl_gran  = [r for r in wl if _match_canasta(r.get("canasta",""), CATEG_GRANDE)]

    info_s = get_sesion_info(fecha_iso, hora)
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

    def fit_text(ca, text, max_w, font="Helvetica", size=10):
        if not text:
            return ""
        if stringWidth(text, font, size) <= max_w:
            return text
        ell = "…"
        ell_w = stringWidth(ell, font, size)
        t = text
        while t and stringWidth(t, font, size) + ell_w > max_w:
            t = t[:-1]
        return t + ell

    left   = 2.0*cm
    right  = width - 2.0*cm
    x_num  = left
    x_name = left + 0.9*cm
    x_cat  = left + 11.0*cm
    x_team = left + 14.0*cm

    x_email = x_name
    x_tel   = x_cat
    x_tutor = x_team

    w_name  = (x_cat  - x_name) - 0.2*cm
    w_cat   = (x_team - x_cat)  - 0.2*cm
    w_team  = (right  - x_team)

    w_email = (x_cat  - x_email) - 0.3*cm
    w_tel   = (x_team - x_tel)   - 0.3*cm
    w_tutor = (right  - x_tutor)

    line_spacing        = 0.46*cm
    separator_offset    = 0.30*cm
    post_separator_gap  = 0.50*cm
    min_margin          = 3.0*cm

    def redraw_headers(y_cur, titulo=""):
        c.setFont("Helvetica-Bold", 11)
        if titulo:
            c.drawString(left, y_cur, titulo)
            y_cur -= 0.5*cm
        c.setFont("Helvetica", 10)
        c.drawString(x_num,  y_cur, "#")
        c.drawString(x_name, y_cur, "Nombre (jugador)")
        c.drawString(x_cat,  y_cur, "Canasta")
        c.drawString(x_team, y_cur, "Equipo")
        y2 = y_cur - 0.35*cm
        c.line(left, y2, right, y2)
        return y2 - 0.35*cm

    def pintar_lista(registros, titulo, y, start_idx=1):
        if not registros:
            c.setFont("Helvetica", 10)
            c.drawString(left, y, f"— Sin inscripciones en {titulo.lower()} —")
            return y - 0.6*cm

        y = redraw_headers(y, f"{titulo}:")
        for i, r in enumerate(registros, start=start_idx):
            required_height = line_spacing + separator_offset + post_separator_gap
            if y - required_height < min_margin:
                c.showPage()
                y = height - 2*cm
                y = redraw_headers(y, f"{titulo}:")

            nombre = to_text(r.get("nombre",""))
            cat    = to_text(r.get("canasta",""))
            team   = to_text(r.get("equipo",""))
            tutor  = to_text(r.get("tutor",""))
            tel    = to_text(r.get("telefono",""))
            email  = to_text(r.get("email",""))

            c.setFont("Helvetica", 10)
            c.drawString(x_num,  y, to_text(i))
            c.drawString(x_name, y, fit_text(c, nombre, w_name))
            c.drawString(x_cat,  y, fit_text(c, cat,   w_cat))
            c.drawString(x_team, y, fit_text(c, team,  w_team))

            y -= line_spacing
            c.setFont("Helvetica", 9)
            c.drawString(x_email, y, "Email: " + fit_text(c, email, w_email, size=9))
            c.drawString(x_tel,   y, "Tel.: "  + fit_text(c, tel,   w_tel,   size=9))
            c.drawString(x_tutor, y, "Tutor: " + fit_text(c, tutor, w_tutor))

            y -= separator_offset
            c.setLineWidth(0.3)
            c.setDash(1, 2)
            c.line(left, y, right, y)
            c.setDash()
            c.setLineWidth(1)
            y -= post_separator_gap
        return y

    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, y, "Inscripciones confirmadas:")
    y -= 0.8*cm

    grande = [r for r in lista if _match_canasta(r.get("canasta",""), CATEG_GRANDE)]
    mini   = [r for r in lista if _match_canasta(r.get("canasta",""), CATEG_MINI)]

    if not lista:
        c.setFont("Helvetica", 10)
        c.drawString(left, y, "— Sin inscripciones —")
        y -= 0.6*cm
    else:
        y = pintar_lista(grande, "Canasta grande", y, start_idx=1)
        y = pintar_lista(mini,   "Minibasket",    y, start_idx=len(grande)+1)

    y -= 1*cm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, y, "Lista de espera:")
    y -= 0.8*cm

    grande_wl = [r for r in wl if _match_canasta(r.get("canasta",""), CATEG_GRANDE)]
    mini_wl   = [r for r in wl if _match_canasta(r.get("canasta",""), CATEG_MINI)]

    if not wl:
        c.setFont("Helvetica", 10)
        c.drawString(left, y, "— Vacía —")
        y -= 0.6*cm
    else:
        y = pintar_lista(grande_wl, "Canasta grande", y, start_idx=1)
        y = pintar_lista(mini_wl,   "Minibasket",    y, start_idx=len(grande_wl)+1)

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
        df_all_ins = load_df("inscripciones")
        df_all_wl  = load_df("waitlist")

        # ===== Tabla de inscripciones / espera por sesión (fecha+hora) =====
        fechas_horas = set()
        if not df_all_ins.empty:
            for _, r in df_all_ins.iterrows():
                fechas_horas.add((r.get("fecha_iso",""), _norm_hora(r.get("hora",""))))
        if not df_all_wl.empty:
            for _, r in df_all_wl.iterrows():
                fechas_horas.add((r.get("fecha_iso",""), _norm_hora(r.get("hora",""))))

        fechas_horas = sorted([(f,h) for (f,h) in fechas_horas if f], key=lambda x:(x[0], x[1]))

        if not fechas_horas:
            st.info("Aún no hay sesiones con datos.")
        else:
            opciones = {
                (f,h): f"{dt.datetime.strptime(f,'%Y-%m-%d').strftime('%d/%m/%Y')}  ·  {_norm_hora(h)}  ·  {get_sesion_info(f,h).get('estado','—')}"
                for (f,h) in fechas_horas
            }
            f_h_admin = st.selectbox("Selecciona sesión (fecha + hora)", options=fechas_horas,
                                     format_func=lambda t: opciones.get(t, f"{t[0]} · {t[1]}"))

            f_sel, h_sel = f_h_admin
            ins_f = get_inscripciones_por_sesion(f_sel, h_sel)
            wl_f  = get_waitlist_por_sesion(f_sel, h_sel)
            df_show = pd.DataFrame(ins_f)
            df_wl   = pd.DataFrame(wl_f)

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
                        file_name=f"sesion_{f_sel}_{_norm_hora(h_sel)}.pdf",
                        mime="application/pdf"
                    )
                except ModuleNotFoundError:
                    st.error("Falta el paquete 'reportlab'. Añádelo a requirements.txt (línea: reportlab).")

        st.divider()
        st.subheader("🗓️ Gestión de sesiones (fecha + hora)")

        # --- Formulario para añadir/actualizar ---
        with st.form("form_sesiones_admin", clear_on_submit=True):
            col1, col2, col3 = st.columns([1,1,1])
            with col1:
                fecha_nueva = st.date_input("Fecha", value=dt.date.today())
            with col2:
                hora_nueva = st.text_input("Hora (HH:MM)", value="09:30")
            with col3:
                estado_nuevo = st.selectbox("Estado sesión", ["ABIERTA", "CERRADA"], index=0)

            submitted = st.form_submit_button("➕ Añadir / Actualizar sesión")
            if submitted:
                f_iso = fecha_nueva.isoformat()
                upsert_sesion(f_iso, hora_nueva, estado_nuevo)
                st.success(f"Sesión {f_iso} { _norm_hora(hora_nueva) } guardada ({estado_nuevo}).")
                st.cache_data.clear()
                st.rerun()

        # --- Tabla de sesiones con acciones (fecha+hora) ---
        df_ses = load_sesiones_df()
        if df_ses.empty:
            st.info("No hay sesiones creadas todavía.")
        else:
            try:
                df_ses["__f"] = pd.to_datetime(df_ses["fecha_iso"])
                df_ses["hora"] = df_ses["hora"].apply(_norm_hora)
                df_ses = df_ses.sort_values(["__f","hora"]).drop(columns="__f")
            except Exception:
                pass

            st.dataframe(df_ses, use_container_width=True)

            st.markdown("#### Acciones sobre una sesión")
            opciones_ses = [(r["fecha_iso"], _norm_hora(r["hora"])) for _, r in df_ses.iterrows()]
            opciones_ses = list(dict.fromkeys(opciones_ses))  # sin duplicados exactos
            if opciones_ses:
                fsel, hsel = st.selectbox(
                    "Selecciona sesión",
                    options=opciones_ses,
                    format_func=lambda t: f"{dt.datetime.strptime(t[0],'%Y-%m-%d').strftime('%d/%m/%Y')} · {_norm_hora(t[1])}"
                )

                c1, c2, c3 = st.columns(3)
                with c1:
                    if st.button("⛔ Cerrar sesión (bloquear reservas)", use_container_width=True):
                        set_estado_sesion(fsel, hsel, "CERRADA")
                        st.info(f"Sesión {fsel} {hsel} CERRADA.")
                        st.cache_data.clear()
                        st.rerun()
                with c2:
                    if st.button("✅ Abrir sesión", use_container_width=True):
                        set_estado_sesion(fsel, hsel, "ABIERTA")
                        st.success(f"Sesión {fsel} {hsel} ABIERTA.")
                        st.cache_data.clear()
                        st.rerun()
                with c3:
                    if st.button("🗑️ Eliminar sesión", use_container_width=True):
                        delete_sesion(fsel, hsel)
                        st.warning(f"Sesión {fsel} {hsel} eliminada.")
                        st.cache_data.clear()
                        st.rerun()

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

**Política de Reorganización de Grupos**  
Si en una categoría hay menos de 3 jugadores inscritos y en la otra hay lista de espera, se cancelará la sesión con menor asistencia para abrir una adicional en la categoría con más demanda.
    """)

        # >>> Instrucciones de uso (plegadas)
    with st.expander("ℹ️ Cómo usar esta web", expanded=False):
        st.markdown("""
1. Revisa el **calendario** y elige una fecha con plazas disponibles.  
2. Selecciona la **Canasta** (Minibasket / Canasta Grande) y tu **Categoría/Equipo**.  
3. Rellena los **datos del jugador y del tutor** y pulsa **Reservar**.  
4. Si la categoría está llena, entrarás **automáticamente en lista de espera***.  
5. Tras una reserva correcta, podrás **descargar tu justificante en PDF**.

\\* Si en algún momento alguien **cancela** o hay **ajustes de última hora**, pasarás a tener **plaza confirmada** en esa sesión. Se te informará a través del **correo electrónico facilitado**.
        """)

    st.divider()

    # Refrescar sesiones (agrupadas por día)
    SESIONES_DIA = get_sesiones_por_dia()
    today = dt.date.today()

    # Días con alguna sesión ABIERTA en el futuro
    fechas_disponibles = sorted([
        f for f, sesiones in SESIONES_DIA.items()
        if dt.date.fromisoformat(f) >= today and any(s["estado"] == "ABIERTA" for s in sesiones)
    ])

    # Calendario
    fecha_seleccionada = None
    try:
        from streamlit_calendar import calendar

        events = []
        for f, sesiones in SESIONES_DIA.items():
            fecha_dt = dt.date.fromisoformat(f)

            # Color agregado por día (estado/ocupación)
            if fecha_dt < today:
                color = "#dc3545"
            else:
                any_abierta = any(s["estado"] == "ABIERTA" for s in sesiones)
                if not any_abierta:
                    color = "#fd7e14"  # todas cerradas
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
                    if full_all:
                        color = "#dc3545"
                    elif any_full:
                        color = "#ffc107"
                    else:
                        color = "#28a745"

            # Fondo del día
            if fecha_dt != today:
                events.append({
                    "title": "",
                    "start": f,
                    "end": f,
                    "display": "background",
                    "backgroundColor": color,
                })

            # 🔹 Una línea por sesión con su rango “HH:MM–HH:MM”
            for s in sorted(sesiones, key=lambda x: _norm_hora(x["hora"])):
                h_ini = _norm_hora(s["hora"])
                h_fin = hora_mas(h_ini, 60)  # sesiones de 1 hora
                label = f"{h_ini}–{h_fin}"
                events.append({
                    "title": label,
                    "start": f,
                    "end": f,
                    "display": "auto",
                })

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
        .fc-toolbar-title::first-letter {
            text-transform: uppercase;
        }
        """

        cal = calendar(
            events=events,
            options={
                "initialView": "dayGridMonth",
                "height": 600,
                "locale": "es",
                "firstDay": 1,
            },
            custom_css=custom_css,
            key="cal",
        )

        if cal and cal.get("clickedEvent"):
            fclicked = cal["clickedEvent"].get("start")[:10]
            if fclicked in SESIONES_DIA and dt.date.fromisoformat(fclicked) >= today:
                if any(s["estado"] == "ABIERTA" for s in SESIONES_DIA.get(fclicked, [])):
                    fecha_seleccionada = fclicked
    except Exception:
        pass

    st.caption("🟥 Rojo: pasada / sin plazas en ambas · 🟧 Naranja: cerrada (no admite reservas) · 🟨 Una categoría llena · 🟩 Plazas en ambas")

    # Select de fechas abiertas
    if not fecha_seleccionada:
        st.subheader("📅 Selecciona fecha")
        if fechas_disponibles:
            etiqueta = {f: f"{dt.datetime.strptime(f,'%Y-%m-%d').strftime('%d/%m/%Y')}" for f in fechas_disponibles}
            fecha_seleccionada = st.selectbox(
                "Fechas con sesión",
                options=fechas_disponibles,
                format_func=lambda f: etiqueta[f]
            )
        else:
            st.info("De momento no hay fechas futuras disponibles.")
            st.stop()

    # Selector de HORA para la fecha elegida
    sesiones_del_dia = [s for s in SESIONES_DIA.get(fecha_seleccionada, []) if s["estado"] == "ABIERTA"]
    if not sesiones_del_dia:
        st.warning("Ese día no tiene sesiones abiertas.")
        st.stop()

    horas_ops = sorted({_norm_hora(s["hora"]) for s in sesiones_del_dia})
    hora_seleccionada = st.selectbox("⏰ Elige la hora", options=horas_ops)

    # Bloque de reserva para la sesión (fecha+hora)
    fkey = fecha_seleccionada
    hkey = _norm_hora(hora_seleccionada)
    info_s = get_sesion_info(fkey, hkey)
    hora_sesion = info_s.get("hora","—")
    estado_sesion = info_s.get("estado","ABIERTA").upper()

    st.write(f"### Sesión del **{dt.datetime.strptime(fkey,'%Y-%m-%d').strftime('%d/%m/%Y')}** de **{hora_sesion} a {hora_mas(hora_sesion, 60)}**")

    if estado_sesion == "CERRADA":
        st.warning("Esta sesión está **CERRADA**: no admite más reservas en ninguna categoría.")
        st.stop()

    libres_mini = plazas_libres(fkey, hkey, CATEG_MINI)
    libres_gran = plazas_libres(fkey, hkey, CATEG_GRANDE)

    avisos = []
    if libres_mini <= 0:
        avisos.append("**Minibasket** está **COMPLETA**.")
    if libres_gran <= 0:
        avisos.append("**Canasta grande** está **COMPLETA**.")

    if avisos:
        st.warning("⚠️ " + "  \n• ".join([""] + avisos))

    ambas_completas = (libres_mini <= 0 and libres_gran <= 0)
    if not ambas_completas:
        if libres_mini > 0 and libres_gran <= 0:
            st.info(f"Plazas disponibles · {CATEG_MINI}: {libres_mini}/{MAX_POR_CANASTA}")
        elif libres_gran > 0 and libres_mini <= 0:
            st.info(f"Plazas disponibles · {CATEG_GRANDE}: {libres_gran}/{MAX_POR_CANASTA}")
        else:
            st.info(
                f"Plazas · {CATEG_MINI}: {libres_mini}/{MAX_POR_CANASTA}  ·  "
                f"{CATEG_GRANDE}: {libres_gran}/{MAX_POR_CANASTA}"
            )

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

    if st.session_state.get(ok_flag):
        data = st.session_state.get(ok_data_key, {})
        with placeholder.container():
            if data.get("status") == "ok":
                st.success("✅ Inscripción realizada correctamente")
            else:
                st.info("ℹ️ Te hemos añadido a la lista de espera")

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
                file_name=f"justificante_{data.get('fecha_iso','')}_{_norm_name(data.get('nombre','')).replace(' ','_')}_{_norm_hora(data.get('hora','')).replace(':','')}.pdf",
                mime="application/pdf",
                key=f"dl_btn_{fkey}_{hkey}"
            )

            if st.button("Hacer otra reserva", key=f"otra_{fkey}_{hkey}"):
                st.session_state.pop(ok_flag, None)
                st.session_state.pop(ok_data_key, None)
                st.rerun()

        if st.session_state.pop(celebrate_key, False) and data.get("status") == "ok":
            st.toast("✅ Inscripción realizada correctamente", icon="✅")
            st.balloons()

    else:
        with placeholder.form(f"form_{fkey}_{hkey}", clear_on_submit=True):
            st.write("📝 Información del jugador")
            nombre = st.text_input("Nombre y apellidos del jugador", key=f"nombre_{fkey}_{hkey}")
            canasta = st.radio("Canasta", [CATEG_MINI, CATEG_GRANDE], horizontal=True)

            equipo_sel = st.selectbox(
                "Categoría / Equipo",
                EQUIPOS_OPCIONES,
                index=0,
                key=f"equipo_sel_{fkey}_{hkey}"
            )
            equipo_otro = ""
            if equipo_sel == "Otro":
                equipo_otro = st.text_input("Especifica la categoría/equipo", key=f"equipo_otro_{fkey}_{hkey}")

            equipo_val = ""
            if equipo_sel and equipo_sel not in ("— Selecciona —", "Otro"):
                equipo_val = equipo_sel
            elif equipo_sel == "Otro":
                equipo_val = (equipo_otro or "").strip()

            padre = st.text_input("Nombre del padre/madre/tutor", key=f"padre_{fkey}_{hkey}")
            telefono = st.text_input("Teléfono de contacto del tutor", key=f"telefono_{fkey}_{hkey}")
            email = st.text_input("Email", key=f"email_{fkey}_{hkey}")

            st.caption("Tras pulsar **Reservar**, debe aparecer el botón **“⬇️ Descargar justificante (PDF)”**. Si no aparece, la reserva no se ha completado.")

            enviar = st.form_submit_button("Reservar")

            if enviar:
                errores = []
                if not nombre:
                    errores.append("**nombre del jugador**")
                if not telefono:
                    errores.append("**teléfono**")
                if not equipo_val:
                    errores.append("**categoría/equipo** (obligatorio)")

                if errores:
                    st.error("Por favor, rellena: " + ", ".join(errores) + ".")
                else:
                    ya = ya_existe_en_sesion(fkey, hkey, nombre)
                    if ya == "inscripciones":
                        st.error("❌ Este jugador ya está inscrito en esta sesión.")
                    elif ya == "waitlist":
                        st.warning("ℹ️ Este jugador ya está en lista de espera para esta sesión.")
                    else:
                        libres_cat = plazas_libres(fkey, hkey, canasta)
                        row = [
                            dt.datetime.now().isoformat(timespec="seconds"),
                            fkey, hora_sesion, nombre, canasta,
                            (equipo_val or ""), (padre or ""), telefono, (email or "")
                        ]
                        if libres_cat <= 0:
                            append_row("waitlist", row)
                            st.session_state[ok_flag] = True
                            st.session_state[ok_data_key] = {
                                "status": "wait",
                                "fecha_iso": fkey,
                                "fecha_txt": dt.datetime.strptime(fkey, "%Y-%m-%d").strftime("%d/%m/%Y"),
                                "hora": hora_sesion,
                                "nombre": nombre,
                                "canasta": canasta,
                                "equipo": (equipo_val or "—"),
                                "tutor": (padre or "—"),
                                "telefono": telefono,
                                "email": (email or "—"),
                            }
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            append_row("inscripciones", row)
                            st.session_state[ok_flag] = True
                            st.session_state[ok_data_key] = {
                                "status": "ok",
                                "fecha_iso": fkey,
                                "fecha_txt": dt.datetime.strptime(fkey, "%Y-%m-%d").strftime("%d/%m/%Y"),
                                "hora": hora_sesion,
                                "nombre": nombre,
                                "canasta": canasta,
                                "equipo": (equipo_val or "—"),
                                "tutor": (padre or "—"),
                                "telefono": telefono,
                                "email": (email or "—"),
                            }
                            st.session_state[celebrate_key] = True
                            st.cache_data.clear()
                            st.rerun()


