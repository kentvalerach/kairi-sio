"""
KAIRI-SIO — src/ingestion/saih_ebro_reader.py
Lector e ingestor para datos SAIH Ebro (formato sep=; / FECHA_GRUPO).

Diferencias respecto al reader Guadalquivir:
  - Separador: ; con cabecera 'sep=;' en línea 0
  - Columna nivel: 'VALOR (msnm)'
  - Columna precip: 'VALOR (l/m2)'
  - Columna caudal: 'VALOR (m3/s)' (solo Yesa)
  - Fecha: DD/MM/YYYY HH:MM — mismo formato

Uso:
  python src/ingestion/saih_ebro_reader.py --embalse ITOIZ
  python src/ingestion/saih_ebro_reader.py --embalse MEQUINENZA
  python src/ingestion/saih_ebro_reader.py --embalse YESA
  python src/ingestion/saih_ebro_reader.py --all
"""

import argparse
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Rutas ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
EBRO_RAW = ROOT / "03_Datos_Fuentes_Oficiales" / "SNCZI_Cartografia" / "Ebro" / \
           "SAIH_Ebro" / "20260312_Ingestion_Original"
OUT_RAW   = ROOT / "data" / "raw" / "saih_ebro"
OUT_CUR   = ROOT / "data" / "curated" / "ebro"

# ── Configuración por embalse ─────────────────────────────────────────────────
EMBALSE_CONFIG = {
    "ITOIZ": {
        "carpeta": "Itoiz",
        "prefijo_dir": "DatosH_quinceminutal_ITOIZ_20260313",
        "archivos": {
            "nivel":  "20260313_SAIH_EBRO_ITOIZ_NIVEL_RAW.csv",
            "precip": "20260313_SAIH_EBRO_ITOIZ_PRECIP_RAW.csv",
        },
    },
    "MEQUINENZA": {
        "carpeta": "Mequinenza",
        "prefijo_dir": "DatosH_quinceminutal_MEQUINENZA_20260313",
        "archivos": {
            "nivel":  "20260313_SAIH_EBRO_MEQUINENZA_NIVEL_RAW.csv",
            "precip": "20260313_SAIH_EBRO_MEQUINENZA_PRECIP_RAW.csv",
        },
    },
    "YESA": {
        "carpeta": "Yesa",
        "prefijo_dir": "DatosH_quinceminutal_YESA_20260313",
        "archivos": {
            "nivel":  "20260313_SAIH_EBRO_YESA_NIVEL_RAW.csv",
            "precip": "20260313_SAIH_EBRO_YESA_PRECIP_RAW.csv",
            "caudal": "20260313_SAIH_EBRO_YESA_CAUDAL_RAW.csv",
        },
    },
}

# Mapeo nombre columna → nombre interno KAIRI-SIO
COL_MAP = {
    "VALOR (msnm)": "nivel_m",
    "VALOR (l/m2)": "precip_mm",
    "VALOR (m3/s)": "caudal_m3s",
}


