import re
import uuid

import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime

# -----------------------------
# Configuración
# -----------------------------
st.set_page_config(page_title="Registro de Tratamientos", page_icon="🦷", layout="wide")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

ID_HOJA = "117m17ax3UznyF3iLpEBWpIbDvhYUtLb8bTMqdwRm7FU"   # ID de tu Google Sheet (de la URL)

TAB_CATALOGO = "Catalogo"   # columnas: Tratamiento | Precio
TAB_CITAS = "Citas"         # columnas: ID | Fecha | ClienteID | Tratamiento | Precio | Observaciones (una fila por tratamiento, mismo ID agrupa la cita)
TAB_CLIENTES = "Clientes"   # columnas: ID | RUT | Nombre | Telefono | Email | FechaNacimiento | Direccion | FechaRegistro | Notas

CITAS_COLUMNAS = ["ID", "Fecha", "ClienteID", "Tratamiento", "Precio", "Observaciones"]
CLIENTES_COLUMNAS = [
    "ID", "RUT", "Nombre", "Telefono", "Email",
    "FechaNacimiento", "Direccion", "FechaRegistro", "Notas",
]


def formatear_rut(rut):
    limpio = re.sub(r"[^0-9kK]", "", rut or "")
    if len(limpio) < 2:
        return limpio.upper()
    cuerpo, dv = limpio[:-1], limpio[-1].upper()
    return f"{cuerpo}-{dv}"


def parsear_fecha(texto):
    if not texto:
        return None
    try:
        return datetime.strptime(texto, "%d/%m/%Y").date()
    except ValueError:
        return None


# -----------------------------
# Conexión a Google Sheets
# -----------------------------
@st.cache_resource
def conectar_sheets():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    client = gspread.authorize(creds)
    return client.open_by_key(ID_HOJA)


def get_worksheet(nombre_tab):
    sh = conectar_sheets()
    return sh.worksheet(nombre_tab)


@st.cache_data(ttl=60)
def cargar_catalogo():
    ws = get_worksheet(TAB_CATALOGO)
    data = ws.get_all_records(value_render_option="UNFORMATTED_VALUE")
    df = pd.DataFrame(data)
    if df.empty:
        return pd.DataFrame(columns=["Tratamiento", "Precio"])
    df["Precio"] = pd.to_numeric(df["Precio"], errors="coerce").fillna(0)
    return df


@st.cache_data(ttl=60)
def cargar_clientes():
    ws = get_worksheet(TAB_CLIENTES)
    data = ws.get_all_records(value_render_option="UNFORMATTED_VALUE")
    df = pd.DataFrame(data)
    if df.empty:
        return pd.DataFrame(columns=CLIENTES_COLUMNAS)
    for col in CLIENTES_COLUMNAS:
        if col not in df.columns:
            df[col] = ""
    return df.astype(str)


@st.cache_data(ttl=30)
def cargar_citas():
    """Cada fila es UN tratamiento. Varias filas comparten el mismo ID = una cita."""
    ws = get_worksheet(TAB_CITAS)
    data = ws.get_all_records(value_render_option="UNFORMATTED_VALUE")
    df = pd.DataFrame(data)
    if df.empty:
        return pd.DataFrame(columns=CITAS_COLUMNAS)
    if "Observaciones" not in df.columns:
        df["Observaciones"] = ""
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce", dayfirst=True)
    df["Precio"] = pd.to_numeric(df["Precio"], errors="coerce").fillna(0)
    df["Observaciones"] = df["Observaciones"].fillna("").astype(str)
    return df


def agrupar_citas(citas):
    """Colapsa las filas por tratamiento a una fila por cita (mismo ID)."""
    if citas.empty:
        return citas.assign(Tratamientos="", Total=0.0)
    return (
        citas.groupby(["ID", "Fecha", "ClienteID"], as_index=False)
        .agg(
            Tratamientos=("Tratamiento", lambda x: ", ".join(x)),
            Total=("Precio", "sum"),
            Observaciones=("Observaciones", "first"),
        )
    )


