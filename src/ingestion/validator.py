"""
KAIRI-SIO — validator.py
Validates a normalized DataFrame against Data Contract v1.1.

Fail-fast principle: if any critical check fails, raises ValidationError
with a clear human-readable message. Does not continue silently.
"""

import pandas as pd
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when a DataFrame fails Data Contract validation."""
    pass


@dataclass
class ValidationReport:
    embalse_id: str
    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def fail(self, msg: str):
        self.passed = False
        self.errors.append(msg)
        logger.error(f"  [FAIL] {msg}")

    def warn(self, msg: str):
        self.warnings.append(msg)
        logger.warning(f"  [WARN] {msg}")

    def info(self, msg: str):
        logger.info(f"  [OK]   {msg}")

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        lines = [
            f"=== Validation {status}: {self.embalse_id} ===",
            f"  Errors:   {len(self.errors)}",
            f"  Warnings: {len(self.warnings)}",
        ]
        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        for w in self.warnings:
            lines.append(f"  WARN:  {w}")
        for k, v in self.stats.items():
            lines.append(f"  {k}: {v}")
        return '\n'.join(lines)


# Required columns and their expected dtypes
_REQUIRED_COLUMNS = {
    'uuid':         'object',
    'sensor_id':    'object',
    'ts_station':   'datetime64[ns]',
    'ts_ingest':    'datetime64[ns]',
    'H_level':      'float64',
    'Q_inflow':     'float64',
    'P_rain':       'float64',
    'source_files': 'object',
}

_NUMERIC_FIELDS = ['H_level', 'Q_inflow', 'P_rain']

# Physical bounds — conservative until real embalse metadata is loaded
_PHYSICAL_BOUNDS = {
    'H_level':  (0.0, 500.0),
    'Q_inflow': (0.0, 10000.0),
    'P_rain':   (0.0, 500.0),
}

# Maximum allowed gap rate before warning
_GAP_RATE_WARN = 0.05     # 5%
_GAP_RATE_FAIL = 0.30     # 30%

# Expected hourly resolution tolerance in minutes
_EXPECTED_RESOLUTION_HOURS = 1.0
_RESOLUTION_TOLERANCE_MINUTES = 5


def validate_contract(
    df: pd.DataFrame,
    embalse_id: str,
    raise_on_failure: bool = True,
) -> ValidationReport:
    """
    Validate a curated DataFrame against Data Contract v1.1.

    Parameters
    ----------
    df              : output of normalizer.normalize_embalse()
    embalse_id      : for reporting
    raise_on_failure: if True, raises ValidationError on any hard failure

    Returns
    -------
    ValidationReport with full results
    """
    report = ValidationReport(embalse_id=embalse_id)
    logger.info(f"Validating {embalse_id} ({len(df)} rows)")

    if df is None or len(df) == 0:
        report.fail("DataFrame is empty")
        if raise_on_failure:
            raise ValidationError(report.summary())
        return report

    # ── 1. Required columns ──────────────────────────────────────────────────
    missing_cols = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        report.fail(f"Missing required columns: {missing_cols}")
    else:
        report.info(f"All required columns present")

    # ── 2. UUID uniqueness ───────────────────────────────────────────────────
    if 'uuid' in df.columns:
        n_dup_uuid = df['uuid'].duplicated().sum()
        if n_dup_uuid > 0:
            report.fail(f"Duplicate UUIDs: {n_dup_uuid}")
        else:
            report.info("UUIDs unique")

    # ── 3. Timestamps ────────────────────────────────────────────────────────
    if 'ts_station' in df.columns:
        # Convert if needed
        if not pd.api.types.is_datetime64_any_dtype(df['ts_station']):
            try:
                df['ts_station'] = pd.to_datetime(df['ts_station'])
            except Exception as e:
                report.fail(f"ts_station cannot be converted to datetime: {e}")

        if pd.api.types.is_datetime64_any_dtype(df['ts_station']):
            n_null_ts = df['ts_station'].isna().sum()
            if n_null_ts > 0:
                report.fail(f"Null timestamps: {n_null_ts}")
            else:
                report.info("No null timestamps")

            # Check monotonic
            if not df['ts_station'].is_monotonic_increasing:
                report.fail("ts_station is not monotonically increasing (not sorted)")
            else:
                report.info("Timestamps monotonically increasing")

            # Check for duplicate timestamps
            n_dup_ts = df['ts_station'].duplicated().sum()
            if n_dup_ts > 0:
                report.fail(f"Duplicate timestamps: {n_dup_ts}")
            else:
                report.info("No duplicate timestamps")

            # Check resolution
            if len(df) > 1:
                diffs_hours = df['ts_station'].diff().dt.total_seconds().dropna() / 3600
                expected = _EXPECTED_RESOLUTION_HOURS
                tol = _RESOLUTION_TOLERANCE_MINUTES / 60
                irregular = diffs_hours[
                    (diffs_hours < expected - tol) | (diffs_hours > expected + tol)
                ]
                n_irregular = len(irregular)
                if n_irregular > len(df) * 0.01:
                    report.fail(f"Irregular time resolution: {n_irregular} gaps "
                                f"not equal to {expected}h (>{1}% of rows)")
                elif n_irregular > 0:
                    report.warn(f"Minor irregular resolution: {n_irregular} rows")
                else:
                    report.info(f"Resolution consistent at {expected}h")

            report.stats['date_range'] = (
                f"{df['ts_station'].min()} -> {df['ts_station'].max()}"
            )

    # ── 4. None != 0.0 policy (document, don't fail) ─────────────────────────
    # Zero IS a valid value. We only check that we haven't accidentally
    # replaced None with 0.0 systematically (all-zeros = suspicious).
    for field in _NUMERIC_FIELDS:
        if field not in df.columns:
            continue
        n_total = len(df)
        n_null  = df[field].isna().sum()
        n_zero  = (df[field] == 0.0).sum()
        n_valid = n_total - n_null
        gap_rate = n_null / n_total if n_total > 0 else 0

        report.stats[f'{field}_null_rate'] = f"{gap_rate:.4f}"
        report.stats[f'{field}_zero_count'] = n_zero
        report.stats[f'{field}_valid'] = n_valid

        if gap_rate >= _GAP_RATE_FAIL:
            report.fail(f"{field}: gap rate {gap_rate:.1%} >= {_GAP_RATE_FAIL:.0%} threshold")
        elif gap_rate >= _GAP_RATE_WARN:
            report.warn(f"{field}: gap rate {gap_rate:.1%} (above {_GAP_RATE_WARN:.0%} warning)")
        else:
            report.info(f"{field}: gap rate {gap_rate:.2%} ({n_null} nulls / {n_total} rows)")

        # Suspicious: if zero_count = valid_count, all non-null values are zero
        if n_valid > 0 and n_zero == n_valid:
            report.warn(f"{field}: ALL non-null values are 0.0 — possible None->0 substitution?")

    # ── 5. Physical bounds (warn only — bounds may be conservative) ──────────
    for field, (lo, hi) in _PHYSICAL_BOUNDS.items():
        if field not in df.columns:
            continue
        series = df[field].dropna()
        if len(series) == 0:
            continue
        n_below = (series < lo).sum()
        n_above = (series > hi).sum()
        if n_below > 0:
            report.warn(f"{field}: {n_below} values below physical min ({lo})")
        if n_above > 0:
            report.warn(f"{field}: {n_above} values above physical max ({hi})")
        if n_below == 0 and n_above == 0:
            report.info(f"{field}: all values within physical bounds [{lo}, {hi}]")

    # ── 6. sensor_id consistent ──────────────────────────────────────────────
    if 'sensor_id' in df.columns:
        unique_ids = df['sensor_id'].unique()
        if len(unique_ids) != 1:
            report.warn(f"Multiple sensor_ids in single embalse file: {unique_ids}")
        else:
            report.info(f"sensor_id consistent: '{unique_ids[0]}'")

    # ── Final ────────────────────────────────────────────────────────────────
    report.stats['total_rows'] = len(df)
    print(report.summary())

    if not report.passed and raise_on_failure:
        raise ValidationError(
            f"Validation FAILED for {embalse_id}. "
            f"Errors: {report.errors}"
        )

    return report