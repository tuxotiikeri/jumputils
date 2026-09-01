"""Locale-aware report value and date formatting."""

from datetime import datetime
from typing import Sequence

import numpy as np

from app.analysis.averaging import mean_sd
from app.models import TrialResult


def fmt_num(value: float, decimals: int = 1) -> str:
    if value is None or not np.isfinite(value):
        return '-'
    return f'{value:.{decimals}f}'.replace('.', ',')

def fmt_mean_sd(values: Sequence[float], decimals: int = 1) -> str:
    mean_v, sd_v = mean_sd(values)
    return f'{fmt_num(mean_v, decimals)} ± {fmt_num(sd_v, decimals)}'

def fmt_date(dt: datetime) -> str:
    return dt.strftime('%d.%m.%Y')

def infer_measurement_date(results: Sequence[TrialResult]) -> str:
    if not results:
        return '-'
    dates = sorted({res.file_date.date() for res in results})
    if len(dates) == 1:
        return dates[0].strftime('%d.%m.%Y')
    return f"{dates[0].strftime('%d.%m.%Y')}–{dates[-1].strftime('%d.%m.%Y')}"
