from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import requests
import pandas as pd
import io
from googleapiclient.http import MediaFileUpload
from datetime import datetime, timedelta, timezone  # Añadimos timezone para UTC
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
    df = pd.read_csv(io.StringIO(response.text), header=None, names=COLUMNAS, encoding='UTF-8', sep=";")
    df['datetime'] = pd.to_datetime(df['datetime'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
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
    
    # Filtrar datos futuros (posteriores al momento actual en UTC)
    current_utc = datetime.now(timezone.utc)
    df_nuevo = df_nuevo[df_nuevo['datetime'] <= current_utc]
    
    return df_nuevo.drop(columns=['datetime_simu'])

def descargar_y_actualizar_csv(original_file, folder_id, new_file):
    df_original = descargar_csv(original_file, folder_id)
    if df_original is None:
        return None
    df_nuevo = read_new_file(new_file)
    min_datetime_nuevo = df_nuevo['datetime'].min()
    df_original_filtered = df_original[df_original['datetime'] < min_datetime_nuevo]
    df_actualizado = pd.concat([df_original_filtered, df_nuevo], ignore_index=True)
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
    folder_id = '1B8gnCmbBaGMBT77ba4ntjpZj_NkJcvuI'
    input_pdf_path = descargar_pdf_template(entry_file, folder_id)
    
    if not os.path.exists(input_pdf_path):
        st.error(f"PDF template no encontrado después de descargarlo: {input_pdf_path}")
        raise FileNotFoundError(f"No such file: {input_pdf_path}")
    
    df = data
    
    if df.iloc[0, 0] == "Fecha":
        df = df.iloc[1:]
    
    df.loc[:, df.columns.difference(['Nombre del PIC', 'Tipo'])] = df.loc[:, df.columns.difference(['Nombre del PIC', 'Tipo'])].replace(r'\.', ':', regex=True)
    df['Fabricante'] = df['Fabricante'].str.replace(r'B737.*', 'B738', regex=True)
    df.drop(columns=["Remark", "datetime"], inplace=True, errors='ignore')

    dataframes = [df.iloc[i:i + 14] for i in range(0, len(df), 14)]

    def time_to_minutes(time_str):
        if pd.isna(time_str) or not time_str:
            return 0
        try:
            hours, minutes = map(int, str(time_str).split(":"))
            return hours * 60 + minutes
        except (ValueError, TypeError):
            return 0

    def minutes_to_time(minutes):
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
                        df_totals[col] = sum(int(df[col].iloc[i]) if df[col].iloc[i] else 0 for i in range(len(df)))
                    else:
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
    df_clean = df.copy()
    df_clean['Fabricante'] = df_clean['Fabricante'].str.replace(r'B737.*', 'B738', regex=True)
    df_clean['Fabricante'] = df_clean['Fabricante'].str.replace(r'.*172.*', 'C172', regex=True)
    columns_to_clean = [
        "SE", "ME", "Tiempo multipiloto", "Tiempo total de vuelo",
        "Landings Día", "Landings Noche", "Noche", "IFR", 
        "Piloto al mando", "Co-piloto", "Doble mando", "Instructor", "Total de sesión"
    ]
    for col in columns_to_clean:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].replace('--', '0')

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

    time_columns = [
        "SE", "ME", "Tiempo multipiloto", "Tiempo total de vuelo",
        "Noche", "IFR", "Piloto al mando", "Co-piloto", "Doble mando", 
        "Instructor", "Total de sesión"
    ]
    for col in time_columns:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].apply(time_to_minutes)

    df_clean["Landings Día"] = pd.to_numeric(df_clean["Landings Día"], errors='coerce').fillna(0)
    df_clean["Landings Noche"] = pd.to_numeric(df_clean["Landings Noche"], errors='coerce').fillna(0)
    df_clean['datetime'] = pd.to_datetime(df_clean['datetime'], errors='coerce')
    return df_clean

def calculate_statistics(df):
    df_clean = preprocess_data(df)
    total_flight_time = df_clean["Tiempo total de vuelo"].sum() / 60
    total_sim_time = df_clean["Total de sesión"].sum() / 60
    total_landings = df_clean["Landings Día"].sum() + df_clean["Landings Noche"].sum()
    hours_by_aircraft = (df_clean.groupby("Fabricante")["Tiempo total de vuelo"].sum() / 60).to_dict()
    b738_hours = df_clean[df_clean["Fabricante"] == "B738"]["Tiempo total de vuelo"].sum() / 60
    print(f"Debug: Horas calculadas para B738: {b738_hours:.2f} horas")
    sim_hours = (df_clean.groupby("Tipo")["Total de sesión"].sum() / 60).to_dict()
    hours_by_aircraft.update(sim_hours)
    total_pic_time = df_clean["Piloto al mando"].sum() / 60
    total_night_time = df_clean["Noche"].sum() / 60
    total_ifr_time = df_clean["IFR"].sum() / 60
    flights_by_month = (df_clean.groupby(df_clean["datetime"].dt.to_period("M")).size().to_dict())
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
