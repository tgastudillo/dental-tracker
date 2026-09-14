import re
import uuid

import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date

# -----------------------------
# Configuración
# -----------------------------
st.set_page_config(page_title="Registro de Tratamientos", page_icon="🦷", layout="wide")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

ID_HOJA = "117m17ax3UznyF3iLpEBWpIbDvhYUtLb8bTMqdwRm7FU"   # ID de tu Google Sheet (de la URL)

TAB_CATALOGO = "Catalogo"   # columnas: Tratamiento | Precio
TAB_CITAS = "Citas"         # columnas: ID | Fecha | ClienteID | Tratamientos | Total
TAB_CLIENTES = "Clientes"   # columnas: ID | RUT | Nombre | Telefono | Email | FechaNacimiento | Direccion | FechaRegistro | Notas

CITAS_COLUMNAS = ["ID", "Fecha", "ClienteID", "Tratamientos", "Total"]
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
    ws = get_worksheet(TAB_CITAS)
    data = ws.get_all_records(value_render_option="UNFORMATTED_VALUE")
    df = pd.DataFrame(data)
    if df.empty:
        return pd.DataFrame(columns=CITAS_COLUMNAS)
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce", dayfirst=True)
    df["Total"] = pd.to_numeric(df["Total"], errors="coerce").fillna(0)
    return df


def guardar_cliente(nombre, rut, telefono, email, fecha_nacimiento, direccion, notas):
    ws = get_worksheet(TAB_CLIENTES)
    fecha_nac_str = fecha_nacimiento.strftime("%d/%m/%Y") if fecha_nacimiento else ""
    ws.append_row([
        uuid.uuid4().hex[:8].upper(),
        rut,
        nombre,
        telefono,
        email,
        fecha_nac_str,
        direccion,
        date.today().strftime("%d/%m/%Y"),
        notas,
    ])


def guardar_cita(fecha, cliente_id, tratamientos, total):
    ws = get_worksheet(TAB_CITAS)
    ws.append_row([
        uuid.uuid4().hex[:8].upper(),
        fecha.strftime("%d/%m/%Y"),
        cliente_id,
        ", ".join(tratamientos),
        float(total),
    ])


# -----------------------------
# UI
# -----------------------------
st.title("🦷 Registro de Tratamientos")

tab_clientes, tab_registro, tab_resumen, tab_ficha_cliente = st.tabs(
    ["🧑 Nuevo cliente", "➕ Nueva cita", "📊 Resumen", "📋 Ficha de cliente"]
)

