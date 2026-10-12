"""CMJ C3D adapter using the shared Nexus labels and force CSV reader.

CSV Frame/Sub Frame timestamps are aligned with the C3D first_frame, so a
cropped C3D does not shift the joint sequence relative to the force record.
No inverse dynamics are fabricated when exported joint moments are absent.
"""

from pathlib import Path
import ezc3d
import numpy as np

from app.analysis.cmj_models import CMJSignals
from app.config import AXIS_INDEX, Config
from app.c3d.forceplate import (
    _fill_group_labels, _find_nexus_csv_header, _parse_float_cell, _raw_csv_path_for_c3d,
    _read_csv_rows, get_c3d_analog_force, read_raw_force_csv,
)
from app.c3d.labels import find_matching_label
from app.c3d.reader import (
    get_body_mass_kg, get_c3d_point_series, get_c3d_rotation_series,
    infer_euler_from_transforms,
)


def moment_scale(unit: str, mass_kg: float | None) -> float:
    """Convert explicitly declared exported units to Nm/kg (no magnitude guess)."""
    scales = {'Nmm/kg': .001, 'Nm/kg': 1.0, 'Nmm': .001, 'Nm': 1.0}
    if unit not in scales:
        raise ValueError(f'Unsupported CMJ moment unit: {unit}')
    if '/kg' not in unit:
        if mass_kg is None or not np.isfinite(mass_kg) or mass_kg <= 0:
            raise ValueError('Absolute joint moments require C3D body mass or --body-mass')
        return scales[unit] / mass_kg
    return scales[unit]


def csv_point_offset(path: Path, fs: float, point_rate: float, first_frame: int,
                     expected_samples: int) -> float:
    rows = _read_csv_rows(path)
    header = _find_nexus_csv_header(rows)
    stamps = []
    for row in rows[header + 1:]:
        if len(row) < 2:
            continue
        frame, sub = _parse_float_cell(row[0]), _parse_float_cell(row[1])
        if frame is not None and sub is not None:
            stamps.append((frame - 1.0) / point_rate + sub / fs)
    stamps = np.asarray(stamps)
    if len(stamps) != expected_samples or not np.isfinite(stamps).all():
        raise ValueError('CMJ CSV timestamps do not match force samples')
    if not np.allclose(np.diff(stamps), 1.0 / fs, atol=1e-7, rtol=1e-5):
        raise ValueError('CMJ CSV Frame/Sub Frame contains gaps or incompatible sample rates')
    return first_frame / point_rate - float(stamps[0])


def validate_csv_force_units(path, cfg):
    """The shared DJ parser assumes Newtons; CMJ validates its integration units."""
    import re
    rows = _read_csv_rows(path)
    header = _find_nexus_csv_header(rows)
    groups = _fill_group_labels(rows[header-1], len(rows[header]))
    units = rows[header+1]
    for col, channel in enumerate(rows[header]):
        plate = re.match(r'^\s*(\d+)\s*-\s*Force\s*$', groups[col], re.IGNORECASE)
        if plate and int(plate.group(1)) in {cfg.plate_left, cfg.plate_right} and channel.strip() == 'F'+cfg.vertical_axis:
            if col >= len(units) or units[col].strip().lower() != 'n':
                raise ValueError('CMJ raw CSV vertical forces must have declared units N')


def _point(c3d, label):
    values = get_c3d_point_series(c3d, label)[:, 0].copy()
    idx = list(c3d['parameters']['POINT']['LABELS']['value']).index(label)
    residual = np.asarray(c3d['data']['points'])[3, idx, :]
    values[residual < 0] = np.nan
    return values


def _relative_angle(parent, child, signs):
    values = np.full(len(parent), np.nan)
    valid = np.isfinite(parent).all(axis=(1, 2)) & np.isfinite(child).all(axis=(1, 2))
    for i in np.flatnonzero(valid):
        try:
            values[i] = infer_euler_from_transforms(parent[i:i+1], child[i:i+1], 'XYZ', signs)[0, 0]
        except (ValueError, np.linalg.LinAlgError):
            pass
    return values


