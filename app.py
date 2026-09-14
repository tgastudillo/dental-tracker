import re
import uuid

import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime, timedelta

# -----------------------------
# Configuración
# -----------------------------
st.set_page_config(page_title="Registro de Tratamientos", page_icon="🦷", layout="wide")


def verificar_login():
    """Login simple: correo + contraseña contra st.secrets['usuarios']."""
    if st.session_state.get("autenticado"):
        return True

    st.title("🦷 Registro de Tratamientos")
    st.subheader("Iniciar sesión")

    with st.form("form_login"):
        email = st.text_input("Correo")
        password = st.text_input("Contraseña", type="password")
        enviado = st.form_submit_button("Ingresar")

    if enviado:
        usuarios = st.secrets.get("usuarios", {})
        if email in usuarios and usuarios[email] == password:
            st.session_state["autenticado"] = True
            st.session_state["usuario_email"] = email
            st.rerun()
        else:
            st.error("Correo o contraseña incorrectos.")

    return False


if not verificar_login():
    st.stop()


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


def formatear_clp(monto):
    """Formatea como peso chileno: separador de miles con punto, sin decimales."""
    return f"${monto:,.0f}".replace(",", ".")


def parsear_fecha(texto):
    if not texto:
        return None
    try:
        return datetime.strptime(texto, "%d/%m/%Y").date()
    except ValueError:
        return None


MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def selector_fecha_nacimiento(key_prefix, valor_actual=None):
    """Tres selectbox (Día/Mes/Año) en vez de un calendario, para elegir
    fechas viejas sin pelear con la paginación por años del date_input."""
    anios = list(range(date.today().year, 1899, -1))

    col_d, col_m, col_a = st.columns(3)
    with col_d:
        dia = st.selectbox(
            "Día",
            options=[None] + list(range(1, 32)),
            format_func=lambda d: "—" if d is None else str(d),
            index=(valor_actual.day if valor_actual else 0),
            key=f"{key_prefix}_dia",
        )
    with col_m:
        mes = st.selectbox(
            "Mes",
            options=[None] + list(range(1, 13)),
            format_func=lambda m: "—" if m is None else MESES[m - 1],
            index=(valor_actual.month if valor_actual else 0),
            key=f"{key_prefix}_mes",
        )
    with col_a:
        anio = st.selectbox(
            "Año",
            options=[None] + anios,
            format_func=lambda a: "—" if a is None else str(a),
            index=(anios.index(valor_actual.year) + 1 if valor_actual else 0),
            key=f"{key_prefix}_anio",
        )

    if dia and mes and anio:
        try:
            return date(anio, mes, dia)
        except ValueError:
            st.error("Esa fecha de nacimiento no existe (ej: 31 de febrero).")
            return None
    return None


def limpiar_seleccion_invalida(key, opciones_validas):
    """Si un selectbox guardó un valor (cliente/cita) que ya no existe -por
    ejemplo porque se eliminó-, lo saca de session_state para que el widget
    vuelva a un valor por defecto en vez de romper con las opciones nuevas."""
    if key in st.session_state and st.session_state[key] not in opciones_validas:
        del st.session_state[key]


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


@st.cache_data(ttl=5)
def cargar_catalogo():
    ws = get_worksheet(TAB_CATALOGO)
    data = ws.get_all_records(value_render_option="UNFORMATTED_VALUE")
    df = pd.DataFrame(data)
    if df.empty:
        return pd.DataFrame(columns=["Tratamiento", "Precio"])
    df["Precio"] = pd.to_numeric(df["Precio"], errors="coerce").fillna(0)
    return df


@st.cache_data(ttl=5)
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


@st.cache_data(ttl=5)
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
def render_carrito_agregar(catalogo, carrito_key):
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
        st.metric("Precio", formatear_clp(precio_sel))
    with col_btn:
        st.write("")
        st.write("")
        if st.button("➕ Agregar", key=f"{carrito_key}_add_btn"):
            st.session_state[carrito_key].append(
                {"Tratamiento": tratamiento_sel, "Precio": precio_sel}
            )
            st.rerun()