# --- TAB 1: registro de nuevo cliente ---
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
        if "carrito" not in st.session_state:
            st.session_state.carrito = []
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

        col_sel, col_precio, col_btn = st.columns([3, 1, 1])
        with col_sel:
            tratamiento_sel = st.selectbox(
                "Tratamiento",
                options=catalogo["Tratamiento"].tolist(),
                key="tratamiento_sel",
            )
        precio_sel = float(
            catalogo.loc[catalogo["Tratamiento"] == tratamiento_sel, "Precio"].iloc[0]
        )
        with col_precio:
            st.metric("Precio", f"${precio_sel:,.0f}")
        with col_btn:
            st.write("")
            st.write("")
            if st.button("➕ Agregar"):
                st.session_state.carrito.append(
                    {"Tratamiento": tratamiento_sel, "Precio": precio_sel}
                )
                st.rerun()

        st.divider()

        if not st.session_state.carrito:
            st.info("Todavía no agregaste tratamientos a esta cita.")
        else:
            st.subheader("Tratamientos de la cita")
            carrito_df = pd.DataFrame(st.session_state.carrito)
            st.dataframe(carrito_df, use_container_width=True, hide_index=True)

            col_quitar, col_vaciar = st.columns([3, 1])
            with col_quitar:
                idx_quitar = st.selectbox(
                    "Quitar un tratamiento agregado",
                    options=list(range(len(st.session_state.carrito))),
                    format_func=lambda i: (
                        f"{st.session_state.carrito[i]['Tratamiento']} "
                        f"(${st.session_state.carrito[i]['Precio']:,.0f})"
                    ),
                    key="idx_quitar",
                )
                if st.button("🗑️ Quitar seleccionado"):
                    st.session_state.carrito.pop(idx_quitar)
                    st.rerun()
            with col_vaciar:
                st.write("")
                st.write("")
                if st.button("Vaciar lista"):
                    st.session_state.carrito = []
                    st.rerun()

            total_calculado = carrito_df["Precio"].sum()
            st.metric("Total de la cita", f"${total_calculado:,.0f}")

            if st.button("✅ Guardar cita", type="primary"):
                tratamientos = [item["Tratamiento"] for item in st.session_state.carrito]
                guardar_cita(fecha, cliente_id_sel, tratamientos, total_calculado)
                st.cache_data.clear()
                st.session_state.carrito = []
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
        citas_detalle = citas.merge(
            clientes[["ID", "Nombre", "RUT"]].rename(columns={"ID": "ClienteID"}),
            on="ClienteID",
            how="left",
        )
        citas_detalle["Nombre"] = citas_detalle["Nombre"].fillna("(cliente desconocido)")
        citas_detalle["RUT"] = citas_detalle["RUT"].fillna("")

        st.subheader("Detalle de citas")
        st.dataframe(
            citas_detalle[["Fecha", "Nombre", "RUT", "Tratamientos", "Total"]]
            .sort_values("Fecha", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Resumen por cliente")
            resumen_cliente = (
                citas_detalle.groupby(["ClienteID", "Nombre"])
                .agg(Visitas=("ClienteID", "count"), Total_gastado=("Total", "sum"))
                .sort_values("Total_gastado", ascending=False)
                .reset_index()
                .drop(columns=["ClienteID"])
            )
            st.dataframe(resumen_cliente, use_container_width=True, hide_index=True)

        with col2:
            st.subheader("Ingresos por período")
            periodo = st.radio("Agrupar por", ["Día", "Semana", "Mes"], horizontal=True)
            freq_map = {"Día": "D", "Semana": "W", "Mes": "ME"}
            ingresos = (
                citas.set_index("Fecha")
                .resample(freq_map[periodo])["Total"]
                .sum()
            )
            st.bar_chart(ingresos)

        st.divider()
        st.metric("Ingreso total registrado", f"${citas['Total'].sum():,.0f}")

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
            citas_cliente = citas_cliente.sort_values("Fecha", ascending=False)

            col_a, col_b = st.columns(2)
            col_a.metric("Visitas", len(citas_cliente))
            col_b.metric("Total gastado", f"${citas_cliente['Total'].sum():,.0f}")

            opciones_citas = {
                row.ID: (
                    f"{row.Fecha.strftime('%d/%m/%Y') if pd.notna(row.Fecha) else '(sin fecha)'}"
                    f" — ${row.Total:,.0f}"
                )
                for row in citas_cliente.itertuples()
            }
            cita_sel = st.selectbox(
                "Elegí una cita para ver el detalle",
                options=list(opciones_citas.keys()),
                format_func=lambda cid: opciones_citas[cid],
                key="cita_sel_ficha",
            )

            fila_cita = citas_cliente.loc[citas_cliente["ID"] == cita_sel].iloc[0]

            precios_catalogo = catalogo.set_index("Tratamiento")["Precio"]
            nombres_tratamientos = [
                t.strip() for t in str(fila_cita["Tratamientos"]).split(",") if t.strip()
            ]
            tabla_tratamientos = pd.DataFrame([
                {
                    "Tratamiento": nombre,
                    "Precio": precios_catalogo.get(nombre, None),
                }
                for nombre in nombres_tratamientos
            ])

            st.dataframe(tabla_tratamientos, use_container_width=True, hide_index=True)
            st.metric("Total de esta cita", f"${fila_cita['Total']:,.0f}")