def read_cmj_trial(path: Path, cfg: Config) -> CMJSignals:
    c3d = ezc3d.c3d(str(path))
    rate = float(c3d['header']['points']['frame_rate'])
    n = c3d['data']['points'].shape[2]
    point_time = np.arange(n) / rate if n else np.empty(0)
    warnings = []
    provenance = {}
    vertical = AXIS_INDEX[cfg.vertical_axis]
    try:
        mass = get_body_mass_kg(c3d, path, cfg.body_mass_override)
    except RuntimeError:
        mass = None  # Whole-body mass can be measured during quiet standing.
    if cfg.plate_left == cfg.plate_right:
        raise ValueError('CMJ requires two distinct selected force plates; do not double-count one plate')
    csv_path = _raw_csv_path_for_c3d(path, cfg)
    source = cfg.cmj.force_source
    use_csv = source == 'csv' or (source == 'auto' and csv_path.is_file())
    event_total = None
    event_time = None
    if use_csv:
        validate_csv_force_units(csv_path, cfg)
        fs, time, forces = read_raw_force_csv(csv_path, cfg)
        csv_offset = csv_point_offset(csv_path, fs, rate,
                                      c3d['header']['points']['first_frame'], len(time))
        point_time += csv_offset
        event_time = time
        source_text = str(csv_path)
        provenance['synchronization'] = 'CSV Frame/Sub Frame aligned to C3D first_frame; no guessed offset'
        event_total = sum(force[:, vertical] * (-1 if np.nanpercentile(-force[:, vertical], 99.5) > np.nanpercentile(force[:, vertical], 99.5) else 1) for force in forces.values())
    else:
        if source not in {'auto', 'c3d'}:
            raise ValueError(f'Unknown CMJ force source: {source}')
        fs = float(c3d['header']['analogs']['frame_rate'])
        forces = {s: get_c3d_analog_force(c3d, p, cfg.force_signs)
                  for s, p in [('L', cfg.plate_left), ('R', cfg.plate_right)]}
        analog_labels = list(c3d['parameters']['ANALOG']['LABELS']['value'])
        units = list(c3d['parameters']['ANALOG'].get('UNITS', {}).get('value', []))
        for plate in (cfg.plate_left, cfg.plate_right):
            index = analog_labels.index(f'Force.F{cfg.vertical_axis}{plate}')
            if index >= len(units) or units[index].strip().lower() != 'n':
                raise ValueError('CMJ analog vertical force must have declared units N; use a Newton CSV export')
        time = np.arange(len(forces['L'])) / fs
        source_text = f'{path} (C3D analogs)'
        provenance['synchronization'] = 'C3D point and analog samples share recording start'
        warnings.append('Using C3D analog force. Record must include quiet standing; upstream filtering is unknown.')
    # The C3D analog force is the filtered Nexus signal used for COM dynamics.
    # A matching CSV is retained separately for event detection and QC.
    c3d_fs = fs if source == 'csv' else float(c3d['header']['analogs']['frame_rate'])
    c3d_forces = forces if source == 'csv' else {
        s: get_c3d_analog_force(c3d, p, cfg.force_signs)
        for s, p in [('L', cfg.plate_left), ('R', cfg.plate_right)]}
    if source != 'csv':
        analog_labels = list(c3d['parameters']['ANALOG']['LABELS']['value'])
        units = list(c3d['parameters']['ANALOG'].get('UNITS', {}).get('value', []))
        for plate in (cfg.plate_left, cfg.plate_right):
            index = analog_labels.index(f'Force.F{cfg.vertical_axis}{plate}')
            if index >= len(units) or units[index].strip().lower() != 'n':
                raise ValueError('CMJ C3D vertical forces must have declared units N')
    c3d_total = sum(force[:, vertical] * (-1 if np.nanpercentile(-force[:, vertical], 99.5) > np.nanpercentile(force[:, vertical], 99.5) else 1) for force in c3d_forces.values())
    c3d_start = csv_offset if use_csv else 0.0
    c3d_time = c3d_start + np.arange(len(c3d_total)) / c3d_fs
    if event_total is not None:
        provenance['force_source'] = f'COM dynamics: {path} C3D analogs (Nexus-filtered); events/QC: {csv_path} raw CSV'
    else:
        event_total = c3d_total.copy()
        event_time = c3d_time.copy()
        provenance['force_source'] = f'{path} C3D analogs (Nexus-filtered; no raw CSV event signal)'
    if len(c3d_forces['L']) != len(c3d_forces['R']):
        raise ValueError('CMJ left/right forces must share the same sample grid')
    total = np.zeros(len(c3d_total))
    side_forces = {}
    for side, force in c3d_forces.items():
        z = force[:, vertical].copy()
        if not np.isfinite(z).all():
            raise ValueError(f'{side} vertical force contains missing samples')
        # Orient each plate once, never abs(sample), which would rectify noise.
        orientation = -1 if np.percentile(-z, 99.5) > np.percentile(z, 99.5) else 1
        total += orientation * z
        side_forces[side] = orientation * z
        provenance[f'force_{side}'] = f'plate {cfg.plate_left if side == "L" else cfg.plate_right}; orientation multiplier {orientation:g} after configured signs'

    if source == 'csv':
        total, c3d_time = event_total.copy(), event_time.copy()
        provenance['force_source'] = f'COM dynamics and events: {csv_path} raw CSV (explicit source selection)'
    source_text = provenance['force_source']
    point_labels = list(c3d['parameters']['POINT'].get('LABELS', {}).get('value', []))
    rot_labels = list(c3d['parameters'].get('ROTATION', {}).get('LABELS', {}).get('value', []))
    angles, moments = {}, {}
    meta_unit = c3d['parameters']['POINT'].get('MOMENT_UNITS', {}).get('value', ['unspecified'])[0]
    provenance['moments'] = (f'Export profile: {cfg.cmj.moment_unit}; POINT:MOMENT_UNITS={meta_unit}; '
                             f'hip/knee/ankle sign multipliers={cfg.cmj.moment_signs}. '
                             'Multipliers convert exported moments to internal flexion/dorsiflexion-positive moments. '
                             'Default -1 converts the Nexus external-moment convention; verify custom exports.')
    angle_unit = c3d['parameters']['POINT'].get('ANGLE_UNITS', {}).get('value', ['deg'])[0]
    if angle_unit not in {'deg', 'degrees'}:
        raise ValueError(f'Unsupported CMJ angle units: {angle_unit}')
    for side, word in [('L', 'Left'), ('R', 'Right')]:
        for j, joint in enumerate(('Hip', 'Knee', 'Ankle')):
            key = f'{side}_{joint}'
            for quantity, target in [('Angles', angles), ('Moment', moments)]:
                candidates = [f'{side}{joint}{quantity}', f'{word}{joint}{quantity}',
                              f'{joint}{quantity}_{side}', f'{joint}{quantity}{word}']
                hit = find_matching_label(point_labels, candidates)
                if hit:
                    values = _point(c3d, hit)
                    if np.isfinite(values).any():
                        if quantity == 'Moment':
                            try:
                                values *= moment_scale(cfg.cmj.moment_unit, mass) * cfg.cmj.moment_signs[j]
                            except ValueError as exc:
                                warnings.append(str(exc))
                                continue
                        target[key] = values
                        provenance[f'{key}_{quantity}'] = f'POINT:{hit}, sagittal component X'
            if key not in angles:
                segments = {'Hip': ('pelvis', f'{side.lower()}_thigh', 'NPP'),
                            'Knee': (f'{side.lower()}_thigh', f'{side.lower()}_shank', 'PPP'),
                            'Ankle': (f'{side.lower()}_shank', f'{side.lower()}_foot', 'NPP')}
                parent, child, signs = segments[joint]
                ph = find_matching_label(rot_labels, [f'{parent}_4X4'])
                ch = find_matching_label(rot_labels, [f'{child}_4X4'])
                if ph and ch:
                    angles[key] = _relative_angle(get_c3d_rotation_series(c3d, ph),
                                                   get_c3d_rotation_series(c3d, ch), signs)
                    provenance[f'{key}_Angles'] = f'ROTATION:{ph} -> {ch}; intrinsic XYZ, sagittal X, {signs}'
            if key not in angles or key not in moments:
                warnings.append(f'{key}: joint power/work unavailable unless both angle and moment are present')

    for key, candidates in [('Thorax', ['ThoraxAngles', 'LThoraxAngles', 'RThoraxAngles', 'TrunkAngles']),
                            ('TrunkRelativePelvis', ['SpineAngles', 'LSpineAngles', 'RSpineAngles'])]:
        for candidate in candidates:
            hit = find_matching_label(point_labels, [candidate])
            if hit and np.isfinite(_point(c3d, hit)).any():
                angles[key] = _point(c3d, hit)
                provenance[key] = f'POINT:{hit}, sagittal X; export forward-flexion convention'
                break
    if 'Thorax' not in angles:
        thorax = find_matching_label(rot_labels, ['thorax_4X4', 'torso_4X4'])
        pelvis = find_matching_label(rot_labels, ['pelvis_4X4', 'pelvis_shifted_4X4'])
        if thorax:
            ap = AXIS_INDEX[cfg.cmj.forward_axis]
            if ap == vertical:
                raise ValueError('CMJ forward axis must differ from vertical axis')
            def inclination(label):
                tf = get_c3d_rotation_series(c3d, label)
                angle = np.rad2deg(np.arctan2(cfg.cmj.forward_sign * tf[:, ap, 2], tf[:, vertical, 2]))
                norm = np.linalg.norm(tf[:, :3, 2], axis=1)
                angle[(norm < .9) | (norm > 1.1) | ~np.isfinite(tf).all(axis=(1, 2))] = np.nan
                return angle
            angles['Thorax'] = inclination(thorax)
            provenance['Thorax'] = f'ROTATION:{thorax}, local z projected onto lab {cfg.cmj.forward_sign:+g}{cfg.cmj.forward_axis}/{cfg.vertical_axis}; verify forward axis'
            warnings.append('Thorax inclination uses a configured laboratory sagittal projection; verify facing direction.')
            if pelvis and 'TrunkRelativePelvis' not in angles:
                angles['TrunkRelativePelvis'] = angles['Thorax'] - inclination(pelvis)
                provenance['TrunkRelativePelvis'] = 'Difference of projected thorax and pelvis inclinations (not a 3D spine angle)'
    if 'Thorax' not in angles:
        warnings.append('Thorax signal missing: trunk position and timing are unavailable')
    provenance['force_rate_hz'] = str(c3d_fs)
    provenance['kinematics_source'] = str(path)
    return CMJSignals(path.stem, path, c3d_time, total, point_time, angles, moments,
                      mass, source_text, provenance, warnings, event_total, event_time, side_forces)


