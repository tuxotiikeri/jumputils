"""C3D discovery and conversion into protocol-independent trial signals."""

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import ezc3d
import numpy as np
from scipy.spatial.transform import Rotation as R

from app.config import Config
from app.models import TrialSignals
from app.protocols.common import classify_trial
from app.c3d.events import read_raw_contacts_for_trial
from app.c3d.forceplate import get_c3d_analog_force
from app.c3d.labels import find_matching_label, normalize_label


def scan_trial_files(folder: Path, recursive: bool = False) -> List[Path]:
    files = folder.rglob('*.c3d') if recursive else folder.glob('*.c3d')
    return sorted([p for p in files if classify_trial(p.stem) is not None])

def get_value_or_default(container: Dict[str, Any], keys: Sequence[str], default: float) -> float:
    for key in keys:
        if key in container:
            val = container[key]
            if isinstance(val, dict) and 'value' in val:
                arr = np.asarray(val['value'], dtype=float).ravel()
                if arr.size:
                    return float(arr[0])
    return float(default)

def get_body_mass_kg(c3d_obj: Dict[str, Any], path: Path, override: Optional[float] = None) -> float:
    """Read body mass from common Nexus/Theia C3D parameter locations.

    GRF must be normalized from N to N/kg using body mass. These files normally
    store the value as PROCESSING:Bodymass. If missing, fail fast unless the
    user supplied --body-mass.
    """
    if override is not None and np.isfinite(override) and override > 0:
        return float(override)

    candidates = [
        ('PROCESSING', 'Bodymass'),
        ('PROCESSING', 'BODYMASS'),
        ('PROCESSING', 'BodyMass'),
        ('SUBJECTS', 'MASS'),
        ('SUBJECTS', 'Mass'),
        ('SUBJECT', 'MASS'),
        ('SUBJECT', 'Mass'),
        ('POINT', 'BODYMASS'),
    ]
    for group, key in candidates:
        try:
            val = c3d_obj['parameters'][group][key]['value']
            arr = np.asarray(val, dtype=float).ravel()
            if arr.size and np.isfinite(arr[0]) and arr[0] > 0:
                return float(arr[0])
        except Exception:
            pass

    # Last-resort generic scan for a parameter that looks like body mass.
    for group_name, group in c3d_obj.get('parameters', {}).items():
        if not isinstance(group, dict):
            continue
        for key, val in group.items():
            if not isinstance(val, dict) or 'value' not in val:
                continue
            nk = normalize_label(key)
            if nk in {'bodymass', 'mass'} or 'bodymass' in nk:
                try:
                    arr = np.asarray(val['value'], dtype=float).ravel()
                    if arr.size and np.isfinite(arr[0]) and arr[0] > 0:
                        return float(arr[0])
                except Exception:
                    pass

    raise RuntimeError(
        f'Body mass not found in {path.name}. GRF cannot be reported in N/kg. '
        'Expected e.g. PROCESSING:Bodymass. Supply --body-mass <kg> if needed.'
    )

def get_c3d_point_series(c3d_obj: Dict[str, Any], label: str) -> np.ndarray:
    labels = list(c3d_obj['parameters']['POINT']['LABELS']['value'])
    idx = labels.index(label)
    points = np.asarray(c3d_obj['data']['points'], dtype=float)
    return points[0:3, idx, :].T

def get_c3d_rotation_series(c3d_obj: Dict[str, Any], label: str) -> np.ndarray:
    labels = list(c3d_obj['parameters']['ROTATION']['LABELS']['value'])
    idx = labels.index(label)
    rots = np.asarray(c3d_obj['data']['rotations'], dtype=float)
    return rots[:, :, idx, :].transpose(2, 0, 1)

def infer_euler_from_transforms(parent_tf: np.ndarray, child_tf: np.ndarray, order: str, negate: str) -> np.ndarray:
    rel = np.empty((len(parent_tf), 3), dtype=float)
    for i in range(len(parent_tf)):
        rel_tf = np.linalg.inv(parent_tf[i]) @ child_tf[i]
        rel[i] = R.from_matrix(rel_tf[:3, :3]).as_euler(order, degrees=True)
    signs = np.array([1.0 if ch.upper() == 'P' else -1.0 for ch in negate], dtype=float)
    return rel * signs[None, :]

