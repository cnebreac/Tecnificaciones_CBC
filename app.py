### conda activate basketapp
### streamlit run /Users/cnebreac/Desktop/Tecnificaciones_CBC/app.py
### URL Admin + '?admin=1' y contraseña 'tecnifi2025' 

import streamlit as st
import pandas as pd
from io import BytesIO
import datetime as dt
import os

# ====== CONFIGURACIÓN DE SESIONES DISPONIBLES ======
SESIONES = {
    "2025-10-05": "16:30",
    "2025-09-05": "16:30",
    "2025-10-11": "11:00",
    "2025-10-16": "10:00",
}

# Capacidad por categoría
MAX_POR_CANASTA = 4
CATEG_MINI = "Minibasket"
CATEG_GRANDE = "Canasta grande"

# ====== CHEQUEOS DE SECRETS (SIN USAR VARIABLES NO DEFINIDAS) ======
if "gcp_service_account" not in st.secrets:
    st.error("Faltan credenciales de Google en secrets: bloque [gcp_service_account].")
    st.stop()

# lee posibles formas de identificar la hoja sin usar SHEET_ID todavía
_SID = st.secrets.get("SHEETS_SPREADSHEET_ID")
_URL = st.secrets.get("SHEETS_SPREADSHEET_URL")
_SID_BLOCK = (st.secrets.get("sheets") or {}).get("sheet_id")

if not (_SID or _URL or _SID_BLOCK):
    st.error("Configura en secrets la hoja: SHEETS_SPREADSHEET_ID o SHEETS_SPREADSHEET_URL (o [sheets].sheet_id).")
    st.stop()

# ====== AJUSTES GENERALES ======
st.set_page_config(page_title="Tecnificación Baloncesto", layout="centered")
APP_TITLE = "🏀 Reserva de Sesiones - Tecnificación Baloncesto"
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

# (opcional) por si quieres seguir exponiendo SHEET_ID
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
    sh = _open_sheet()
    ws = sh.worksheet(sheet_name)
    ws.append_row(values, value_input_option="USER_ENTERED")

def get_inscripciones_por_fecha(fecha_iso: str) -> list:
    df = load_df("inscripciones")
    if df.empty:
        return []
    need = ["timestamp","fecha_iso","hora","nombre","canasta","equipo","tutor","telefono"]
    for c in need:
        if c not in df.columns:
            df[c] = ""
    return df[df["fecha_iso"] == fecha_iso][need].to_dict("records")

def get_waitlist_por_fecha(fecha_iso: str) -> list:
    df = load_df("waitlist")
    if df.empty:
        return []
    need = ["timestamp","fecha_iso","hora","nombre","canasta", "equipo", "tutor","telefono"]
    for c in need:
        if c not in df.columns:
            df[c] = ""
    return df[df["fecha_iso"] == fecha_iso][need].to_dict("records")

# ====== CAPACIDAD POR CATEGORÍA ======
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

