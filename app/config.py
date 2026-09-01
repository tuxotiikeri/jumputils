"""Application-wide analysis configuration."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np


AXIS_INDEX = {"x": 0, "y": 1, "z": 2}
DEFAULT_FORCE_SIGNS = np.array([1.0, -1.0, -1.0], dtype=float)


@dataclass
class Config:
    output_html: Path = Path('dropjump_report.html')
    subject_name: str = ''
    summary_csv: Optional[Path] = None
    contact_csv: Optional[Path] = None
    raw_csv_folder: Optional[Path] = None
    recursive: bool = False
    plate_left: int = 4
    plate_right: int = 3
    threshold_n: float = 20.0
    min_contact_s: float = 0.08
    merge_gap_s: float = 0.02
    phase_points: int = 101
    pelvis_tz_unit: str = 'mm'
    force_signs: np.ndarray = field(default_factory=lambda: DEFAULT_FORCE_SIGNS.copy())
    ap_axis: str = 'x'
    ml_axis: str = 'y'
    vertical_axis: str = 'z'
    filter_hz: float = 15.0
    filter_order: int = 4
    body_mass_override: Optional[float] = None
