"""Signal processing and per-trial jump metrics."""

from datetime import datetime
from typing import Dict, Tuple

import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import butter, filtfilt

from app.config import AXIS_INDEX, Config
from app.models import TrialResult, TrialSignals
from app.protocols.common import TRIAL_DJ, active_sides_for_trial, contact_key_for_trial


def _fill_nan_1d(y: np.ndarray) -> np.ndarray:
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(y)
    if finite.all() or y.size == 0:
        return y.copy()
    if not finite.any():
        return y.copy()
    x = np.arange(y.size, dtype=float)
    out = y.copy()
    out[~finite] = np.interp(x[~finite], x[finite], y[finite])
    return out

def butter_lowpass_zero_lag(data: np.ndarray, fs: float, cutoff_hz: float, order: int = 4) -> np.ndarray:
    data = np.asarray(data, dtype=float)
    if data.size < max(12, order * 3):
        return data.copy()
    nyq = 0.5 * fs
    wn = min(max(cutoff_hz / nyq, 1e-4), 0.999)
    b, a = butter(order, wn, btype='low')
    if data.ndim == 1:
        y = _fill_nan_1d(data)
        return filtfilt(b, a, y) if np.isfinite(y).all() else data.copy()
    out = np.empty_like(data)
    for i in range(data.shape[1]):
        y = _fill_nan_1d(data[:, i])
        out[:, i] = filtfilt(b, a, y) if np.isfinite(y).all() else data[:, i]
    return out

def interpolate_segment(time_s: np.ndarray, values: np.ndarray, start_s: float, end_s: float, n_points: int) -> np.ndarray:
    phase_time = np.linspace(start_s, end_s, n_points)
    values = np.asarray(values, dtype=float)
    if values.ndim == 1:
        f = interp1d(time_s, values, kind='linear', bounds_error=False, fill_value='extrapolate')
        return np.asarray(f(phase_time), dtype=float)
    cols = []
    for i in range(values.shape[1]):
        f = interp1d(time_s, values[:, i], kind='linear', bounds_error=False, fill_value='extrapolate')
        cols.append(np.asarray(f(phase_time), dtype=float))
    return np.stack(cols, axis=1)

def compute_jump_height(point_time_s: np.ndarray, pelvis_tz: np.ndarray, takeoff_s: float, unit: str = 'mm') -> Tuple[float, float]:
    takeoff_val = float(np.interp(takeoff_s, point_time_s, pelvis_tz))
    start_idx = int(np.searchsorted(point_time_s, takeoff_s, side='left'))
    if start_idx >= len(pelvis_tz) - 2:
        raise RuntimeError('Take-off occurs too late to estimate apex')
    dt = float(np.median(np.diff(point_time_s)))
    end_idx = min(len(pelvis_tz), start_idx + max(10, int(round(1.0 / dt))))
    seg = np.asarray(pelvis_tz[start_idx:end_idx], dtype=float)
    diffs = np.diff(seg)
    had_rise = False
    peak_idx = None
    for i, d in enumerate(diffs, start=1):
        if d > 1e-9:
            had_rise = True
        if had_rise and d < -1e-9:
            peak_idx = int(np.argmax(seg[: i + 1]))
            break
    if peak_idx is None:
        peak_idx = int(np.argmax(seg))
    jump_height = float(seg[peak_idx] - takeoff_val)
    jump_height_m = jump_height / 1000.0 if unit.lower() == 'mm' else jump_height
    return float(jump_height_m), float(point_time_s[start_idx + peak_idx])

