import streamlit as st
import pandas as pd
import requests
import io

# Título de la aplicación
st.title("LogBook")

st.write("Hola, sube el registro de Air Europa Express para ir actualizando tu LogBook.")

# Subida de archivo por parte del usuario
AirEuropaX = st.file_uploader("Archivo de OVA", type=["xls", "xlsx"])

# URL del archivo en Google Drive
url = "https://drive.google.com/uc?id=1EEOw7lwds1JtqfKPLoeQDWhMLVpkaATJ"

# Función para cargar datos desde Google Drive
@st.cache_resource
def cargar_datos_desde_drive():
    response = requests.get(url)
    if response.status_code == 200:
        # Leer datos como CSV desde el contenido descargado
        df = pd.read_csv(io.StringIO(response.text), header=None, sep=";")
        df.columns = [
            "Fecha", "Origen", "Salida", "Destino", "Llegada", "Fabricante", 
            "Matrícula", "SE", "ME", "Tiempo multipiloto", "Tiempo total de vuelo", 
            "Nombre del PIC", "Landings Día", "Landings Noche", "Noche", "IFR", 
            "Piloto al mando", "Co-piloto", "Doble mando", "Instructor", 
            "Fecha simu", "Tipo", "Total de sesión", "Observaciones"
        ]
        return df
    else:
        st.error("Error al descargar los datos desde Google Drive.")
        return pd.DataFrame()  # Devuelve un DataFrame vacío en caso de error

# Cargar datos desde Drive
datos_drive = cargar_datos_desde_drive()

if not datos_drive.empty:
    st.write("Datos cargados desde Google Drive:")
    st.dataframe(datos_drive)

# Procesar el archivo subido por el usuario
if AirEuropaX is not None:
    try:
        # Detectar formato de archivo
        if AirEuropaX.name.endswith(".xls"):
            datos_usuario = pd.read_excel(AirEuropaX, engine="xlrd")
        else:
            datos_usuario = pd.read_excel(AirEuropaX, engine="openpyxl")
        
        st.write("Datos cargados del archivo subido:")
        st.dataframe(datos_usuario)
    except Exception as e:
        st.error(f"Error al leer el archivo: {e}")