def render_carrito_tabla(carrito_key):
    if not st.session_state.get(carrito_key):
        st.info("Todavía no agregaste tratamientos.")
        return None

    carrito_df = pd.DataFrame(st.session_state[carrito_key])
    carrito_mostrar = carrito_df.copy()
    carrito_mostrar["Precio"] = carrito_mostrar["Precio"].apply(formatear_clp)
    st.dataframe(carrito_mostrar, use_container_width=True, hide_index=True)

    col_quitar, col_vaciar = st.columns([3, 1])
    with col_quitar:
        idx_quitar = st.selectbox(
            "Quitar un tratamiento agregado",
            options=list(range(len(st.session_state[carrito_key]))),
            format_func=lambda i: (
                f"{st.session_state[carrito_key][i]['Tratamiento']} "
                f"({formatear_clp(st.session_state[carrito_key][i]['Precio'])})"
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
    st.metric("Total", formatear_clp(total))
    return carrito_df


def render_carrito(catalogo, carrito_key):
    render_carrito_agregar(catalogo, carrito_key)
    return render_carrito_tabla(carrito_key)


# -----------------------------
# Página: Clientes (buscar/crear/editar/eliminar + historial de citas)
# -----------------------------
def formulario_nuevo_cliente():
    with st.expander("➕ Nuevo cliente"):
        with st.form("form_cliente", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                nombre_cliente = st.text_input("Nombre completo")
                rut_cliente = st.text_input("RUT", placeholder="12345678-9")
                telefono_cliente = st.text_input("Teléfono")
            with col2:
                email_cliente = st.text_input("Email")
                direccion_cliente = st.text_input("Dirección")

            st.write("Fecha de nacimiento")
            fecha_nacimiento = selector_fecha_nacimiento("nac_nuevo")
            notas_cliente = st.text_area("Notas (alergias, antecedentes médicos, etc.)")

            if st.form_submit_button("Guardar cliente"):
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
                    st.success(f"Cliente guardado: {nombre_cliente.strip()}")
                    st.rerun()


def formulario_editar_cliente(cliente_id, info):
    with st.form(f"form_editar_cliente_{cliente_id}"):
        col1, col2 = st.columns(2)
        with col1:
            nombre_e = st.text_input("Nombre completo", value=info["Nombre"])
            rut_e = st.text_input("RUT", value=info["RUT"])
            telefono_e = st.text_input("Teléfono", value=info["Telefono"])
        with col2:
            email_e = st.text_input("Email", value=info["Email"])
            direccion_e = st.text_input("Dirección", value=info["Direccion"])

        st.write("Fecha de nacimiento")
        fecha_nacimiento_e = selector_fecha_nacimiento(
            f"nac_editar_{cliente_id}", valor_actual=parsear_fecha(info["FechaNacimiento"])
        )
        notas_e = st.text_area("Notas", value=info["Notas"])

        col_guardar, col_cancelar = st.columns(2)
        with col_guardar:
            guardar = st.form_submit_button("💾 Guardar cambios", type="primary")
        with col_cancelar:
            cancelar = st.form_submit_button("Cancelar")

        if guardar:
            if not nombre_e.strip():
                st.error("Falta el nombre del cliente.")
            else:
                actualizar_cliente(
                    cliente_id, nombre_e.strip(), formatear_rut(rut_e),
                    telefono_e.strip(), email_e.strip(), fecha_nacimiento_e,
                    direccion_e.strip(), notas_e.strip(),
                )
                st.cache_data.clear()
                st.session_state["editando_cliente_id"] = None
                st.success("Cliente actualizado.")
                st.rerun()
        if cancelar:
            st.session_state["editando_cliente_id"] = None
            st.rerun()


def fila_cita(row, cliente_id, clientes, citas_cliente, catalogo):
    editando = st.session_state.get("editando_cita_id") == row.ID
    confirmar_key = f"confirmar_eliminar_cita_{row.ID}"

    with st.container(border=True):
        col_fecha, col_texto, col_total, col_acciones = st.columns([1.1, 3, 1.2, 1.4])
        with col_fecha:
            st.write(row.Fecha.strftime("%d/%m/%Y") if pd.notna(row.Fecha) else "—")
        with col_texto:
            tratamientos_fila = citas_cliente.loc[
                citas_cliente["ID"] == row.ID, "Tratamiento"
            ].tolist()
            texto = "\n".join(f"- {t}" for t in tratamientos_fila)
            if row.Observaciones:
                texto += f"\n\n📝 {row.Observaciones}"
            st.markdown(texto)
        with col_total:
            st.write(f"**{formatear_clp(row.Total)}**")
        with col_acciones:
            b1, b2 = st.columns(2)
            with b1:
                if not editando and st.button("✏️", key=f"editar_cita_{row.ID}", help="Editar cita"):
                    st.session_state["editando_cita_id"] = row.ID
                    st.session_state["carrito_edicion"] = citas_cliente.loc[
                        citas_cliente["ID"] == row.ID, ["Tratamiento", "Precio"]
                    ].to_dict("records")
                    st.rerun()
            with b2:
                if not editando and not st.session_state.get(confirmar_key) and st.button(
                    "🗑️", key=f"eliminar_cita_{row.ID}", help="Eliminar cita"
                ):
                    st.session_state[confirmar_key] = True
                    st.rerun()

        if st.session_state.get(confirmar_key):
            st.warning("¿Eliminar esta cita completa? No se puede deshacer.")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Sí, eliminar", key=f"si_eliminar_cita_{row.ID}"):
                    eliminar_cita(row.ID)
                    st.cache_data.clear()
                    st.session_state[confirmar_key] = False
                    st.success("Cita eliminada.")
                    st.rerun()
            with c2:
                if st.button("Cancelar", key=f"no_eliminar_cita_{row.ID}"):
                    st.session_state[confirmar_key] = False
                    st.rerun()

        if editando:
            st.write("**Editar cita**")
            col_f, col_c = st.columns(2)
            with col_f:
                fecha_edit = st.date_input(
                    "Fecha",
                    value=row.Fecha.date() if pd.notna(row.Fecha) else date.today(),
                    key=f"fecha_edit_{row.ID}",
                )
            with col_c:
                ids_cliente_todos = clientes["ID"].tolist()
                limpiar_seleccion_invalida(f"cliente_edit_{row.ID}", ids_cliente_todos)
                cliente_edit_id = st.selectbox(
                    "Cliente",
                    options=ids_cliente_todos,
                    format_func=lambda cid: (
                        f"{clientes.loc[clientes['ID'] == cid, 'Nombre'].iloc[0]} "
                        f"({clientes.loc[clientes['ID'] == cid, 'RUT'].iloc[0]})"
                    ),
                    index=ids_cliente_todos.index(cliente_id) if cliente_id in ids_cliente_todos else 0,
                    key=f"cliente_edit_{row.ID}",
                )

            carrito_edit_df = render_carrito(catalogo, "carrito_edicion")
            observaciones_edit = st.text_area(
                "Observaciones / Acción clínica",
                value=row.Observaciones,
                key=f"obs_edit_{row.ID}",
            )

            col_guardar, col_cancelar = st.columns(2)
            with col_guardar:
                if st.button("💾 Guardar cambios", key=f"guardar_edit_cita_{row.ID}", type="primary"):
                    if carrito_edit_df is None or carrito_edit_df.empty:
                        st.error("La cita necesita al menos un tratamiento.")
                    else:
                        actualizar_cita(
                            row.ID, fecha_edit, cliente_edit_id,
                            st.session_state["carrito_edicion"], observaciones_edit.strip(),
                        )
                        st.cache_data.clear()
                        st.session_state["editando_cita_id"] = None
                        st.session_state.pop("carrito_edicion", None)
                        st.success("Cita actualizada.")
                        st.rerun()
            with col_cancelar:
                if st.button("Cancelar", key=f"cancelar_edit_cita_{row.ID}"):
                    st.session_state["editando_cita_id"] = None
                    st.session_state.pop("carrito_edicion", None)
                    st.rerun()


def ficha_cliente(cliente_id, clientes, citas):
    info = clientes.loc[clientes["ID"] == cliente_id].iloc[0]
    editando = st.session_state.get("editando_cliente_id") == cliente_id
    confirmar_key = f"confirmar_eliminar_cliente_{cliente_id}"

    col_titulo, col_editar, col_eliminar = st.columns([3, 1, 1])
    with col_titulo:
        st.subheader(info["Nombre"])
    with col_editar:
        if not editando and st.button("✏️ Editar", key=f"btn_editar_cliente_{cliente_id}"):
            st.session_state["editando_cliente_id"] = cliente_id
            st.rerun()
    with col_eliminar:
        if not editando and not st.session_state.get(confirmar_key) and st.button(
            "🗑️ Eliminar", key=f"btn_eliminar_cliente_{cliente_id}"
        ):
            st.session_state[confirmar_key] = True
            st.rerun()

    if st.session_state.get(confirmar_key):
        n_citas = citas.loc[citas["ClienteID"] == cliente_id, "ID"].nunique() if not citas.empty else 0
        aviso = f"¿Seguro que querés eliminar a **{info['Nombre']}**? Esta acción no se puede deshacer."
        if n_citas:
            aviso += (
                f" Tiene {n_citas} cita(s) registrada(s); van a quedar "
                "como \"cliente desconocido\" en los reportes."
            )
        st.warning(aviso)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Sí, eliminar definitivamente", key=f"confirmar_del_cliente_{cliente_id}"):
                eliminar_cliente(cliente_id)
                st.cache_data.clear()
                st.session_state[confirmar_key] = False
                st.session_state["cliente_activo"] = None
                st.success("Cliente eliminado.")
                st.rerun()
        with c2:
            if st.button("Cancelar", key=f"cancelar_del_cliente_{cliente_id}"):
                st.session_state[confirmar_key] = False
                st.rerun()
        return

    if editando:
        formulario_editar_cliente(cliente_id, info)
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("RUT", info["RUT"] or "—")
    col2.metric("Teléfono", info["Telefono"] or "—")
    col3.metric("Nacimiento", info["FechaNacimiento"] or "—")
    if info["Email"]:
        st.caption(f"✉️ {info['Email']}")
    if info["Direccion"]:
        st.caption(f"📍 {info['Direccion']}")
    if info["Notas"]:
        st.info(f"**Notas:** {info['Notas']}")

    st.divider()
    st.markdown("**Historial de citas**")

    citas_cliente = citas[citas["ClienteID"] == cliente_id] if not citas.empty else citas
    if citas_cliente.empty:
        st.caption("Todavía no tiene citas registradas.")
        return

    citas_agrupadas = agrupar_citas(citas_cliente).sort_values("Fecha", ascending=False)

    col_a, col_b = st.columns(2)
    col_a.metric("Visitas", len(citas_agrupadas))
    col_b.metric("Total gastado", formatear_clp(citas_cliente["Precio"].sum()))

    catalogo = cargar_catalogo()
    for row in citas_agrupadas.itertuples():
        fila_cita(row, cliente_id, clientes, citas_cliente, catalogo)


def pagina_clientes():
    st.title("🧑 Clientes y Citas Pasadas")
    clientes = cargar_clientes()
    citas = cargar_citas()

    col_lista, col_detalle = st.columns([1, 2], gap="large")

    with col_lista:
        formulario_nuevo_cliente()

        if clientes.empty:
            st.info("Todavía no hay clientes registrados.")
            return

        ids_validos = clientes["ID"].tolist()
        cliente_id_actual = st.session_state.get("cliente_activo")
        if cliente_id_actual not in ids_validos:
            cliente_id_actual = ids_validos[0]
            st.session_state["cliente_activo"] = cliente_id_actual

        st.text_input("🔍 Buscar por nombre o RUT", key="busqueda_cliente")
        busqueda = st.session_state.get("busqueda_cliente", "").strip().lower()

        clientes_filtrados = clientes.sort_values("Nombre").reset_index(drop=True)
        if busqueda:
            busqueda_rut = busqueda.replace("-", "").replace(".", "")
            mask = (
                clientes_filtrados["Nombre"].str.lower().str.contains(busqueda, regex=False)
                | clientes_filtrados["RUT"].str.replace("-", "").str.lower().str.contains(
                    busqueda_rut, regex=False
                )
            )
            clientes_filtrados = clientes_filtrados[mask].reset_index(drop=True)

        ultima_visita = (
            citas.groupby("ClienteID")["Fecha"].max().to_dict() if not citas.empty else {}
        )
        tabla_lista = pd.DataFrame({
            "Nombre": clientes_filtrados["Nombre"],
            "RUT": clientes_filtrados["RUT"],
            "Última visita": [
                ultima_visita[cid].strftime("%d/%m/%Y")
                if cid in ultima_visita and pd.notna(ultima_visita[cid]) else "—"
                for cid in clientes_filtrados["ID"]
            ],
        })

        st.caption("Seleccioná un cliente para ver el detalle e historial de citas.")

        if tabla_lista.empty:
            st.caption("Sin resultados para esa búsqueda.")
        else:
            filas_coincidentes = clientes_filtrados.index[
                clientes_filtrados["ID"] == cliente_id_actual
            ].tolist()
            selection_default = (
                {"selection": {"rows": [filas_coincidentes[0]]}} if filas_coincidentes else None
            )

            evento = st.dataframe(
                tabla_lista,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                selection_default=selection_default,
                key="tabla_clientes_sel",
            )
            filas_sel = evento.selection.rows if evento and evento.selection else []
            if filas_sel:
                cliente_id_actual = clientes_filtrados.iloc[filas_sel[0]]["ID"]
                st.session_state["cliente_activo"] = cliente_id_actual

    with col_detalle:
        ficha_cliente(cliente_id_actual, clientes, citas)


# -----------------------------
# Página: Nueva cita
# -----------------------------
def pagina_nueva_cita():
    st.title("➕ Nueva cita")
    catalogo = cargar_catalogo()
    clientes = cargar_clientes()

    if catalogo.empty:
        st.warning(
            "El catálogo está vacío. Agrega tratamientos y precios en la hoja "
            f"'{TAB_CATALOGO}' de tu Google Sheet."
        )
        return
    if clientes.empty:
        st.warning(
            "Todavía no hay clientes registrados. Creá uno en la sección '🧑 Clientes' "
            "antes de registrar una cita."
        )
        return

    if "carrito" not in st.session_state:
        st.session_state.carrito = []
    if "mensaje_guardado" not in st.session_state:
        st.session_state.mensaje_guardado = None

    opciones_cliente = {row.ID: f"{row.Nombre} ({row.RUT})" for row in clientes.itertuples()}

    col_izq, col_der = st.columns([1.1, 0.9], gap="large")

    with col_izq:
        with st.container(border=True):
            st.markdown("**Datos de la cita**")
            limpiar_seleccion_invalida("cliente_id_sel", list(opciones_cliente.keys()))
            cliente_id_sel = st.selectbox(
                "Cliente",
                options=list(opciones_cliente.keys()),
                format_func=lambda cid: opciones_cliente[cid],
                key="cliente_id_sel",
            )
            fecha = st.date_input("Fecha", value=date.today(), key="fecha_input")

            st.markdown("**Agregar tratamiento**")
            render_carrito_agregar(catalogo, "carrito")

            observaciones_nueva = st.text_area(
                "Observaciones / Acción clínica (opcional)", key="observaciones_input"
            )

    with col_der:
        with st.container(border=True):
            st.markdown("**Tratamientos de la cita**")
            carrito_df = render_carrito_tabla("carrito")

            if carrito_df is not None and not carrito_df.empty:
                total_calculado = carrito_df["Precio"].sum()
                if st.button("✅ Guardar cita", type="primary", use_container_width=True):
                    guardar_cita(
                        fecha, cliente_id_sel, st.session_state.carrito,
                        observaciones_nueva.strip(),
                    )
                    st.cache_data.clear()
                    st.session_state.carrito = []
                    st.session_state.pop("observaciones_input", None)
                    st.session_state.mensaje_guardado = (
                        f"Cita guardada: {opciones_cliente[cliente_id_sel]} — "
                        f"{formatear_clp(total_calculado)}"
                    )
                    st.rerun()

    if st.session_state.mensaje_guardado:
        st.success(st.session_state.mensaje_guardado)
        st.session_state.mensaje_guardado = None


# -----------------------------
# Página: Resumen
# -----------------------------
def pagina_resumen():
    st.title("📊 Resumen")
    citas = cargar_citas()
    clientes = cargar_clientes()

    if citas.empty:
        st.info("Todavía no hay citas registradas.")
        return

    citas_agrupadas = agrupar_citas(citas).merge(
        clientes[["ID", "Nombre", "RUT"]].rename(columns={"ID": "ClienteID"}),
        on="ClienteID",
        how="left",
    )
    citas_agrupadas["Nombre"] = citas_agrupadas["Nombre"].fillna("(cliente desconocido)")
    citas_agrupadas["RUT"] = citas_agrupadas["RUT"].fillna("")

    ticket_promedio = citas_agrupadas["Total"].mean() if len(citas_agrupadas) else 0

    col1, col2, col3 = st.columns(3)
    col1.metric("Ingreso total registrado", formatear_clp(citas["Precio"].sum()))
    col2.metric("Citas registradas", len(citas_agrupadas))
    col3.metric("Ticket promedio", formatear_clp(ticket_promedio))

    st.divider()

    col_chart, col_rank = st.columns([1.2, 0.8], gap="large")

    with col_chart:
        st.markdown("**Ingresos por día**")
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

    with col_rank:
        st.markdown("**Resumen por cliente**")
        resumen_cliente = (
            citas_agrupadas.groupby(["ClienteID", "Nombre"])
            .agg(Visitas=("ID", "count"), Total_gastado=("Total", "sum"))
            .sort_values("Total_gastado", ascending=False)
            .reset_index()
            .drop(columns=["ClienteID"])
        )
        resumen_cliente_mostrar = resumen_cliente.copy()
        resumen_cliente_mostrar["Total_gastado"] = resumen_cliente_mostrar["Total_gastado"].apply(
            formatear_clp
        )
        st.dataframe(resumen_cliente_mostrar, use_container_width=True, hide_index=True)

    st.divider()
    with st.expander("Ver detalle completo de citas"):
        detalle_mostrar = citas_agrupadas[
            ["Fecha", "Nombre", "RUT", "Tratamientos", "Total", "Observaciones"]
        ].sort_values("Fecha", ascending=False).copy()
        detalle_mostrar["Total"] = detalle_mostrar["Total"].apply(formatear_clp)
        st.dataframe(detalle_mostrar, use_container_width=True, hide_index=True)


# -----------------------------
# Barra de KPIs (se muestra en todas las páginas)
# -----------------------------
def render_kpis():
    citas = cargar_citas()
    clientes = cargar_clientes()

    col_kpis, col_filtro = st.columns([3, 1])
    with col_filtro:
        periodo_kpi = st.segmented_control(
            "Período de los KPI",
            ["Semana", "Mes"],
            default="Semana",
            key="periodo_kpi",
            label_visibility="collapsed",
        ) or "Semana"

    hoy = date.today()
    if periodo_kpi == "Mes":
        inicio = hoy.replace(day=1)
        fin = (
            date(hoy.year, 12, 31) if hoy.month == 12
            else date(hoy.year, hoy.month + 1, 1) - timedelta(days=1)
        )
        etiqueta = "este mes"
    else:
        inicio = hoy - timedelta(days=hoy.weekday())
        fin = inicio + timedelta(days=6)
        etiqueta = "esta semana"

    inicio_ts, fin_ts = pd.Timestamp(inicio), pd.Timestamp(fin)

    if not citas.empty:
        citas_periodo = citas[(citas["Fecha"] >= inicio_ts) & (citas["Fecha"] <= fin_ts)]
    else:
        citas_periodo = citas
    n_citas_periodo = citas_periodo["ID"].nunique() if not citas_periodo.empty else 0
    ingresos_periodo = citas_periodo["Precio"].sum() if not citas_periodo.empty else 0

    if not clientes.empty:
        fechas_registro = clientes["FechaRegistro"].apply(parsear_fecha)
        clientes_nuevos_periodo = fechas_registro.apply(
            lambda f: f is not None and inicio <= f <= fin
        ).sum()
    else:
        clientes_nuevos_periodo = 0

    with col_kpis:
        col1, col2, col3 = st.columns(3)
        col1.metric(f"Citas {etiqueta}", n_citas_periodo)
        col2.metric(f"Ingresos {etiqueta}", formatear_clp(ingresos_periodo))
        col3.metric(f"Clientes nuevos {etiqueta}", clientes_nuevos_periodo)
    st.divider()


# -----------------------------
# Navegación
# -----------------------------
st.logo("🦷", size="large")

with st.sidebar:
    st.caption("Registro de Tratamientos")
    if st.session_state.get("usuario_email"):
        st.caption(f"Sesión: {st.session_state['usuario_email']}")
    if st.button("Cerrar sesión"):
        st.session_state["autenticado"] = False
        st.session_state.pop("usuario_email", None)
        st.rerun()

pagina = st.navigation([
    st.Page(pagina_clientes, title="Clientes y Citas Pasadas", icon="🧑", default=True),
    st.Page(pagina_nueva_cita, title="Nueva cita", icon="➕"),
    st.Page(pagina_resumen, title="Resumen", icon="📊"),
])

render_kpis()
pagina.run()