def fila_segun_encabezado(encabezado, valores):
    """valores: dict columna->valor. Arma la fila en el mismo orden que el encabezado real
    de la hoja, para no depender de que las columnas estén en un orden fijo."""
    return [valores.get(col, "") for col in encabezado]


def eliminar_filas_por_id(ws, valor_id):
    """Elimina todas las filas donde la columna 'ID' sea igual a valor_id."""
    all_values = ws.get_all_values()
    encabezado = all_values[0]
    idx_id = encabezado.index("ID")
    filas_borrar = [
        i + 1
        for i, row in enumerate(all_values)
        if i > 0 and len(row) > idx_id and row[idx_id] == valor_id
    ]
    for fila in sorted(filas_borrar, reverse=True):
        ws.delete_rows(fila)
    return len(filas_borrar)


def guardar_cliente(nombre, rut, telefono, email, fecha_nacimiento, direccion, notas):
    ws = get_worksheet(TAB_CLIENTES)
    encabezado = ws.row_values(1)
    fecha_nac_str = fecha_nacimiento.strftime("%d/%m/%Y") if fecha_nacimiento else ""
    valores = {
        "ID": uuid.uuid4().hex[:8].upper(),
        "RUT": rut,
        "Nombre": nombre,
        "Telefono": telefono,
        "Email": email,
        "FechaNacimiento": fecha_nac_str,
        "Direccion": direccion,
        "FechaRegistro": date.today().strftime("%d/%m/%Y"),
        "Notas": notas,
    }
    ws.append_row(fila_segun_encabezado(encabezado, valores), value_input_option="RAW")


def actualizar_cliente(cliente_id, nombre, rut, telefono, email, fecha_nacimiento, direccion, notas):
    ws = get_worksheet(TAB_CLIENTES)
    celda = ws.find(cliente_id, in_column=1)
    fila_num = celda.row
    encabezado = ws.row_values(1)
    fila_actual = ws.row_values(fila_num)
    fecha_registro_actual = ""
    if "FechaRegistro" in encabezado:
        idx = encabezado.index("FechaRegistro")
        if idx < len(fila_actual):
            fecha_registro_actual = fila_actual[idx]

    fecha_nac_str = fecha_nacimiento.strftime("%d/%m/%Y") if fecha_nacimiento else ""
    valores = {
        "ID": cliente_id,
        "RUT": rut,
        "Nombre": nombre,
        "Telefono": telefono,
        "Email": email,
        "FechaNacimiento": fecha_nac_str,
        "Direccion": direccion,
        "FechaRegistro": fecha_registro_actual,
        "Notas": notas,
    }
    ws.update(
        f"A{fila_num}",
        [fila_segun_encabezado(encabezado, valores)],
        value_input_option="RAW",
    )


def guardar_cita(fecha, cliente_id, items, observaciones):
    """items: lista de {"Tratamiento": ..., "Precio": ...}. Genera un solo ID de cita
    y guarda una fila por tratamiento, todas con ese mismo ID para poder agruparlas."""
    ws = get_worksheet(TAB_CITAS)
    encabezado = ws.row_values(1)
    cita_id = uuid.uuid4().hex[:8].upper()
    fecha_str = fecha.strftime("%d/%m/%Y")
    filas = []
    for item in items:
        valores = {
            "ID": cita_id,
            "Fecha": fecha_str,
            "ClienteID": cliente_id,
            "Tratamiento": item["Tratamiento"],
            "Precio": float(item["Precio"]),
            "Observaciones": observaciones,
        }
        filas.append(fila_segun_encabezado(encabezado, valores))
    ws.append_rows(filas, value_input_option="RAW")


def eliminar_cliente(cliente_id):
    ws = get_worksheet(TAB_CLIENTES)
    eliminar_filas_por_id(ws, cliente_id)


def eliminar_cita(cita_id):
    ws = get_worksheet(TAB_CITAS)
    eliminar_filas_por_id(ws, cita_id)


