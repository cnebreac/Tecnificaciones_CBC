import streamlit as st
import pandas as pd
from io import BytesIO
import datetime as dt
import os
from streamlit_cookies_manager import EncryptedCookieManager
import secrets
import string


# ====== CONFIGURACIÓN DE SESIONES DISPONIBLES ======
SESIONES = {
}

# Capacidad por categoría
MAX_POR_CANASTA = 4
CATEG_MINI = "Minibasket"
CATEG_GRANDE = "Canasta grande"

# Opciones para Categoría/Equipo (edítalas a tu gusto)
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

# ====== AJUSTES GENERALES ======
st.set_page_config(page_title="Tecnificaciones CBC ", layout="centered")
APP_TITLE = "🏀 Tecnificaciones CBC - Reserva de Sesiones"
ADMIN_QUERY_FLAG = "admin"

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

def iso(d: dt.date) -> str:
    return d.isoformat()

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

# ====== GOOGLE SHEETS ======
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def _gc():
    info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

SHEET_ID = _SID or _SID_BLOCK

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

@st.cache_data(ttl=15)
def load_df(sheet_name: str) -> pd.DataFrame:
    sh = _open_sheet()
    ws = sh.worksheet(sheet_name)
    data = ws.get_all_records()
    return pd.DataFrame(data)

def append_row(sheet_name: str, values: list):
    """Añade la fila y, si falta la cabecera 'email', la crea al final de la fila 1."""
    sh = _open_sheet()
    ws = sh.worksheet(sheet_name)
    headers = ws.row_values(1)
    lowered = [h.strip().lower() for h in headers]
    if "email" not in lowered:
        ws.update_cell(1, len(headers) + 1, "email")
    ws.append_row(values, value_input_option="USER_ENTERED")

def get_inscripciones_por_fecha(fecha_iso: str) -> list:
    df = load_df("inscripciones")
    if df.empty:
        return []
    need = ["timestamp","fecha_iso","hora","nombre","canasta","equipo","tutor","telefono","email"]
    for c in need:
        if c not in df.columns:
            df[c] = ""
    return df[df["fecha_iso"] == fecha_iso][need].to_dict("records")

def get_waitlist_por_fecha(fecha_iso: str) -> list:
    df = load_df("waitlist")
    if df.empty:
        return []
    need = ["timestamp","fecha_iso","hora","nombre","canasta","equipo","tutor","telefono","email"]
    for c in need:
        if c not in df.columns:
            df[c] = ""
    return df[df["fecha_iso"] == fecha_iso][need].to_dict("records")

# ====== CAPACIDAD, DUPLICADOS ======
def _match_canasta(valor: str, objetivo: str) -> bool:
    v = (valor or "").strip().lower()
    o = objetivo.strip().lower()
    if o.startswith("mini"):
        return v.startswith("mini")
    if o.startswith("canasta"):
        return v.startswith("canasta")
    return v == o

def plazas_ocupadas(fecha_iso: str, canasta: str) -> int:
    ins = get_inscripciones_por_fecha(fecha_iso)
    return sum(1 for r in ins if _match_canasta(r.get("canasta",""), canasta))

def plazas_libres(fecha_iso: str, canasta: str) -> int:
    return max(0, MAX_POR_CANASTA - plazas_ocupadas(fecha_iso, canasta))

def ya_existe_en_sesion(fecha_iso: str, nombre: str) -> str | None:
    """Devuelve 'inscripciones' o 'waitlist' si el nombre ya existe en esa fecha."""
    nn = _norm_name(nombre)
    for r in get_inscripciones_por_fecha(fecha_iso):
        if _norm_name(r.get("nombre","")) == nn:
            return "inscripciones"
    for r in get_waitlist_por_fecha(fecha_iso):
        if _norm_name(r.get("nombre","")) == nn:
            return "waitlist"
    return None

