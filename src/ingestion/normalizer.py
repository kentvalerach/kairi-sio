"""
KAIRI-SIO — normalizer.py
Converts raw reader output to Data Contract v1.1 (CURATED_ZONE).

Data Contract v1.1 columns per embalse:
    uuid        : str       UUIDv4 per row
    sensor_id   : str
    ts_station  : datetime  original timestamp from sensor
    ts_ingest   : datetime  timestamp when KAIRI processed this record
    H_level     : float|None  nivel embalse (m)
    Q_inflow    : float|None  caudal entrante (m3/s)
    P_rain      : float|None  precipitacion (mm)
    source_files: str       comma-separated source filenames
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# All numeric fields in the contract
_NUMERIC_FIELDS = ['H_level', 'Q_inflow', 'P_rain']

# Physical bounds per field — CONFIG_PENDING means use conservative values
# These will be refined with real embalse metadata
_PHYSICAL_BOUNDS = {
    'H_level':  {'min': 0.0,  'max': 500.0},   # meters above datum
    'Q_inflow': {'min': 0.0,  'max': 10000.0},  # m3/s
    'P_rain':   {'min': 0.0,  'max': 500.0},    # mm per hour
}


def _pivot_to_contract(
    variable_dfs: dict[str, pd.DataFrame],
    embalse_id: str,
    ts_ingest: datetime,
) -> pd.DataFrame:
    """
    Pivot dict of {variable -> long DataFrame} into one wide DataFrame
    aligned on ts_station, one row per timestamp.
    """
    # Build one series per variable
    series_list = []
    source_files = set()

    for variable, df in variable_dfs.items():
        field = df['field_name'].iloc[0]  # e.g. 'H_level'
        s = df.set_index('ts_station')['value_raw'].rename(field)
        series_list.append(s)
        source_files.update(df['source_file'].unique())
        # Keep sensor_id from first variable (they share embalse)

    if not series_list:
        raise ValueError(f"No variable data for {embalse_id}")

    # Outer join on timestamp — gaps in one variable don't drop other variables
    wide = pd.concat(series_list, axis=1, join='outer')
    wide = wide.sort_index()

    # Fill in missing columns with None
    for field in _NUMERIC_FIELDS:
        if field not in wide.columns:
            wide[field] = None

    wide = wide[_NUMERIC_FIELDS]  # enforce column order

    # Reset index
    wide = wide.reset_index().rename(columns={'ts_station': 'ts_station'})

    # Add contract fields
    wide.insert(0, 'uuid', [str(uuid.uuid4()) for _ in range(len(wide))])
    wide['sensor_id']    = embalse_id
    wide['ts_ingest']    = ts_ingest
    wide['source_files'] = ', '.join(sorted(source_files))

    # Final column order per Data Contract v1.1
    ordered = [
        'uuid', 'sensor_id',
        'ts_station', 'ts_ingest',
        'H_level', 'Q_inflow', 'P_rain',
        'source_files'
    ]
    return wide[ordered]


def _enforce_none_not_zero(df: pd.DataFrame) -> pd.DataFrame:
    """
    Core principle: None != 0.0
    This function does NOT replace 0.0 with None — zero is a valid value for
    Q_inflow (no flow) and P_rain (no rain). It only documents the policy and
    ensures NaN is used consistently (not mixed with None or empty string).
    """
    for field in _NUMERIC_FIELDS:
        if field in df.columns:
            # Convert any empty string to NaN
            df[field] = pd.to_numeric(df[field], errors='coerce')
    return df


def normalize_embalse(
    variable_dfs: dict[str, pd.DataFrame],
    embalse_id: str,
    ts_ingest: datetime | None = None,
) -> pd.DataFrame:
    """
    Normalize raw reader output for one embalse into Data Contract v1.1.

    Parameters
    ----------
    variable_dfs : output of saih_reader.read_embalse_all_variables()
    embalse_id   : e.g. 'E32_VADOMOJON'
    ts_ingest    : processing timestamp (defaults to now UTC)

    Returns
    -------
    pd.DataFrame conforming to Data Contract v1.1
    """
    if ts_ingest is None:
        ts_ingest = datetime.now(timezone.utc)

    logger.info(f"Normalizing {embalse_id} ({len(variable_dfs)} variables)")

    df = _pivot_to_contract(variable_dfs, embalse_id, ts_ingest)
    df = _enforce_none_not_zero(df)

    # Log summary
    n = len(df)
    for field in _NUMERIC_FIELDS:
        if field in df.columns:
            n_null = df[field].isna().sum()
            n_zero = (df[field] == 0.0).sum()
            logger.info(f"  {field}: {n - n_null}/{n} valid | {n_null} None | {n_zero} zero")

    date_range = f"{df['ts_station'].min()} -> {df['ts_station'].max()}"
    logger.info(f"  Date range: {date_range}")

    return df


def save_curated(
    df: pd.DataFrame,
    embalse_id: str,
    curated_dir: Path | str,
    format: str = 'parquet',
) -> Path:
    """
    Save normalized DataFrame to CURATED_ZONE.

    Parameters
    ----------
    df           : output of normalize_embalse()
    embalse_id   : e.g. 'E32_VADOMOJON'
    curated_dir  : C:/KAIRI-SIO/data/curated/
    format       : 'parquet' (default) or 'csv'

    Returns
    -------
    Path to saved file
    """
    curated_dir = Path(curated_dir)
    curated_dir.mkdir(parents=True, exist_ok=True)

    if format == 'parquet':
        out_path = curated_dir / f"{embalse_id}.parquet"
        df.to_parquet(out_path, index=False, engine='pyarrow')
    elif format == 'csv':
        out_path = curated_dir / f"{embalse_id}.csv"
        df.to_csv(out_path, index=False)
    else:
        raise ValueError(f"Unknown format '{format}'. Use 'parquet' or 'csv'.")

    size_kb = out_path.stat().st_size / 1024
    logger.info(f"Saved {embalse_id} -> {out_path} ({size_kb:.1f} KB, {len(df)} rows)")
    return out_path