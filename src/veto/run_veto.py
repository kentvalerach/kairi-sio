"""
KAIRI-SIO — run_veto.py
Sprint 3 pipeline: veto + forensic JSONL output.

Reads scored Parquet from data/analytic/,
applies decision engine, writes JSONL + summary CSV to output/forensics/.

Usage (from C:/KAIRI-SIO):
    python src/veto/run_veto.py
    python src/veto/run_veto.py --level 1   # only DEGRADADA + VETADA in JSONL
    python src/veto/run_veto.py --level 2   # only VETADA in JSONL
"""

import sys
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from src.scoring.scorer import score_embalse
from src.veto.decision_engine import apply_veto
from src.forensics.forensic_logger import write_forensic_jsonl, write_forensic_summary_csv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('kairi.veto')

EMBALSES = [
    'E32_VADOMOJON',
    'E33_SRRA_BOYERA',
    'E37_BEMBEZAR',
]


def run_pipeline(
    analytic_dir: Path,
    output_dir: Path,
    curated_dir: Path,
    filter_level: int | None = None,
) -> dict:

    ts_run = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    forensics_dir = output_dir / 'forensics'
    forensics_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("KAIRI-SIO Veto + Forensic Pipeline")
    logger.info(f"ANALYTIC dir : {analytic_dir}")
    logger.info(f"OUTPUT dir   : {forensics_dir}")
    logger.info(f"Filter level : {filter_level if filter_level is not None else 'ALL'}")
    logger.info("=" * 60)

    results = {}

    for embalse_id in EMBALSES:
        logger.info(f"\n{'─'*50}")
        logger.info(f"Processing: {embalse_id}")
        logger.info(f"{'─'*50}")

        # Try analytic first, re-score from curated if needed
        scored_path = analytic_dir / f"{embalse_id}_scored.parquet"
        if scored_path.exists():
            scored = pd.read_parquet(scored_path)
            # Check if detailed columns are present
            has_detail = 'sf_flag_H_level_range' in scored.columns
            if not has_detail:
                logger.info(f"  Re-scoring {embalse_id} with detailed=True...")
                curated_path = curated_dir / f"{embalse_id}.parquet"
                if not curated_path.exists():
                    logger.error(f"  Curated file not found: {curated_path} — skipping")
                    continue
                df = pd.read_parquet(curated_path)
                scored = score_embalse(df, embalse_id, detailed=True)
        else:
            logger.error(f"  Scored file not found: {scored_path} — skipping")
            continue

        # Apply veto engine
        logger.info(f"  Applying veto engine...")
        veto_df = apply_veto(scored)

        # Veto summary
        n = len(veto_df)
        for flag in ['CERTIFICADA', 'DEGRADADA', 'VETADA']:
            count = (veto_df['veto_flag'] == flag).sum()
            critical = (veto_df['critical_flag'] & (veto_df['veto_flag'] == flag)).sum()
            crit_str = f" ({critical} critical)" if critical > 0 else ""
            logger.info(f"  {flag:<15} {count:>7,} ({count/n*100:.1f}%){crit_str}")

        # Write JSONL (append-only, timestamped filename)
        jsonl_path = forensics_dir / f"{embalse_id}_forensic_{ts_run}.jsonl"
        n_written = write_forensic_jsonl(veto_df, jsonl_path, filter_level=filter_level)

        # Write summary CSV
        csv_path = forensics_dir / f"{embalse_id}_summary_{ts_run}.csv"
        write_forensic_summary_csv(veto_df, csv_path)

        results[embalse_id] = {
            'veto_df':    veto_df,
            'jsonl_path': jsonl_path,
            'csv_path':   csv_path,
            'n_written':  n_written,
        }

    # ── Final summary ─────────────────────────────────────────────────────
    logger.info(f"\n{'='*60}")
    logger.info("VETO + FORENSIC COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"{'Embalse':<22} {'Events':>8} {'JSONL file'}")
    logger.info(f"{'─'*22} {'─'*8} {'─'*40}")
    for embalse_id, r in results.items():
        logger.info(f"{embalse_id:<22} {r['n_written']:>8,} {r['jsonl_path'].name}")

    return results


def main():
    parser = argparse.ArgumentParser(description='KAIRI-SIO Veto + Forensic Pipeline')
    parser.add_argument('--analytic', type=Path, default=Path('data/analytic'))
    parser.add_argument('--curated',  type=Path, default=Path('data/curated'))
    parser.add_argument('--output',   type=Path, default=Path('output'))
    parser.add_argument('--level', type=int, default=None,
                        help='Min veto level to log: 0=all, 1=DEGRADADA+VETADA, 2=VETADA only')
    args = parser.parse_args()
    run_pipeline(args.analytic, args.output, args.curated, args.level)


if __name__ == '__main__':
    main()