def actualizar_cita(cita_id, fecha, cliente_id, items, observaciones):
    """Borra todas las filas de esa cita (mismo ID) y las vuelve a escribir."""
    ws = get_worksheet(TAB_CITAS)
    eliminar_filas_por_id(ws, cita_id)
    encabezado = ws.row_values(1)

    fecha_str = fecha.strftime("%d/%m/%Y")
    nuevas_filas = []
    for item in items:
        valores = {
            "ID": cita_id,
            "Fecha": fecha_str,
            "ClienteID": cliente_id,
            "Tratamiento": item["Tratamiento"],
            "Precio": float(item["Precio"]),
            "Observaciones": observaciones,
        }
        nuevas_filas.append(fila_segun_encabezado(encabezado, valores))
    ws.append_rows(nuevas_filas, value_input_option="RAW")


# -----------------------------
# Widget reutilizable: carrito de tratamientos
# -----------------------------
def render_carrito(catalogo, carrito_key):
    if carrito_key not in st.session_state:
        st.session_state[carrito_key] = []

    col_sel, col_precio, col_btn = st.columns([3, 1, 1])
    with col_sel:
        tratamiento_sel = st.selectbox(
            "Tratamiento",
            options=catalogo["Tratamiento"].tolist(),
            key=f"{carrito_key}_trat_sel",
        )
    precio_sel = float(
        catalogo.loc[catalogo["Tratamiento"] == tratamiento_sel, "Precio"].iloc[0]
    )
    with col_precio:
        st.metric("Precio", f"${precio_sel:,.0f}")
    with col_btn:
        st.write("")
        st.write("")
        if st.button("➕ Agregar", key=f"{carrito_key}_add_btn"):
            st.session_state[carrito_key].append(
                {"Tratamiento": tratamiento_sel, "Precio": precio_sel}
            )
            st.rerun()

    if not st.session_state[carrito_key]:
        st.info("Todavía no agregaste tratamientos.")
        return None

    carrito_df = pd.DataFrame(st.session_state[carrito_key])
    st.dataframe(carrito_df, use_container_width=True, hide_index=True)

    col_quitar, col_vaciar = st.columns([3, 1])
    with col_quitar:
        idx_quitar = st.selectbox(
            "Quitar un tratamiento agregado",
            options=list(range(len(st.session_state[carrito_key]))),
            format_func=lambda i: (
                f"{st.session_state[carrito_key][i]['Tratamiento']} "
                f"(${st.session_state[carrito_key][i]['Precio']:,.0f})"
            ),
            key=f"{carrito_key}_quitar_sel",
        )
        if st.button("🗑️ Quitar seleccionado", key=f"{carrito_key}_quitar_btn"):
            st.session_state[carrito_key].pop(idx_quitar)
            st.rerun()
    with col_vaciar:
        st.write("")
        st.write("")
        if st.button("Vaciar lista", key=f"{carrito_key}_vaciar_btn"):
            st.session_state[carrito_key] = []
            st.rerun()

    total = carrito_df["Precio"].sum()
    st.metric("Total", f"${total:,.0f}")
    return carrito_df


# -----------------------------
# UI
# -----------------------------
st.title("🦷 Registro de Tratamientos")

tab_clientes, tab_registro, tab_resumen, tab_ficha_cliente = st.tabs(
    ["🧑 Nuevo cliente", "➕ Nueva cita", "📊 Resumen", "📋 Ficha de cliente"]
)

