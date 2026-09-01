"""Ground-contact event detection from force-plate signals."""

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.config import AXIS_INDEX, Config
from app.models import ContactWindow
from app.protocols.common import TRIAL_DJ, active_sides_for_trial
from app.c3d.forceplate import _raw_csv_path_for_c3d, read_raw_force_csv


def find_true_bouts(mask: np.ndarray) -> List[Tuple[int, int]]:
    bouts: List[Tuple[int, int]] = []
    i = 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j < len(mask) and mask[j]:
                j += 1
            bouts.append((i, j))
            i = j
        else:
            i += 1
    return bouts

def merge_bouts(bouts: Sequence[Tuple[int, int]], max_gap_samples: int) -> List[Tuple[int, int]]:
    if not bouts:
        return []
    merged: List[List[int]] = [[bouts[0][0], bouts[0][1]]]
    for start, end in bouts[1:]:
        if start - merged[-1][1] <= max_gap_samples:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]

def _threshold_crossing_time(time_s: np.ndarray, values: np.ndarray, idx: int, threshold: float, rising: bool) -> float:
    idx = int(idx)
    if rising:
        if idx <= 0:
            return float(time_s[0])
        i0, i1 = idx - 1, idx
    else:
        if idx >= len(time_s):
            return float(time_s[-1])
        if idx <= 0:
            return float(time_s[0])
        i0, i1 = idx - 1, idx

    x0, x1 = float(time_s[i0]), float(time_s[i1])
    y0, y1 = float(values[i0]), float(values[i1])
    if not (np.isfinite(y0) and np.isfinite(y1)) or abs(y1 - y0) < 1e-12:
        return x1 if rising else x0
    frac = (threshold - y0) / (y1 - y0)
    frac = float(np.clip(frac, 0.0, 1.0))
    return x0 + frac * (x1 - x0)

def detect_contact_from_verticals(
    force_time_s: np.ndarray,
    vertical_signals: Sequence[np.ndarray],
    cfg: Config,
    *,
    side: str,
    plate_number: Optional[int],
    source_path: Path,
) -> ContactWindow:
    if len(force_time_s) < 2:
        raise RuntimeError('Not enough force samples for contact detection')
    if not vertical_signals:
        raise RuntimeError('No vertical force signals supplied for contact detection')

    signals = [np.asarray(v, dtype=float) for v in vertical_signals]
    if any(len(v) != len(force_time_s) for v in signals):
        raise RuntimeError('Force time and vertical force signal lengths do not match')

    combined_vertical = np.nanmax(np.vstack(signals), axis=0)
    dt = float(np.median(np.diff(force_time_s)))
    max_gap_samples = max(0, int(round(cfg.merge_gap_s / dt)))
    min_contact_samples = max(1, int(round(cfg.min_contact_s / dt)))
    active_mask = combined_vertical > cfg.threshold_n
    bouts = merge_bouts(find_true_bouts(active_mask), max_gap_samples)
    if not bouts:
        raise RuntimeError(f'No raw force contact bout detected for {side}')

    selected = None
    for start, end in bouts:
        if end - start >= min_contact_samples:
            selected = (start, end)
            break
    if selected is None:
        selected = max(bouts, key=lambda b: b[1] - b[0])

    start_idx, end_idx = selected
    start_s = _threshold_crossing_time(force_time_s, combined_vertical, start_idx, cfg.threshold_n, rising=True)
    end_s = _threshold_crossing_time(force_time_s, combined_vertical, end_idx, cfg.threshold_n, rising=False)
    if end_s <= start_s:
        end_s = float(force_time_s[min(max(end_idx, start_idx + 1), len(force_time_s) - 1)])
    sample_rate_hz = 1.0 / dt if dt > 0 else float('nan')
    return ContactWindow(
        side=side,
        plate_number=plate_number,
        start_s=float(start_s),
        end_s=float(end_s),
        start_sample=int(start_idx),
        end_sample=int(end_idx),
        sample_rate_hz=float(sample_rate_hz),
        source_path=source_path,
        source_signal='raw_csv',
    )

def read_raw_contacts_for_trial(c3d_path: Path, trial_type: str, cfg: Config) -> Tuple[Dict[str, ContactWindow], float, Path, List[str]]:
    csv_path = _raw_csv_path_for_c3d(c3d_path, cfg)
    sample_rate_hz, raw_time_s, raw_forces = read_raw_force_csv(csv_path, cfg)
    warnings: List[str] = []
    contacts: Dict[str, ContactWindow] = {}
    active_sides = active_sides_for_trial(trial_type)
    plate_by_side = {'L': cfg.plate_left, 'R': cfg.plate_right}

    for side in active_sides:
        try:
            vertical = raw_forces[side][:, AXIS_INDEX[cfg.vertical_axis]]
            contacts[side] = detect_contact_from_verticals(
                raw_time_s,
                [vertical],
                cfg,
                side=side,
                plate_number=plate_by_side[side],
                source_path=csv_path,
            )
        except Exception as exc:
            if trial_type == TRIAL_DJ:
                warnings.append(f'Raw individual {side} contact could not be detected: {exc}')
            else:
                raise

    if trial_type == TRIAL_DJ:
        verticals = [raw_forces[side][:, AXIS_INDEX[cfg.vertical_axis]] for side in active_sides]
        contacts['combined'] = detect_contact_from_verticals(
            raw_time_s,
            verticals,
            cfg,
            side='combined',
            plate_number=None,
            source_path=csv_path,
        )
    else:
        active = active_sides[0]
        contacts['combined'] = contacts[active]

    return contacts, float(sample_rate_hz), csv_path, warnings

def detect_contact_window(force_time_s: np.ndarray, forces: Dict[str, np.ndarray], active_sides: Sequence[str], cfg: Config) -> Tuple[float, float]:
    verticals = [np.asarray(forces[side])[:, AXIS_INDEX[cfg.vertical_axis]] for side in active_sides]
    contact = detect_contact_from_verticals(
        force_time_s,
        verticals,
        cfg,
        side='combined' if len(active_sides) > 1 else active_sides[0],
        plate_number=None,
        source_path=Path('c3d_analog'),
    )
    return contact.start_s, contact.end_s