def compute_peak_com_displacement(point_time_s: np.ndarray, pelvis_tz: np.ndarray, contact_start_s: float, takeoff_s: float, unit: str = 'mm') -> Tuple[float, float, float]:
    sample_time = np.linspace(contact_start_s, takeoff_s, 401)
    sample_vals = np.asarray(np.interp(sample_time, point_time_s, pelvis_tz), dtype=float)
    start_val = float(sample_vals[0])
    min_idx = int(np.argmin(sample_vals))
    disp = start_val - float(sample_vals[min_idx])
    disp_m = disp / 1000.0 if unit.lower() == 'mm' else disp
    min_time = float(sample_time[min_idx])
    pct = 100.0 * (min_time - contact_start_s) / max(takeoff_s - contact_start_s, 1e-9)
    return float(max(disp_m, 0.0)), float(np.clip(pct, 0.0, 100.0)), min_time

def safe_trapezoid(y: np.ndarray, x: np.ndarray) -> float:
    """Compatibility wrapper for NumPy versions where np.trapz is unavailable."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    if hasattr(np, 'trapezoid'):
        return float(np.trapezoid(y, x))
    if hasattr(np, 'trapz'):
        return float(np.trapz(y, x))
    if y.size < 2 or x.size < 2:
        return 0.0
    return float(np.sum(0.5 * (y[1:] + y[:-1]) * np.diff(x)))

def process_trial(signals: TrialSignals, cfg: Config) -> TrialResult:
    active_sides = active_sides_for_trial(signals.trial_type)
    contact_key = contact_key_for_trial(signals.trial_type)
    if contact_key not in signals.raw_contacts:
        raise RuntimeError(f'Raw contact window {contact_key!r} was not available for {signals.trial_name}')

    primary_contact = signals.raw_contacts[contact_key]
    contact_start_s = primary_contact.start_s
    takeoff_s = primary_contact.end_s
    jump_height_m, _ = compute_jump_height(signals.point_time_s, signals.pelvis_tz, takeoff_s, unit=cfg.pelvis_tz_unit)
    peak_com_disp_m, peak_com_disp_time_pct, peak_com_time_s = compute_peak_com_displacement(signals.point_time_s, signals.pelvis_tz, contact_start_s, takeoff_s, unit=cfg.pelvis_tz_unit)
    contact_time_s = takeoff_s - contact_start_s
    rsi_m_per_s = jump_height_m / contact_time_s if contact_time_s > 0 else float('nan')
    mass = signals.body_mass_kg if np.isfinite(signals.body_mass_kg) and signals.body_mass_kg > 0 else 1.0

    # The contact timing comes from the unsmoothed raw CSV. The force curves and
    # inverse-dynamics variables still come from the pre-filtered C3D signal.
    contact_force_time = np.linspace(contact_start_s, takeoff_s, max(25, int(round((takeoff_s - contact_start_s) * signals.force_rate_hz)) + 1))
    total_force = np.zeros((len(contact_force_time), 3), dtype=float)
    for side in active_sides:
        for comp in range(3):
            total_force[:, comp] += np.interp(contact_force_time, signals.force_time_s, signals.forces[side][:, comp])

    pelvis_m = signals.pelvis_tz / (1000.0 if cfg.pelvis_tz_unit.lower() == 'mm' else 1.0)
    pelvis_on_force = np.interp(contact_force_time, signals.point_time_s, pelvis_m)
    com_disp_down = pelvis_on_force[0] - pelvis_on_force
    com_vel = np.interp(contact_force_time, signals.point_time_s, np.gradient(pelvis_m, signals.point_time_s))

    peak_vertical_force_n = float(np.max(total_force[:, AXIS_INDEX[cfg.vertical_axis]]))
    vertical_stiffness_kn_per_m = (peak_vertical_force_n / max(peak_com_disp_m, 1e-9)) / 1000.0 if peak_com_disp_m > 0 else float('nan')
    spring_correlation = float(np.corrcoef(total_force[:, AXIS_INDEX[cfg.vertical_axis]], com_disp_down)[0, 1]) if np.std(total_force[:, AXIS_INDEX[cfg.vertical_axis]]) > 1e-9 and np.std(com_disp_down) > 1e-9 else float('nan')

    braking_mask = contact_force_time <= peak_com_time_s
    if np.any(braking_mask):
        brake_force = total_force[braking_mask, AXIS_INDEX[cfg.vertical_axis]]
        brake_time = contact_force_time[braking_mask]
        peak_brake_time = float(brake_time[int(np.argmax(brake_force))])
        peak_braking_force_timing_pct = 100.0 * (peak_brake_time - contact_start_s) / max(contact_time_s, 1e-9)
    else:
        peak_braking_force_timing_pct = float('nan')

    power_w_per_kg = (total_force[:, AXIS_INDEX[cfg.vertical_axis]] / mass) * com_vel
    braking_work_j_per_kg = float(-safe_trapezoid(np.minimum(power_w_per_kg, 0.0), contact_force_time))
    propulsive_work_j_per_kg = float(safe_trapezoid(np.maximum(power_w_per_kg, 0.0), contact_force_time))

    normalized_kinematics: Dict[str, Dict[str, np.ndarray]] = {}
    normalized_moments: Dict[str, np.ndarray] = {}
    normalized_forces: Dict[str, np.ndarray] = {}
    side_map = {'L': {'Hip': 'L_Hip', 'Knee': 'L_Knee', 'Ankle': 'L_Ankle'}, 'R': {'Hip': 'R_Hip', 'Knee': 'R_Knee', 'Ankle': 'R_Ankle'}}

    sides_to_extract = ['L', 'R'] if signals.trial_type == TRIAL_DJ else active_sides
    for side in sides_to_extract:
        kin_side: Dict[str, np.ndarray] = {}
        for joint_name, metric_key in side_map[side].items():
            if metric_key in signals.angles:
                kin_side[joint_name] = interpolate_segment(signals.point_time_s, signals.angles[metric_key], contact_start_s, takeoff_s, cfg.phase_points)
            if metric_key in signals.moments:
                normalized_moments[f'{side}_{joint_name}'] = interpolate_segment(signals.point_time_s, signals.moments[metric_key], contact_start_s, takeoff_s, cfg.phase_points)
        normalized_kinematics[side] = kin_side
        force_xyz = np.stack([
            signals.forces[side][:, AXIS_INDEX[cfg.ap_axis]],
            signals.forces[side][:, AXIS_INDEX[cfg.ml_axis]],
            signals.forces[side][:, AXIS_INDEX[cfg.vertical_axis]],
        ], axis=1) / mass
        normalized_forces[side] = interpolate_segment(signals.force_time_s, force_xyz, contact_start_s, takeoff_s, cfg.phase_points)

    return TrialResult(
        trial_name=signals.trial_name,
        trial_type=signals.trial_type,
        source_path=signals.source_path,
        file_date=datetime.fromtimestamp(signals.source_path.stat().st_mtime),
        point_rate_hz=signals.point_rate_hz,
        force_rate_hz=signals.force_rate_hz,
        body_mass_kg=signals.body_mass_kg,
        contact_start_s=contact_start_s,
        takeoff_s=takeoff_s,
        contact_time_s=contact_time_s,
        jump_height_m=jump_height_m,
        rsi_m_per_s=rsi_m_per_s,
        peak_com_disp_m=peak_com_disp_m,
        peak_com_disp_time_pct=peak_com_disp_time_pct,
        vertical_stiffness_kn_per_m=vertical_stiffness_kn_per_m,
        spring_correlation=spring_correlation,
        peak_braking_force_timing_pct=peak_braking_force_timing_pct,
        braking_work_j_per_kg=braking_work_j_per_kg,
        propulsive_work_j_per_kg=propulsive_work_j_per_kg,
        contact_source='raw_csv',
        contact_key=contact_key,
        raw_force_rate_hz=signals.raw_force_rate_hz,
        raw_csv_path=signals.raw_csv_path,
        contact_windows=signals.raw_contacts,
        normalized_kinematics=normalized_kinematics,
        normalized_moments=normalized_moments,
        normalized_forces=normalized_forces,
        warnings=signals.warnings,
    )