def read_c3d_trial(path: Path, trial_type: str, cfg: Config) -> TrialSignals:
    c3d_obj = ezc3d.c3d(str(path))
    point_rate_hz = float(c3d_obj['header']['points']['frame_rate'])
    force_rate_hz = float(c3d_obj['header']['analogs']['frame_rate'])
    point_frames = int(c3d_obj['data']['points'].shape[2])
    force_frames = int(c3d_obj['data']['analogs'].shape[2]) if np.asarray(c3d_obj['data']['analogs']).size else 0
    point_time_s = np.arange(point_frames, dtype=float) / point_rate_hz
    force_time_s = np.arange(force_frames, dtype=float) / force_rate_hz if force_frames else np.empty(0, dtype=float)
    body_mass_kg = get_body_mass_kg(c3d_obj, path, cfg.body_mass_override)

    point_labels = list(c3d_obj['parameters']['POINT']['LABELS']['value'])
    rot_labels = list(c3d_obj['parameters'].get('ROTATION', {}).get('LABELS', {}).get('value', []))
    warnings: List[str] = []
    angles: Dict[str, np.ndarray] = {}
    moments: Dict[str, np.ndarray] = {}

    direct_angle_candidates = {
        'L_Hip': ['LHipAngles', 'LeftHipAngles_Theia', 'LHipAngles_Theia', 'LeftHipAngles'],
        'R_Hip': ['RHipAngles', 'RightHipAngles_Theia', 'RHipAngles_Theia', 'RightHipAngles'],
        'L_Knee': ['LKneeAngles', 'LeftKneeAngles_Theia', 'LKneeAngles_Theia', 'LeftKneeAngles'],
        'R_Knee': ['RKneeAngles', 'RightKneeAngles_Theia', 'RKneeAngles_Theia', 'RightKneeAngles'],
        'L_Ankle': ['LAnkleAngles', 'LeftAnkleAngles_Theia', 'LAnkleAngles_Theia', 'LeftAnkleAngles'],
        'R_Ankle': ['RAnkleAngles', 'RightAnkleAngles_Theia', 'RAnkleAngles_Theia', 'RightAnkleAngles'],
    }
    for metric, candidates in direct_angle_candidates.items():
        hit = find_matching_label(point_labels, candidates)
        if hit is not None:
            angles[metric] = get_c3d_point_series(c3d_obj, hit)[:, :3]

    fallback_specs = {
        'L_Hip': ('pelvis_4X4', 'l_thigh_4X4', 'XYZ', 'NPP'),
        'R_Hip': ('pelvis_4X4', 'r_thigh_4X4', 'XYZ', 'NNN'),
        'L_Knee': ('l_thigh_4X4', 'l_shank_4X4', 'XYZ', 'PPP'),
        'R_Knee': ('r_thigh_4X4', 'r_shank_4X4', 'XYZ', 'PNN'),
        'L_Ankle': ('l_shank_4X4', 'l_foot_4X4', 'XYZ', 'NPP'),
        'R_Ankle': ('r_shank_4X4', 'r_foot_4X4', 'XYZ', 'NNN'),
    }
    for metric, (parent_name, child_name, order, negate) in fallback_specs.items():
        if metric in angles:
            continue
        parent_hit = find_matching_label(rot_labels, [parent_name])
        child_hit = find_matching_label(rot_labels, [child_name])
        if parent_hit and child_hit:
            angles[metric] = infer_euler_from_transforms(
                get_c3d_rotation_series(c3d_obj, parent_hit),
                get_c3d_rotation_series(c3d_obj, child_hit),
                order=order,
                negate=negate,
            )

    moment_candidates = {
        'L_Hip': [
            'LHipMoment', 'LeftHipMoment', 'L_HipMoment', 'L.HipMoment', 'L Hip Moment',
            'LHipMoment_Theia', 'LeftHipMoment_Theia', 'HipMoment_L', 'HipMomentLeft'
        ],
        'R_Hip': [
            'RHipMoment', 'RightHipMoment', 'R_HipMoment', 'R.HipMoment', 'R Hip Moment',
            'RHipMoment_Theia', 'RightHipMoment_Theia', 'HipMoment_R', 'HipMomentRight'
        ],
        'L_Knee': [
            'LKneeMoment', 'LeftKneeMoment', 'L_KneeMoment', 'L.KneeMoment', 'L Knee Moment',
            'LKneeMoment_Theia', 'LeftKneeMoment_Theia', 'KneeMoment_L', 'KneeMomentLeft'
        ],
        'R_Knee': [
            'RKneeMoment', 'RightKneeMoment', 'R_KneeMoment', 'R.KneeMoment', 'R Knee Moment',
            'RKneeMoment_Theia', 'RightKneeMoment_Theia', 'KneeMoment_R', 'KneeMomentRight'
        ],
        'L_Ankle': [
            'LAnkleMoment', 'LeftAnkleMoment', 'L_AnkleMoment', 'L.AnkleMoment', 'L Ankle Moment',
            'LAnkleMoment_Theia', 'LeftAnkleMoment_Theia', 'AnkleMoment_L', 'AnkleMomentLeft'
        ],
        'R_Ankle': [
            'RAnkleMoment', 'RightAnkleMoment', 'R_AnkleMoment', 'R.AnkleMoment', 'R Ankle Moment',
            'RAnkleMoment_Theia', 'RightAnkleMoment_Theia', 'AnkleMoment_R', 'AnkleMomentRight'
        ],
    }
    available_moment_labels = [label for label in point_labels if 'moment' in label.lower()]
    for metric, candidates in moment_candidates.items():
        hit = find_matching_label(point_labels, candidates)
        if hit is not None:
            # These C3D files store moments as Nmm/kg. Convert to Nm/kg.
            moments[metric] = get_c3d_point_series(c3d_obj, hit)[:, :3] / 1000.0
        else:
            warnings.append(
                f"Moment label missing for {metric}. Available POINT labels containing 'moment': "
                + (', '.join(available_moment_labels) if available_moment_labels else 'none')
            )

    pelvis_tz = None
    pelvis_source = None
    for candidate in ['pelvis_4X4', 'pelvis_shifted_4X4']:
        hit = find_matching_label(rot_labels, [candidate])
        if hit:
            pelvis_tz = get_c3d_rotation_series(c3d_obj, hit)[:, 2, 3]
            pelvis_source = f'ROTATION:{hit}'
            break
    if pelvis_tz is None:
        raise KeyError('pelvis_4X4 / pelvis_shifted_4X4 not found in ROTATION data. Marker-based fallback is disabled by design.')

    forces = {
        'L': get_c3d_analog_force(c3d_obj, cfg.plate_left, cfg.force_signs),
        'R': get_c3d_analog_force(c3d_obj, cfg.plate_right, cfg.force_signs),
    }

    # Data are expected to be pre-filtered before report generation.
    # No additional filtering is applied in this reporting script.

    raw_contacts, raw_force_rate_hz, raw_csv_path, raw_warnings = read_raw_contacts_for_trial(path, trial_type, cfg)
    warnings.extend(raw_warnings)

    return TrialSignals(
        trial_name=path.stem,
        trial_type=trial_type,
        source_path=path,
        point_rate_hz=point_rate_hz,
        force_rate_hz=force_rate_hz,
        body_mass_kg=body_mass_kg,
        point_time_s=point_time_s,
        force_time_s=force_time_s,
        pelvis_tz=pelvis_tz,
        angles=angles,
        moments=moments,
        forces=forces,
        raw_contacts=raw_contacts,
        raw_force_rate_hz=raw_force_rate_hz,
        raw_csv_path=raw_csv_path,
        warnings=warnings,
    )
