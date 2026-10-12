"""CMJ signals and results; units are explicit at the analysis boundary."""

from dataclasses import dataclass, field
from pathlib import Path
import numpy as np


@dataclass
class CMJSignals:
    trial_name: str
    source_path: Path
    force_time_s: np.ndarray
    vertical_force_n: np.ndarray  # total external vertical force, upward positive
    point_time_s: np.ndarray
    angles_deg: dict[str, np.ndarray] = field(default_factory=dict)
    moments_nm_per_kg: dict[str, np.ndarray] = field(default_factory=dict)
    metadata_mass_kg: float | None = None
    force_source: str = ""
    provenance: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    event_vertical_force_n: np.ndarray | None = None  # optional raw CSV signal
    event_time_s: np.ndarray | None = None
    side_vertical_force_n: dict[str, np.ndarray] = field(default_factory=dict)


@dataclass
class CMJResult:
    trial_name: str
    source_path: Path
    events: dict[str, float]
    metrics: dict[str, float]
    force_time_s: np.ndarray
    curves: dict[str, np.ndarray]
    point_time_s: np.ndarray
    angles_deg: dict[str, np.ndarray]
    angular_velocity_deg_s: dict[str, np.ndarray]
    moments_nm_per_kg: dict[str, np.ndarray]
    powers_w_per_kg: dict[str, np.ndarray]
    joint_metrics: dict[str, dict[str, float]]
    bottom_position: dict[str, float]
    sequencing: dict[str, dict[str, float]]
    waveform: dict
    provenance: dict[str, str]
    warnings: list[str]
    event_time_s: np.ndarray | None = None
    event_force_n: np.ndarray | None = None