def read_cmj_csv(path: Path, cfg: Config) -> CMJSignals:
    """Standalone force-only CMJ, without requiring Theia or a C3D file."""
    if cfg.plate_left == cfg.plate_right:
        raise ValueError('Select two distinct CMJ force plates')
    validate_csv_force_units(path, cfg)
    fs, time, forces = read_raw_force_csv(path, cfg)
    rows = _read_csv_rows(path)
    header = _find_nexus_csv_header(rows)
    frames = [(float(row[0]), float(row[1])) for row in rows[header+1:]
              if len(row) >= 2 and _parse_float_cell(row[0]) is not None
              and _parse_float_cell(row[1]) is not None]
    frame, subframe = np.asarray(frames, float).T
    samples_per_frame = int(np.max(subframe))+1
    sample_index = frame*samples_per_frame+subframe
    if len(sample_index) != len(time) or not np.allclose(np.diff(sample_index), 1):
        raise ValueError('Standalone CMJ CSV Frame/Sub Frame contains gaps or repeated samples')
    vertical = AXIS_INDEX[cfg.vertical_axis]
    total = sum(force[:, vertical] for force in forces.values())
    source = f'{path} raw CSV'
    return CMJSignals(path.stem, path, time, total, np.empty(0),
                      metadata_mass_kg=cfg.body_mass_override, force_source=source,
                      provenance={'force_source': source, 'force_rate_hz': str(fs),
                                  'synchronization': 'Single CSV clock; force-only recording'},
                      event_vertical_force_n=total.copy(), event_time_s=time.copy(),
                      side_vertical_force_n={side: force[:, vertical].copy() for side, force in forces.items()})
