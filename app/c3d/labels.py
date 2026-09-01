"""Normalization and matching of C3D/Nexus signal labels."""

import re
from typing import Iterable, Optional, Sequence


def normalize_label(label: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', label.lower())

def find_matching_label(labels: Iterable[str], candidates: Sequence[str]) -> Optional[str]:
    """Find C3D labels robustly.

    Matching order:
    1) exact normalized match
    2) suffix match for subject prefixes, e.g. TEKLI309:LKneeMoment
    3) contains match for Theia/Nexus suffixes, e.g. LKneeMoment_Theia
    """
    norm_map = {normalize_label(label): label for label in labels}
    candidate_keys = [normalize_label(cand) for cand in candidates]

    for key in candidate_keys:
        if key in norm_map:
            return norm_map[key]

    for key in candidate_keys:
        for norm_label, original_label in norm_map.items():
            if norm_label.endswith(key):
                return original_label

    for key in candidate_keys:
        for norm_label, original_label in norm_map.items():
            if key in norm_label:
                return original_label

    return None
