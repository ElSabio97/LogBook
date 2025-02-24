from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import requests
import pandas as pd
import io
from googleapiclient.http import MediaFileUpload
from datetime import timedelta
import pdfrw
import fitz
import csv
import streamlit as st

SERVICE_ACCOUNT_FILE = 'service_account.json'
SCOPES = ['https://www.googleapis.com/auth/drive']
COLUMNAS = [
    "Fecha", "Origen", "Salida", "Destino", "Llegada", "Fabricante",
    "Matrícula", "SE", "ME", "Tiempo multipiloto", "Tiempo total de vuelo",
    "Nombre del PIC", "Landings Día", "Landings Noche", "Noche", "IFR",
    "Piloto al mando", "Co-piloto", "Doble mando", "Instructor",
    "Fecha simu", "Tipo", "Total de sesión", "Observaciones", "datetime"
]

def get_drive_service():
    credentials = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=credentials)

def descargar_csv(file_name, folder_id):
    service = get_drive_service()
    query = f"name='{file_name}' and parents='{folder_id}'"
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
    query = f"name='{file_name}' and parents='{folder_id}'"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    items = results.get('files', [])
    if not items:
        return None
    file_id = items[0]['id']
    media = MediaFileUpload(file_path, resumable=True)
    file = service.files().update(fileId=file_id, media_body=media).execute()
    return file.get('id')

def rellenar_y_combinar_pdfs(entry_file, exit_file, data):    
    df = data
    
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
                        
                        # Inicializar text para cada widget
                        text = ""
                        
                        # Procesar el número de página
                        if field_name == "Número de página":
                            text = str((page_num // 2) + 1)  # Número de página (1-based)
                        
                        # Procesar datos individuales
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
                        
                        # Procesar totales
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
                        
                        # Escribir el texto en el PDF
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
            
            # Actualizar acumulativos
            for col in sum_columns:
                if col in df.columns:
                    cumulative_totals[col] += df_totals[col]

        final_doc.ez_save(output_pdf_path, garbage=3, clean=True)
        final_doc.close()

    process_pdf_widgets(entry_file, exit_file, dataframes)
    return exit_file  # Devuelve la ruta del archivo procesado