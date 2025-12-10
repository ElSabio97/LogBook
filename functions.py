from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import requests
import pandas as pd
import io
from googleapiclient.http import MediaFileUpload
from datetime import timedelta, datetime
import fitz
import os
import json
import streamlit as st

SCOPES = ['https://www.googleapis.com/auth/drive']
COLUMNAS = [
    "Fecha", "Origen", "Salida", "Destino", "Llegada", "Fabricante",
    "Matrícula", "SE", "ME", "Tiempo multipiloto", "Tiempo total de vuelo",
    "Nombre del PIC", "Landings Día", "Landings Noche", "Noche", "IFR",
    "Piloto al mando", "Co-piloto", "Doble mando", "Instructor",
    "Fecha simu", "Tipo", "Total de sesión", "Observaciones", "datetime"
]

# Rutas y utilidades para normalizar aeropuertos (IATA -> ICAO) y mapas
BASE_DIR = os.path.dirname(__file__)
ICAO_IATA_PATH = os.path.join(BASE_DIR, "icaoiata.json")
AIRPORTS_JSON_PATH = os.path.join(BASE_DIR, "airports.json")


def _load_airport_mappings():
    """Carga el mapeo IATA->ICAO desde icaoiata.json.

    Devuelve:
        (dict, set):
            - dict IATA -> ICAO
            - set de códigos ICAO válidos
    """
    try:
        with open(ICAO_IATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        # Si falla la carga (archivo no encontrado, JSON inválido, etc.),
        # devolvemos estructuras vacías para que el resto del código siga funcionando.
        return {}, set()

    iata_to_icao = {}
    icao_codes = set()

    for row in data if isinstance(data, list) else []:
        if not isinstance(row, dict):
            continue
        icao = str(row.get("ICAO", "")).strip().upper()
        iata = str(row.get("IATA", "")).strip().upper()

        if icao:
            icao_codes.add(icao)
        if iata and icao:
            # En caso de duplicados, el último sobrescribe al anterior
            iata_to_icao[iata] = icao

    return iata_to_icao, icao_codes


IATA_TO_ICAO, ICAO_CODES = _load_airport_mappings()
# Mapa inverso aproximado para poder pasar de ICAO -> IATA
ICAO_TO_IATA = {icao: iata for iata, icao in IATA_TO_ICAO.items()}


def _load_airports_coordinates():
    """Carga coordenadas de aeropuertos desde airports.json (IATA -> lat/lon)."""
    try:
        with open(AIRPORTS_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}

    coords = {}
    if isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            iata = str(row.get("IATA", "")).strip().upper()
            if not iata:
                continue
            try:
                lat = float(row.get("Latitude"))
                lon = float(row.get("Longitude"))
            except (TypeError, ValueError):
                continue
            coords[iata] = (lat, lon)
    return coords


AIRPORT_COORDS = _load_airports_coordinates()


def normalize_airport_code_to_icao(code):
    """Normaliza un código de aeropuerto a ICAO usando icaoiata.json.

    - Si ya es un ICAO conocido, se deja tal cual.
    - Si es un IATA conocido, se convierte a ICAO.
    - Si no se conoce, se devuelve el código normalizado (upper/strip).
    - Maneja NaN y cadenas vacías devolviendo "".
    """
    if pd.isna(code):
        return ""

    code = str(code).strip().upper()
    if not code:
        return ""

    # Permitir combinaciones separadas por "/" (ej. "MAD/PMI")
    if "/" in code and len(code) > 4:
        parts = [normalize_airport_code_to_icao(part) for part in code.split("/")]
        parts = [p for p in parts if p]
        return "/".join(parts)

    # Si ya es un ICAO conocido, lo dejamos
    if code in ICAO_CODES:
        return code

    # Intentar conversión desde IATA
    if code in IATA_TO_ICAO:
        return IATA_TO_ICAO[code]

    # Si parece un ICAO (4 letras) aunque no esté en la lista, lo dejamos
    if len(code) == 4 and code.isalpha():
        return code

    # En cualquier otro caso devolvemos el código tal cual
    return code


def normalize_airport_columns_to_icao(df, columns=None):
    """Devuelve una copia de df con columnas de aeropuertos normalizadas a ICAO.

    Por defecto actúa sobre las columnas "Origen" y "Destino" si existen.
    """
    if columns is None:
        columns = ["Origen", "Destino"]

    df_norm = df.copy()
    for col in columns:
        if col in df_norm.columns:
            df_norm[col] = df_norm[col].apply(normalize_airport_code_to_icao)
    return df_norm

def get_drive_service():
    try:
        credentials_json = st.secrets["google_drive"]["credentials"]
        credentials_info = json.loads(credentials_json)
        credentials = Credentials.from_service_account_info(credentials_info, scopes=SCOPES)
        return build('drive', 'v3', credentials=credentials)
    except KeyError:
        st.error("Google Drive credentials not found.")
        raise
    except json.JSONDecodeError as e:
        st.error(f"Invalid JSON in credentials: {str(e)}")
        raise

def descargar_csv(file_name, folder_id):
    service = get_drive_service()
    query = f"name='{file_name}' and '{folder_id}' in parents"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    items = results.get('files', [])
    if not items:
        return None
    file_id = items[0]['id']
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
    response = requests.get(url, headers={"Authorization": f"Bearer {service._http.credentials.token}"})
    if response.status_code != 200:
        return None
    df = pd.read_csv(io.StringIO(response.text), header=None, names=COLUMNAS, sep=";")

    # Si la primera fila es la cabecera original del fichero, eliminarla
    if not df.empty and str(df.iloc[0, 0]).strip().upper() == "FECHA":
        df = df.iloc[1:]

    # Parsear la columna datetime en formato europeo (dd/mm/aaaa hh:mm)
    df['datetime'] = pd.to_datetime(df['datetime'], dayfirst=True, errors='coerce')

    # Eliminar filas sin datetime válido
    df = df.dropna(subset=['datetime'])

    # Normalizar aeropuertos a ICAO
    df = normalize_airport_columns_to_icao(df)
    return df

def read_new_file(new_file):
    renamed_name = new_file.name.replace(".xls", ".html")
    new_file.name = renamed_name
    file_nuevo = pd.read_html(new_file)
    df_nuevo = pd.DataFrame(file_nuevo[0]).iloc[:-2]
    df_nuevo.columns = COLUMNAS
    df_nuevo['datetime'] = pd.to_datetime(df_nuevo['Fecha'] + ' ' + df_nuevo['Salida'], format='%d/%m/%y %H:%M', errors='coerce')
    df_nuevo['datetime_simu'] = pd.to_datetime(df_nuevo['Fecha simu'], format='%d/%m/%y', errors='coerce')
    df_nuevo['datetime_simu'] += pd.to_timedelta(df_nuevo.groupby('Fecha simu').cumcount(), unit='m')
    df_nuevo['datetime'] = df_nuevo['datetime'].combine_first(df_nuevo['datetime_simu'])
    df_nuevo = df_nuevo.drop(columns=['datetime_simu'])
    # Normalizar aeropuertos a ICAO
    df_nuevo = normalize_airport_columns_to_icao(df_nuevo)
    return df_nuevo

def descargar_y_actualizar_csv(original_file, folder_id, new_file):
    df_original = descargar_csv(original_file, folder_id)
    if df_original is None:
        return None
    df_nuevo = read_new_file(new_file)
    min_datetime_nuevo = df_nuevo['datetime'].min()
    df_original_filtered = df_original[df_original['datetime'] < min_datetime_nuevo]
    df_actualizado = pd.concat([df_original_filtered, df_nuevo], ignore_index=True)
    # Normalizar aeropuertos a ICAO en el DataFrame combinado
    df_actualizado = normalize_airport_columns_to_icao(df_actualizado)
    return df_actualizado.drop_duplicates(subset=['datetime'], keep='last')

def update_file_in_drive_by_name(file_name, folder_id, file_path):
    service = get_drive_service()
    query = f"name='{file_name}' and '{folder_id}' in parents"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    items = results.get('files', [])
    if not items:
        return None
    file_id = items[0]['id']
    media = MediaFileUpload(file_path, resumable=True)
    file = service.files().update(fileId=file_id, media_body=media).execute()
    return file.get('id')

def descargar_pdf_template(file_name, folder_id):
    service = get_drive_service()
    query = f"name='{file_name}' and '{folder_id}' in parents"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    items = results.get('files', [])
    if not items:
        st.error(f"No se encontró {file_name} en Google Drive.")
        raise FileNotFoundError(f"No se encontró {file_name} en Google Drive.")
    file_id = items[0]['id']
    request = service.files().get_media(fileId=file_id)
    with open(file_name, "wb") as f:
        f.write(request.execute())
    return file_name

def rellenar_y_combinar_pdfs(entry_file, exit_file, data):
    # Descargar el PDF desde Google Drive
    folder_id = '1B8gnCmbBaGMBT77ba4ntjpZj_NkJcvuI'  # Usamos el mismo folder_id que en app.py
    input_pdf_path = descargar_pdf_template(entry_file, folder_id)

    if not os.path.exists(input_pdf_path):
        st.error(f"PDF template no encontrado después de descargarlo: {input_pdf_path}")
        raise FileNotFoundError(f"No such file: {input_pdf_path}")

    df = data.copy()

    # Si no hay datos, no podemos generar el PDF
    if df.empty:
        st.error("No hay datos en el LogBook para generar el PDF.")
        raise ValueError("DataFrame vacío en rellenar_y_combinar_pdfs")

    # Drop first row if it contains the str "Fecha"
    if df.iloc[0, 0] == "Fecha":
        df = df.iloc[1:]
    
    # Replace any . to : except in column Nombre del PIC and Tipo
    df.loc[:, df.columns.difference(['Nombre del PIC', 'Tipo'])] = df.loc[:, df.columns.difference(['Nombre del PIC', 'Tipo'])].replace(r'\.', ':', regex=True)
    
    # Set a regex to replace all str after 'B737' in column 'Fabricante' but change it to 'B738'
    df['Fabricante'] = df['Fabricante'].str.replace(r'B737.*', 'B738', regex=True)
    
    df.drop(columns=["Remark", "datetime"], inplace=True, errors='ignore')

    dataframes = [df.iloc[i:i + 14] for i in range(0, len(df), 14)]

    def time_to_minutes(time_str):
        """Convierte un string en formato HH:MM a minutos. Devuelve 0 si está vacío."""
        if pd.isna(time_str) or not time_str:
            return 0
        try:
            hours, minutes = map(int, str(time_str).split(":"))
            return hours * 60 + minutes
        except (ValueError, TypeError):
            return 0

    def minutes_to_time(minutes):
        """Convierte minutos a formato HH:MM."""
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours:02d}:{mins:02d}"

    def process_pdf_widgets(input_pdf_path, output_pdf_path, dataframes):
        base_doc = fitz.open(input_pdf_path)
        widget_data = {}
        sum_columns = ["SE", "ME", "Tiempo multipiloto", "Tiempo total de vuelo", 
                       "Landings Día", "Landings Noche", "Noche", "IFR", "Piloto al mando", 
                       "Co-piloto", "Doble mando", "Instructor", "Total de sesión"]
        numeric_columns = ["Landings Día", "Landings Noche"]
        
        for page_num, page in enumerate(base_doc):
            widgets = page.widgets()
            if widgets:
                widget_data[page_num] = []
                for widget in widgets:
                    rect = widget.rect
                    field_name = widget.field_name or "default"
                    widget_data[page_num].append({
                        'coords': (rect.x0, rect.y0, rect.x1, rect.y1),
                        'field_name': field_name
                    })
                    page.delete_widget(widget)
        
        final_doc = fitz.open()
        num_base_pages = len(base_doc)
        for _ in dataframes:
            final_doc.insert_pdf(base_doc, from_page=0, to_page=num_base_pages - 1)
        base_doc.close()
        
        def get_base_font_size(field_name):
            if "TOTAL DESDE LAS PÁGINAS PREVIAS SE" in field_name or "TOTAL DE ESTA PÁGINA SE" in field_name or "TIEMPO TOTAL SE" in field_name:
                return 6
            else:
                return 8
        
        def adjust_font_size(text, rect, max_font_size, font):
            target_width = rect.width * 0.9
            target_height = rect.height * 0.9
            low, high = 5, max_font_size
            optimal_size = low
            while low <= high:
                mid = (low + high) // 2
                text_width = font.text_length(str(text), fontsize=mid)
                text_height = mid * 1.2
                if text_width <= target_width and text_height <= target_height:
                    optimal_size = mid
                    low = mid + 1
                else:
                    high = mid - 1
            return optimal_size
        
        cumulative_totals = {col: 0 for col in sum_columns}
        font = fitz.Font("helv")
        total_pages_per_df = num_base_pages
        
        for df_idx, df in enumerate(dataframes):
            df = df.replace("--", "")
            df_totals = {col: 0 for col in sum_columns}
            for col in sum_columns:
                if col in df.columns:
                    if col in numeric_columns:
                        # Sumar aterrizajes tratando NaN o vacíos como 0
                        total = 0
                        for i in range(len(df)):
                            value = df[col].iloc[i]
                            if pd.isna(value) or value == "":
                                continue
                            try:
                                total += int(value)
                            except (ValueError, TypeError):
                                continue
                        df_totals[col] = total
                    else:
                        # Columnas de tiempo: usar conversión segura a minutos
                        df_totals[col] = sum(time_to_minutes(df[col].iloc[i]) for i in range(len(df)))
            
            start_page = df_idx * total_pages_per_df
            end_page = start_page + total_pages_per_df
            
            for page_num in range(start_page, min(end_page, len(final_doc))):
                page = final_doc[page_num]
                base_page_num = page_num % total_pages_per_df
                
                if base_page_num in widget_data:
                    widgets_list = widget_data[base_page_num]
                    
                    for widget in widgets_list:
                        x0, y0, x1, y1 = widget['coords']
                        field_name = widget['field_name']
                        rect = fitz.Rect(x0, y0, x1, y1)
                        
                        text = ""
                        
                        if field_name == "Número de página":
                            text = str((page_num // 2) + 1)
                        
                        elif not any(x in field_name for x in ["TIEMPO TOTAL", "TOTAL DE ESTA PÁGINA", "TOTAL DESDE LAS PÁGINAS PREVIAS"]):
                            parts = field_name.split("_")
                            if len(parts) > 1 and parts[-1].isdigit():
                                row_idx = int(parts[-1])
                                if row_idx < len(df):
                                    row = df.iloc[row_idx]
                                    for col in df.columns:
                                        expected_prefix = f"{col.upper()}_"
                                        if col != "datetime" and field_name.upper().startswith(expected_prefix):
                                            text = str(row[col]) if pd.notna(row[col]) else ""
                                            if text == "0" or text == "00:00":
                                                text = ""
                                            break
                        
                        else:
                            col_name = None
                            total_type = None
                            for col in sum_columns:
                                if f"TIEMPO TOTAL {col.upper()}" == field_name.upper():
                                    col_name = col
                                    total_type = "TIEMPO TOTAL"
                                    break
                                elif f"TOTAL DE ESTA PÁGINA {col.upper()}" == field_name.upper():
                                    col_name = col
                                    total_type = "TOTAL DE ESTA PÁGINA"
                                    break
                                elif f"TOTAL DESDE LAS PÁGINAS PREVIAS {col.upper()}" == field_name.upper():
                                    col_name = col
                                    total_type = "TOTAL DESDE LAS PÁGINAS PREVIAS"
                                    break
                            
                            if col_name:
                                if total_type == "TIEMPO TOTAL":
                                    total = cumulative_totals[col_name] + df_totals[col_name]
                                    text = str(total) if col_name in numeric_columns else minutes_to_time(total)
                                    if text == "0" or text == "00:00":
                                        text = ""
                                elif total_type == "TOTAL DE ESTA PÁGINA":
                                    total = df_totals[col_name]
                                    text = str(total) if col_name in numeric_columns else minutes_to_time(total)
                                    if text == "0" or text == "00:00":
                                        text = ""
                                elif total_type == "TOTAL DESDE LAS PÁGINAS PREVIAS":
                                    total = cumulative_totals[col_name]
                                    text = str(total) if col_name in numeric_columns else minutes_to_time(total)
                                    if text == "0" or text == "00:00":
                                        text = ""
                        
                        max_font_size = get_base_font_size(field_name)
                        if "Nombre del PIC" in field_name or "Tipo" in field_name:
                            font_size = adjust_font_size(text, rect, min(8, max_font_size), font)
                            if font_size == 5 and font.text_length(text, fontsize=5) > rect.width * 0.9:
                                page.insert_textbox(rect, text, fontsize=5, fontname="helv", color=[0, 0, 0], align=fitz.TEXT_ALIGN_CENTER)
                            else:
                                text_width = font.text_length(text, fontsize=font_size)
                                text_height = font_size * 1.2
                                x_center = x0 + (rect.width - text_width) / 2
                                y_center = y0 + (rect.height - text_height) / 2 + text_height * 0.8
                                page.insert_text((x_center, y_center), text, fontsize=font_size, fontname="helv", color=[0, 0, 0])
                        else:
                            font_size = max_font_size
                            text_width = font.text_length(text, fontsize=font_size)
                            text_height = font_size * 1.2
                            x_center = x0 + (rect.width - text_width) / 2
                            y_center = y0 + (rect.height - text_height) / 2 + text_height * 0.8
                            page.insert_text((x_center, y_center), text, fontsize=font_size, fontname="helv", color=[0, 0, 0])
            
            for col in sum_columns:
                if col in df.columns:
                    cumulative_totals[col] += df_totals[col]

        final_doc.ez_save(output_pdf_path, garbage=3, clean=True)
        final_doc.close()

    process_pdf_widgets(input_pdf_path, exit_file, dataframes)
    return exit_file

def preprocess_data(df):
    """Preprocesa el DataFrame para cálculos estadísticos."""
    df_clean = df.copy()

    # Generalizar B737 a B738
    df_clean['Fabricante'] = df_clean['Fabricante'].str.replace(r'B737.*', 'B738', regex=True)
    # Generalizar cualquier "172" a C172
    df_clean['Fabricante'] = df_clean['Fabricante'].str.replace(r'.*172.*', 'C172', regex=True)

    # Reemplazar '--' por '0' en columnas relevantes
    columns_to_clean = [
        "SE", "ME", "Tiempo multipiloto", "Tiempo total de vuelo",
        "Landings Día", "Landings Noche", "Noche", "IFR", 
        "Piloto al mando", "Co-piloto", "Doble mando", "Instructor", "Total de sesión"
    ]
    for col in columns_to_clean:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].replace('--', '0')

    # Función para convertir cualquier formato de tiempo a minutos
    def time_to_minutes(time_str):
        if pd.isna(time_str) or time_str == '0':
            return 0
        time_str = str(time_str).strip()
        try:
            if ':' in time_str:
                hours, minutes = map(int, time_str.split(':'))
                return hours * 60 + minutes
            elif '.' in time_str:
                hours, minutes = map(int, time_str.split('.'))
                return hours * 60 + minutes
            else:
                return int(float(time_str) * 60)
        except (ValueError, TypeError):
            return 0

    # Aplicar conversión a columnas de tiempo
    time_columns = [
        "SE", "ME", "Tiempo multipiloto", "Tiempo total de vuelo",
        "Noche", "IFR", "Piloto al mando", "Co-piloto", "Doble mando", 
        "Instructor", "Total de sesión"
    ]
    for col in time_columns:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].apply(time_to_minutes)

    # Convertir landings a numérico
    df_clean["Landings Día"] = pd.to_numeric(df_clean["Landings Día"], errors='coerce').fillna(0)
    df_clean["Landings Noche"] = pd.to_numeric(df_clean["Landings Noche"], errors='coerce').fillna(0)

    # Asegurar que datetime esté en formato correcto
    df_clean['datetime'] = pd.to_datetime(df_clean['datetime'], errors='coerce')

    return df_clean