# ====== PDF ======
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

    # hora: prioriza la guardada en registros; si no, la de SESIONES
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
        t = (text or "")
        if stringWidth(t, font, size) <= max_w:
            return t
        ell = "…"
        ell_w = stringWidth(ell, font, size)
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
    x_tutor = x_cat
    x_tel   = x_team

    # Anchos máximos
    w_name  = (x_cat  - x_name) - 0.2*cm
    w_cat   = (x_team - x_cat)  - 0.2*cm
    w_team  = (right  - x_team)
    w_tutor = (x_tel  - x_tutor) - 0.3*cm
    w_tel   = (right  - x_tel)

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

            # Línea 1
            c.setFont("Helvetica", 10)
            c.drawString(x_num,  y, to_text(i))
            c.drawString(x_name, y, fit_text(c, nombre, w_name))
            c.drawString(x_cat,  y, fit_text(c, cat,   w_cat))
            c.drawString(x_team, y, fit_text(c, team,  w_team))

            # Línea 2 (Tutor y Tel.)
            y -= line_spacing
            c.setFont("Helvetica", 9)
            c.drawString(x_tutor, y, "Tutor: " + fit_text(c, tutor, w_tutor, size=9))
            c.drawString(x_tel,   y, "Tel.: "  + fit_text(c, tel,   w_tel,   size=9))

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

            # Botón PDF abajo, ocupa el mismo ancho
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
    st.caption("Reserva solo en las fechas activas. Si no ves tu fecha, es que no hay sesión ese día.")

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

            # Colores:
            # - rojo: pasada o ambas categorías completas
            # - amarillo: se completó 1 categoría
            # - verde: queda hueco en ambas
            if fecha_dt < today:
                color = "#dc3545"  # pasada
            else:
                full_mini = ocupadas_mini >= MAX_POR_CANASTA
                full_gran = ocupadas_gran >= MAX_POR_CANASTA
                if full_mini and full_gran:
                    color = "#dc3545"  # ambas completas -> rojo
                elif full_mini or full_gran:
                    color = "#ffc107"  # una completa -> amarillo
                else:
                    color = "#28a745"  # hay hueco -> verde

            # Fondo (no para hoy)
            if fecha_dt != today:
                events.append({
                    "title": "",
                    "start": f,
                    "end": f,
                    "display": "background",
                    "backgroundColor": color,
                })

            # Tooltip informativo
            hora = SESIONES.get(f, "Cancelada")
            estado = []
            if fecha_dt < today:
                estado.append("PASADA")
            else:
                if ocupadas_mini >= MAX_POR_CANASTA: estado.append("Mini completa")
                if ocupadas_gran >= MAX_POR_CANASTA: estado.append("Grande completa")
            tooltip = f"Sesión {hora}" + (f" — {' · '.join(estado)}" if estado else "")
            events.append({
                "title": tooltip,
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

    # Avisos grandes si alguna categoría está completa
    if libres_mini == 0:
        st.warning("⚠️ **Minibasket está COMPLETA.** Si seleccionas esta categoría te apuntaremos a **lista de espera**.")
    if libres_gran == 0:
        st.warning("⚠️ **Canasta grande está COMPLETA.** Si seleccionas esta categoría te apuntaremos a **lista de espera**.")

    st.info(f"Plazas libres · {CATEG_MINI}: {libres_mini}/{MAX_POR_CANASTA}  ·  {CATEG_GRANDE}: {libres_gran}/{MAX_POR_CANASTA}")

    # ⬇️ Formulario con autolimpieza
    with st.form(f"form_{fkey}", clear_on_submit=True):
        st.write("📝 Información del jugador")
        nombre = st.text_input("Nombre y apellidos del jugador", key=f"nombre_{fkey}")
        canasta = st.radio("Categoría", [CATEG_MINI, CATEG_GRANDE], horizontal=True)
        equipo = st.text_input("Equipo", key=f"equipo_{fkey}")
        padre = st.text_input("Nombre del padre/madre/tutor", key=f"padre_{fkey}")
        telefono = st.text_input("Teléfono de contacto del tutor", key=f"telefono_{fkey}")
        enviar = st.form_submit_button("Reservar")

        if enviar:
            if nombre and telefono:
                # Duplicados por nombre y apellidos
                ya = ya_existe_en_sesion(fkey, nombre)
                if ya == "inscripciones":
                    st.error("❌ Este jugador **ya está inscrito** en esta sesión.")
                elif ya == "waitlist":
                    st.warning("ℹ️ Este jugador **ya está en lista de espera** para esta sesión.")
                else:
                    libres_cat = plazas_libres(fkey, canasta)
                    if libres_cat <= 0:
                        st.warning("⚠️ No hay plazas en esta categoría. Te pasamos a **lista de espera**.")
                        append_row("waitlist", [
                            dt.datetime.now().isoformat(timespec="seconds"),
                            fkey, hora_sesion, nombre, canasta, (equipo or ""), (padre or ""), telefono
                        ])
                    else:
                        append_row("inscripciones", [
                            dt.datetime.now().isoformat(timespec="seconds"),
                            fkey, hora_sesion, nombre, canasta, (equipo or ""), (padre or ""), telefono
                        ])
                        st.success("✅ Inscripción realizada correctamente")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Por favor, rellena al menos: **nombre** y **teléfono**.")


