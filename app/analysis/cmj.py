"""Force-derived CMJ dynamics and sagittal joint strategy.

Conventions: upward COM motion positive; joint flexion/dorsiflexion positive;
internal moments conjugate to those angles; P = M * d(theta)/dt in radians.
Braking = minimum downward velocity to upward zero crossing (COM bottom).
Propulsion = COM bottom to take-off. Impulses are NET (Fz - body weight).
Work is integrated on the original time grid, with interpolated boundaries.
"""

import numpy as np
from scipy.integrate import cumulative_trapezoid
from scipy.signal import butter, find_peaks, sosfiltfilt
from scipy.optimize import brentq

from app.analysis.cmj_models import CMJResult, CMJSignals
from app.config import Config

JOINTS = ('Hip', 'Knee', 'Ankle')


def lowpass(values, time, cutoff):
    """Zero-lag filtering within finite runs only; missing samples stay missing."""
    values = np.asarray(values, dtype=float)
    if cutoff == 0:
        return values.copy()
    fs = 1 / np.median(np.diff(time))
    if not 0 < cutoff < fs / 2:
        raise ValueError(f'CMJ cutoff {cutoff:g} Hz must be below Nyquist ({fs/2:g} Hz), or zero')
    sos = butter(4, cutoff, fs=fs, output='sos')
    result = np.full_like(values, np.nan)
    edges = np.diff(np.r_[False, np.isfinite(values), False].astype(int))
    for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        if b - a > 15:
            result[a:b] = sosfiltfilt(sos, values[a:b])
    return result


def window(time, values, start, end):
    """Keep true phase boundaries; never extrapolate or bridge missing samples."""
    if len(time) < 2 or start < time[0] - 1e-9 or end > time[-1] + 1e-9 or end <= start:
        return np.array([]), np.array([])
    t = np.r_[start, time[(time > start) & (time < end)], end]
    y = np.interp(t, time, values)
    return t, y


def integral(time, values, start, end, sign=None):
    t, y = window(time, values, start, end)
    if len(t) < 2 or not np.isfinite(y).all():
        return float('nan')
    if sign:
        # Split zero crossings before clipping, so sign-specific work does not
        # integrate a triangle across the wrong side of zero.
        i = np.flatnonzero(y[:-1] * y[1:] < 0)
        zeros = t[i] - y[i] * (t[i+1] - t[i]) / (y[i+1] - y[i])
        grid = np.sort(np.r_[t, zeros])
        y = np.interp(grid, t, y)
        t = grid
        y = np.maximum(y, 0) if sign == 'positive' else np.minimum(y, 0)
    return float(np.trapezoid(y, t))


def first_run(mask, count, start=0):
    edges = np.diff(np.r_[False, np.asarray(mask, bool), False].astype(int))
    for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        a = max(a, start)
        if b - a >= count:
            return int(a)
    return None


def crossing(time, values, index, level):
    if index == 0 or values[index] == values[index-1]:
        return float(time[index])
    fraction = (level - values[index-1]) / (values[index] - values[index-1])
    return float(time[index-1] + np.clip(fraction, 0, 1) * (time[index] - time[index-1]))


def velocity_at(time, acceleration, velocity, stamp):
    """Evaluate integrated piecewise-linear acceleration within a sample.

Linear interpolation of velocity at a force threshold is inconsistent with
the trapezoidal impulse over that fractional sample, especially at take-off.
"""
    i = min(max(0, int(np.searchsorted(time, stamp, side='right')-1)), len(time)-2)
    elapsed = stamp-time[i]
    slope = (acceleration[i+1]-acceleration[i])/(time[i+1]-time[i])
    return float(velocity[i] + acceleration[i]*elapsed + .5*slope*elapsed**2)


