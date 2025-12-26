from __future__ import annotations

from dataclasses import dataclass
import io
import math
import pandas as pd
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth


@dataclass(frozen=True)
class ColumnBox:
    field: str
    x_left: float
    x_right: float


@dataclass(frozen=True)
class Layout:
    y_top: float
    y_bottom: float
    columns: tuple[ColumnBox, ...]
    rows_per_page: int = 14
    totals_pagina: tuple[float, float] | None = None
    acumulado_sin_pagina: tuple[float, float] | None = None
    acumulado_con_pagina: tuple[float, float] | None = None


DEFAULT_LAYOUT = Layout(
    y_top=52.441,
    y_bottom=344.761,
    columns=(
        ColumnBox("Fecha", 0.0, 45.120),
        ColumnBox("Origen", 45.120, 79.560),
        ColumnBox("Salida", 79.560, 114.000),
        ColumnBox("Destino", 114.000, 148.440),
        ColumnBox("Llegada", 148.440, 182.880),
        ColumnBox("Fabricante", 182.880, 229.2),
        ColumnBox("Matrícula", 229.2, 275.52),
        ColumnBox("SE", 275.52, 298.680),
        ColumnBox("ME", 298.68, 321.84),
        ColumnBox("Tiempo multipiloto", 321.84, 368.88),
        ColumnBox("Tiempo total de vuelo", 368.88, 439.08),
        ColumnBox("Nombre del PIC", 439.08, 508.68),
        ColumnBox("Landings día", 508.68, 543.120),
        ColumnBox("Landings Noche", 543.120, 577.555),
        ColumnBox("Noche", 577.555, 620.755),
        ColumnBox("IFR", 620.755, 657.115),
        ColumnBox("Piloto al mando", 657.115, 710.995),
        ColumnBox("Co-piloto", 710.995, 764.875),
        ColumnBox("Doble mando", 764.875, 818.755),
        ColumnBox("Instructor", 818.755, 872.635),
        ColumnBox("Fecha simu", 872.635, 929.035),
        ColumnBox("Tipo", 929.035, 985.435),
        ColumnBox("Total de sesión", 985.435, 1041.835),
        ColumnBox("Observaciones", 1041.835, 1155.235),
    ),
    totals_pagina=(344.761, 377.161),
    acumulado_sin_pagina=(377.161, 409.561),
    acumulado_con_pagina=(409.561, 441.961),
)


def _is_empty_value(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    txt = str(value).strip()
    return txt == "" or txt.casefold() in {"nan", "none", "nat"}


def _format_value(field: str, value) -> str:
    if _is_empty_value(value):
        return ""

    if field in {"Fecha", "Fecha simu"}:
        try:
            dt = pd.to_datetime(value, errors="coerce", dayfirst=True)
            if pd.isna(dt):
                return str(value).strip()
            return dt.strftime("%d/%m/%Y")
        except Exception:
            return str(value).strip()

    # Evitar 1.0 -> 1 en landings y otras columnas numéricas
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, (float,)):
        if math.isfinite(value) and float(value).is_integer():
            return str(int(value))
        return str(value)

    return str(value).strip()


def _parse_time_to_minutes(value) -> int:
    """Convierte un valor tipo hh:mm (o numérico) a minutos enteros."""
    if _is_empty_value(value):
        return 0

    txt = str(value).strip()
    if txt == "":
        return 0

    if ":" in txt:
        parts = txt.split(":")
        try:
            if len(parts) == 2:
                h = int(parts[0] or 0)
                m = int(parts[1] or 0)
                return max(0, h * 60 + m)
            if len(parts) >= 3:
                h = int(parts[0] or 0)
                m = int(parts[1] or 0)
                s = int(parts[2] or 0)
                return max(0, h * 60 + m + (1 if s >= 30 else 0))
        except Exception:
            return 0

    # Fallback numérico: interpretar como horas decimales
    try:
        hours = float(txt.replace(",", "."))
        if not math.isfinite(hours):
            return 0
        return max(0, int(round(hours * 60)))
    except Exception:
        return 0


def _format_minutes_as_hhmm(total_minutes: int) -> str:
    total_minutes = int(total_minutes or 0)
    if total_minutes < 0:
        total_minutes = 0
    h = total_minutes // 60
    m = total_minutes % 60
    return f"{h:02d}:{m:02d}"


