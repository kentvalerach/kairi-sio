"""
KAIRI-SIO — run_ingestion.py
Pipeline entry point: reads all raw xlsx, normalizes, validates, saves to curated/.

Usage (from C:/KAIRI-SIO):
    python src/ingestion/run_ingestion.py

Or with custom paths:
    python src/ingestion/run_ingestion.py --raw data/raw/saih_guadalquivir --curated data/curated
"""

import sys
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ingestion.saih_reader  import read_embalse_all_variables
from src.ingestion.normalizer   import normalize_embalse, save_curated
from src.ingestion.validator    import validate_contract

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('kairi.ingestion')

EMBALSES = [
    'E32_VADOMOJON',
    'E33_SRRA_BOYERA',
    'E37_BEMBEZAR',
]


def run_pipeline(raw_dir: Path, curated_dir: Path, format: str = 'parquet') -> dict:
    """
    Full ingestion pipeline for all embalses.

    Returns
    -------
    dict mapping embalse_id -> {'path': Path, 'rows': int, 'validation': report}
    """
    ts_ingest = datetime.now(timezone.utc)
    results = {}

    logger.info("=" * 60)
    logger.info("KAIRI-SIO Ingestion Pipeline")
    logger.info(f"RAW dir    : {raw_dir}")
    logger.info(f"CURATED dir: {curated_dir}")
    logger.info(f"ts_ingest  : {ts_ingest.isoformat()}")
    logger.info("=" * 60)

    for embalse_id in EMBALSES:
        logger.info(f"\n{'─'*50}")
        logger.info(f"Processing: {embalse_id}")
        logger.info(f"{'─'*50}")

        try:
            # Step 1: Read raw xlsx
            variable_dfs = read_embalse_all_variables(raw_dir, embalse_id)

            if not variable_dfs:
                logger.error(f"No data loaded for {embalse_id} — skipping")
                continue

            # Step 2: Normalize to Data Contract v1.1
            df = normalize_embalse(variable_dfs, embalse_id, ts_ingest)

            # Step 3: Validate (fail-fast)
            report = validate_contract(df, embalse_id, raise_on_failure=True)

            # Step 4: Save to curated/
            out_path = save_curated(df, embalse_id, curated_dir, format=format)

            results[embalse_id] = {
                'path':       out_path,
                'rows':       len(df),
                'validation': report,
                'df':         df,
            }

        except Exception as e:
            logger.error(f"PIPELINE FAILED for {embalse_id}: {e}")
            raise

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info(f"\n{'='*60}")
    logger.info("INGESTION COMPLETE")
    logger.info(f"{'='*60}")
    total_rows = sum(r['rows'] for r in results.values())
    for embalse_id, r in results.items():
        logger.info(f"  {embalse_id:20s} -> {r['rows']:7,} rows -> {r['path'].name}")
    logger.info(f"  {'TOTAL':20s} -> {total_rows:7,} rows")

    return results


def main():
    parser = argparse.ArgumentParser(description='KAIRI-SIO Ingestion Pipeline')
    parser.add_argument(
        '--raw', type=Path,
        default=Path('data/raw/saih_guadalquivir'),
        help='Path to raw SAIH data directory'
    )
    parser.add_argument(
        '--curated', type=Path,
        default=Path('data/curated'),
        help='Output path for curated Parquet files'
    )
    parser.add_argument(
        '--format', choices=['parquet', 'csv'],
        default='parquet',
        help='Output format (default: parquet)'
    )
    args = parser.parse_args()

    run_pipeline(args.raw, args.curated, args.format)


if __name__ == '__main__':
    main()