def calculate_statistics(df):
    """Calcula estadísticas basadas en el DataFrame preprocesado."""
    df_clean = preprocess_data(df)
    
    # Separar vuelos reales y sesiones de simulador
    if "Fecha" in df_clean.columns:
        flights_df = df_clean[df_clean["Fecha"] != "--"].copy()
        sim_df = df_clean[df_clean["Fecha"] == "--"].copy()
    else:
        flights_df = df_clean.copy()
        sim_df = df_clean.iloc[0:0].copy()

    # Total de horas de vuelo (solo vuelos, excluye simulador)
    total_flight_time = flights_df["Tiempo total de vuelo"].sum() / 60

    # Total de horas de simulador (solo filas marcadas como simulador)
    total_sim_time = sim_df["Total de sesión"].sum() / 60

    # Total de landings (solo vuelos)
    total_landings = flights_df["Landings Día"].sum() + flights_df["Landings Noche"].sum()

    # Horas por tipo de avión (solo vuelos reales, por "Fabricante")
    hours_by_aircraft = (flights_df.groupby("Fabricante")["Tiempo total de vuelo"]
                        .sum() / 60).to_dict()

    # Horas como piloto al mando (solo vuelos)
    total_pic_time = flights_df["Piloto al mando"].sum() / 60

    # Horas nocturnas (solo vuelos)
    total_night_time = flights_df["Noche"].sum() / 60

    # Horas IFR (solo vuelos)
    total_ifr_time = flights_df["IFR"].sum() / 60

    # Vuelos por mes/año (solo vuelos)
    flights_by_month = (flights_df.groupby(flights_df["datetime"].dt.to_period("M"))
                       .size().to_dict())
    
    return {
        "Total Flight Hours": total_flight_time,
        "Total Simulator Hours": total_sim_time,
        "Total Landings": total_landings,
        "Hours by Aircraft": hours_by_aircraft,
        "Total PIC Hours": total_pic_time,
        "Total Night Hours": total_night_time,
        "Total IFR Hours": total_ifr_time,
        "Flights by Month": flights_by_month
    }