def _parse_int(value) -> int:
    if _is_empty_value(value):
        return 0
    try:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int,)):
            return int(value)
        if isinstance(value, (float,)):
            if math.isfinite(value):
                return int(round(value))
            return 0
        txt = str(value).strip()
        if txt == "":
            return 0
        return int(float(txt.replace(",", ".")))
    except Exception:
        return 0


def _fit_text_centered(
    text: str,
    *,
    max_width: float,
    font_name: str,
    max_font_size: int,
    min_font_size: int,
) -> tuple[str, int]:
    text = (text or "").strip()
    if text == "" or max_width <= 0:
        return "", max_font_size

    for size in range(max_font_size, min_font_size - 1, -1):
        if stringWidth(text, font_name, size) <= max_width:
            return text, size

    # No cabe ni al mínimo: aplicar elipsis "..."
    size = min_font_size
    ellipsis = "..."
    if stringWidth(ellipsis, font_name, size) > max_width:
        return "", size

    trimmed = text
    while trimmed and stringWidth(trimmed + ellipsis, font_name, size) > max_width:
        trimmed = trimmed[:-1]

    return (trimmed + ellipsis) if trimmed else "", size


def generate_logbook_pdf_bytes(
    df_rows: pd.DataFrame,
    *,
    template_path: str = "Logbook_Rellenable.pdf",
    layout: Layout = DEFAULT_LAYOUT,
    font_name: str = "Helvetica",
    max_font_size: int = 10,
    min_font_size: int = 6,
    cell_padding: float = 2.0,
) -> bytes:
    """Genera un PDF rellenado sobre una plantilla plana, duplicando páginas según sea necesario.

    Coordenadas de entrada: origen arriba-izquierda.
    """

    # Cargar la plantilla en memoria para poder clonar una página limpia N veces.
    # Si reutilizamos el mismo PageObject y hacemos merge_page, el overlay puede
    # acumularse y provocar texto duplicado en las celdas.
    with open(template_path, "rb") as f:
        template_pdf_bytes = f.read()

    reader = PdfReader(io.BytesIO(template_pdf_bytes))
    if not reader.pages:
        raise ValueError("La plantilla PDF no tiene páginas.")

    template_page = reader.pages[0]
    page_width = float(template_page.mediabox.width)
    page_height = float(template_page.mediabox.height)

    usable_columns = [c for c in layout.columns if (c.x_right - c.x_left) > 0.5]

    time_sum_fields = {
        "SE",
        "ME",
        "Tiempo multipiloto",
        "Tiempo total de vuelo",
        "Noche",
        "IFR",
        "Piloto al mando",
        "Co-piloto",
        "Doble mando",
        "Instructor",
        "Total de sesión",
    }
    int_sum_fields = {"Landings día", "Landings Noche"}

    # Ordenar respetando el orden del logbook:
    # - si viene _doc_num (doc ids 0000..), usarlo (incluye filas vacías intercaladas)
    # - si no, caer a _fecha_ref
    df = df_rows.copy()
    if "_doc_num" in df.columns and df["_doc_num"].notna().any():
        sort_cols = ["_doc_num"]
        if "_doc_id" in df.columns:
            sort_cols.append("_doc_id")
        if "_row_order" in df.columns:
            sort_cols.append("_row_order")
        df = df.sort_values(sort_cols, ascending=True, na_position="last")
    elif "_fecha_ref" in df.columns:
        df = df.sort_values("_fecha_ref", ascending=True, na_position="last")

    total_rows = int(len(df))
    if total_rows == 0:
        # Devuelve una copia de la plantilla
        writer = PdfWriter()
        writer.add_page(PdfReader(io.BytesIO(template_pdf_bytes)).pages[0])
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()

    rows_per_page = int(layout.rows_per_page)
    num_pages = int(math.ceil(total_rows / rows_per_page))
    row_height = (float(layout.y_bottom) - float(layout.y_top)) / float(rows_per_page)

    writer = PdfWriter()

    running_minutes: dict[str, int] = {k: 0 for k in time_sum_fields}
    running_ints: dict[str, int] = {k: 0 for k in int_sum_fields}

    for page_index in range(num_pages):
        # IMPORTANTE: crear SIEMPRE una página limpia (nuevo PageObject)
        # para evitar acumulación de overlays entre páginas.
        page = PdfReader(io.BytesIO(template_pdf_bytes)).pages[0]

        overlay_buf = io.BytesIO()
        c = canvas.Canvas(overlay_buf, pagesize=(page_width, page_height))

        start = page_index * rows_per_page
        end = min(start + rows_per_page, total_rows)
        page_df = df.iloc[start:end]

        page_minutes: dict[str, int] = {k: 0 for k in time_sum_fields}
        page_ints: dict[str, int] = {k: 0 for k in int_sum_fields}

        for local_row_idx, (_, row) in enumerate(page_df.iterrows()):
            cell_top = float(layout.y_top) + float(local_row_idx) * row_height
            cell_bottom = float(layout.y_top) + float(local_row_idx + 1) * row_height

            # Centro vertical en sistema con origen arriba-izquierda
            y_center_top_origin = (cell_top + cell_bottom) / 2.0
            # Convertir a sistema PDF (origen abajo-izquierda)
            y_center_pdf = page_height - y_center_top_origin

            for col in usable_columns:
                raw_value = row.get(col.field, "")
                text = _format_value(col.field, raw_value)
                if text == "":
                    continue

                width = float(col.x_right) - float(col.x_left)
                max_width = max(0.0, width - 2.0 * cell_padding)
                x_center = (float(col.x_left) + float(col.x_right)) / 2.0

                fitted_text, font_size = _fit_text_centered(
                    text,
                    max_width=max_width,
                    font_name=font_name,
                    max_font_size=max_font_size,
                    min_font_size=min_font_size,
                )
                if fitted_text == "":
                    continue

                c.setFont(font_name, font_size)
                # drawCentredString usa baseline; ajustamos un poco para centrar visualmente
                baseline_y = y_center_pdf - (font_size * 0.35)
                c.drawCentredString(x_center, baseline_y, fitted_text)

            # Acumular totales para esta fila
            for field in time_sum_fields:
                page_minutes[field] += _parse_time_to_minutes(row.get(field, ""))
            for field in int_sum_fields:
                page_ints[field] += _parse_int(row.get(field, ""))

        def _draw_totals_row(
            y_pair: tuple[float, float] | None,
            *,
            minutes_totals: dict[str, int],
            int_totals: dict[str, int],
        ):
            if not y_pair:
                return
            y_top, y_bottom = y_pair
            y_center_top_origin = (float(y_top) + float(y_bottom)) / 2.0
            y_center_pdf = page_height - y_center_top_origin

            for col in usable_columns:
                field = col.field
                if field in time_sum_fields:
                    minutes_value = int(minutes_totals.get(field, 0) or 0)
                    if minutes_value == 0:
                        continue
                    text = _format_minutes_as_hhmm(minutes_value)
                elif field in int_sum_fields:
                    int_value = int(int_totals.get(field, 0) or 0)
                    if int_value == 0:
                        continue
                    text = str(int_value)
                else:
                    continue

                width = float(col.x_right) - float(col.x_left)
                max_width = max(0.0, width - 2.0 * cell_padding)
                x_center = (float(col.x_left) + float(col.x_right)) / 2.0

                fitted_text, font_size = _fit_text_centered(
                    text,
                    max_width=max_width,
                    font_name=font_name,
                    max_font_size=max_font_size,
                    min_font_size=min_font_size,
                )
                if fitted_text == "":
                    continue

                c.setFont(font_name, font_size)
                baseline_y = y_center_pdf - (font_size * 0.35)
                c.drawCentredString(x_center, baseline_y, fitted_text)

        prev_minutes = dict(running_minutes)
        prev_ints = dict(running_ints)

        cum_minutes = {k: prev_minutes.get(k, 0) + page_minutes.get(k, 0) for k in time_sum_fields}
        cum_ints = {k: prev_ints.get(k, 0) + page_ints.get(k, 0) for k in int_sum_fields}

        _draw_totals_row(layout.totals_pagina, minutes_totals=page_minutes, int_totals=page_ints)
        _draw_totals_row(layout.acumulado_sin_pagina, minutes_totals=prev_minutes, int_totals=prev_ints)
        _draw_totals_row(layout.acumulado_con_pagina, minutes_totals=cum_minutes, int_totals=cum_ints)

        running_minutes = cum_minutes
        running_ints = cum_ints

        c.showPage()
        c.save()
        overlay_buf.seek(0)

        overlay_reader = PdfReader(overlay_buf)
        if overlay_reader.pages:
            page.merge_page(overlay_reader.pages[0])

        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
