"""Across-trial curve aggregation and descriptive statistics."""

from typing import List, Optional, Sequence, Tuple

import numpy as np

from app.models import TrialResult


def aggregate_curves(results: Sequence[TrialResult], side: str, extractor) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    curves: List[np.ndarray] = []
    for res in results:
        arr = extractor(res, side)
        if arr is not None:
            curves.append(np.asarray(arr, dtype=float))
    if not curves:
        return None
    data = np.stack(curves, axis=0)
    return np.nanmean(data, axis=0), np.nanstd(data, axis=0, ddof=0)

def aggregate_mean(values: Sequence[float]) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(np.mean(arr)) if arr.size else float('nan')

def mean_sd(values: Sequence[float]) -> Tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    return (float(np.mean(arr)), float(np.std(arr, ddof=0))) if arr.size else (float('nan'), float('nan'))

def grouped_pairs(left_results: Sequence[TrialResult], right_results: Sequence[TrialResult]) -> Tuple[List[str], List[Optional[TrialResult]], List[Optional[TrialResult]]]:
    left_sorted = sorted(left_results, key=lambda r: r.trial_name)
    right_sorted = sorted(right_results, key=lambda r: r.trial_name)
    n = max(len(left_sorted), len(right_sorted))
    keys = [f'#{i + 1}' for i in range(n)]
    return keys, [left_sorted[i] if i < len(left_sorted) else None for i in range(n)], [right_sorted[i] if i < len(right_sorted) else None for i in range(n)]
