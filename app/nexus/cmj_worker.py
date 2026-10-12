"""JSON stdin/stdout bridge; runs in the Jumputils environment, not Nexus Python."""

import json
import sys
from pathlib import Path
import numpy as np
from app.analysis.cmj import process_cmj_trial
from app.analysis.cmj_models import CMJSignals
from app.config import Config


def analyze_payload(payload):
    rate = float(payload['sample_rate_hz'])
    if not np.isfinite(rate) or rate <= 0:
        raise ValueError('Nexus force sample rate must be positive')
    force = np.asarray(payload['force_n'], float)
    if force.ndim != 1:
        raise ValueError('Nexus force must be a single summed vertical signal')
    # Orient from the loaded force distribution, not sample-by-sample abs().
    if np.percentile(-force, 99.5) > np.percentile(force, 99.5):
        force = -force
    cfg = Config(body_mass_override=payload.get('mass_kg'))
    cfg.cmj.force_filter_hz = 0
    cfg.cmj.baseline_start_s = payload.get('baseline_start_s')
    cfg.cmj.baseline_duration_s = payload.get('baseline_duration_s', 1.)
    t = np.arange(len(force))/rate
    signals = CMJSignals(payload.get('trial_name', 'CMJ'), Path(payload.get('source_path') or 'CMJ'),
                         t, force, np.empty(0), metadata_mass_kg=payload.get('mass_kg'),
                         force_source='Nexus current device channels; no additional filtering')
    result = process_cmj_trial(signals, cfg)
    metrics = result.metrics
    # Retain original v3 field names for existing Nexus analysis parameters.
    aliases = {'mass_kg': 'body_mass_kg', 'rsi_mod_m_s': 'rsi_mod_m_s',
               'peak_force_n': 'peak_vertical_force_n', 'peak_force_n_kg': 'peak_vertical_force_n_kg',
               'min_velocity_m_s': 'peak_downward_velocity_m_s',
               'baseline_force_n': 'quiet_standing_force_n', 'movement_threshold_n': 'onset_threshold_n'}
    data = dict(metrics)
    data.update({key: metrics[value] for key, value in aliases.items()})
    data.update({'movement_onset_s': result.events['onset'], 'takeoff_s': result.events['takeoff'],
                 'braking_start_s': result.events['braking_start'], 'propulsive_start_s': result.events['com_bottom']})
    return {'metrics': data, 'events': result.events, 'warnings': result.warnings,
            'method': 'Impulse-momentum: take-off COM to ballistic apex',
            'provenance': result.provenance}


def main():
    try:
        response = analyze_payload(json.load(sys.stdin))
        print(json.dumps(response, allow_nan=False))
        return 0
    except Exception as exc:
        print(json.dumps({'error': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
