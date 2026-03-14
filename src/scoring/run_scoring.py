"""
KAIRI-SIO — run_scoring.py
Scoring pipeline entry point.

Reads curated Parquet files, computes S_c for all embalses,
saves scored Parquet to data/analytic/.

Usage (from C:/KAIRI-SIO):
    python src/scoring/run_scoring.py
    python src/scoring/run_scoring.py --detailed
    python src/scoring/run_scoring.py --confederation CHE
    python src/scoring/run_scoring.py --confederation CHE --detailed
    python src/scoring/run_scoring.py --confederation CHG --embalse E32_VADOMOJON
"""

import sys
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.scoring.scorer import score_embalse, save_analytic
from src.config.confederation_config import load_confederation_config, list_available_confederations
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("kairi.scoring")

# ── Embalses por confederación ────────────────────────────────────────────────
EMBALSES_BY_CONFEDERATION = {
    "CHG": ["E32_VADOMOJON", "E33_SRRA_BOYERA", "E37_BEMBEZAR"],
    "CHE": ["ITOIZ", "MEQUINENZA", "YESA"],
    "CHD": [],
    "CHT": [],
}

# Subdirectorios curados/analytic por confederación
CURATED_SUBDIR  = {"CHG": "",      "CHE": "ebro",  "CHD": "duero", "CHT": "tajo"}
ANALYTIC_SUBDIR = {"CHG": "",      "CHE": "ebro",  "CHD": "duero", "CHT": "tajo"}


def resolve_dirs(base_curated, base_analytic, confederation):
    cur_sub = CURATED_SUBDIR.get(confederation, "")
    ana_sub = ANALYTIC_SUBDIR.get(confederation, "")
    curated_dir  = base_curated  / cur_sub if cur_sub else base_curated
    analytic_dir = base_analytic / ana_sub if ana_sub else base_analytic
    curated_dir.mkdir(parents=True, exist_ok=True)
    analytic_dir.mkdir(parents=True, exist_ok=True)
    return curated_dir, analytic_dir


def _normalize_columns(df, confederation):
    """
    Normaliza el parquet curado al Data Contract v1.1 que espera scorer.py.

    Data Contract v1.1 (scorer.py base_cols):
        uuid, sensor_id, ts_station, ts_ingest,
        H_level, Q_inflow, P_rain

    Ebro reader produce:
        ts_station, nivel_m, precip_mm, [caudal_m3s], embalse_id, confederation
    """
    import uuid as _uuid
    import pandas as pd
    import numpy as np

    if confederation == "CHG":
        return df

    df = df.copy()

    # 1. Renombrar columnas de valor al esquema interno
    rename_map = {}
    if "nivel_m" in df.columns:
        rename_map["nivel_m"] = "H_level"
    elif "value" in df.columns:
        rename_map["value"] = "H_level"

    if "precip_mm" in df.columns:
        rename_map["precip_mm"] = "P_rain"
    elif "precip" in df.columns:
        rename_map["precip"] = "P_rain"

    if "caudal_m3s" in df.columns:
        rename_map["caudal_m3s"] = "Q_inflow"
    elif "caudal" in df.columns:
        rename_map["caudal"] = "Q_inflow"

    if rename_map:
        df = df.rename(columns=rename_map)

    # 2. Añadir columnas requeridas que no existen en el reader Ebro
    n = len(df)
    if "uuid" not in df.columns:
        df["uuid"] = [str(_uuid.uuid4()) for _ in range(n)]
    if "sensor_id" not in df.columns:
        df["sensor_id"] = "SAIH_EBRO"
    if "ts_ingest" not in df.columns:
        df["ts_ingest"] = df["ts_station"]
    if "H_level" not in df.columns:
        df["H_level"] = np.nan
    if "Q_inflow" not in df.columns:
        df["Q_inflow"] = np.nan
    if "P_rain" not in df.columns:
        df["P_rain"] = np.nan

    # 3. Eliminar columnas extra que rompen el scoring (strings no numéricos)
    cols_to_drop = [c for c in ["embalse_id", "confederation", "variable", "tipo"]
                    if c in df.columns]
    if cols_to_drop:
        df = df.drop(columns=cols_to_drop)

    return df