def _read_saih_ebro_csv(path: Path, tipo: str) -> pd.DataFrame:
    """Lee un CSV SAIH Ebro con cabecera sep=;"""
    if not path.exists():
        log.warning(f"Archivo no encontrado: {path}")
        return pd.DataFrame()

    df = pd.read_csv(
        path,
        sep=";",
        skiprows=1,          # salta línea 'sep=;'
        parse_dates=["FECHA_GRUPO"],
        dayfirst=True,
        #decimal=",",         # por si hay comas en decimales
        encoding="utf-8-sig",
    )

    # Renombrar timestamp
    df = df.rename(columns={"FECHA_GRUPO": "ts_station"})

    # Renombrar columna de valor al nombre interno
    for col_src, col_dst in COL_MAP.items():
        if col_src in df.columns:
            df = df.rename(columns={col_src: col_dst})

    # Forzar numérico — evita str si el separador decimal no coincide
    for col in ["nivel_m", "precip_mm", "caudal_m3s"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["tipo"] = tipo
    return df


def ingest_embalse(embalse_id: str) -> pd.DataFrame:
    """
    Lee todos los archivos de un embalse Ebro, los une y genera
    el parquet curado en data/curated/ebro/{EMBALSE_ID}.parquet
    """
    cfg = EMBALSE_CONFIG[embalse_id]
    base = EBRO_RAW / cfg["carpeta"] / cfg["prefijo_dir"]

    log.info(f"=== Ingesta {embalse_id} ===")
    log.info(f"Ruta fuente: {base}")

    dfs = {}
    for tipo, fname in cfg["archivos"].items():
        fpath = base / fname
        log.info(f"  Leyendo {tipo}: {fname}")
        df = _read_saih_ebro_csv(fpath, tipo)
        if not df.empty:
            log.info(f"    → {len(df):,} observaciones")
            dfs[tipo] = df

    if not dfs:
        log.error(f"No se encontraron datos para {embalse_id}")
        return pd.DataFrame()

    # Pivot: una fila por timestamp con columnas nivel, precip, [caudal]
    df_nivel  = dfs.get("nivel",  pd.DataFrame())
    df_precip = dfs.get("precip", pd.DataFrame())
    df_caudal = dfs.get("caudal", pd.DataFrame())

    # Base: nivel (siempre presente)
    df_out = df_nivel[["ts_station", "nivel_m"]].copy()

    # Merge precipitación
    if not df_precip.empty and "precip_mm" in df_precip.columns:
        df_out = df_out.merge(
            df_precip[["ts_station", "precip_mm"]],
            on="ts_station", how="left"
        )

    # Merge caudal (solo Yesa)
    if not df_caudal.empty and "caudal_m3s" in df_caudal.columns:
        df_out = df_out.merge(
            df_caudal[["ts_station", "caudal_m3s"]],
            on="ts_station", how="left"
        )

    # Metadatos
    df_out["embalse_id"]    = embalse_id
    df_out["confederation"] = "CHE"
    df_out = df_out.sort_values("ts_station").reset_index(drop=True)

    # Estadísticas básicas
    log.info(f"  Total observaciones merged: {len(df_out):,}")
    log.info(f"  Rango temporal: {df_out['ts_station'].min()} → {df_out['ts_station'].max()}")
    if "nivel_m" in df_out.columns:
        log.info(f"  Nivel: min={df_out['nivel_m'].min():.2f} max={df_out['nivel_m'].max():.2f} m")
    nans = df_out.isna().sum()
    if nans.any():
        log.warning(f"  NaNs: {nans[nans > 0].to_dict()}")

    # Guardar raw curado
    OUT_RAW.mkdir(parents=True, exist_ok=True)
    out_raw_path = OUT_RAW / f"{embalse_id}_raw.parquet"
    df_out.to_parquet(out_raw_path, index=False)
    log.info(f"  Raw guardado: {out_raw_path}")

    # Guardar curated (compatible con pipeline scoring)
    OUT_CUR.mkdir(parents=True, exist_ok=True)
    out_cur_path = OUT_CUR / f"{embalse_id}.parquet"

    # Renombrar para compatibilidad con normalizer.py existente
    df_cur = df_out.rename(columns={
        "nivel_m":    "value",
        "precip_mm":  "precip",
        "caudal_m3s": "caudal",
    })
    df_cur["variable"] = "nivel"
    df_cur.to_parquet(out_cur_path, index=False)
    log.info(f"  Curated guardado: {out_cur_path}")

    return df_out


def main():
    parser = argparse.ArgumentParser(description="Ingestor SAIH Ebro — KAIRI-SIO")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--embalse",
        choices=list(EMBALSE_CONFIG.keys()),
        help="Embalse a ingestar",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Ingestar todos los embalses Ebro",
    )
    args = parser.parse_args()

    embalses = list(EMBALSE_CONFIG.keys()) if args.all else [args.embalse]

    resultados = {}
    for eid in embalses:
        df = ingest_embalse(eid)
        resultados[eid] = len(df)

    print("\n" + "═" * 50)
    print("RESUMEN INGESTA SAIH EBRO")
    print("═" * 50)
    for eid, n in resultados.items():
        status = "✅" if n > 0 else "❌"
        print(f"  {status} {eid}: {n:,} observaciones")
    print("═" * 50)


if __name__ == "__main__":
    main()