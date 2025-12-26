import streamlit as st
import pandas as pd
import altair as alt
import pydeck as pdk
from google.cloud import firestore
from google.oauth2 import service_account
from datetime import datetime
from pathlib import Path

from logbook_pdf import DEFAULT_LAYOUT, generate_logbook_pdf_bytes

@st.cache_resource
def get_db_client():
    credentials = service_account.Credentials.from_service_account_file("serviceAccountKey.json")
    return firestore.Client(credentials=credentials, project=credentials.project_id)

@st.cache_data(show_spinner=False)
def load_data_from_firestore():
    db = get_db_client()
    # Orden estable por ID de documento (0000..), para reproducir el orden del logbook
    docs = db.collection("logbook").order_by("__name__").stream()
    # Mantener un orden estable de lectura para poder desempatar ordenaciones y
    # conservar filas vacías en el export a PDF.
    rows = [{**(doc.to_dict() or {}), "_doc_id": doc.id} for doc in docs]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)

    # Índice estable de filas (orden de llegada desde Firestore)
    df["_row_order"] = range(len(df))

    # Documento numérico (por ejemplo "0007" -> 7). Si falla, queda NaN.
    df["_doc_num"] = pd.to_numeric(df.get("_doc_id"), errors="coerce")

    # Ordenar por id para reproducir el orden cronológico del logbook
    if "_doc_num" in df.columns:
        df = df.sort_values(by=["_doc_num", "_doc_id", "_row_order"], ascending=True, na_position="last").reset_index(drop=True)

    # Normalizar nombres de columnas (espacios, mayúsculas, guiones bajos...)
    def _norm_name(name: str) -> str:
        return (
            str(name)
            .replace("_", " ")
            .replace("-", " ")
            .strip()
            .casefold()
        )

    canonical = {
        "fecha": "Fecha",
        "tiempo total de vuelo": "Tiempo total de vuelo",
        "noche": "Noche",
        "ifr": "IFR",
        "total de sesion": "Total de sesión",
        "piloto al mando": "Piloto al mando",
    }

    rename_map = {}
    for col in df.columns:
        key = _norm_name(col)
        if key in canonical:
            rename_map[col] = canonical[key]

    if rename_map:
        df = df.rename(columns=rename_map)

    # Convertir fecha
    if "Fecha" in df.columns:
        # Aceptar tanto string tipo dd/mm/YYYY como timestamp de Firestore
        if pd.api.types.is_datetime64_any_dtype(df["Fecha"]):
            df["Fecha"] = pd.to_datetime(df["Fecha"]).dt.date
        else:
            df["Fecha"] = pd.to_datetime(df["Fecha"], dayfirst=True, errors="coerce").dt.date

    # Función auxiliar para convertir valores tipo "hh:mm" o numéricos a horas decimales
    def time_to_hours(series):
        if series is None:
            return pd.Series(dtype="float")

        s = series

        def parse_value(x) -> float:
            if pd.isna(x):
                return 0.0
            txt = str(x).strip()
            if txt == "":
                return 0.0

            # Formato hh:mm (por ejemplo "01:54")
            if ":" in txt:
                parts = txt.split(":")
                try:
                    h = int(parts[0]) if len(parts) > 0 else 0
                    m = int(parts[1]) if len(parts) > 1 else 0
                    return float(h) + float(m) / 60.0
                except Exception:
                    return 0.0

            # Intentar interpretarlo como número de horas (1.5 -> 1.5 h)
            try:
                return float(txt.replace(",", "."))
            except Exception:
                return 0.0

        return s.apply(parse_value).astype(float)

    for col in ["Tiempo total de vuelo", "Noche", "IFR", "Total de sesión", "Piloto al mando"]:
        if col in df.columns:
            df[col + "_horas"] = time_to_hours(df[col])

    return df


