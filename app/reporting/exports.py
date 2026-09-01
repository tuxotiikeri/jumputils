"""CSV sidecar exports produced alongside the HTML report."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.models import ContactWindow, TrialResult
from app.protocols.common import platform_cm_for_trial, trial_family_label
from app.utils import ensure_parent


def _default_side_columns(row: Dict[str, Any], prefix: str) -> None:
    row[f'{prefix}_contact_start_s'] = np.nan
    row[f'{prefix}_takeoff_s'] = np.nan
    row[f'{prefix}_contact_time_ms'] = np.nan
    row[f'{prefix}_start_sample'] = np.nan
    row[f'{prefix}_end_sample'] = np.nan
    row[f'{prefix}_plate'] = np.nan

def _fill_contact_columns(row: Dict[str, Any], prefix: str, contact: Optional[ContactWindow]) -> None:
    if contact is None:
        _default_side_columns(row, prefix)
        return
    row[f'{prefix}_contact_start_s'] = round(contact.start_s, 6)
    row[f'{prefix}_takeoff_s'] = round(contact.end_s, 6)
    row[f'{prefix}_contact_time_ms'] = round(contact.duration_s * 1000.0, 2)
    row[f'{prefix}_start_sample'] = contact.start_sample
    row[f'{prefix}_end_sample'] = contact.end_sample
    row[f'{prefix}_plate'] = contact.plate_number if contact.plate_number is not None else ''

def write_contact_csvs(results: Sequence[TrialResult], wide_path: Path, threshold_n: float) -> Tuple[Path, Path]:
    ensure_parent(wide_path)
    wide_rows: List[Dict[str, Any]] = []
    long_rows: List[Dict[str, Any]] = []
    for r in sorted(results, key=lambda item: item.trial_name):
        row: Dict[str, Any] = {
            'trial_name': r.trial_name,
            'trial_type': r.trial_type,
            'trial_family': trial_family_label(r.trial_type),
            'platform_cm': platform_cm_for_trial(r.trial_type),
            'primary_contact': r.contact_key,
            'raw_csv': str(r.raw_csv_path),
            'raw_force_rate_hz': round(r.raw_force_rate_hz, 3),
            'threshold_n': threshold_n,
        }
        _fill_contact_columns(row, 'combined', r.contact_windows.get('combined'))
        _fill_contact_columns(row, 'left', r.contact_windows.get('L'))
        _fill_contact_columns(row, 'right', r.contact_windows.get('R'))
        wide_rows.append(row)

        for key, contact in r.contact_windows.items():
            long_rows.append({
                'trial_name': r.trial_name,
                'trial_type': r.trial_type,
                'trial_family': trial_family_label(r.trial_type),
                'platform_cm': platform_cm_for_trial(r.trial_type),
                'contact_key': key,
                'side': contact.side,
                'plate': contact.plate_number if contact.plate_number is not None else '',
                'contact_start_s': round(contact.start_s, 6),
                'takeoff_s': round(contact.end_s, 6),
                'contact_time_ms': round(contact.duration_s * 1000.0, 2),
                'start_sample': contact.start_sample,
                'end_sample': contact.end_sample,
                'raw_force_rate_hz': round(contact.sample_rate_hz, 3),
                'threshold_n': threshold_n,
                'raw_csv': str(contact.source_path),
            })

    pd.DataFrame(wide_rows).to_csv(wide_path, index=False)
    long_path = wide_path.with_name(f'{wide_path.stem}_long{wide_path.suffix}')
    pd.DataFrame(long_rows).to_csv(long_path, index=False)
    return wide_path, long_path
