# ===========================
# app.py — Tecnificaciones CBC
# ===========================

import streamlit as st
import pandas as pd
from io import BytesIO
import datetime as dt
import os
import re
import time

# ====== AJUSTES GENERALES ======
st.set_page_config(page_title="Tecnificaciones CBC", layout="centered")
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
    st.error("Faltan credenciales de Google en secrets.")
    st.stop()

_SID = st.secrets.get("SHEETS_SPREADSHEET_ID")
_SID_BLOCK = (st.secrets.get("sheets") or {}).get("sheet_id")
if not (_SID or _SID_BLOCK):
    st.error("Configura SHEETS_SPREADSHEET_ID en secrets.")
    st.stop()

# ====== UTILS ======
def read_secret(key: str, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, default)

def _norm_name(s: str) -> str:
    return " ".join((s or "").split()).casefold()

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
        return f"{hh:02d}:{mm:02d}"
    try:
        return dt.datetime.strptime(h[:5], "%H:%M").strftime("%H:%M")
    except Exception:
        return h

def _norm_fecha_iso(x) -> str:
    if isinstance(x, (dt.date, dt.datetime)):
        return (x.date() if isinstance(x, dt.datetime) else x).isoformat()
    try:
        return pd.to_datetime(x, dayfirst=True).date().isoformat()
    except Exception:
        return ""

def hora_mas(h: str, minutos: int) -> str:
    try:
        t = dt.datetime.strptime(h, "%H:%M") + dt.timedelta(minutes=minutos)
        return t.strftime("%H:%M")
    except Exception:
        return h

def texto_plazas(libres: int) -> tuple[str, str]:
    if libres <= 0:
        return "warning", "🔴 **Completa** → lista de espera"
    if libres == 1:
        return "warning", "🟡 **Última plaza**"
    return "info", "🟢 **Plazas disponibles**"

# ====== GOOGLE SHEETS ======
import gspread
from gspread.exceptions import WorksheetNotFound, APIError
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

def _gc():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=SCOPES
    )
    return gspread.authorize(creds)

def _open_sheet():
    gc = _gc()
    sheet_id = _SID or _SID_BLOCK
    return gc.open_by_key(sheet_id)

_EXPECTED_HEADERS = ["timestamp","fecha_iso","hora","nombre","canasta","equipo","tutor","telefono","email"]

@st.cache_data(ttl=60)
def _load_ws_df_cached(sheet_name: str) -> pd.DataFrame:
    sh = _open_sheet()
    ws = sh.worksheet(sheet_name)
    vals = ws.get_all_values()
    if not vals:
        if sheet_name == "sesiones":
            return pd.DataFrame(columns=["fecha_iso","hora","estado","estado_mini","estado_grande"])
        return pd.DataFrame(columns=_EXPECTED_HEADERS)

    df = pd.DataFrame(vals[1:], columns=[h.strip() for h in vals[0]])

    if sheet_name == "sesiones":
        for c in ["fecha_iso","hora","estado","estado_mini","estado_grande"]:
            if c not in df.columns:
                df[c] = ""
        df["fecha_iso"] = df["fecha_iso"].map(_norm_fecha_iso)
        df["hora"] = df["hora"].map(_norm_hora)
        df["estado"] = df["estado"].replace("", "ABIERTA").str.upper()
        df["estado_mini"] = df["estado_mini"].replace("", "ABIERTA").str.upper()
        df["estado_grande"] = df["estado_grande"].replace("", "ABIERTA").str.upper()
    else:
        df["fecha_iso"] = df["fecha_iso"].map(_norm_fecha_iso)
        df["hora"] = df["hora"].map(_norm_hora)
        df["canasta"] = df["canasta"].astype(str)

    return df

@st.cache_data(ttl=60)
def load_all_data():
    sh = _open_sheet()
    try:
        sh.worksheet("sesiones")
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

# ====== LÓGICA DE ESTADOS ======
def _match_canasta(valor: str, objetivo: str) -> bool:
    v = (valor or "").lower()
    o = objetivo.lower()
    return v.startswith(o.split()[0])

def get_sesion_info_mem(fecha_iso: str, hora: str) -> dict:
    df = load_all_data()["sesiones"]
    m = df[(df["fecha_iso"] == fecha_iso) & (df["hora"] == hora)]
    if m.empty:
        return {"estado":"ABIERTA","estado_mini":"ABIERTA","estado_grande":"ABIERTA","hora":hora}
    r = m.iloc[0]
    return {
        "hora": r["hora"],
        "estado": r["estado"],
        "estado_mini": r["estado_mini"],
        "estado_grande": r["estado_grande"],
    }

def get_estado_grupo_mem(fecha_iso: str, hora: str, canasta: str) -> str:
    info = get_sesion_info_mem(fecha_iso, hora)
    if info["estado"] == "CERRADA":
        return "CERRADA"
    return info["estado_mini"] if _match_canasta(canasta, CATEG_MINI) else info["estado_grande"]

def plazas_ocupadas_mem(fecha_iso: str, hora: str, canasta: str) -> int:
    df = load_all_data()["ins"]
    m = df[(df["fecha_iso"] == fecha_iso) & (df["hora"] == hora)]
    return sum(_match_canasta(r["canasta"], canasta) for _, r in m.iterrows())