def filter_future_dates(df):
    current_date = datetime.now()
    df['datetime'] = pd.to_datetime(df['datetime'])
    return df[df['datetime'] <= current_date]

# NUEVA FUNCION: calcular despegues y aterrizajes por aeropuerto
# Devuelve dos Series ordenadas descendentemente: despegues (por Origen) y aterrizajes (por Destino)
def airport_operations(df):
    df_ops = df.copy()

    # Excluir sesiones de simulador (Fecha == "--") del conjunto de vuelos
    if "Fecha" in df_ops.columns:
        df_ops = df_ops[df_ops["Fecha"] != "--"]
    # Normalizar
    for col in ['Origen', 'Destino']:
        if col in df_ops.columns:
            df_ops[col] = (df_ops[col].astype(str)
                                         .str.strip()
                                         .str.upper()
                                         .replace({'': pd.NA, 'NAN': pd.NA}))
    # Filtrar filas vacías
    df_ops = df_ops.dropna(subset=['Origen', 'Destino'], how='all')
    takeoffs = (df_ops.dropna(subset=['Origen'])
                      .groupby('Origen').size()
                      .sort_values(ascending=False)
                      .rename('Despegues'))
    landings = (df_ops.dropna(subset=['Destino'])
                      .groupby('Destino').size()
                      .sort_values(ascending=False)
                      .rename('Aterrizajes'))
    return takeoffs, landings


