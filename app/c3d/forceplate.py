"""Nexus raw-force CSV parsing and C3D force-plate access."""

import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.config import AXIS_INDEX, Config
from app.c3d.labels import normalize_label


def _parse_float_cell(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        text = str(value).strip().replace(',', '.')
        if not text:
            return None
        return float(text)
    except Exception:
        return None

def _read_csv_rows(path: Path) -> List[List[str]]:
    encodings = ['utf-8-sig', 'utf-8', 'cp1252', 'latin1']
    last_exc: Optional[Exception] = None
    for enc in encodings:
        try:
            with path.open('r', encoding=enc, newline='') as f:
                return [row for row in csv.reader(f)]
        except UnicodeDecodeError as exc:
            last_exc = exc
    raise RuntimeError(f'Could not read CSV file {path}: {last_exc}')

def _find_nexus_csv_header(rows: Sequence[Sequence[str]]) -> int:
    for i, row in enumerate(rows):
        if len(row) >= 2 and normalize_label(row[0]) == 'frame' and normalize_label(row[1]) == 'subframe':
            return i
    raise RuntimeError('CSV header row "Frame, Sub Frame, ..." was not found')

def _find_nexus_csv_rate(rows: Sequence[Sequence[str]], header_idx: int) -> float:
    # Nexus exports usually contain: Devices / 1200 / group row / channel row.
    for i in range(header_idx):
        row = rows[i]
        if row and normalize_label(row[0]) == 'devices':
            for j in range(i + 1, header_idx):
                if rows[j]:
                    val = _parse_float_cell(rows[j][0])
                    if val and val > 0:
                        return float(val)
    # Fallback: first single numeric-looking row before the header.
    for row in rows[:header_idx]:
        non_empty = [cell for cell in row if str(cell).strip()]
        if len(non_empty) == 1:
            val = _parse_float_cell(non_empty[0])
            if val and val > 0:
                return float(val)
    raise RuntimeError('CSV analog sample rate was not found before the header row')

def _fill_group_labels(group_row: Sequence[str], length: int) -> List[str]:
    filled: List[str] = []
    current = ''
    for i in range(length):
        cell = group_row[i].strip() if i < len(group_row) else ''
        if cell:
            current = cell
        filled.append(current)
    return filled

def _raw_csv_path_for_c3d(c3d_path: Path, cfg: Config) -> Path:
    if cfg.raw_csv_folder is not None:
        return cfg.raw_csv_folder / f'{c3d_path.stem}.csv'
    return c3d_path.with_suffix('.csv')

def read_raw_force_csv(path: Path, cfg: Config) -> Tuple[float, np.ndarray, Dict[str, np.ndarray]]:
    """Read unsmoothed Nexus force-plate CSV data.

    The returned force arrays are in columns Fx, Fy, Fz and Fz is auto-oriented so
    that contact is positive. No filtering is applied.
    """
    if not path.exists():
        raise FileNotFoundError(f'Raw force CSV not found: {path}')

    rows = _read_csv_rows(path)
    header_idx = _find_nexus_csv_header(rows)
    sample_rate_hz = _find_nexus_csv_rate(rows, header_idx)
    group_row = rows[header_idx - 1] if header_idx > 0 else []
    channel_row = rows[header_idx]
    n_cols = max(len(group_row), len(channel_row))
    groups = _fill_group_labels(group_row, n_cols)

    plate_cols: Dict[int, Dict[str, int]] = {}
    for col_idx in range(n_cols):
        group = groups[col_idx]
        channel = channel_row[col_idx].strip() if col_idx < len(channel_row) else ''
        match = re.match(r'^\s*(\d+)\s*-\s*Force\s*$', group, flags=re.IGNORECASE)
        if not match or channel not in {'Fx', 'Fy', 'Fz'}:
            continue
        plate = int(match.group(1))
        plate_cols.setdefault(plate, {})[channel] = col_idx

    requested = {'L': cfg.plate_left, 'R': cfg.plate_right}
    missing: List[str] = []
    for side, plate in requested.items():
        cols = plate_cols.get(plate, {})
        if not all(ch in cols for ch in ('Fx', 'Fy', 'Fz')):
            missing.append(f'{side}=plate {plate}')
    if missing:
        available = ', '.join(str(p) for p in sorted(plate_cols)) or 'none'
        raise RuntimeError(f'CSV is missing required force columns for {", ".join(missing)}. Available force plates: {available}')

    data_rows: List[List[str]] = []
    for row in rows[header_idx + 1:]:
        if len(row) < 2:
            continue
        if _parse_float_cell(row[0]) is None or _parse_float_cell(row[1]) is None:
            continue
        data_rows.append(list(row))
    if not data_rows:
        raise RuntimeError('CSV does not contain numeric force data rows')

    n = len(data_rows)
    time_s = np.arange(n, dtype=float) / sample_rate_hz
    forces: Dict[str, np.ndarray] = {}
    for side, plate in requested.items():
        arr = np.full((n, 3), np.nan, dtype=float)
        cols = plate_cols[plate]
        for comp_idx, ch in enumerate(('Fx', 'Fy', 'Fz')):
            col_idx = cols[ch]
            vals = []
            for row in data_rows:
                vals.append(_parse_float_cell(row[col_idx]) if col_idx < len(row) else np.nan)
            arr[:, comp_idx] = np.asarray(vals, dtype=float)
        arr = arr * cfg.force_signs[None, :]

        # Auto-orient vertical raw force so the contact threshold is always positive.
        z = arr[:, AXIS_INDEX[cfg.vertical_axis]]
        if np.isfinite(z).any():
            pos_peak = float(np.nanpercentile(z, 99.5))
            neg_peak = float(np.nanpercentile(-z, 99.5))
            if neg_peak > pos_peak:
                arr[:, AXIS_INDEX[cfg.vertical_axis]] *= -1.0
        forces[side] = arr

    return float(sample_rate_hz), time_s, forces

def get_c3d_analog_force(c3d_obj: Dict[str, Any], plate_number: int, force_signs: np.ndarray) -> np.ndarray:
    labels = list(c3d_obj['parameters']['ANALOG']['LABELS']['value'])
    analogs = np.asarray(c3d_obj['data']['analogs'], dtype=float)
    if analogs.size == 0:
        raise RuntimeError('C3D does not contain analog channels')
    analogs = analogs[0]
    idx = [labels.index(f'Force.Fx{plate_number}'), labels.index(f'Force.Fy{plate_number}'), labels.index(f'Force.Fz{plate_number}')]
    return analogs[idx, :].T.astype(float) * force_signs[None, :]