def plazas_libres_mem(fecha_iso: str, hora: str, canasta: str) -> int:
    if get_estado_grupo_mem(fecha_iso, hora, canasta) == "CERRADA":
        return 0
    return max(0, MAX_POR_CANASTA - plazas_ocupadas_mem(fecha_iso, hora, canasta))

# ====== ESCRITURAS ======
def _retry(call, *args):
    for _ in range(5):
        try:
            return call(*args)
        except APIError:
            time.sleep(1)
    raise RuntimeError("Error Google Sheets")

def append_row(sheet_name: str, row: list):
    ws = _open_sheet().worksheet(sheet_name)
    _retry(ws.append_row, row)
    load_all_data.clear()

def set_estado_sesion(fecha_iso: str, hora: str, estado: str):
    ws = _open_sheet().worksheet("sesiones")
    rows = ws.get_all_values()
    for i, r in enumerate(rows[1:], start=2):
        if r[0] == fecha_iso and r[1] == hora:
            ws.update_cell(i, 3, estado)
            load_all_data.clear()
            return

def set_estado_grupo(fecha_iso: str, hora: str, canasta: str, estado: str):
    ws = _open_sheet().worksheet("sesiones")
    rows = ws.get_all_values()
    col = 4 if _match_canasta(canasta, CATEG_MINI) else 5
    for i, r in enumerate(rows[1:], start=2):
        if r[0] == fecha_iso and r[1] == hora:
            ws.update_cell(i, col, estado)
            load_all_data.clear()
            return

def delete_sesion(fecha_iso: str, hora: str):
    ws = _open_sheet().worksheet("sesiones")
    rows = ws.get_all_values()
    for i, r in enumerate(rows[1:], start=2):
        if r[0] == fecha_iso and r[1] == hora:
            ws.delete_rows(i)
            load_all_data.clear()
            return

# ====== ADMIN ======
params = st.query_params
show_admin = params.get(ADMIN_QUERY_FLAG, ["0"])[0] == "1"

if show_admin:
    st.title("🛠️ Panel de administración")

    if not st.session_state.get("is_admin"):
        pwd = st.text_input("Contraseña", type="password")
        if st.button("Entrar") and pwd == read_secret("ADMIN_PASS"):
            st.session_state.is_admin = True
            st.rerun()
    else:
        data = load_all_data()
        df = data["sesiones"]

        if not df.empty:
            opciones = [(r["fecha_iso"], r["hora"]) for _, r in df.iterrows()]
            fsel, hsel = st.selectbox("Sesión", opciones, format_func=lambda x: f"{x[0]} · {x[1]}")

            st.markdown("#### Acción rápida sobre la sesión")
            accion = st.selectbox(
                "Acción",
                [
                    "— Selecciona —",
                    "Abrir TODO",
                    "Cerrar TODO",
                    "Abrir solo Minibasket",
                    "Cerrar solo Minibasket",
                    "Abrir solo Canasta grande",
                    "Cerrar solo Canasta grande",
                    "Eliminar sesión",
                ],
            )

            if st.button("✅ Aplicar"):
                if accion == "Abrir TODO":
                    set_estado_sesion(fsel, hsel, "ABIERTA")
                    set_estado_grupo(fsel, hsel, CATEG_MINI, "ABIERTA")
                    set_estado_grupo(fsel, hsel, CATEG_GRANDE, "ABIERTA")
                elif accion == "Cerrar TODO":
                    set_estado_sesion(fsel, hsel, "CERRADA")
                elif accion == "Abrir solo Minibasket":
                    set_estado_sesion(fsel, hsel, "ABIERTA")
                    set_estado_grupo(fsel, hsel, CATEG_MINI, "ABIERTA")
                elif accion == "Cerrar solo Minibasket":
                    set_estado_grupo(fsel, hsel, CATEG_MINI, "CERRADA")
                elif accion == "Abrir solo Canasta grande":
                    set_estado_sesion(fsel, hsel, "ABIERTA")
                    set_estado_grupo(fsel, hsel, CATEG_GRANDE, "ABIERTA")
                elif accion == "Cerrar solo Canasta grande":
                    set_estado_grupo(fsel, hsel, CATEG_GRANDE, "CERRADA")
                elif accion == "Eliminar sesión":
                    delete_sesion(fsel, hsel)
                st.rerun()

else:
    # ====== USUARIO ======
    st.title(APP_TITLE)

    data = load_all_data()
    df = data["sesiones"]

    if df.empty:
        st.info("No hay sesiones disponibles.")
        st.stop()

    opciones = [(r["fecha_iso"], r["hora"]) for _, r in df.iterrows() if r["estado"] == "ABIERTA"]
    fkey, hkey = st.selectbox("Selecciona sesión", opciones, format_func=lambda x: f"{x[0]} · {x[1]}")

    libres_m = plazas_libres_mem(fkey, hkey, CATEG_MINI)
    libres_g = plazas_libres_mem(fkey, hkey, CATEG_GRANDE)

    for cat, libres in [(CATEG_MINI, libres_m), (CATEG_GRANDE, libres_g)]:
        lvl, txt = texto_plazas(libres)
        getattr(st, lvl)(f"**{cat}:** {txt}")

    st.info("Formulario de reserva aquí (sin cambios respecto al tuyo).")