def build_airport_map_df(df):
    """Construye un DataFrame con coordenadas y número de operaciones por aeropuerto.

    Usa columnas Origen/Destino (ya normalizadas a ICAO), excluye simulador (Fecha == "--"),
    y convierte ICAO -> IATA para buscar lat/lon en AIRPORT_COORDS.
    """
    df_ops = df.copy()
    if "Fecha" in df_ops.columns:
        df_ops = df_ops[df_ops["Fecha"] != "--"]

    # Contar operaciones por aeropuerto (origen + destino)
    counts = {}
    for col in ["Origen", "Destino"]:
        if col not in df_ops.columns:
            continue
        series = (
            df_ops[col]
            .astype(str)
            .str.strip()
            .str.upper()
            .replace({"": pd.NA, "NAN": pd.NA})
            .dropna()
        )
        for code, n in series.value_counts().items():
            counts[code] = counts.get(code, 0) + int(n)

    rows = []
    for icao, n_ops in counts.items():
        # Intentar pasar de ICAO a IATA
        iata = ICAO_TO_IATA.get(icao)
        if not iata:
            # Si ya parece IATA (3 letras), usarlo directamente
            if len(icao) == 3 and icao.isalpha():
                iata = icao
            else:
                continue
        coords = AIRPORT_COORDS.get(iata)
        if not coords:
            continue
        lat, lon = coords
        rows.append({
            "Aeropuerto": icao,
            "IATA": iata,
            "Lat": lat,
            "Lon": lon,
            "Operaciones": n_ops,
        })

    if not rows:
        return pd.DataFrame(columns=["Aeropuerto", "IATA", "Lat", "Lon", "Operaciones"])

    return pd.DataFrame(rows)


