with placeholder.form(f"form_{fkey}_{hkey}", clear_on_submit=True):
    st.write("📝 Información del jugador")

    # Radio con clave para poder forzarlo
    canasta_key = f"canasta_{fkey}_{hkey}"
    nombre = st.text_input("Nombre y apellidos del jugador", key=f"nombre_{fkey}_{hkey}")
    canasta = st.radio("Canasta", [CATEG_MINI, CATEG_GRANDE], horizontal=True, key=canasta_key)

    equipo_sel = st.selectbox("Categoría / Equipo", EQUIPOS_OPCIONES, index=0, key=f"equipo_sel_{fkey}_{hkey}")
    equipo_otro = st.text_input("Especifica la categoría/equipo", key=f"equipo_otro_{fkey}_{hkey}") if equipo_sel == "Otro" else ""
    equipo_val = equipo_sel if (equipo_sel and equipo_sel not in ("— Selecciona —", "Otro")) else (equipo_otro or "").strip()

    # 🔒 Forzar Minibasket si es Benjamín/Alevín (también actualiza el radio visualmente)
    if _force_mini_from_equipo(equipo_val):
        if st.session_state.get(canasta_key) != CATEG_MINI:
            st.session_state[canasta_key] = CATEG_MINI
            st.info("Categoría Benjamín/Alevín → asignada automáticamente a **Minibasket**.")
        canasta = CATEG_MINI  # por si ya venía del state

    padre = st.text_input("Nombre del padre/madre/tutor", key=f"padre_{fkey}_{hkey}")
    telefono = st.text_input("Teléfono de contacto del tutor", key=f"telefono_{fkey}_{hkey}")
    email = st.text_input("Email", key=f"email_{fkey}_{hkey}")

    st.caption("Tras pulsar **Reservar**, debe aparecer el botón **“⬇️ Descargar justificante (PDF)”**. Si no aparece, la reserva no se ha completado.")

    enviar = st.form_submit_button("Reservar")

    if enviar:
        errores = []
        if not nombre: errores.append("**nombre del jugador**")
        if not telefono: errores.append("**teléfono**")
        if not equipo_val: errores.append("**categoría/equipo** (obligatorio)")

        if errores:
            st.error("Por favor, rellena: " + ", ".join(errores) + ".")
        else:
            # ⚠️ Recalcular canasta final por si el padre cambia equipo justo antes de enviar
            final_canasta = CATEG_MINI if _force_mini_from_equipo(equipo_val) else canasta

            ya = ya_existe_en_sesion_mem(fkey, hkey, nombre)
            if ya == "inscripciones":
                st.error("❌ Este jugador ya está inscrito en esta sesión.")
            elif ya == "waitlist":
                st.warning("ℹ️ Este jugador ya está en lista de espera para esta sesión.")
            else:
                libres_cat = plazas_libres_mem(fkey, hkey, final_canasta)
                row = [
                    dt.datetime.now().isoformat(timespec="seconds"),
                    fkey, hora_sesion, nombre, final_canasta,
                    (equipo_val or ""), (padre or ""), telefono, (email or "")
                ]
                if libres_cat <= 0:
                    append_row("waitlist", row)
                    st.session_state[ok_flag] = True
                    st.session_state[ok_data_key] = {
                        "status": "wait",
                        "fecha_iso": fkey,
                        "fecha_txt": pd.to_datetime(fkey).strftime("%d/%m/%Y"),
                        "hora": hora_sesion,
                        "nombre": nombre,
                        "canasta": final_canasta,
                        "equipo": (equipo_val or "—"),
                        "tutor": (padre or "—"),
                        "telefono": telefono,
                        "email": (email or "—"),
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
                        "canasta": final_canasta,
                        "equipo": (equipo_val or "—"),
                        "tutor": (padre or "—"),
                        "telefono": telefono,
                        "email": (email or "—"),
                    }
                    st.session_state[celebrate_key] = True
                    st.rerun()
