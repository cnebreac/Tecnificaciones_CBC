import streamlit as st
import pandas as pd
from io import BytesIO
import datetime

st.set_page_config(page_title="Tecnificación Baloncesto", layout="centered")

st.title("🏀 Reserva de Sesiones - Tecnificación Baloncesto")

# ---- Datos iniciales ----
# Para demo: sesiones de lunes a viernes a las 17:00
dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
sesiones = {dia: [] for dia in dias}  # Inscripciones por día (demo en memoria)

# Inicializamos en sesión Streamlit (para que persista mientras está abierta la app)
if "inscripciones" not in st.session_state:
    st.session_state.inscripciones = {dia: [] for dia in dias}

st.subheader("📅 Selecciona un día de la semana")

dia_sel = st.selectbox("Día disponible", dias)

st.write(f"### Sesión del {dia_sel} a las 17:00")
plazas_ocupadas = len(st.session_state.inscripciones[dia_sel])
plazas_libres = 4 - plazas_ocupadas

st.info(f"Plazas ocupadas: {plazas_ocupadas} / 4")

if plazas_libres > 0:
    with st.form(f"form_{dia_sel}"):
        st.write("📝 Información del jugador")
        nombre = st.text_input("Nombre y apellidos del jugador")
        edad = st.number_input("Edad", min_value=6, max_value=18, step=1)
        nivel = st.selectbox("Nivel", ["Iniciación", "Medio", "Avanzado"])
        padre = st.text_input("Nombre del padre/madre/tutor")
        email = st.text_input("Email de contacto")
        enviar = st.form_submit_button("Reservar plaza")

        if enviar:
            if nombre and email:
                st.session_state.inscripciones[dia_sel].append({
                    "Día": dia_sel,
                    "Nombre": nombre,
                    "Edad": edad,
                    "Nivel": nivel,
                    "Padre/Madre": padre,
                    "Email": email
                })
                st.success("✅ Inscripción realizada correctamente")
            else:
                st.error("Por favor, rellena al menos nombre y email")
else:
    st.warning("⚠️ No hay plazas disponibles para esta sesión")

st.divider()

# ---- Admin / Descarga ----
st.subheader("📥 Descargar inscripciones (para administradores)")
dia_admin = st.selectbox("Selecciona día para exportar", dias, key="admin")

if st.button("Generar Excel de inscripciones"):
    df = pd.DataFrame(st.session_state.inscripciones[dia_admin])
    if not df.empty:
        output = BytesIO()
        df.to_excel(output, index=False)
        st.download_button(
            label="📥 Descargar Excel",
            data=output,
            file_name=f"inscripciones_{dia_admin}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("No hay inscripciones todavía para este día")
