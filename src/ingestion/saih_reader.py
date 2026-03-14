"""
KAIRI-SIO — saih_reader.py
LANDING_ZONE reader for SAIH Guadalquivir xlsx files.

Findings from Sprint 0 inspection (E32_VAD_aport_2015_2020.xlsx):
  - Native xlsx format (NOT HTML encapsulated)
  - Two sheets: 'Info' (metadata) and 'Datos' (time series)
  - Column A: Excel date serial float -> must convert via datetime(1899,12,30) + timedelta
  - Column B: numeric value (float)
  - Column C: always None — quality flag placeholder, not populated by SAIH
  - Footer block at end of Datos sheet: 'Estadisticas', 'Minimo', 'Maximo', 'Media',
    'Total', 'Numero' — must be stripped before processing
  - Nulls: ~0.01% — represented as missing cells (None), never as 0.0
  - Resolution: exactly 1 hour between rows
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Excel date epoch
_EXCEL_EPOCH = datetime(1899, 12, 30)
_NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'

# Words that mark the start of the stats footer in the Datos sheet
_FOOTER_MARKERS = {'estadísticas', 'estadisticas', 'mínimo', 'minimo',
                   'máximo', 'maximo', 'media', 'total', 'número', 'numero'}

# Variable name -> canonical field name in Data Contract
_VARIABLE_MAP = {
    'nivel':        'H_level',
    'precipitacion': 'P_rain',
    'aportacion':   'Q_inflow',
}


def _excel_serial_to_datetime(serial: float) -> datetime:
    """
    Convert Excel date serial float to Python datetime.
    Rounds to nearest minute to eliminate microsecond drift from float precision
    (e.g. 42005.0833333333 -> 01:59:59.999997 instead of 02:00:00).
    """
    raw = _EXCEL_EPOCH + timedelta(days=float(serial))
    # Round to nearest minute
    rounded = raw.replace(second=0, microsecond=0)
    if raw.second >= 30 or raw.microsecond >= 500000:
        rounded += timedelta(minutes=1)
    return rounded


def _load_shared_strings(xlsx_path: Path) -> list[str]:
    """Extract shared strings table from xlsx ZIP."""
    import zipfile
    with zipfile.ZipFile(xlsx_path, 'r') as z:
        if 'xl/sharedStrings.xml' not in z.namelist():
            return []
        with z.open('xl/sharedStrings.xml') as f:
            tree = ET.parse(f)
    root = tree.getroot()
    result = []
    for si in root.findall(f'{_NS}si'):
        t = si.find(f'{_NS}t')
        result.append(t.text if t is not None and t.text else '')
    return result


def _parse_datos_sheet(xlsx_path: Path, shared: list[str]) -> pd.DataFrame:
    """
    Parse the 'Datos' sheet XML directly.
    Returns raw DataFrame with columns: ts_raw (float), value (float|None)
    """
    import zipfile

    # Find sheet index for 'Datos'
    with zipfile.ZipFile(xlsx_path, 'r') as z:
        wb_tree = ET.parse(z.open('xl/workbook.xml'))
        wb_root = wb_tree.getroot()

        sheets = wb_root.findall(f'.//{_NS}sheet')
        datos_idx = None
        for i, sheet in enumerate(sheets, start=1):
            if sheet.get('name', '').strip().lower() == 'datos':
                datos_idx = i
                break

        if datos_idx is None:
            raise ValueError(f"No 'Datos' sheet found in {xlsx_path.name}. "
                             f"Available: {[s.get('name') for s in sheets]}")

        sheet_path = f'xl/worksheets/sheet{datos_idx}.xml'
        logger.debug(f"  Reading sheet index {datos_idx} -> {sheet_path}")

        with z.open(sheet_path) as f:
            tree = ET.parse(f)

    root = tree.getroot()
    sheet_data = root.find(f'{_NS}sheetData')
    if sheet_data is None:
        raise ValueError(f"No sheetData found in {xlsx_path.name}")

    all_rows = sheet_data.findall(f'{_NS}row')
    logger.debug(f"  Total XML rows (including header+footer): {len(all_rows)}")

    def _cell_value(c):
        t = c.get('t', 'n')
        v_elem = c.find(f'{_NS}v')
        if v_elem is None or v_elem.text is None:
            return None
        if t == 's':
            idx = int(v_elem.text)
            return shared[idx] if idx < len(shared) else None
        return v_elem.text

    records = []
    header_found = False

    for row in all_rows:
        cells = {}
        for c in row.findall(f'{_NS}c'):
            ref = c.get('r', '')
            col = ''.join(ch for ch in ref if ch.isalpha())
            cells[col] = _cell_value(c)

        a_val = cells.get('A')
        b_val = cells.get('B')

        # Skip header row (A='FECHA')
        if not header_found:
            if isinstance(a_val, str) and a_val.upper() == 'FECHA':
                header_found = True
            continue

        # Stop at footer
        if isinstance(a_val, str) and a_val.strip().lower() in _FOOTER_MARKERS:
            logger.debug(f"  Footer detected at row with A='{a_val}', stopping.")
            break

        # Skip rows where A is not a numeric serial
        if a_val is None:
            continue
        try:
            ts_serial = float(a_val)
        except (ValueError, TypeError):
            continue

        # B value: None if missing (genuine gap, not 0.0)
        value = None
        if b_val is not None:
            try:
                value = float(b_val)
            except (ValueError, TypeError):
                value = None  # unexpected string -> treat as None

        records.append({'ts_serial': ts_serial, 'value': value})

    if not records:
        raise ValueError(f"No data rows extracted from {xlsx_path.name}")

    df = pd.DataFrame(records)
    logger.debug(f"  Extracted {len(df)} data rows")
    return df


def _read_info_sheet(xlsx_path: Path, shared: list[str]) -> dict:
    """
    Read the 'Info' sheet to extract sensor metadata.
    Returns dict with keys: sensor_tag, unit, description
    """
    import zipfile

    with zipfile.ZipFile(xlsx_path, 'r') as z:
        wb_tree = ET.parse(z.open('xl/workbook.xml'))
        sheets = wb_tree.getroot().findall(f'.//{_NS}sheet')
        info_idx = None
        for i, sheet in enumerate(sheets, start=1):
            if sheet.get('name', '').strip().lower() == 'info':
                info_idx = i
                break

        if info_idx is None:
            return {}

        with z.open(f'xl/worksheets/sheet{info_idx}.xml') as f:
            tree = ET.parse(f)

    root = tree.getroot()
    sheet_data = root.find(f'{_NS}sheetData')
    if sheet_data is None:
        return {}

    # Collect all text values from sheet
    texts = []
    for row in sheet_data.findall(f'{_NS}row'):
        for c in row.findall(f'{_NS}c'):
            t = c.get('t', 'n')
            v = c.find(f'{_NS}v')
            if v is not None and v.text and t == 's':
                idx = int(v.text)
                if idx < len(shared):
                    texts.append(shared[idx])

    # sensor tag is the string containing '-->'
    sensor_tag = None
    description = None
    for txt in texts:
        if '-->' in txt:
            parts = txt.split('-->')
            if len(parts) >= 2:
                description = parts[1].strip()
                # Extract tag code (e.g. E32_250_X)
                tag_part = description.split(':')[0].strip() if ':' in description else ''
                # Also look for the tag in parentheses or after last space
                sensor_tag = tag_part.split()[-1] if tag_part else None

    return {
        'sensor_tag': sensor_tag,
        'description': description,
    }


def read_saih_xlsx(
    xlsx_path: Path | str,
    embalse_id: str,
    variable: str,
) -> pd.DataFrame:
    """
    Read a single SAIH xlsx file from the LANDING_ZONE.

    Parameters
    ----------
    xlsx_path : path to the xlsx file
    embalse_id : e.g. 'E32_VADOMOJON'
    variable : 'nivel' | 'precipitacion' | 'aportacion'

    Returns
    -------
    pd.DataFrame with columns:
        ts_station  : datetime (UTC-naive, local Spanish time as recorded)
        sensor_id   : str
        field_name  : str  (canonical Data Contract field: H_level / P_rain / Q_inflow)
        value_raw   : float | None  (original value, None = genuine gap)
        source_file : str
    """
    xlsx_path = Path(xlsx_path)
    if not xlsx_path.exists():
        raise FileNotFoundError(f"File not found: {xlsx_path}")

    variable_lower = variable.strip().lower()
    if variable_lower not in _VARIABLE_MAP:
        raise ValueError(f"Unknown variable '{variable}'. "
                         f"Expected one of: {list(_VARIABLE_MAP.keys())}")

    field_name = _VARIABLE_MAP[variable_lower]

    logger.info(f"Reading {xlsx_path.name} [{embalse_id} / {variable}]")

    shared = _load_shared_strings(xlsx_path)
    meta   = _read_info_sheet(xlsx_path, shared)
    df_raw = _parse_datos_sheet(xlsx_path, shared)

    sensor_id = meta.get('sensor_tag') or f"{embalse_id}_{variable_lower}"

    # Convert Excel serial to datetime
    df_raw['ts_station'] = df_raw['ts_serial'].apply(_excel_serial_to_datetime)
    df_raw['sensor_id']  = sensor_id
    df_raw['field_name'] = field_name
    df_raw['value_raw']  = df_raw['value']
    df_raw['source_file'] = xlsx_path.name

    result = df_raw[['ts_station', 'sensor_id', 'field_name', 'value_raw', 'source_file']].copy()
    result = result.sort_values('ts_station').reset_index(drop=True)

    n_nulls = result['value_raw'].isna().sum()
    logger.info(f"  -> {len(result)} rows | nulls: {n_nulls} ({n_nulls/len(result)*100:.2f}%) | "
                f"range: {result['ts_station'].min()} -> {result['ts_station'].max()}")

    return result


def read_embalse_all_variables(
    raw_dir: Path | str,
    embalse_id: str,
) -> dict[str, pd.DataFrame]:
    """
    Read all available xlsx files for a given embalse from the raw directory.
    Merges the two time periods (2015-2020 and 2020-2024) per variable.

    Parameters
    ----------
    raw_dir : C:/KAIRI-SIO/data/raw/saih_guadalquivir/
    embalse_id : e.g. 'E32_VADOMOJON'

    Returns
    -------
    dict mapping variable name -> merged DataFrame (full 2015-2024)
    """
    raw_dir  = Path(raw_dir)
    emb_dir  = raw_dir / embalse_id
    result   = {}

    for variable in _VARIABLE_MAP:
        var_dir = emb_dir / variable.capitalize()
        if not var_dir.exists():
            logger.warning(f"Variable directory not found: {var_dir}")
            continue

        xlsx_files = sorted(var_dir.glob('*.xlsx'))
        if not xlsx_files:
            logger.warning(f"No xlsx files in {var_dir}")
            continue

        logger.info(f"Loading {embalse_id}/{variable}: {[f.name for f in xlsx_files]}")

        parts = []
        for f in xlsx_files:
            try:
                df = read_saih_xlsx(f, embalse_id, variable)
                parts.append(df)
            except Exception as e:
                logger.error(f"Failed to read {f.name}: {e}")
                raise

        if parts:
            merged = pd.concat(parts, ignore_index=True)
            merged = merged.sort_values('ts_station').drop_duplicates(
                subset='ts_station'
            ).reset_index(drop=True)
            logger.info(f"  Merged {embalse_id}/{variable}: {len(merged)} rows total")
            result[variable] = merged

    return result