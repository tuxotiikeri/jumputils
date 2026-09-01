"""Trial naming and protocol metadata shared by supported jump protocols."""

import re
from typing import List, Optional

from app.protocols.dj import TRIAL_DJ
from app.protocols.sdj import TRIAL_SDJ_L, TRIAL_SDJ_R, TRIAL_SDJ30_L, TRIAL_SDJ30_R


SINGLE_LEG_TRIAL_TYPES = {TRIAL_SDJ_L, TRIAL_SDJ_R, TRIAL_SDJ30_L, TRIAL_SDJ30_R}


def _compact_trial_name(stem: str) -> str:
    return re.sub(r'[^A-Z0-9]+', '', stem.upper())

def classify_trial(stem: str) -> Optional[str]:
    """Classify supported drop-jump trial names.

    Supported examples:
    - DJ_1
    - SDJ_L_1 / SDJ_R_1         (single-leg drop jump, 15 cm platform)
    - SDJ30_L_1 / SDJ30_R_1     (single-leg drop jump, 30 cm platform)
    """
    compact = _compact_trial_name(stem)
    if 'SDJ30L' in compact:
        return TRIAL_SDJ30_L
    if 'SDJ30R' in compact:
        return TRIAL_SDJ30_R
    if 'SDJL' in compact:
        return TRIAL_SDJ_L
    if 'SDJR' in compact:
        return TRIAL_SDJ_R
    if 'DJ' in compact and 'SDJ' not in compact:
        return TRIAL_DJ
    return None

def active_sides_for_trial(trial_type: str) -> List[str]:
    if trial_type == TRIAL_DJ:
        return ['L', 'R']
    if trial_type in {TRIAL_SDJ_L, TRIAL_SDJ30_L}:
        return ['L']
    if trial_type in {TRIAL_SDJ_R, TRIAL_SDJ30_R}:
        return ['R']
    raise ValueError(f'Unsupported trial type: {trial_type}')

def platform_cm_for_trial(trial_type: str) -> Optional[int]:
    if trial_type == TRIAL_DJ:
        return 30
    if trial_type in {TRIAL_SDJ_L, TRIAL_SDJ_R}:
        return 15
    if trial_type in {TRIAL_SDJ30_L, TRIAL_SDJ30_R}:
        return 30
    return None

def trial_family_label(trial_type: str) -> str:
    if trial_type == TRIAL_DJ:
        return 'Drop Jump'
    if trial_type in {TRIAL_SDJ_L, TRIAL_SDJ_R}:
        return 'Single-Leg Drop Jump'
    if trial_type in {TRIAL_SDJ30_L, TRIAL_SDJ30_R}:
        return 'Single-Leg Drop Jump 30 cm'
    return trial_type

def contact_key_for_trial(trial_type: str) -> str:
    if trial_type == TRIAL_DJ:
        return 'combined'
    sides = active_sides_for_trial(trial_type)
    return sides[0]