def _peak(time, values, start, end, bottom, propulsion, negative=False):
    t, y = window(time, values, start, end)
    if len(t) < 2 or not np.isfinite(y).all():
        return (float('nan'),) * 3
    i = int(np.argmin(y) if negative else np.argmax(y))
    if (negative and y[i] >= 0) or (not negative and y[i] <= 0):
        return 0.0, float('nan'), float('nan')
    return float(y[i]), float((t[i]-bottom)*1000), float((t[i]-bottom)/propulsion*100)


def force_peak_times(time, force, start, takeoff, bw, cfg):
    """Up to two resolved GRF peaks across braking and propulsion, in time order.

    Always retain the overall maximum. A second peak must meet the existing
    prominence and separation thresholds; no smoothing or quality score.
    """
    t, y = window(time, force, start, takeoff)
    maximum = int(np.argmax(y))
    peaks, properties = find_peaks(y, prominence=cfg.cmj.waveform_prominence_bw*bw,
                                  distance=max(1, round(cfg.cmj.waveform_peak_distance_s/np.median(np.diff(time)))))
    # A flat maximum is one peak: use scipy's plateau midpoint rather than
    # counting its first sample and midpoint as two separate peaks.
    matching = peaks[y[peaks] == y[maximum]]
    if len(matching):
        maximum = int(matching[0])
    candidates = [(int(index), prominence) for index, prominence in zip(peaks, properties['prominences'])
                  if abs(t[index]-t[maximum]) >= cfg.cmj.waveform_peak_distance_s]
    chosen = [maximum]
    if candidates:
        chosen.append(max(candidates, key=lambda entry: entry[1])[0])
    return sorted(float(t[index]) for index in chosen)


def waveform_profile(time, force, bottom, takeoff, bw, cfg):
    t, y = window(time, force, bottom, takeoff)
    fs = 1 / np.median(np.diff(time))
    prominence = cfg.cmj.waveform_prominence_bw * bw
    distance = max(1, round(cfg.cmj.waveform_peak_distance_s * fs))
    peaks, _ = find_peaks(y, prominence=prominence, distance=distance)
    dips, _ = find_peaks(-y, prominence=prominence, distance=distance)
    # Explicitly retain a high force at COM bottom as a boundary peak; scipy
    # find_peaks excludes endpoints. Do not call a rising take-off edge a peak.
    if len(y) > 2 and y[0] > y[1] and y[0] - np.min(y[:(peaks[0]+1) if len(peaks) else len(y)]) >= prominence:
        if not len(peaks) or t[peaks[0]] - bottom >= cfg.cmj.waveform_peak_distance_s:
            peaks = np.r_[0, peaks]
    shape = {0: 'No resolved peak', 1: 'One resolved peak', 2: 'Two resolved peaks'}.get(len(peaks), 'Multiple resolved peaks')
    return {'description': shape, 'peak_times_s': t[peaks].tolist(),
            'dip_times_s': t[dips].tolist(), 'dip_forces_n': y[dips].tolist(),
            'dip_accelerations_m_s2': ((y[dips]-bw)/(bw/cfg.cmj.gravity)).tolist(),
            'prominence_n': prominence,
            'minimum_peak_distance_ms': cfg.cmj.waveform_peak_distance_s * 1000,
            'bottom_boundary_peak': bool(len(peaks) and peaks[0] == 0)}


