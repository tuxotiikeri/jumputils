"""Shared data models passed between reading, analysis and reporting."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np


@dataclass
class ContactWindow:
    side: str
    plate_number: Optional[int]
    start_s: float
    end_s: float
    start_sample: int
    end_sample: int
    sample_rate_hz: float
    source_path: Path
    source_signal: str = 'raw_csv'

    @property
    def duration_s(self) -> float:
        return float(self.end_s - self.start_s)

@dataclass
class TrialSignals:
    trial_name: str
    trial_type: str
    source_path: Path
    point_rate_hz: float
    force_rate_hz: float
    body_mass_kg: float
    point_time_s: np.ndarray
    force_time_s: np.ndarray
    pelvis_tz: np.ndarray
    angles: Dict[str, np.ndarray]
    moments: Dict[str, np.ndarray]
    forces: Dict[str, np.ndarray]
    raw_contacts: Dict[str, ContactWindow]
    raw_force_rate_hz: float
    raw_csv_path: Path
    warnings: List[str] = field(default_factory=list)

@dataclass
class TrialResult:
    trial_name: str
    trial_type: str
    source_path: Path
    file_date: datetime
    point_rate_hz: float
    force_rate_hz: float
    body_mass_kg: float
    contact_start_s: float
    takeoff_s: float
    contact_time_s: float
    jump_height_m: float
    rsi_m_per_s: float
    peak_com_disp_m: float
    peak_com_disp_time_pct: float
    vertical_stiffness_kn_per_m: float
    spring_correlation: float
    peak_braking_force_timing_pct: float
    braking_work_j_per_kg: float
    propulsive_work_j_per_kg: float
    contact_source: str
    contact_key: str
    raw_force_rate_hz: float
    raw_csv_path: Path
    contact_windows: Dict[str, ContactWindow]
    normalized_kinematics: Dict[str, Dict[str, np.ndarray]]
    normalized_moments: Dict[str, np.ndarray]
    normalized_forces: Dict[str, np.ndarray]
    warnings: List[str] = field(default_factory=list)
