import streamlit as st
from functions import (
    descargar_csv,
    rellenar_y_combinar_pdfs,
    preprocess_data,
    calculate_statistics,
    filter_future_dates,
    airport_operations,
    build_airport_map_df,
    build_routes_map_df,
)
import plotly.express as px
import pandas as pd

FOLDER_ID = "1B8gnCmbBaGMBT77ba4ntjpZj_NkJcvuI"  # Drive folder ID (sólo lectura)


def main():
    st.title("LogBook")
    st.write(
        "Visualizador de tu LogBook. Los datos se leen de `LogBook.csv` "
        "(en Google Drive) y podrás ver estadísticas y descargar el PDF."
    )
    # Cargar datos automáticamente al iniciar
    user_data = descargar_csv('LogBook.csv', FOLDER_ID)

    if user_data is not None:
        # Filtrar posibles vuelos en fechas futuras
        user_data = filter_future_dates(user_data)

        # Si después de filtrar no queda nada, avisar y salir
        if user_data.empty:
            st.warning(
                "No se han encontrado vuelos en `LogBook.csv` "
                "(puede que esté vacío o todas las fechas sean futuras)."
            )
            return

        # ---- Filtro opcional por periodo de fechas ----
        min_date = user_data["datetime"].dt.date.min()
        max_date = user_data["datetime"].dt.date.max()

        st.subheader("Periodo de tiempo")
        start_date, end_date = st.date_input(
            "Selecciona el rango de fechas",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )

        # Asegurar que start_date <= end_date
        if start_date > end_date:
            st.error("La fecha de inicio no puede ser posterior a la fecha de fin.")
            return

        mask = (user_data["datetime"].dt.date >= start_date) & (
            user_data["datetime"].dt.date <= end_date
        )
        period_data = user_data[mask].copy()

        if period_data.empty:
            st.warning("No hay vuelos en el rango de fechas seleccionado.")
            return

        # Calcular y mostrar estadísticas para el periodo seleccionado
        stats = calculate_statistics(period_data)
        st.subheader("Estadísticas del LogBook")
        st.write(f"**Total de Horas de Vuelo:** {stats['Total Flight Hours']:.2f} horas")
        st.write(f"**Total de Horas de Simulador:** {stats['Total Simulator Hours']:.2f} horas")
        st.write(f"**Total de Landings:** {stats['Total Landings']}")
        
        # Gráfica de horas por tipo de avión (interactiva con Plotly)
        st.subheader("Horas por Tipo de Avión")
        aircraft_items = [
            (aircraft, h)
            for aircraft, h in stats["Hours by Aircraft"].items()
            if h > 0
        ]
        df_aircraft = pd.DataFrame(
            aircraft_items, columns=["Tipo de Avión", "Horas de Vuelo"]
        )
        fig1 = px.bar(
            df_aircraft,
            x="Tipo de Avión",
            y="Horas de Vuelo",
            labels={"Tipo de Avión": "Tipo de Avión", "Horas de Vuelo": "Horas de Vuelo"},
            title="Horas por Tipo de Avión",
            color_discrete_sequence=["lightgreen"],  # Color similar al original
        )
        fig1.update_layout(xaxis_tickangle=-45)  # Rotar etiquetas para mejor legibilidad
        st.plotly_chart(fig1, width="stretch")
        
        st.write(f"**Total de Horas como Piloto al Mando:** {stats['Total PIC Hours']:.2f} horas")
        st.write(f"**Total de Horas Nocturnas:** {stats['Total Night Hours']:.2f} horas")
        st.write(f"**Total de Horas IFR:** {stats['Total IFR Hours']:.2f} horas")
        
        # Gráfica de vuelos por mes/año (interactiva con Plotly)
        st.subheader("Vuelos por Mes/Año")
        months = [str(month) for month in stats['Flights by Month'].keys()]
        flight_counts = list(stats['Flights by Month'].values())
        df_flights = pd.DataFrame({
            'Mes/Año': months,
            'Número de Vuelos': flight_counts
        })
        fig2 = px.bar(
            df_flights,
            x='Mes/Año',
            y='Número de Vuelos',
            labels={'Mes/Año': 'Mes/Año', 'Número de Vuelos': 'Número de Vuelos'},
            title='Vuelos por Mes/Año',
            color_discrete_sequence=['skyblue']  # Color similar al original
        )
        fig2.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig2, width="stretch")
        
        # Gráfica de horas por mes/año (interactiva con Plotly)
        st.subheader("Horas de Vuelo por Mes/Año")
        df_clean = preprocess_data(period_data)
        hours_by_month = (df_clean.groupby(df_clean["datetime"].dt.to_period("M"))
                         ["Tiempo total de vuelo"].sum() / 60).to_dict()
        months_hours = [str(month) for month in hours_by_month.keys()]
        hours_values = list(hours_by_month.values())
        df_hours = pd.DataFrame({
            'Mes/Año': months_hours,
            'Horas de Vuelo': hours_values
        })
        fig3 = px.bar(
            df_hours,
            x='Mes/Año',
            y='Horas de Vuelo',
            labels={'Mes/Año': 'Mes/Año', 'Horas de Vuelo': 'Horas de Vuelo'},
            title='Horas de Vuelo por Mes/Año',
            color_discrete_sequence=['salmon']  # Color similar al original
        )
        fig3.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig3, width="stretch")

        # Gráfica: Top 10 matrículas más voladas (solo vuelos, sin simulador)
        st.subheader("Top 10 Matrículas Más Voladas")
        df_flights_regs = df_clean.copy()
        if "Fecha" in df_flights_regs.columns:
            df_flights_regs = df_flights_regs[df_flights_regs["Fecha"] != "--"]

        if "Matrícula" in df_flights_regs.columns:
            regs = (
                df_flights_regs["Matrícula"]
                .astype(str)
                .str.strip()
                .replace({"": pd.NA, "NAN": pd.NA, "--": pd.NA})
                .dropna()
            )

            reg_counts = regs.value_counts().head(10)
            if not reg_counts.empty:
                df_regs = reg_counts.reset_index()
                df_regs.columns = ["Matrícula", "Número de Vuelos"]
                fig_regs = px.bar(
                    df_regs,
                    x="Matrícula",
                    y="Número de Vuelos",
                    labels={
                        "Matrícula": "Matrícula",
                        "Número de Vuelos": "Número de Vuelos",
                    },
                    title="Top 10 Matrículas Más Voladas",
                    color_discrete_sequence=["mediumpurple"],
                )
                fig_regs.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig_regs, width="stretch")

        # Top 10 PIC con los que más he volado (solo vuelos, sin simulador)
        st.subheader("Top 10 PIC con los que más he volado")
        df_pics = df_clean.copy()
        if "Fecha" in df_pics.columns:
            df_pics = df_pics[df_pics["Fecha"] != "--"]

        if "Nombre del PIC" in df_pics.columns:
            omit_galan = st.checkbox("Omitir GALÁN", value=True)
            if omit_galan:
                # Excluir específicamente el nombre GALÁN (con o sin acento)
                names = df_pics["Nombre del PIC"].astype(str).str.strip()
                mask = ~names.str.contains(r"^GAL[ÁA]N$", case=False, regex=True, na=False)
                df_pics = df_pics[mask]

            pics = (
                df_pics["Nombre del PIC"]
                .astype(str)
                .str.strip()
                .replace({"": pd.NA, "NAN": pd.NA, "--": pd.NA})
                .dropna()
            )

            pic_counts = pics.value_counts().head(10)
            if not pic_counts.empty:
                df_pics_top = pic_counts.reset_index()
                df_pics_top.columns = ["Nombre del PIC", "Número de Vuelos"]
                fig_pics = px.bar(
                    df_pics_top,
                    x="Nombre del PIC",
                    y="Número de Vuelos",
                    labels={
                        "Nombre del PIC": "Nombre del PIC",
                        "Número de Vuelos": "Número de Vuelos",
                    },
                    title="Top 10 PIC con los que más he volado",
                    color_discrete_sequence=["seagreen"],
                )
                fig_pics.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig_pics, width="stretch")

        # NUEVAS GRAFICAS: Despegues y Aterrizajes por Aeropuerto
        st.subheader("Despegues y Aterrizajes por Aeropuerto")
        takeoffs, landings = airport_operations(period_data)
        # Opción para omitir aeropuertos base LEMD y LECU
        omit_hubs = st.checkbox("Omitir LEMD y LECU", value=True)
        if omit_hubs:
            takeoffs = takeoffs[~takeoffs.index.isin(["LEMD", "LECU"])]
            landings = landings[~landings.index.isin(["LEMD", "LECU"])]
        # Limitar a top 20 para evitar saturar (configurable)
        top_n = st.slider("Número de aeropuertos a mostrar", 5, 50, 20)
        takeoffs_top = takeoffs.head(top_n).reset_index()
        takeoffs_top.columns = ['Aeropuerto', 'Despegues']
        landings_top = landings.head(top_n).reset_index()
        landings_top.columns = ['Aeropuerto', 'Aterrizajes']
        fig4 = px.bar(takeoffs_top, x='Aeropuerto', y='Despegues', title='Despegues por Aeropuerto', color='Despegues', color_continuous_scale='Blues')
        fig4.update_layout(xaxis_tickangle=-60)
        st.plotly_chart(fig4, width="stretch")
        fig5 = px.bar(landings_top, x='Aeropuerto', y='Aterrizajes', title='Aterrizajes por Aeropuerto', color='Aterrizajes', color_continuous_scale='Oranges')
        fig5.update_layout(xaxis_tickangle=-60)
        st.plotly_chart(fig5, width="stretch")

        # Mapa de aeropuertos visitados
        st.subheader("Mapa de Aeropuertos Visitados")
        df_map = build_airport_map_df(period_data)
        if df_map.empty:
            st.info("No hay datos suficientes para mostrar el mapa de aeropuertos.")
        else:
            fig_map = px.scatter_geo(
                df_map,
                lat="Lat",
                lon="Lon",
                size="Operaciones",
                hover_name="Aeropuerto",
                hover_data={"IATA": True, "Operaciones": True, "Lat": False, "Lon": False},
                title="Aeropuertos visitados (tamaño según nº de operaciones)",
                projection="natural earth",
            )
            fig_map.update_geos(fitbounds="locations", showcountries=True, showcoastlines=True)
            st.plotly_chart(fig_map, width="stretch")

        # Mapa de rutas voladas
        st.subheader("Mapa de Rutas Voladas")
        df_routes = build_routes_map_df(period_data)
        if df_routes.empty:
            st.info("No hay datos suficientes para mostrar el mapa de rutas.")
        else:
            fig_routes = px.line_geo(
                df_routes,
                lat="Lat",
                lon="Lon",
                line_group="route",
                hover_name="route",
                projection="natural earth",
            )
            fig_routes.update_traces(
                line_width=2,
                hovertemplate="<b>%{hovertext}</b><extra></extra>",
            )
            fig_routes.update_geos(fitbounds="locations", showcountries=True, showcoastlines=True)
            fig_routes.update_layout(showlegend=False)
            st.plotly_chart(fig_routes, width="stretch")

        # Top 10 rutas más voladas
        st.subheader("Top 10 Rutas Más Voladas")
        if not df_routes.empty:
            directed_routes = (
                df_routes[["route", "Flights"]]
                .drop_duplicates()
                .copy()
            )

            def canonical_route(route_str: str) -> str:
                parts = route_str.split("-")
                if len(parts) == 2:
                    origin = parts[0].strip()
                    dest = parts[1].strip()
                    ordered = sorted([origin, dest])
                    return f"{ordered[0]}-{ordered[1]}"
                return route_str

            directed_routes["route_group"] = directed_routes["route"].apply(
                canonical_route
            )

            route_counts = (
                directed_routes.groupby("route_group")["Flights"]
                .sum()
                .sort_values(ascending=False)
                .head(10)
            )
            if not route_counts.empty:
                df_routes_top = route_counts.reset_index()
                df_routes_top.columns = ["Ruta", "Número de Vuelos"]
                fig_routes_top = px.bar(
                    df_routes_top,
                    x="Ruta",
                    y="Número de Vuelos",
                    labels={
                        "Ruta": "Ruta (Origen-Destino)",
                        "Número de Vuelos": "Número de Vuelos",
                    },
                    title="Top 10 Rutas Más Voladas",
                    color_discrete_sequence=["teal"],
                )
                fig_routes_top.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig_routes_top, width="stretch")

        # Generar y ofrecer descarga del PDF bajo demanda
        st.subheader("LogBook en PDF")
        if st.button("Generar LogBook"):
            try:
                pdf_path = rellenar_y_combinar_pdfs(
                    "LogBook_Rellenable.pdf",
                    "LogBook_Rellenado.pdf",
                    period_data,
                )
                with open(pdf_path, "rb") as pdf_file:
                    pdf_data = pdf_file.read()

                st.download_button(
                    label="Descargar LogBook",
                    data=pdf_data,
                    file_name="LogBook.pdf",
                    mime="application/pdf",
                )
            except Exception as e:
                st.error(f"No se pudo generar el LogBook: {e}")
    else:
        st.error(
            "No se han podido cargar los datos de `LogBook.csv` "
            "desde Google Drive."
        )

if __name__ == "__main__":
    main()