def run_pipeline(base_curated, base_analytic, detailed=False,
                 confederation="CHG", embalse_filter=None):

    cfg = load_confederation_config(confederation)
    curated_dir, analytic_dir = resolve_dirs(base_curated, base_analytic, confederation)

    embalses_all = EMBALSES_BY_CONFEDERATION.get(confederation, [])
    if not embalses_all:
        logger.error(f"No hay embalses configurados para {confederation}.")
        return {}

    embalses = [embalse_filter] if embalse_filter else embalses_all
    for eid in embalses:
        if eid not in embalses_all:
            logger.error(f"\'{eid}\' no pertenece a {confederation}. Disponibles: {embalses_all}")
            return {}

    logger.info("=" * 60)
    logger.info("KAIRI-SIO Scoring Pipeline")
    logger.info(f"CURATED dir   : {curated_dir}")
    logger.info(f"ANALYTIC dir  : {analytic_dir}")
    logger.info(f"Confederation : {cfg.code} — {cfg.name}")
    logger.info(f"Embalses      : {embalses}")
    logger.info(f"Detailed      : {detailed}")
    logger.info("=" * 60)

    results = {}

    for embalse_id in embalses:
        logger.info(f"\n{chr(45)*50}")
        logger.info(f"Processing: {embalse_id}")
        logger.info(f"{chr(45)*50}")

        parquet_path = curated_dir / f"{embalse_id}.parquet"
        if not parquet_path.exists():
            logger.error(f"No encontrado: {parquet_path}")
            logger.error(f"  → Ejecuta primero: python src/ingestion/saih_ebro_reader.py --all")
            continue

        df = pd.read_parquet(parquet_path)
        df = _normalize_columns(df, confederation)

        scored = score_embalse(df, embalse_id, detailed=detailed,
                               confederation_config=cfg)
        out_path = save_analytic(scored, embalse_id, analytic_dir)
        results[embalse_id] = {"path": out_path, "rows": len(scored), "df": scored}

    if results:
        logger.info(f"\n{chr(61)*60}")
        logger.info(f"SCORING COMPLETE — {confederation}")
        logger.info(f"{chr(61)*60}")
        logger.info(f"{'Embalse':<22} {'Rows':>8} {'CERT%':>7} {'DEG%':>7} {'VET%':>7} {'S_c mean':>9}")
        logger.info(f"{chr(45)*22} {chr(45)*8} {chr(45)*7} {chr(45)*7} {chr(45)*7} {chr(45)*9}")
        for embalse_id, r in results.items():
            df = r["df"]
            n  = len(df)
            qf = df["quality_flag"]
            sc = df["S_c"]
            logger.info(
                f"{embalse_id:<22} {n:>8,} "
                f"{(qf=='CERTIFICADA').sum()/n*100:>6.1f}% "
                f"{(qf=='DEGRADADA').sum()/n*100:>6.1f}% "
                f"{(qf=='VETADA').sum()/n*100:>6.1f}% "
                f"{sc.mean():>9.4f}"
            )
    return results


def main():
    parser = argparse.ArgumentParser(description="KAIRI-SIO Scoring Pipeline")
    parser.add_argument("--curated",  type=Path, default=Path("data/curated"))
    parser.add_argument("--analytic", type=Path, default=Path("data/analytic"))
    available = [c["code"] for c in list_available_confederations()]
    parser.add_argument("--confederation", type=str, default="CHG",
                        choices=available,
                        help=f"Confederación. Disponibles: {available}")
    parser.add_argument("--embalse", type=str, default=None,
                        help="Procesar un solo embalse (opcional)")
    parser.add_argument("--detailed", action="store_true")
    args = parser.parse_args()

    run_pipeline(
        base_curated=args.curated,
        base_analytic=args.analytic,
        detailed=args.detailed,
        confederation=args.confederation,
        embalse_filter=args.embalse,
    )


if __name__ == "__main__":
    main()