import streamlit as st
from functions import (descargar_y_actualizar_csv, 
                       update_file_in_drive_by_name, 
                       descargar_csv, 
                       rellenar_y_combinar_pdfs,
                       preprocess_data,
                       calculate_statistics)
import plotly.express as px  # Importamos Plotly Express para gráficas interactivas
import pandas as pd

FOLDER_ID = '1B8gnCmbBaGMBT77ba4ntjpZj_NkJcvuI'  # Drive folder ID

def main():
    st.title("LogBook")
    st.write("Hola, sube el registro de Air Europa Express para ir actualizando tu LogBook.")
    file_uploader = st.file_uploader("label", type="xls", label_visibility="hidden")
    
    if st.button("Subir datos") and file_uploader is not None:
        user_data = descargar_y_actualizar_csv('LogBook.csv', FOLDER_ID, file_uploader)
        if user_data is None or len(user_data) < 2:
            st.write("El archivo está vacío o no se pudo descargar.")
        else:
            st.write(user_data)
            user_data.to_csv('Actualizado.csv', index=False, sep=';', encoding='UTF-8')
            local_path = 'Actualizado.csv'
            update_file_in_drive_by_name('LogBook.csv', FOLDER_ID, local_path)
            st.write("Archivo actualizado y subido a Google Drive.")
            
    if st.button("Ver datos"):
        user_data = descargar_csv('LogBook.csv', FOLDER_ID)
        
        if user_data is not None:
            # Calcular y mostrar estadísticas
            stats = calculate_statistics(user_data)
            st.subheader("Estadísticas del LogBook")
            st.write(f"**Total de Horas de Vuelo:** {stats['Total Flight Hours']:.2f} horas")
            st.write(f"**Total de Horas de Simulador:** {stats['Total Simulator Hours']:.2f} horas")
            st.write(f"**Total de Landings:** {stats['Total Landings']}")
            
            # Gráfica de horas por tipo de avión (interactiva con Plotly)
            st.subheader("Horas por Tipo de Avión")
            aircraft_types = [aircraft for aircraft, hours in stats['Hours by Aircraft'].items() if hours > 0]
            hours = [hours for hours in stats['Hours by Aircraft'].values() if hours > 0]
            fig1 = px.bar(
                x=aircraft_types, 
                y=hours, 
                labels={'x': 'Tipo de Avión', 'y': 'Horas de Vuelo'},
                title='Horas por Tipo de Avión',
                color_discrete_sequence=['lightgreen']  # Color similar al original
            )
            fig1.update_layout(xaxis_tickangle=-45)  # Rotar etiquetas para mejor legibilidad
            st.plotly_chart(fig1, use_container_width=True)
            
            st.write(f"**Total de Horas como Piloto al Mando:** {stats['Total PIC Hours']:.2f} horas")
            st.write(f"**Total de Horas Nocturnas:** {stats['Total Night Hours']:.2f} horas")
            st.write(f"**Total de Horas IFR:** {stats['Total IFR Hours']:.2f} horas")
            
            # Gráfica de vuelos por mes/año (interactiva con Plotly)
            st.subheader("Vuelos por Mes/Año")
            months = [str(month) for month in stats['Flights by Month'].keys()]
            flight_counts = list(stats['Flights by Month'].values())
            fig2 = px.bar(
                x=months, 
                y=flight_counts, 
                labels={'x': 'Mes/Año', 'y': 'Número de Vuelos'},
                title='Vuelos por Mes/Año',
                color_discrete_sequence=['skyblue']  # Color similar al original
            )
            fig2.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig2, use_container_width=True)
            
            # Gráfica de horas por mes/año (interactiva con Plotly)
            st.subheader("Horas de Vuelo por Mes/Año")
            df_clean = preprocess_data(user_data)
            hours_by_month = (df_clean.groupby(df_clean["datetime"].dt.to_period("M"))
                             ["Tiempo total de vuelo"].sum() / 60).to_dict()
            months_hours = [str(month) for month in hours_by_month.keys()]
            hours_values = list(hours_by_month.values())
            fig3 = px.bar(
                x=months_hours, 
                y=hours_values, 
                labels={'x': 'Mes/Año', 'y': 'Horas de Vuelo'},
                title='Horas de Vuelo por Mes/Año',
                color_discrete_sequence=['salmon']  # Color similar al original
            )
            fig3.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig3, use_container_width=True)
            
            # Generar y ofrecer descarga del PDF
            pdf_path = rellenar_y_combinar_pdfs("LogBook_Rellenable.pdf", "LogBook_Rellenado.pdf", user_data)
            with open(pdf_path, "rb") as pdf_file:
                pdf_data = pdf_file.read()

            if st.download_button(
                label="Descargar LogBook",
                data=pdf_data,
                file_name='LogBook.pdf',
                mime='application/pdf'
            ):
                st.write("¡LogBook descargado!")
        else:
            st.write("No se ha podido actualizar el archivo.")
            st.write(user_data)

if __name__ == "__main__":
    main()