def select_baseline(time, raw, cfg):
    """Find the last quiet window before pre-peak unweighting of first flight.

This keeps integration close to the jump instead of accumulating several
seconds of standing drift. The explicit override is useful for difficult
records. No quiet window means no valid force-derived CMJ result.
"""
    c = cfg.cmj
    if c.baseline_start_s is not None:
        return c.baseline_start_s
    dt = np.median(np.diff(time))
    count = max(2, round(c.flight_hold_s/dt))
    # Ignore unloaded recording starts; flight must follow a loaded interval.
    loaded = first_run(raw > 100, max(2, round(c.baseline_duration_s/dt)))
    if loaded is None:
        raise ValueError('No loaded quiet-standing interval for CMJ')
    flight = first_run(raw < cfg.threshold_n, count, loaded+round(c.baseline_duration_s/dt))
    if flight is None:
        raise ValueError('No sustained flight after loaded standing')
    f = np.asarray(raw, float).copy()  # event/QC source always remains unfiltered
    # Search the pre-flight maximum and its preceding unweighting trough.
    a = max(loaded, flight-round(3/dt))
    peak = a + int(np.argmax(f[a:flight]))
    if peak <= a:
        raise ValueError('No CMJ force rise before take-off')
    trough = a + int(np.argmin(f[a:peak]))
    standing_values = raw[loaded:trough]
    standing_values = standing_values[standing_values > 100]
    if not len(standing_values):
        raise ValueError('No standing interval before CMJ unweighting')
    reference = float(np.median(standing_values))
    size = round(c.baseline_duration_s/dt)
    for end in range(trough, loaded+size-1, -max(1, round(.01/dt))):
        sample = raw[end-size:end]
        mean = float(np.mean(sample))
        slope = float(np.polyfit(np.arange(size)*dt, sample, 1)[0])
        # A preparatory force plateau is not a new body weight. Keep the
        # local estimate within 1% of the preceding standing median and leave
        # 100 ms before a clear force departure; otherwise use an earlier window.
        guard = f[end:min(trough, end+round(.1/dt))]
        if (len(guard) >= round(.08/dt) and mean > 100 and abs(mean-reference) < .01*reference
                and np.max(np.abs(guard-mean)) < max(10, .025*mean, 3*np.std(sample))
                and np.std(sample, ddof=1)/mean <= c.baseline_max_cv
                and abs(slope)*c.baseline_duration_s <= c.baseline_max_cv*mean):
            return float(time[end-size])
    raise ValueError('No stable quiet-standing baseline before unweighting; inspect the record or set --cmj-baseline-start')


