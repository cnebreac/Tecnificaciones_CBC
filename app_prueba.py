import streamlit as st
import pandas as pd
from io import BytesIO
import datetime as dt
import os

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

else:
    # ====== SOLO USUARIO NORMAL ======
    st.title(APP_TITLE)

    # >>> Bienvenida y funcionamiento
    st.markdown("""
**Bienvenid@ a las Tecnificaciones CBC**  
Entrenamientos de alto enfoque en grupos muy reducidos para maximizar el aprendizaje de cada jugador/a.

**Cómo funcionan**  
- Cada sesión se divide en **dos grupos**: **Minibasket** y **Canasta Grande**.  
- **Máximo 4 jugadores por grupo** (hasta 8 por sesión).  
- Trabajo **individualizado** en: manejo de balón, finalizaciones, tiro, lectura de juego, toma de decisiones, fundamentos defensivos y coordinación.

**Política de Reorganización de Grupos: Si en una categoría hay menos de 3 jugadores inscritos y en la otra hay lista de espera, se cancelará la sesión con menor asistencia para abrir una adicional en la categoría con más demanda.**
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

    today = dt.date.today()

    # Solo sesiones futuras (>= hoy)
    fechas_disponibles = sorted(
        [f for f in SESIONES.keys() if dt.date.fromisoformat(f) >= today]
    )

    # Calendario (opcional)
    fecha_seleccionada = None
    try:
        from streamlit_calendar import calendar

        events = []
        for f in SESIONES.keys():
            fecha_dt = dt.date.fromisoformat(f)
            ocupadas_mini = plazas_ocupadas(f, CATEG_MINI)
            ocupadas_gran = plazas_ocupadas(f, CATEG_GRANDE)

            # Colores: rojo (pasada o ambas llenas), amarillo (una llena), verde (hay hueco)
            if fecha_dt < today:
                color = "#dc3545"  # pasada
            else:
                full_mini = ocupadas_mini >= MAX_POR_CANASTA
                full_gran = ocupadas_gran >= MAX_POR_CANASTA
                if full_mini and full_gran:
                    color = "#dc3545"
                elif full_mini or full_gran:
                    color = "#ffc107"
                else:
                    color = "#28a745"

            # Fondo (no para hoy)
            if fecha_dt != today:
                events.append({
                    "title": "",
                    "start": f,
                    "end": f,
                    "display": "background",
                    "backgroundColor": color,
                })

            # Etiqueta solo con hora (o "Cancelada")
            hora = SESIONES.get(f, "Cancelada")
            label = hora if hora != "Cancelada" else "Cancelada"
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
            # Aceptar solo si es sesión válida y no pasada
            if fclicked in SESIONES and dt.date.fromisoformat(fclicked) >= today:
                fecha_seleccionada = fclicked
    except Exception:
        pass
    
    # >>> Leyenda del calendario
    st.caption("🟥 Rojo: no hay plazas · 🟨 Amarillo: plazas en un grupo · 🟩 Verde: plazas en ambos grupos")

    # Si no viene del calendario, usar selectbox con solo futuras
    if not fecha_seleccionada:
        st.subheader("📅 Selecciona fecha")
        if fechas_disponibles:
            etiqueta = {f: f"{dt.datetime.strptime(f,'%Y-%m-%d').strftime('%d/%m/%Y')}  ·  {SESIONES[f]}" for f in fechas_disponibles}
            fecha_seleccionada = st.selectbox(
                "Fechas con sesión",
                options=fechas_disponibles,
                format_func=lambda f: etiqueta[f]
            )
        else:
            st.info("De momento no hay fechas futuras disponibles.")
            st.stop()

    # Bloque de reserva
    fkey = fecha_seleccionada
    hora_sesion = SESIONES.get(fkey, "—")
    st.write(f"### Sesión del **{dt.datetime.strptime(fkey,'%Y-%m-%d').strftime('%d/%m/%Y')}** a las **{hora_sesion}**")

    libres_mini = plazas_libres(fkey, CATEG_MINI)
    libres_gran = plazas_libres(fkey, CATEG_GRANDE)

    # >>> Aviso de capacidad + info de plazas
    avisos = []
    if libres_mini <= 0:
        avisos.append("**Minibasket** está **COMPLETA**. Si seleccionas esta categoría te apuntaremos a **lista de espera**.")
    if libres_gran <= 0:
        avisos.append("**Canasta grande** está **COMPLETA**. Si seleccionas esta categoría te apuntaremos a **lista de espera**.")

    # Warning único si hay categorías completas
    if avisos:
        st.warning("⚠️ " + "  \n• ".join([""] + avisos))

    # Mostrar info de plazas siempre que no estén las dos completas
    ambas_completas = (libres_mini <= 0 and libres_gran <= 0)
    if not ambas_completas:
        if libres_mini > 0 and libres_gran <= 0:
            st.info(f"Plazas libres · {CATEG_MINI}: {libres_mini}/{MAX_POR_CANASTA}")
        elif libres_gran > 0 and libres_mini <= 0:
            st.info(f"Plazas libres · {CATEG_GRANDE}: {libres_gran}/{MAX_POR_CANASTA}")
        else:
            st.info(
                f"Plazas libres · {CATEG_MINI}: {libres_mini}/{MAX_POR_CANASTA}  ·  "
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
    
        # 🎈 La celebración va FUERA (sin else)
        if st.session_state.pop(celebrate_key, False) and data.get("status") == "ok":
            st.toast("✅ Inscripción realizada correctamente", icon="✅")
            st.balloons()
    
    else:
        # ---- Autorrelleno seguro por código ----
        codigo_cookie = (cookies.get("family_code") or "").strip()
        codigo_familia = st.text_input(
            "🔐 Código de familia (opcional)",
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
                st.rerun()
    
        if st.button("✨ Autorrellenar con código", key=f"autofill_{fkey}_{hkey}"):
            fam = get_familia_por_codigo(codigo_familia)
            if not fam:
                st.error("Código no válido (o no encontrado).")
            else:
                hijos = get_hijos_por_codigo(codigo_familia)
    
                st.session_state[f"padre_{fkey}_{hkey}"] = fam.get("tutor","")
                st.session_state[f"telefono_{fkey}_{hkey}"] = fam.get("telefono","")
                st.session_state[f"email_{fkey}_{hkey}"] = fam.get("email","")
    
                if hijos:
                    st.session_state[f"hijos_{fkey}_{hkey}"] = hijos
    
                if recordar_dispositivo:
                    cookies["family_code"] = fam["codigo"]
                    cookies.save()
    
                st.success("Datos cargados.")
                st.rerun()
    
        # ==========================
        # ⚡ RESERVA RÁPIDA
        # ==========================
        hijos_cargados = st.session_state.get(f"hijos_{fkey}_{hkey}", [])
        if hijos_cargados:
            st.markdown("### ⚡ Reserva rápida (jugador guardado)")
    
            def _fmt_h(r):
                return f"{to_text(r.get('jugador','—'))} · {to_text(r.get('equipo','—'))} · {to_text(r.get('canasta','—'))}"
    
            sel_h = st.selectbox(
                "Selecciona jugador guardado",
                options=hijos_cargados,
                format_func=_fmt_h,
                key=f"selh_{fkey}_{hkey}"
            )
    
            # (tu bloque de botones Reservar directamente / Editar con formulario aquí, sin cambios)
            st.divider()
    
        # ==========================
        # FORMULARIO NORMAL
        # ==========================
        with placeholder.form(f"form_{fkey}_{hkey}", clear_on_submit=False):
            guardar_familia = st.checkbox(
                "💾 Guardar estos datos para próximas reservas (con código de familia)",
                value=True,
                key=f"savefam_{fkey}_{hkey}"
            )
    
            st.write("📝 Información del jugador")
            nombre = st.text_input("Nombre y apellidos del jugador", key=f"nombre_{fkey}_{hkey}")
    
            opciones_canasta = []
            if get_estado_grupo_mem(fkey, hkey, CATEG_MINI) == "ABIERTA":
                opciones_canasta.append(CATEG_MINI)
            if get_estado_grupo_mem(fkey, hkey, CATEG_GRANDE) == "ABIERTA":
                opciones_canasta.append(CATEG_GRANDE)
    
            canasta = st.radio("Canasta", opciones_canasta, key=f"canasta_{fkey}_{hkey}")
            err_canasta = st.empty()
    
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
    
            enviar = st.form_submit_button("Reservar")
    
            if enviar:
                # (tu lógica de validación + append_row + ok_flag/ok_data_key tal cual)
                pass