# --- TAB 1: registro y edición de clientes ---
with tab_clientes:
    if "mensaje_cliente_guardado" not in st.session_state:
        st.session_state.mensaje_cliente_guardado = None

    st.subheader("Registrar nuevo cliente")

    with st.form("form_cliente", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            nombre_cliente = st.text_input("Nombre completo")
            rut_cliente = st.text_input("RUT", placeholder="12345678-9")
            telefono_cliente = st.text_input("Teléfono")
        with col2:
            email_cliente = st.text_input("Email")
            fecha_nacimiento = st.date_input(
                "Fecha de nacimiento", value=None, format="DD/MM/YYYY"
            )
            direccion_cliente = st.text_input("Dirección")

        notas_cliente = st.text_area("Notas (alergias, antecedentes médicos, etc.)")

        enviado_cliente = st.form_submit_button("Guardar cliente")

        if enviado_cliente:
            if not nombre_cliente.strip():
                st.error("Falta el nombre del cliente.")
            elif not rut_cliente.strip():
                st.error("Falta el RUT del cliente.")
            else:
                guardar_cliente(
                    nombre_cliente.strip(),
                    formatear_rut(rut_cliente),
                    telefono_cliente.strip(),
                    email_cliente.strip(),
                    fecha_nacimiento,
                    direccion_cliente.strip(),
                    notas_cliente.strip(),
                )
                st.cache_data.clear()
                st.session_state.mensaje_cliente_guardado = (
                    f"Cliente guardado: {nombre_cliente.strip()}"
                )
                st.rerun()

    if st.session_state.mensaje_cliente_guardado:
        st.success(st.session_state.mensaje_cliente_guardado)
        st.session_state.mensaje_cliente_guardado = None

    st.divider()
    st.subheader("Editar cliente existente")
    clientes_editar = cargar_clientes()
    if clientes_editar.empty:
        st.info("Todavía no hay clientes para editar.")
    else:
        opciones_editar = {
            row.ID: f"{row.Nombre} ({row.RUT})" for row in clientes_editar.itertuples()
        }
        cliente_id_editar = st.selectbox(
            "Elegí un cliente",
            options=list(opciones_editar.keys()),
            format_func=lambda cid: opciones_editar[cid],
            key="cliente_id_editar",
        )
        datos = clientes_editar.loc[clientes_editar["ID"] == cliente_id_editar].iloc[0]

        with st.form(f"form_editar_cliente_{cliente_id_editar}"):
            col1, col2 = st.columns(2)
            with col1:
                nombre_e = st.text_input("Nombre completo", value=datos["Nombre"])
                rut_e = st.text_input("RUT", value=datos["RUT"])
                telefono_e = st.text_input("Teléfono", value=datos["Telefono"])
            with col2:
                email_e = st.text_input("Email", value=datos["Email"])
                fecha_nacimiento_e = st.date_input(
                    "Fecha de nacimiento",
                    value=parsear_fecha(datos["FechaNacimiento"]),
                    format="DD/MM/YYYY",
                )
                direccion_e = st.text_input("Dirección", value=datos["Direccion"])
            notas_e = st.text_area("Notas", value=datos["Notas"])

            if st.form_submit_button("Guardar cambios"):
                if not nombre_e.strip():
                    st.error("Falta el nombre del cliente.")
                else:
                    actualizar_cliente(
                        cliente_id_editar,
                        nombre_e.strip(),
                        formatear_rut(rut_e),
                        telefono_e.strip(),
                        email_e.strip(),
                        fecha_nacimiento_e,
                        direccion_e.strip(),
                        notas_e.strip(),
                    )
                    st.cache_data.clear()
                    st.success("Cliente actualizado.")
                    st.rerun()

        confirmar_key = f"confirmar_eliminar_cliente_{cliente_id_editar}"
        if confirmar_key not in st.session_state:
            st.session_state[confirmar_key] = False

        if not st.session_state[confirmar_key]:
            if st.button("🗑️ Eliminar cliente", key=f"btn_eliminar_cliente_{cliente_id_editar}"):
                st.session_state[confirmar_key] = True
                st.rerun()
        else:
            citas_todas = cargar_citas()
            n_citas = 0
            if not citas_todas.empty:
                n_citas = citas_todas.loc[
                    citas_todas["ClienteID"] == cliente_id_editar, "ID"
                ].nunique()

            aviso = f"¿Seguro que querés eliminar a **{datos['Nombre']}**? Esta acción no se puede deshacer."
            if n_citas:
                aviso += (
                    f" Tiene {n_citas} cita(s) registrada(s); van a quedar "
                    "como \"cliente desconocido\" en los reportes."
                )
            st.warning(aviso)
            col_si, col_no = st.columns(2)
            with col_si:
                if st.button(
                    "Sí, eliminar definitivamente",
                    key=f"btn_confirmar_eliminar_cliente_{cliente_id_editar}",
                ):
                    eliminar_cliente(cliente_id_editar)
                    st.cache_data.clear()
                    st.session_state[confirmar_key] = False
                    st.success("Cliente eliminado.")
                    st.rerun()
            with col_no:
                if st.button("Cancelar", key=f"btn_cancelar_eliminar_cliente_{cliente_id_editar}"):
                    st.session_state[confirmar_key] = False
                    st.rerun()

    st.divider()
    st.subheader("Clientes registrados")
    clientes_tabla = cargar_clientes()
    if clientes_tabla.empty:
        st.info("Todavía no hay clientes registrados.")
    else:
        st.dataframe(clientes_tabla, use_container_width=True, hide_index=True)

# --- TAB 2: registro de nueva cita ---
with tab_registro:
    catalogo = cargar_catalogo()
    clientes = cargar_clientes()

    if catalogo.empty:
        st.warning(
            "El catálogo está vacío. Agrega tratamientos y precios en la hoja "
            f"'{TAB_CATALOGO}' de tu Google Sheet."
        )
    elif clientes.empty:
        st.warning(
            "Todavía no hay clientes registrados. Creá uno en la pestaña "
            "'🧑 Nuevo cliente' antes de registrar una cita."
        )
    else:
        if "mensaje_guardado" not in st.session_state:
            st.session_state.mensaje_guardado = None

        opciones_cliente = {
            row.ID: f"{row.Nombre} ({row.RUT})" for row in clientes.itertuples()
        }

        col1, col2 = st.columns(2)
        with col1:
            cliente_id_sel = st.selectbox(
                "Cliente",
                options=list(opciones_cliente.keys()),
                format_func=lambda cid: opciones_cliente[cid],
                key="cliente_id_sel",
            )
        with col2:
            fecha = st.date_input("Fecha", value=date.today(), key="fecha_input")

        st.divider()
        st.subheader("Agregar tratamiento")

        carrito_df = render_carrito(catalogo, "carrito")

        st.divider()

        if carrito_df is not None:
            observaciones_nueva = st.text_area(
                "Observaciones / Acción clínica (opcional)", key="observaciones_input"
            )

            if st.button("✅ Guardar cita", type="primary"):
                total_calculado = carrito_df["Precio"].sum()
                guardar_cita(
                    fecha, cliente_id_sel, st.session_state.carrito,
                    observaciones_nueva.strip(),
                )
                st.cache_data.clear()
                st.session_state.carrito = []
                st.session_state.pop("observaciones_input", None)
                st.session_state.mensaje_guardado = (
                    f"Cita guardada: {opciones_cliente[cliente_id_sel]} — "
                    f"${total_calculado:,.0f}"
                )
                st.rerun()

        if st.session_state.mensaje_guardado:
            st.success(st.session_state.mensaje_guardado)
            st.session_state.mensaje_guardado = None

# --- TAB 3: resumen ---
with tab_resumen:
    citas = cargar_citas()
    clientes = cargar_clientes()

    if citas.empty:
        st.info("Todavía no hay citas registradas.")
    else:
        citas_agrupadas = agrupar_citas(citas).merge(
            clientes[["ID", "Nombre", "RUT"]].rename(columns={"ID": "ClienteID"}),
            on="ClienteID",
            how="left",
        )
        citas_agrupadas["Nombre"] = citas_agrupadas["Nombre"].fillna("(cliente desconocido)")
        citas_agrupadas["RUT"] = citas_agrupadas["RUT"].fillna("")

        st.subheader("Detalle de citas")
        st.dataframe(
            citas_agrupadas[["Fecha", "Nombre", "RUT", "Tratamientos", "Total", "Observaciones"]]
            .sort_values("Fecha", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Resumen por cliente")
            resumen_cliente = (
                citas_agrupadas.groupby(["ClienteID", "Nombre"])
                .agg(Visitas=("ID", "count"), Total_gastado=("Total", "sum"))
                .sort_values("Total_gastado", ascending=False)
                .reset_index()
                .drop(columns=["ClienteID"])
            )
            st.dataframe(resumen_cliente, use_container_width=True, hide_index=True)

        with col2:
            st.subheader("Ingresos por día")
            opciones_rango = {
                "Últimos 7 días": 7,
                "Últimos 14 días": 14,
                "Últimos 30 días": 30,
                "Todo el historial": None,
            }
            rango_sel = st.selectbox("Mostrar", list(opciones_rango.keys()))
            dias = opciones_rango[rango_sel]

            citas_grafico = citas
            if dias is not None:
                fecha_limite = pd.Timestamp(date.today()) - pd.Timedelta(days=dias - 1)
                citas_grafico = citas[citas["Fecha"] >= fecha_limite]

            ingresos = citas_grafico.set_index("Fecha").resample("D")["Precio"].sum()
            st.bar_chart(ingresos)

        st.divider()
        st.metric("Ingreso total registrado", f"${citas['Precio'].sum():,.0f}")

# --- TAB 4: ficha de cliente (historial de citas por cliente) ---
with tab_ficha_cliente:
    clientes = cargar_clientes()
    citas = cargar_citas()
    catalogo = cargar_catalogo()

    if clientes.empty:
        st.info(
            "Todavía no hay clientes registrados. Creá uno en la pestaña "
            "'🧑 Nuevo cliente'."
        )
    else:
        opciones_cliente = {
            row.ID: f"{row.Nombre} ({row.RUT})" for row in clientes.itertuples()
        }
        cliente_id_ver = st.selectbox(
            "Cliente",
            options=list(opciones_cliente.keys()),
            format_func=lambda cid: opciones_cliente[cid],
            key="cliente_id_ver",
        )

        info_cliente = clientes.loc[clientes["ID"] == cliente_id_ver].iloc[0]

        st.subheader(info_cliente["Nombre"])
        col1, col2, col3 = st.columns(3)
        col1.metric("RUT", info_cliente["RUT"] or "—")
        col2.metric("Teléfono", info_cliente["Telefono"] or "—")
        col3.metric("Email", info_cliente["Email"] or "—")

        col4, col5 = st.columns(2)
        with col4:
            st.write(f"**Fecha de nacimiento:** {info_cliente['FechaNacimiento'] or '—'}")
        with col5:
            st.write(f"**Dirección:** {info_cliente['Direccion'] or '—'}")
        if info_cliente["Notas"]:
            st.info(f"**Notas:** {info_cliente['Notas']}")

        st.divider()
        st.subheader("Historial de citas")

        citas_cliente = (
            citas[citas["ClienteID"] == cliente_id_ver] if not citas.empty else citas
        )

        if citas_cliente.empty:
            st.info("Este cliente todavía no tiene citas registradas.")
        else:
            citas_cliente_agrupadas = agrupar_citas(citas_cliente).sort_values(
                "Fecha", ascending=False
            )

            col_a, col_b = st.columns(2)
            col_a.metric("Visitas", len(citas_cliente_agrupadas))
            col_b.metric("Total gastado", f"${citas_cliente['Precio'].sum():,.0f}")

            opciones_citas = {
                row.ID: (
                    f"{row.Fecha.strftime('%d/%m/%Y') if pd.notna(row.Fecha) else '(sin fecha)'}"
                    f" — ${row.Total:,.0f}"
                )
                for row in citas_cliente_agrupadas.itertuples()
            }
            cita_sel = st.selectbox(
                "Elegí una cita para ver el detalle",
                options=list(opciones_citas.keys()),
                format_func=lambda cid: opciones_citas[cid],
                key="cita_sel_ficha",
            )

            tabla_tratamientos = (
                citas_cliente.loc[citas_cliente["ID"] == cita_sel, ["Tratamiento", "Precio"]]
                .reset_index(drop=True)
            )
            st.dataframe(tabla_tratamientos, use_container_width=True, hide_index=True)
            st.metric("Total de esta cita", f"${tabla_tratamientos['Precio'].sum():,.0f}")

            obs_actual = citas_cliente_agrupadas.loc[
                citas_cliente_agrupadas["ID"] == cita_sel, "Observaciones"
            ].iloc[0]
            if obs_actual:
                st.info(f"**Observaciones / Acción clínica:** {obs_actual}")

            st.divider()

            if "editando_cita_id" not in st.session_state:
                st.session_state.editando_cita_id = None

            confirmar_del_cita_key = f"confirmar_eliminar_cita_{cita_sel}"
            if confirmar_del_cita_key not in st.session_state:
                st.session_state[confirmar_del_cita_key] = False

            if (
                st.session_state.editando_cita_id != cita_sel
                and not st.session_state[confirmar_del_cita_key]
            ):
                col_editar, col_eliminar = st.columns(2)
                with col_editar:
                    if st.button("✏️ Editar esta cita"):
                        st.session_state.editando_cita_id = cita_sel
                        st.session_state["carrito_edicion"] = tabla_tratamientos.to_dict("records")
                        st.rerun()
                with col_eliminar:
                    if st.button("🗑️ Eliminar cita", key=f"btn_eliminar_cita_{cita_sel}"):
                        st.session_state[confirmar_del_cita_key] = True
                        st.rerun()
            elif st.session_state[confirmar_del_cita_key]:
                st.warning(
                    "¿Seguro que querés eliminar esta cita completa? "
                    "Esta acción no se puede deshacer."
                )
                col_si, col_no = st.columns(2)
                with col_si:
                    if st.button(
                        "Sí, eliminar definitivamente",
                        key=f"btn_confirmar_eliminar_cita_{cita_sel}",
                    ):
                        eliminar_cita(cita_sel)
                        st.cache_data.clear()
                        st.session_state[confirmar_del_cita_key] = False
                        st.success("Cita eliminada.")
                        st.rerun()
                with col_no:
                    if st.button("Cancelar", key=f"btn_cancelar_eliminar_cita_{cita_sel}"):
                        st.session_state[confirmar_del_cita_key] = False
                        st.rerun()
            else:
                st.subheader("Editando cita")

                fecha_actual = citas_cliente_agrupadas.loc[
                    citas_cliente_agrupadas["ID"] == cita_sel, "Fecha"
                ].iloc[0]

                col_f, col_c = st.columns(2)
                with col_f:
                    fecha_edit = st.date_input(
                        "Fecha",
                        value=fecha_actual.date() if pd.notna(fecha_actual) else date.today(),
                        key=f"fecha_edit_{cita_sel}",
                    )
                with col_c:
                    ids_cliente = list(opciones_cliente.keys())
                    cliente_edit_id = st.selectbox(
                        "Cliente",
                        options=ids_cliente,
                        format_func=lambda cid: opciones_cliente[cid],
                        index=ids_cliente.index(cliente_id_ver),
                        key=f"cliente_edit_{cita_sel}",
                    )

                st.write("**Tratamientos**")
                carrito_edit_df = render_carrito(catalogo, "carrito_edicion")

                observaciones_edit = st.text_area(
                    "Observaciones / Acción clínica",
                    value=obs_actual,
                    key=f"obs_edit_{cita_sel}",
                )

                col_guardar, col_cancelar = st.columns(2)
                with col_guardar:
                    if st.button("💾 Guardar cambios", type="primary"):
                        if carrito_edit_df is None or carrito_edit_df.empty:
                            st.error("La cita necesita al menos un tratamiento.")
                        else:
                            actualizar_cita(
                                cita_sel, fecha_edit, cliente_edit_id,
                                st.session_state["carrito_edicion"],
                                observaciones_edit.strip(),
                            )
                            st.cache_data.clear()
                            st.session_state.editando_cita_id = None
                            st.session_state.pop("carrito_edicion", None)
                            st.success("Cita actualizada.")
                            st.rerun()
                with col_cancelar:
                    if st.button("Cancelar edición"):
                        st.session_state.editando_cita_id = None
                        st.session_state.pop("carrito_edicion", None)
                        st.rerun()