def process_cmj_trial(signals: CMJSignals, cfg: Config) -> CMJResult:
    c = cfg.cmj
    t = np.asarray(signals.force_time_s, dtype=float)
    integration_raw = np.asarray(signals.vertical_force_n, dtype=float)
    event_raw = np.asarray(signals.event_vertical_force_n if signals.event_vertical_force_n is not None else signals.vertical_force_n, dtype=float)
    if len(t) < 30 or integration_raw.shape != t.shape or not np.isfinite(t).all() or not np.isfinite(integration_raw).all():
        raise ValueError('CMJ requires a finite total vertical force record with at least 30 samples')
    dt = np.median(np.diff(t))
    if dt <= 0 or not np.allclose(np.diff(t), dt, rtol=1e-4, atol=1e-8):
        raise ValueError('CMJ force timestamps must be strictly increasing and uniformly sampled')
    if c.baseline_duration_s < .2 or c.gravity <= 0 or cfg.threshold_n <= 0:
        raise ValueError('CMJ needs a baseline of at least 0.2 s and positive gravity/force threshold')
    event_t = t if signals.event_time_s is None else np.asarray(signals.event_time_s, float)
    if (event_t.shape != event_raw.shape or len(event_t) < 30
            or not np.isfinite(event_raw).all() or not np.isfinite(event_t).all()):
        raise ValueError('CMJ event force requires finite samples and explicit matching timestamps')
    event_dt = float(np.median(np.diff(event_t)))
    if event_dt <= 0 or not np.allclose(np.diff(event_t), event_dt, rtol=1e-4, atol=1e-8):
        raise ValueError('CMJ event timestamps must be uniformly sampled and increasing')
    baseline_start = select_baseline(event_t, event_raw, cfg)
    baseline_end = baseline_start + c.baseline_duration_s
    if baseline_start < t[0] or baseline_end >= t[-1]:
        raise ValueError('Quiet-standing baseline lies outside the CMJ force record')
    event_baseline = (event_t >= baseline_start) & (event_t < baseline_end)
    baseline = (t >= baseline_start) & (t < baseline_end)
    event_mean = float(np.mean(event_raw[event_baseline]))
    mean_force = float(np.mean(integration_raw[baseline]))
    sd = float(np.std(event_raw[event_baseline], ddof=1))
    if mean_force < 100 or sd / event_mean > c.baseline_max_cv:
        raise ValueError('CMJ baseline is not quiet loaded standing; include 0.5 s before movement or adjust baseline settings')
    slope = float(np.polyfit(event_t[event_baseline] - event_t[event_baseline][0], event_raw[event_baseline], 1)[0])
    if abs(slope) * c.baseline_duration_s > c.baseline_max_cv * mean_force:
        raise ValueError('CMJ baseline has a force trend; select a stable quiet-standing interval')
    warnings = list(signals.warnings)
    mass = mean_force / c.gravity
    bw = mean_force
    if signals.metadata_mass_kg and abs(mass - signals.metadata_mass_kg) / mass > .05:
        raise ValueError(f'Quiet-standing mass {mass:.2f} kg differs >5% from C3D mass {signals.metadata_mass_kg:.2f} kg. Verify full support, calibration, body mass and plate selection.')
    offset = 0.0
    event_offset = 0.0
    if cfg.body_mass_override is not None:
        if not np.isfinite(cfg.body_mass_override) or cfg.body_mass_override <= 0:
            raise ValueError('--body-mass must be finite and positive')
        if abs(mass - cfg.body_mass_override) / mass > .05:
            raise ValueError('Body-mass override differs >5% from quiet-standing load; verify plate selection/calibration')
        mass = cfg.body_mass_override
        bw = mass * c.gravity
        offset = mean_force - bw
        event_offset = event_mean - bw
        warnings.append(f'Body-mass override used; constant force offset {offset:.2f} N removed using quiet standing.')
    f = lowpass(integration_raw - offset, t, c.force_filter_hz)
    event_force = lowpass(event_raw, event_t, 0)
    threshold = max(c.onset_sd * sd, c.onset_bw_fraction * bw, 10.0)
    start_search = int(np.searchsorted(t, baseline_end))
    onset_mask = np.abs(event_force - event_mean) > threshold
    event_onset_i = first_run(onset_mask, max(1, round(c.onset_hold_s/event_dt)), int(np.searchsorted(event_t, baseline_end)))
    if event_onset_i is None:
        raise ValueError('No sustained CMJ movement onset after quiet standing')
    # Threshold onset defines time-to-take-off. Integration starts from quiet
    # standing, retaining subthreshold acceleration before the onset event.
    onset = float(event_t[event_onset_i])
    event_takeoff_i = first_run(event_force - event_offset < cfg.threshold_n, max(2, round(c.flight_hold_s/event_dt)), event_onset_i + 1)
    if event_takeoff_i is None:
        raise ValueError('No sustained flight after CMJ onset; trial may be truncated')
    takeoff = crossing(event_t, event_force-event_offset, event_takeoff_i, cfg.threshold_n)
    if takeoff > t[-1] or onset < t[0]:
        raise ValueError('COM force recording must cover quiet standing, movement onset and raw-force take-off')
    onset_i = int(np.searchsorted(t, onset))
    takeoff_i = int(np.searchsorted(t, takeoff))
    acceleration = (f-bw) / mass
    v = np.zeros_like(t)
    displacement = np.zeros_like(t)
    v[start_search:] = cumulative_trapezoid(acceleration[start_search:], t[start_search:], initial=0)
    displacement[start_search:] = cumulative_trapezoid(v[start_search:], t[start_search:], initial=0)
    minimum_i = onset_i + int(np.argmin(v[onset_i:takeoff_i]))
    if v[minimum_i] >= -.05:
        raise ValueError('No clear downward countermovement (minimum COM velocity must be below -0.05 m/s)')
    zero = np.flatnonzero((v[minimum_i:takeoff_i-1] < 0) & (v[minimum_i+1:takeoff_i] >= 0))
    if not len(zero):
        raise ValueError('No COM bottom/upward velocity zero crossing before take-off')
    bottom_i = minimum_i + int(zero[0]) + 1
    bottom = float(brentq(lambda stamp: velocity_at(t, acceleration, v, stamp), t[bottom_i-1], t[bottom_i]))
    braking_start = float(t[minimum_i])
    for i in (minimum_i, minimum_i+1):
        if i > 0 and acceleration[i-1] < 0 <= acceleration[i]:
            braking_start = crossing(t, acceleration, i, 0)
            break
    duration = takeoff - bottom
    if not onset < braking_start < bottom < takeoff or duration < .03:
        raise ValueError('Invalid CMJ phase order or propulsion shorter than 30 ms')
    if np.min(v[bottom_i:takeoff_i]) < -.02:
        raise ValueError('Multiple COM direction reversals during propulsion; inspect the trial')
    takeoff_velocity = velocity_at(t, acceleration, v, takeoff)
    depth = -float(np.interp(bottom, t, displacement))
    if takeoff_velocity <= 0 or depth <= .005:
        raise ValueError('CMJ requires positive take-off velocity and countermovement depth >5 mm')
    landing_i = first_run(event_force-event_offset >= cfg.threshold_n, max(2, round(.02/event_dt)), event_takeoff_i+round(c.flight_hold_s/event_dt))
    events = {'baseline_start': baseline_start, 'baseline_end': baseline_end,
              'onset': onset, 'braking_start': braking_start, 'com_bottom': bottom, 'takeoff': takeoff}
    if landing_i is not None:
        events['landing'] = crossing(event_t, event_force-event_offset, landing_i, cfg.threshold_n)
        second = first_run(event_force-event_offset < cfg.threshold_n, max(2, round(c.flight_hold_s/event_dt)), landing_i+round(.1/event_dt))
        if second is not None:
            warnings.append('Selected plates unload again after return to contact; this file reports the first take-off only. Walking off the plates can also cause unloading.')
    else:
        warnings.append('Landing was not detected on the selected plates; take-off velocity height remains available.')
    phase_t, phase_f = window(t, f, onset, takeoff)
    peak_i = int(np.argmax(phase_f))
    metrics = {
        'body_mass_kg': mass, 'quiet_standing_force_n': mean_force, 'baseline_sd_n': sd,
        'event_baseline_force_n': event_mean,
        'force_offset_n': offset, 'onset_threshold_n': threshold,
        'jump_height_m': takeoff_velocity**2 / (2*c.gravity),
        'takeoff_velocity_m_s': takeoff_velocity, 'time_to_takeoff_s': takeoff-onset,
        'rsi_mod_m_s': takeoff_velocity**2/(2*c.gravity)/(takeoff-onset),
        'countermovement_depth_m': depth,
        'propulsive_impulse_ns': integral(t, f-bw, bottom, takeoff),
        'braking_impulse_ns': integral(t, f-bw, braking_start, bottom),
        'braking_time_s': bottom-braking_start, 'propulsion_time_s': duration,
        'peak_downward_velocity_m_s': velocity_at(t, acceleration, v, braking_start),
        'peak_vertical_force_n': float(phase_f[peak_i]),
        'peak_vertical_force_n_kg': float(phase_f[peak_i]/mass),
        'peak_force_timing_ms': float((phase_t[peak_i]-bottom)*1000),
    }
    for a, b in [(0, 25), (25, 50), (50, 75), (75, 100)]:
        dv = (velocity_at(t, acceleration, v, bottom+duration*b/100)
              - velocity_at(t, acceleration, v, bottom+duration*a/100))
        metrics[f'velocity_gain_{a}_{b}_m_s'] = dv
        metrics[f'velocity_gain_{a}_{b}_pct'] = dv/takeoff_velocity*100

    pt = np.asarray(signals.point_time_s, dtype=float)
    angles, omega, moments, powers = {}, {}, {}, {}
    if len(pt) >= 3:
        if (not np.isfinite(pt).all() or not np.all(np.diff(pt) > 0)
                or not np.allclose(np.diff(pt), np.median(np.diff(pt)), rtol=1e-4, atol=1e-8)):
            raise ValueError('CMJ point timestamps must be finite, strictly increasing and uniformly sampled')
        for key, values in signals.angles_deg.items():
            if np.asarray(values).shape != pt.shape:
                warnings.append(f'{key}: angle length does not match point samples')
                continue
            # Unwrap only contiguous valid runs to avoid ±180-degree jumps.
            values = np.asarray(values, float).copy()
            edges = np.diff(np.r_[False, np.isfinite(values), False].astype(int))
            for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
                values[a:b] = np.rad2deg(np.unwrap(np.deg2rad(values[a:b])))
            angles[key] = lowpass(values, pt, c.kinematic_filter_hz)
            omega[key] = np.gradient(angles[key], pt)
        for key, values in signals.moments_nm_per_kg.items():
            if np.asarray(values).shape == pt.shape:
                moments[key] = lowpass(values, pt, c.kinematic_filter_hz)
                if key in omega:
                    powers[key] = moments[key] * np.deg2rad(omega[key])
    bottom_position = {'COM_depth_m': depth}
    for key, values in angles.items():
        bottom_position[key] = float(np.interp(bottom, pt, values)) if pt[0] <= bottom <= pt[-1] else float('nan')
    joint_metrics = {}
    for key, power in powers.items():
        entry = {}
        for phase, start, end, negative in [('braking', braking_start, bottom, True), ('propulsion', bottom, takeoff, False)]:
            sign = 'negative' if negative else 'positive'
            entry[f'{phase}_{sign}_work_j_kg'] = integral(pt, power, start, end, sign)
            peak, ms, pct = _peak(pt, power, start, end, bottom, duration, negative)
            entry[f'peak_{sign}_power_w_kg'] = peak
            entry[f'peak_{sign}_timing_ms'] = ms
            entry[f'peak_{sign}_timing_pct'] = pct
        entry['movement_negative_work_j_kg'] = integral(pt, power, onset, takeoff, 'negative')
        entry['movement_positive_work_j_kg'] = integral(pt, power, onset, takeoff, 'positive')
        joint_metrics[key] = entry
    # Bilateral joint work = sum of signed work per limb, NOT signed work of
    # the summed power (which would cancel simultaneous generation/absorption).
    for joint in JOINTS:
        left, right = f'L_{joint}', f'R_{joint}'
        if left in powers and right in powers:
            powers[joint] = powers[left] + powers[right]
            entry = {key: joint_metrics[left][key] + joint_metrics[right][key]
                     for key in joint_metrics[left] if 'work' in key}
            for sign, start, end in [('negative', braking_start, bottom), ('positive', bottom, takeoff)]:
                peak, ms, pct = _peak(pt, powers[joint], start, end, bottom, duration, sign == 'negative')
                entry.update({f'peak_{sign}_power_w_kg': peak, f'peak_{sign}_timing_ms': ms,
                              f'peak_{sign}_timing_pct': pct})
            joint_metrics[joint] = entry
    for scope in ('', 'L_', 'R_'):
        keys = [scope+j for j in JOINTS]
        works = [joint_metrics.get(k, {}).get('propulsion_positive_work_j_kg', np.nan) for k in keys]
        total = float(np.sum(works))
        for key, work in zip(keys, works):
            if key in joint_metrics:
                joint_metrics[key]['positive_work_contribution_pct'] = work/total*100 if np.isfinite(total) and total > 0 else float('nan')
    sequencing = {}
    for scope in ('', 'L_', 'R_'):
        sequence = {}
        for joint in JOINTS:
            entry = joint_metrics.get(scope+joint, {})
            sequence[f'{joint}_peak_ms'] = entry.get('peak_positive_timing_ms', float('nan'))
            sequence[f'{joint}_peak_pct'] = entry.get('peak_positive_timing_pct', float('nan'))
        for first, second in [('Hip', 'Knee'), ('Knee', 'Ankle'), ('Hip', 'Ankle')]:
            sequence[f'{first}_to_{second}_ms'] = sequence[f'{second}_peak_ms'] - sequence[f'{first}_peak_ms']
            sequence[f'{first}_to_{second}_pct'] = sequence[f'{second}_peak_pct'] - sequence[f'{first}_peak_pct']
        sequencing[scope or 'bilateral'] = sequence
    for key, velocity in omega.items():
        peak, ms, pct = _peak(pt, -velocity, bottom, takeoff, bottom, duration)
        sequencing[key+'_extension'] = {'peak_deg_s': peak, 'timing_ms': ms, 'timing_pct': pct}
    for key, entry in joint_metrics.items():
        if not np.isfinite(entry['braking_negative_work_j_kg']) or not np.isfinite(entry['propulsion_positive_work_j_kg']):
            warnings.append(f'{key}: incomplete phase coverage or missing samples; affected work/peak values unavailable (no gap filling)')
    provenance = dict(signals.provenance)
    provenance['force_source'] = signals.force_source
    provenance['processing'] = (f'Additional force filtering: {c.force_filter_hz:g} Hz (0 = disabled); '
                                f'angles and moments: {c.kinematic_filter_hz:g} Hz (0 = disabled). '
                                'Finite runs only; no missing-data interpolation. Raw force defines take-off/landing.')
    provenance['mass'] = f'COM mass {mass:.3f} kg from '+('override with baseline offset' if cfg.body_mass_override is not None else 'quiet-standing Fz/g')
    provenance['baseline'] = (f'{baseline_start:.4f}–{baseline_end:.4f} s; '
                              + ('manual' if c.baseline_start_s is not None else 'last stable interval before pre-peak unweighting')
                              + f'; CV limit {c.baseline_max_cv*100:g}%, force-trend limit {c.baseline_max_cv*100:g}% BW/window')
    if signals.metadata_mass_kg:
        provenance['joint_normalization_mass'] = f'C3D/override mass: {signals.metadata_mass_kg:.3f} kg; pre-normalized exports retain their export normalization'
    provenance['force_rate_hz'] = f'{1/dt:g}'
    provenance['event_rate_hz'] = f'{1/event_dt:g}'
    provenance['point_rate_hz'] = f'{1/np.median(np.diff(pt)):g}' if len(pt) >= 2 else 'unavailable'
    side_curves = {}
    if signals.side_vertical_force_n:
        # Split the total baseline correction equally: no per-leg body-weight
        # estimate is available. The plotted side forces sum to combined GRF.
        for side, force in signals.side_vertical_force_n.items():
            values = np.asarray(force, float)
            if values.shape != integration_raw.shape or not np.isfinite(values).all():
                raise ValueError(f'{side} force must be finite on the COM force grid')
            side_curves[f'force_{side.lower()}_n'] = lowpass(values-offset/len(signals.side_vertical_force_n), t, c.force_filter_hz)
    waveform = waveform_profile(t, f, bottom, takeoff, bw, cfg)
    waveform['braking_propulsion_peak_times_s'] = force_peak_times(t, f, braking_start, takeoff, bw, cfg)
    return CMJResult(signals.trial_name, signals.source_path, events, metrics, t,
                     {**side_curves, 'force_n': f, 'raw_force_n': integration_raw-offset,
                      'event_force_n': np.interp(t, event_t, event_force-event_offset),
                      'acceleration_m_s2': acceleration,
                      'velocity_m_s': v, 'displacement_m': displacement}, pt, angles, omega,
                     moments, powers, joint_metrics, bottom_position, sequencing,
                     waveform, provenance, list(dict.fromkeys(warnings)),
                     event_t, event_force-event_offset)
