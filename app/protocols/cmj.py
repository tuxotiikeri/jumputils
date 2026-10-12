"""CMJ protocol and explicit, reproducible analysis settings.

CMJ events come from whole-body force integration, never DJ contact windows.
The default moment convention follows this laboratory's Nexus export:
Nmm/kg external moments (Nexus convention), negated to internal moments
conjugate to flexion-positive sagittal angles before computing power.
"""

from dataclasses import dataclass

TRIAL_CMJ = "CMJ"
SUPPORTED = True


@dataclass
class CMJConfig:
    gravity: float = 9.80665
    baseline_start_s: float | None = None  # auto: last stable window before unweighting
    baseline_duration_s: float = 1.0
    baseline_max_cv: float = 0.02
    onset_sd: float = 5.0
    onset_bw_fraction: float = 0.025
    onset_hold_s: float = 0.03
    flight_hold_s: float = 0.08
    force_source: str = "auto"  # C3D dynamics + matching raw CSV events; standalone CSV supported
    force_filter_hz: float = 0.0  # C3D analogs already filtered by Nexus
    force_plate_model: str = 'AMTI HPS400600'  # laboratory hardware, not inferred from CSV
    kinematic_filter_hz: float = 10.0
    waveform_prominence_bw: float = 0.05
    waveform_peak_distance_s: float = 0.05
    moment_unit: str = "Nmm/kg"
    moment_signs: tuple[float, float, float] = (-1.0, -1.0, -1.0)
    # Rotation fallback: laboratory AP direction; Theia segment long axis = z.
    forward_axis: str = "x"
    forward_sign: float = 1.0