# ====== PDF: JUSTIFICANTE INDIVIDUAL ======
def crear_justificante_pdf(datos: dict) -> BytesIO:
    """Genera un justificante individual (confirmada o lista de espera)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import cm
    from reportlab.lib import colors

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    x = 2*cm
    y = height - 2*cm

    status_ok = (datos.get("status") == "ok")
    titulo = "Justificante de inscripción" if status_ok else "Justificante - Lista de espera"

    # Cabecera
    c.setFont("Helvetica-Bold", 16)
    c.drawString(x, y, titulo)
    y -= 0.8*cm

    c.setFont("Helvetica", 11)
    c.drawString(x, y, f"Sesión: {datos.get('fecha_txt','—')}  ·  Hora: {datos.get('hora','—')}")
    y -= 0.5*cm
    c.drawString(x, y, f"Estado: {'CONFIRMADA' if status_ok else 'LISTA DE ESPERA'}")
    y -= 0.8*cm

    # Datos
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
    c.setFillColor(colors.grey)
    c.drawString(x, y, "Conserve este justificante como comprobante de su reserva.")
    # ... después del texto de "Conserve este justificante..."
    y -= 0.6*cm
    family_code = to_text(datos.get("family_code","")).strip()
    if family_code:
        c.setFillColor(_colors.black)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x, y, f"Código de familia (para autorrelleno): {family_code}")

    c.setFillColor(colors.black)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf

# ====== PDF: LISTADOS SESIÓN (con email en 2ª línea) ======
def crear_pdf_sesion(fecha_iso: str) -> BytesIO:
    """Genera un PDF con inscripciones y lista de espera (separadas por categoría)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import cm
    from reportlab.pdfbase.pdfmetrics import stringWidth

    d = dt.date.fromisoformat(fecha_iso)
    lista = get_inscripciones_por_fecha(fecha_iso)
    wl = get_waitlist_por_fecha(fecha_iso)

    ins_mini = [r for r in lista if _match_canasta(r.get("canasta",""), CATEG_MINI)]
    ins_gran = [r for r in lista if _match_canasta(r.get("canasta",""), CATEG_GRANDE)]
    wl_mini  = [r for r in wl if _match_canasta(r.get("canasta",""), CATEG_MINI)]
    wl_gran  = [r for r in wl if _match_canasta(r.get("canasta",""), CATEG_GRANDE)]

    # hora
    hora = SESIONES.get(fecha_iso, "—")
    if lista:
        hora = lista[0].get("hora", hora) or hora
    elif wl:
        hora = wl[0].get("hora", hora) or hora

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    # Cabecera
    fecha_txt = d.strftime("%A, %d %B %Y").capitalize()
    y = height - 2*cm
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2*cm, y, f"Tecnificación Baloncesto — {fecha_txt} {hora}")
    y -= 0.8*cm
    c.setFont("Helvetica", 11)
    c.drawString(2*cm, y, f"Capacidad por categoría: {MAX_POR_CANASTA} | Mini: {len(ins_mini)} | Grande: {len(ins_gran)}")
    y -= 1.0*cm

    # Utils texto
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

    # Márgenes y columnas
    left   = 2.0*cm
    right  = width - 2.0*cm
    x_num  = left
    x_name = left + 0.9*cm
    x_cat  = left + 11.0*cm
    x_team = left + 14.0*cm

    # Segunda línea (debajo de cada columna):
    # - Email debajo de NOMBRE
    # - Teléfono debajo de CANASTA
    # - Tutor debajo de EQUIPO
    x_email = x_name
    x_tel   = x_cat
    x_tutor = x_team

    # Anchos máximos
    w_name  = (x_cat  - x_name) - 0.2*cm
    w_cat   = (x_team - x_cat)  - 0.2*cm
    w_team  = (right  - x_team)

    w_email = (x_cat  - x_email) - 0.3*cm
    w_tel   = (x_team - x_tel)   - 0.3*cm
    w_tutor = (right  - x_tutor)

    # Espaciado vertical
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

            # Línea 1
            c.setFont("Helvetica", 10)
            c.drawString(x_num,  y, to_text(i))
            c.drawString(x_name, y, fit_text(c, nombre, w_name))
            c.drawString(x_cat,  y, fit_text(c, cat,   w_cat))
            c.drawString(x_team, y, fit_text(c, team,  w_team))

            # Línea 2
            y -= line_spacing
            c.setFont("Helvetica", 9)
            c.drawString(x_email, y, "Email: " + fit_text(c, email, w_email, size=9))
            c.drawString(x_tel,   y, "Tel.: "  + fit_text(c, tel,   w_tel,   size=9))
            c.drawString(x_tutor, y, "Tutor: " + fit_text(c, tutor, w_tutor))

            # Separador + aire extra
            y -= separator_offset
            c.setLineWidth(0.3)
            c.setDash(1, 2)
            c.line(left, y, right, y)
            c.setDash()
            c.setLineWidth(1)
            y -= post_separator_gap
        return y

    # --- Inscripciones ---
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

    # --- Lista de espera ---
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
        # Panel admin real
        df_all_ins = load_df("inscripciones")
        df_all_wl  = load_df("waitlist")
        fechas_con_datos = sorted(set(df_all_ins.get("fecha_iso", []))
                                  .union(set(df_all_wl.get("fecha_iso", []))))

        if not fechas_con_datos:
            st.info("Aún no hay sesiones con datos.")
        else:
            opciones = {f: f"{dt.datetime.strptime(f,'%Y-%m-%d').strftime('%d/%m/%Y')}  ·  {SESIONES.get(f,'—')}"
                        for f in fechas_con_datos}
            fkey_admin = st.selectbox("Selecciona sesión", options=fechas_con_datos,
                                      format_func=lambda x: opciones.get(x, x))

            ins_f = get_inscripciones_por_fecha(fkey_admin)
            wl_f  = get_waitlist_por_fecha(fkey_admin)
            df_show = pd.DataFrame(ins_f)
            df_wl   = pd.DataFrame(wl_f)

            st.write("**Inscripciones:**")
            if df_show.empty:
                st.write("— Sin inscripciones —")
            else:
                st.dataframe(df_show, use_container_width=True)

            st.write("**Lista de espera:**")
            if df_wl.empty:
                st.write("— Vacía —")
            else:
                st.dataframe(df_wl, use_container_width=True)

            # Botón PDF sesión
            if st.button("🧾 Generar PDF (inscripciones + lista de espera)"):
                try:
                    pdf = crear_pdf_sesion(fkey_admin)
                    st.download_button(
                        label="Descargar PDF",
                        data=pdf,
                        file_name=f"sesion_{fkey_admin}.pdf",
                        mime="application/pdf"
                    )
                except ModuleNotFoundError:
                    st.error("Falta el paquete 'reportlab'. Añádelo a requirements.txt (línea: reportlab).")

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
            font-weight: bold.
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

    # Si YA hay una inscripción correcta en esta sesión para este navegador
    if st.session_state.get(ok_flag):
        data = st.session_state.get(ok_data_key, {})
        with placeholder.container():
            if data.get("status") == "ok":
                st.success("✅ Inscripción realizada correctamente")
            else:
                st.info("ℹ️ Te hemos añadido a la lista de espera")

            # Mostrar código si existe (importante para que lo recuperen)
            if data.get("family_code"):
                st.info(f"🔐 **Tu código de familia:** `{data.get('family_code')}`\n\nGuárdalo: te servirá para autorrellenar próximas veces.")

            # Solo canales por categoría aquí
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
                file_name=f"justificante_{data.get('fecha_iso','')}_{_norm_name(data.get('nombre','')).replace(' ','_')}_{_parse_hora_cell(data.get('hora','')).replace(':','')}.pdf",
                mime="application/pdf",
                key=f"dl_btn_{fkey}_{hkey}"
            )

            if st.button("Hacer otra reserva", key=f"otra_{fkey}_{hkey}"):
                st.session_state.pop(ok_flag, None)
                st.session_state.pop(ok_data_key, None)
                st.session_state.pop(f"hijos_{fkey}_{hkey}", None)
                st.rerun()

        if st.session_state.pop(celebrate_key, False) and data.get("status") == "ok":
            st.toast("✅ Inscripción realizada correctamente", icon="✅")
            st.balloons()

    else:
        # ==========================
        # AUTORRELLENO POR CÓDIGO (FUERA DEL FORM)
        # ==========================
        codigo_cookie = (cookies.get("family_code") or "").strip()

        st.markdown("### 🔐 Autorrellenar (opcional)")
        codigo_familia = st.text_input(
            "Código de familia",
            value=codigo_cookie,
            key=f"family_code_{fkey}_{hkey}",
            placeholder="Ej: CBC-7F3KQ9P2..."
        )

        colc1, colc2 = st.columns([1, 1])
        with colc1:
            recordar_dispositivo = st.checkbox(
                "Recordar este dispositivo",
                value=bool(codigo_cookie),
                key=f"remember_{fkey}_{hkey}"
            )
        with colc2:
            if st.button("🧹 Olvidar este dispositivo", key=f"forget_{fkey}_{hkey}"):
                cookies["family_code"] = ""
                cookies.save()
                st.success("Código eliminado de este dispositivo.")
                st.session_state.pop(f"hijos_{fkey}_{hkey}", None)
                st.rerun()

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

        if st.button("✨ Autorrellenar con código", key=f"autofill_btn_{fkey}_{hkey}"):
            fam = get_familia_por_codigo(codigo_familia)
            if not fam:
                st.error("Código no válido (o no encontrado).")
            else:
                hijos = get_hijos_por_codigo(fam["codigo"])
                st.session_state[f"padre_{fkey}_{hkey}"] = fam.get("tutor", "")
                st.session_state[f"telefono_{fkey}_{hkey}"] = fam.get("telefono", "")
                st.session_state[f"email_{fkey}_{hkey}"] = fam.get("email", "")
                st.session_state[f"hijos_{fkey}_{hkey}"] = hijos or []

                if recordar_dispositivo:
                    cookies["family_code"] = fam["codigo"]
                    cookies.save()

                st.success("Datos cargados.")
                st.rerun()

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

            if st.button("✅ Usar este jugador", key=f"useh_{fkey}_{hkey}"):
                st.session_state[f"nombre_{fkey}_{hkey}"] = to_text(sel_h.get("jugador", ""))
                eq = to_text(sel_h.get("equipo", "")).strip()
                if eq in EQUIPOS_OPCIONES:
                    st.session_state[f"equipo_sel_{fkey}_{hkey}"] = eq
                    st.session_state[f"equipo_otro_{fkey}_{hkey}"] = ""
                else:
                    st.session_state[f"equipo_sel_{fkey}_{hkey}"] = "Otro"
                    st.session_state[f"equipo_otro_{fkey}_{hkey}"] = eq
                st.success("Jugador seleccionado.")
                st.rerun()

        st.divider()

        # ===== FORMULARIO DE RESERVA =====
        with placeholder.form(f"form_{fkey}_{hkey}", clear_on_submit=False):
            # Guardar familia DENTRO del form (es donde tiene sentido)
            guardar_familia = st.checkbox(
                "💾 Guardar estos datos para próximas reservas (con código de familia)",
                value=True,
                key=f"savefam_{fkey}_{hkey}"
            )

            st.write("📝 Información del jugador")
            nombre = st.text_input(
                "Nombre y apellidos del jugador",
                key=f"nombre_{fkey}_{hkey}"
            )

            # Canasta + placeholder de error
            opciones_canasta = []
            if get_estado_grupo_mem(fkey, hkey, CATEG_MINI) == "ABIERTA":
                opciones_canasta.append(CATEG_MINI)
            if get_estado_grupo_mem(fkey, hkey, CATEG_GRANDE) == "ABIERTA":
                opciones_canasta.append(CATEG_GRANDE)

            canasta = st.radio("Canasta", opciones_canasta, key=f"canasta_{fkey}_{hkey}")
            err_canasta = st.empty()

            # Aviso informativo según canasta
            if canasta == CATEG_MINI:
                st.caption("ℹ️ Para **Minibasket** solo se permiten categorías **Benjamín** y **Alevín**.")
            elif canasta == CATEG_GRANDE:
                st.caption("ℹ️ Para **Canasta grande** solo se permiten categorías **Infantil**, **Cadete** y **Junior**.")

            # Categoría / Equipo + placeholder de error
            equipo_sel = st.selectbox(
                "Categoría / Equipo",
                EQUIPOS_OPCIONES,
                index=0,
                key=f"equipo_sel_{fkey}_{hkey}"
            )
            equipo_otro = st.text_input(
                "Especifica la categoría/equipo",
                key=f"equipo_otro_{fkey}_{hkey}"
            ) if equipo_sel == "Otro" else ""

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

                if hay_error:
                    pass
                else:
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

                        # ---- Guardar familia/hijo y cookie (si procede) ----
                        family_code = ""
                        if guardar_familia:
                            # usa el código del input (o cookie)
                            cod_in = (codigo_familia or "").strip() or codigo_cookie
                            family_code = upsert_familia_y_hijo(
                                cod_in if cod_in else None,
                                (padre or ""), telefono, (email or ""),
                                nombre, (equipo_val or ""), canasta
                            )
                            if recordar_dispositivo and family_code:
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