def build_routes_map_df(df):
    """Construye un DataFrame para representar rutas (líneas) entre aeropuertos.

    Cada ruta se identifica por par Origen/Destino (ICAO), se excluyen sesiones de
    simulador (Fecha == "--") y sólo se usan aeropuertos con coordenadas conocidas
    en `AIRPORT_COORDS`.
    """
    df_ops = df.copy()
    if "Fecha" in df_ops.columns:
        df_ops = df_ops[df_ops["Fecha"] != "--"]

    routes_counts: dict[tuple[str, str], int] = {}

    for _, row in df_ops.iterrows():
        o = str(row.get("Origen", "")).strip().upper()
        d = str(row.get("Destino", "")).strip().upper()
        if not o or not d or o in ("--", "NAN") or d in ("--", "NAN"):
            continue
        key = (o, d)
        routes_counts[key] = routes_counts.get(key, 0) + 1

    rows = []
    for (o_icao, d_icao), n in routes_counts.items():
        o_iata = ICAO_TO_IATA.get(o_icao)
        d_iata = ICAO_TO_IATA.get(d_icao)
        if not o_iata or not d_iata:
            continue

        o_coords = AIRPORT_COORDS.get(o_iata)
        d_coords = AIRPORT_COORDS.get(d_iata)
        if not o_coords or not d_coords:
            continue

        o_lat, o_lon = o_coords
        d_lat, d_lon = d_coords
        route_id = f"{o_icao}-{d_icao}"

        rows.append({
            "route": route_id,
            "Lat": o_lat,
            "Lon": o_lon,
            "Flights": n,
            "Punto": "Origen",
        })
        rows.append({
            "route": route_id,
            "Lat": d_lat,
            "Lon": d_lon,
            "Flights": n,
            "Punto": "Destino",
        })

    if not rows:
        return pd.DataFrame(columns=["route", "Lat", "Lon", "Flights", "Punto"])

    return pd.DataFrame(rows)
