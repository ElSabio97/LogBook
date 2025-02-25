import streamlit as st
from functions import (descargar_y_actualizar_csv, 
                       update_file_in_drive_by_name, 
                       descargar_csv, 
                       rellenar_y_combinar_pdfs,
                       preprocess_data,
                       calculate_statistics)
import matplotlib.pyplot as plt
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
            
            # Gráfica de horas por tipo de avión
            st.subheader("Horas por Tipo de Avión")
            aircraft_types = [aircraft for aircraft, hours in stats['Hours by Aircraft'].items() if hours > 0]
            hours = [hours for hours in stats['Hours by Aircraft'].values() if hours > 0]
            
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.bar(aircraft_types, hours, color='lightgreen')
            ax.set_xlabel('Tipo de Avión')
            ax.set_ylabel('Horas de Vuelo')
            ax.set_title('Horas por Tipo de Avión')
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()
            st.pyplot(fig)
            
            st.write(f"**Total de Horas como Piloto al Mando:** {stats['Total PIC Hours']:.2f} horas")
            st.write(f"**Total de Horas Nocturnas:** {stats['Total Night Hours']:.2f} horas")
            st.write(f"**Total de Horas IFR:** {stats['Total IFR Hours']:.2f} horas")
            
            # Gráfica de vuelos por mes/año
            st.subheader("Vuelos por Mes/Año")
            months = [str(month) for month in stats['Flights by Month'].keys()]
            flight_counts = list(stats['Flights by Month'].values())
            
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.bar(months, flight_counts, color='skyblue')
            ax.set_xlabel('Mes/Año')
            ax.set_ylabel('Número de Vuelos')
            ax.set_title('Vuelos por Mes/Año')
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()
            st.pyplot(fig)
            
            # Nueva gráfica de horas por mes/año
            st.subheader("Horas de Vuelo por Mes/Año")
            # Calcular las horas por mes desde los datos preprocesados
            df_clean = preprocess_data(user_data)
            hours_by_month = (df_clean.groupby(df_clean["datetime"].dt.to_period("M"))
                             ["Tiempo total de vuelo"].sum() / 60).to_dict()
            months_hours = [str(month) for month in hours_by_month.keys()]
            hours_values = list(hours_by_month.values())
            
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.bar(months_hours, hours_values, color='salmon')
            ax.set_xlabel('Mes/Año')
            ax.set_ylabel('Horas de Vuelo')
            ax.set_title('Horas de Vuelo por Mes/Año')
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()
            st.pyplot(fig)
            
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