def main():
    st.set_page_config(page_title="Logbook", layout="wide")
    st.title("Estadísticas de Logbook")

    # Función local para mostrar horas decimales como hh:mm
    def format_hours(hours: float) -> str:
        if pd.isna(hours):
            return "00:00"
        total_minutes = int(round(float(hours) * 60))
        h = total_minutes // 60
        m = total_minutes % 60
        return f"{h:02d}:{m:02d}"

    with st.spinner("Cargando datos desde Firestore..."):
        df = load_data_from_firestore()

    if df.empty:
        st.warning("No se han encontrado datos en la colección 'logbook'.")
        return

    # Cargar datos de aeropuertos (ICAO -> lat/lon)
    @st.cache_data(show_spinner=False)
    def load_airports():
        try:
            ap = pd.read_csv("airports.csv", sep=";")
        except Exception:
            return pd.DataFrame()
        ap = ap.rename(columns={"Lat": "lat", "Lon": "lon", "ICAO": "ICAO"})
        ap = ap.dropna(subset=["lat", "lon", "ICAO"])
        return ap[["ICAO", "lat", "lon"]]

    airports_df = load_airports()

    # Filtro de fechas (usando Fecha para vuelos y Fecha simu para sesiones)
    if "Fecha" not in df.columns and "Fecha simu" not in df.columns:
        st.error("No se encuentran columnas de fecha en los datos.")
        return

    # Fecha de vuelo
    fecha_vuelo = pd.to_datetime(df.get("Fecha"), errors="coerce", dayfirst=True)
    fecha_ref = fecha_vuelo.copy()

    # Donde no haya fecha de vuelo, usar Fecha simu (sesiones de simulador)
    if "Fecha simu" in df.columns:
        fecha_simu = pd.to_datetime(df["Fecha simu"], errors="coerce", dayfirst=True)
        fecha_ref = fecha_ref.where(fecha_ref.notna(), fecha_simu)

    fecha_valid = fecha_ref.dropna()

    if fecha_valid.empty:
        st.error("No hay fechas válidas en los datos.")
        return

    fecha_valid_date = fecha_valid.dt.date
    min_date = fecha_valid_date.min()
    max_date = fecha_valid_date.max()

    col1, col2 = st.columns(2)
    with col1:
        st.write("Rango de fechas disponible:", f"{min_date} - {max_date}")
    with col2:
        date_range = st.date_input(
            "Selecciona el periodo",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )

    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date = date_range
        end_date = date_range

    if start_date > end_date:
        st.error("La fecha inicial no puede ser posterior a la final.")
        return

    # Usar la fecha de referencia (vuelo o simulador) para el filtrado
    fecha_ref_date = fecha_ref.dt.date
    mask = (fecha_ref_date >= start_date) & (fecha_ref_date <= end_date)
    df_filtered = df.loc[mask].copy()
    # Mantener la columna "Fecha" original y exponer una fecha de referencia para orden/agregaciones
    df_filtered["_fecha_ref"] = fecha_ref_date[mask]

    st.subheader("Resumen del periodo seleccionado")
    if df_filtered.empty:
        st.info("No hay vuelos en el rango seleccionado.")
        return

    # Cálculo de estadísticas
    total_vuelo = df_filtered.get("Tiempo total de vuelo_horas", pd.Series(dtype="float")).sum()
    total_noche = df_filtered.get("Noche_horas", pd.Series(dtype="float")).sum()
    total_ifr = df_filtered.get("IFR_horas", pd.Series(dtype="float")).sum()
    total_simu = df_filtered.get("Total de sesión_horas", pd.Series(dtype="float")).sum()
    total_piloto_mando = df_filtered.get("Piloto al mando_horas", pd.Series(dtype="float")).sum()

    landings_dia_series = pd.to_numeric(
        df_filtered.get("Landings día", pd.Series(dtype="float")), errors="coerce"
    ).fillna(0)
    landings_noche_series = pd.to_numeric(
        df_filtered.get("Landings Noche", pd.Series(dtype="float")), errors="coerce"
    ).fillna(0)

    total_landings_dia = landings_dia_series.sum()
    total_landings_noche = landings_noche_series.sum()
    total_landings = total_landings_dia + total_landings_noche

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Total de vuelo", format_hours(total_vuelo))
    col_b.metric("Noche", format_hours(total_noche))
    col_c.metric("IFR", format_hours(total_ifr))
    col_d.metric("Total de simulador", format_hours(total_simu))

    col_e, col_f, col_g, col_h = st.columns(4)
    col_e.metric("Aterrizajes día", int(total_landings_dia))
    col_f.metric("Aterrizajes noche", int(total_landings_noche))
    col_g.metric("Total aterrizajes", int(total_landings))
    col_h.metric("Piloto al mando", format_hours(total_piloto_mando))

    # Preparar agregaciones por mes
    df_filtered["año_mes"] = pd.to_datetime(df_filtered["_fecha_ref"], errors="coerce").dt.to_period("M").astype(str)

    # Conteo de vuelos y sesiones de simulador por mes
    vuelos_por_mes = (
        df_filtered.assign(es_vuelo=df_filtered["Tiempo total de vuelo_horas"] > 0)
        .groupby("año_mes")["es_vuelo"]
        .sum()
        .reset_index(name="Vuelos")
    )

    sesiones_por_mes = (
        df_filtered.assign(es_simu=df_filtered["Total de sesión_horas"] > 0)
        .groupby("año_mes")["es_simu"]
        .sum()
        .reset_index(name="Sesiones simulador")
    )

    conteos_mes = (
        vuelos_por_mes.merge(sesiones_por_mes, on="año_mes", how="outer")
        .fillna(0)
        .sort_values("año_mes")
    )

    conteos_long = conteos_mes.melt(
        id_vars="año_mes", value_vars=["Vuelos", "Sesiones simulador"],
        var_name="Tipo", value_name="Cantidad"
    )

    st.subheader("Vuelos y sesiones de simulador por mes")
    chart_conteos = (
        alt.Chart(conteos_long)
        .mark_bar()
        .encode(
            x=alt.X("año_mes:N", axis=alt.Axis(title=None)),
            y=alt.Y("Cantidad:Q", stack="zero", axis=alt.Axis(title=None)),
            color=alt.Color("Tipo:N", legend=None),
        )
    )
    st.altair_chart(chart_conteos, width="stretch")

    # Horas de vuelo y de simulador por mes
    horas_vuelo_mes = (
        df_filtered.groupby("año_mes")["Tiempo total de vuelo_horas"]
        .sum()
        .reset_index(name="Horas vuelo")
    )

    horas_simu_mes = (
        df_filtered.groupby("año_mes")["Total de sesión_horas"]
        .sum()
        .reset_index(name="Horas simulador")
    )

    horas_mes = (
        horas_vuelo_mes.merge(horas_simu_mes, on="año_mes", how="outer")
        .fillna(0)
        .sort_values("año_mes")
    )

    horas_long = horas_mes.melt(
        id_vars="año_mes", value_vars=["Horas vuelo", "Horas simulador"],
        var_name="Tipo", value_name="Horas"
    )

    st.subheader("Horas de vuelo y simulador por mes")
    chart_horas = (
        alt.Chart(horas_long)
        .mark_bar()
        .encode(
            x=alt.X("año_mes:N", axis=alt.Axis(title=None)),
            y=alt.Y("Horas:Q", stack="zero", axis=alt.Axis(title=None)),
            color=alt.Color("Tipo:N", legend=None),
        )
    )
    st.altair_chart(chart_horas, width="stretch")

    # Solo vuelos reales (excluir sesiones de simulador) para gráficas por tipo y por PIC
    if "Tiempo total de vuelo_horas" in df_filtered.columns:
        df_vuelos = df_filtered[df_filtered["Tiempo total de vuelo_horas"] > 0].copy()
    else:
        df_vuelos = df_filtered.iloc[0:0].copy()

    # Vuelos por tipo de avión (columna Fabricante)
    if not df_vuelos.empty and "Fabricante" in df_vuelos.columns:
        vuelos_por_tipo = (
            df_vuelos.groupby("Fabricante")
            .size()
            .reset_index(name="Vuelos")
            .sort_values("Vuelos", ascending=False)
        )

        st.subheader("Vuelos por tipo de avión")
        chart_tipo = (
            alt.Chart(vuelos_por_tipo)
            .mark_bar()
            .encode(
                x=alt.X("Vuelos:Q", axis=alt.Axis(title=None)),
                y=alt.Y("Fabricante:N", sort="-x", axis=alt.Axis(title=None)),
                color=alt.value("#1f77b4"),
            )
        )
        st.altair_chart(chart_tipo, width="stretch")

    # Top 10 Nombre del PIC (Top 10 Captains)
    if not df_vuelos.empty and "Nombre del PIC" in df_vuelos.columns:
        st.subheader("Top 10 Captains")

        # Filtro opcional para excluir a GALÁN, colocado justo debajo del título
        excluir_galan = st.checkbox("Omitirme", value=True)

        df_pic = df_vuelos.copy()
        if excluir_galan:
            df_pic = df_pic[df_pic["Nombre del PIC"] != "GALÁN"]

        if df_pic.empty:
            st.info("No hay datos para mostrar en el Top 10 Captains.")
        else:
            top_pic = (
                df_pic.groupby("Nombre del PIC")
                .size()
                .reset_index(name="Vuelos")
                .sort_values("Vuelos", ascending=False)
                .head(10)
            )

            chart_pic = (
                alt.Chart(top_pic, title="")
                .mark_bar()
                .encode(
                    x=alt.X("Vuelos:Q", axis=alt.Axis(title=None)),
                    y=alt.Y("Nombre del PIC:N", sort="-x", axis=alt.Axis(title=None)),
                    color=alt.value("#ff7f0e"),
                )
            )
            st.altair_chart(chart_pic, width="stretch")

    # Top 10 Matrículas
    if not df_vuelos.empty and "Matrícula" in df_vuelos.columns:
        top_mat = (
            df_vuelos.groupby("Matrícula")
            .size()
            .reset_index(name="Vuelos")
            .sort_values("Vuelos", ascending=False)
            .head(10)
        )

        st.subheader("Top 10 Matrículas")
        chart_mat = (
            alt.Chart(top_mat, title="")
            .mark_bar()
            .encode(
                x=alt.X("Vuelos:Q", axis=alt.Axis(title=None)),
                y=alt.Y("Matrícula:N", sort="-x", axis=alt.Axis(title=None)),
                color=alt.value("#2ca02c"),
            )
        )
        st.altair_chart(chart_mat, width="stretch")

        # Mapa de rutas (solo vuelos reales con origen y destino conocidos)
        if not df_vuelos.empty and not airports_df.empty:
            rutas = df_vuelos.dropna(subset=["Origen", "Destino"])[["Origen", "Destino"]].copy()
            rutas = rutas.rename(columns={"Origen": "ICAO_origen", "Destino": "ICAO_destino"})

            rutas = (
                rutas
                .merge(airports_df.add_prefix("orig_"), left_on="ICAO_origen", right_on="orig_ICAO", how="inner")
                .merge(airports_df.add_prefix("dest_"), left_on="ICAO_destino", right_on="dest_ICAO", how="inner")
            )

            # Hacer las rutas no dirigidas: LEMD->EBBR y EBBR->LEMD cuentan como la misma
            if not rutas.empty:
                rutas_canon = rutas.copy()
                mask_swap = rutas_canon["ICAO_origen"] > rutas_canon["ICAO_destino"]

                # Intercambiar ICAO y coordenadas donde el origen "sea mayor" que el destino
                rutas_canon.loc[mask_swap, ["ICAO_origen", "ICAO_destino"]] = rutas_canon.loc[
                    mask_swap, ["ICAO_destino", "ICAO_origen"]
                ].values
                rutas_canon.loc[mask_swap, ["orig_lat", "orig_lon", "dest_lat", "dest_lon"]] = rutas_canon.loc[
                    mask_swap, ["dest_lat", "dest_lon", "orig_lat", "orig_lon"]
                ].values

                rutas_grouped = (
                    rutas_canon
                    .groupby(["ICAO_origen", "ICAO_destino", "orig_lat", "orig_lon", "dest_lat", "dest_lon"], as_index=False)
                    .size()
                    .rename(columns={"size": "num_vuelos"})
                )

                st.subheader("Mapa de rutas")

                # Centro aproximado del mapa: media de todas las coordenadas
                center_lat = float((rutas_grouped["orig_lat"].mean() + rutas_grouped["dest_lat"].mean()) / 2)
                center_lon = float((rutas_grouped["orig_lon"].mean() + rutas_grouped["dest_lon"].mean()) / 2)

                layer = pdk.Layer(
                    "ArcLayer",
                    data=rutas_grouped,
                    get_source_position="[orig_lon, orig_lat]",
                    get_target_position="[dest_lon, dest_lat]",
                    # Grosor fijo para todas las rutas
                    get_width=3,
                    get_source_color=[31, 119, 180, 200],
                    get_target_color=[255, 127, 14, 200],
                    auto_highlight=True,
                    pickable=False,
                )

                view_state = pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=3, bearing=0, pitch=0)

                # Usar el estilo de mapa por defecto de Streamlit/pydeck (sin Mapbox explícito)
                deck = pdk.Deck(layers=[layer], initial_view_state=view_state)
                st.pydeck_chart(deck)

    st.subheader("Exportar Logbook a PDF")

    @st.cache_data(show_spinner=False)
    def _build_pdf_cached(df_for_pdf: pd.DataFrame, generator_salt: float) -> bytes:
        return generate_logbook_pdf_bytes(
            df_for_pdf,
            template_path="Logbook_Rellenable.pdf",
            layout=DEFAULT_LAYOUT,
            max_font_size=10,
            min_font_size=6,
        )

    # Para el PDF: respetar el orden real del logbook por ID de documento (0000..).
    # Dentro del rango de fechas, cogemos el PRIMER y ÚLTIMO doc_id y exportamos
    # todo lo que haya ENTRE medias (incluye documentos vacíos como filas en blanco).
    df_for_pdf = df_filtered.copy()
    if not df_for_pdf.empty and "_doc_num" in df_for_pdf.columns and df_for_pdf["_doc_num"].notna().any():
        min_doc = float(df_for_pdf["_doc_num"].min())
        max_doc = float(df_for_pdf["_doc_num"].max())

        df_for_pdf = df[(df["_doc_num"] >= min_doc) & (df["_doc_num"] <= max_doc)].copy()

        # Añadir _fecha_ref para el generador (puede ser NaT en documentos vacíos)
        df_for_pdf["_fecha_ref"] = fecha_ref_date.loc[df_for_pdf.index]

        df_for_pdf = df_for_pdf.sort_values(by=["_doc_num", "_doc_id", "_row_order"], ascending=True, na_position="last")
    else:
        # Fallback: si no hay doc_num o no hay filas con fecha, al menos ordenar por fecha ref
        if "_fecha_ref" in df_for_pdf.columns:
            df_for_pdf = df_for_pdf.sort_values("_fecha_ref", ascending=True, na_position="last")

    with st.spinner("Generando Logbook.pdf..."):
        # Invalida la caché automáticamente cuando cambia el generador
        generator_salt = Path("logbook_pdf.py").stat().st_mtime if Path("logbook_pdf.py").exists() else 0.0
        pdf_bytes = _build_pdf_cached(df_for_pdf, generator_salt)

    downloaded = st.download_button(
        "Logbook",
        data=pdf_bytes,
        file_name="Logbook.pdf",
        mime="application/pdf",
    )

    if downloaded:
        with open("Logbook.pdf", "wb") as f:
            f.write(pdf_bytes)


if __name__ == "__main__":
    main()
