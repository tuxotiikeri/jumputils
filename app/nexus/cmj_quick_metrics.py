"""Run this file as a Nexus Python operation (with an open CMJ trial).

SDK acquisition and writing stay in Nexus. Numerical analysis is delegated to
the repository's env/python.exe so Nexus does not need SciPy/reporting packages.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


def analyze_in_jumputils(force, rate, mass=None, trial_name='CMJ', source_path=None,
                         baseline_start=None, baseline_duration=1., python_executable=None):
    executable = Path(python_executable or os.environ.get('JUMPUTILS_PYTHON', PROJECT_DIR/'env'/'python.exe'))
    if not executable.is_file():
        raise RuntimeError('Jumputils Python environment is missing. Run SETUP_jumputils.bat or set JUMPUTILS_PYTHON.')
    payload = {'force_n': list(map(float, force)), 'sample_rate_hz': float(rate),
               'mass_kg': float(mass) if mass is not None else None, 'trial_name': trial_name,
               'source_path': str(source_path) if source_path else None,
               'baseline_start_s': baseline_start, 'baseline_duration_s': baseline_duration}
    completed = subprocess.run([str(executable), '-m', 'app.nexus.cmj_worker'],
                               input=json.dumps(payload, allow_nan=False), capture_output=True,
                               text=True, encoding='utf-8', cwd=PROJECT_DIR, timeout=120,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        response = json.loads(completed.stdout)
    except ValueError:
        raise RuntimeError('Jumputils CMJ worker failed: '+completed.stderr[-1500:])
    if completed.returncode or 'error' in response:
        raise RuntimeError(response.get('error', completed.stderr))
    return response


def run(vicon=None, plate_numbers=(3, 4), show_popup=True, write_parameters=True):
    from app.analysis import CMJ_quick_metrics_v3 as sdk
    if vicon is None:
        from viconnexusapi import ViconNexus
        vicon = ViconNexus.ViconNexus()
    subject = sdk.first_active_subject(vicon)
    folder, trial = vicon.GetTrialName()
    if len(set(plate_numbers)) != 2:
        raise RuntimeError('CMJ requires two distinct selected force plates')
    left, left_rate, left_plate = sdk.get_force_fz(vicon, plate_numbers[0])
    right, right_rate, right_plate = sdk.get_force_fz(vicon, plate_numbers[1])
    if abs(left_rate-right_rate) > 1e-6 or len(left) != len(right):
        raise RuntimeError('Nexus CMJ plate signals must have identical rates and lengths; signals are not truncated')
    if left_plate['id'] == right_plate['id']:
        raise RuntimeError('Selected Nexus plates resolve to the same device')
    import numpy as np
    def oriented(force):
        if not np.isfinite(force).all():
            raise RuntimeError('Nexus force contains missing samples')
        return -force if np.percentile(-force, 99.5) > np.percentile(force, 99.5) else force
    mass, mass_source = sdk.read_mass_from_mp(folder, subject)
    if mass is None:
        mass, mass_source = sdk.read_mass_from_nexus_subject_param(vicon, subject)
    response = analyze_in_jumputils(oriented(left)+oriented(right), left_rate, mass, trial,
                                    Path(folder)/(trial+'.c3d') if folder else None)
    metrics = response['metrics']
    if write_parameters:
        failures = sdk.write_results_to_nexus(vicon, subject, metrics)
        if failures:
            raise RuntimeError('Could not write Nexus parameters: '+', '.join(failures))
        for name, key, scale, unit in [('CMJ_Depth', 'countermovement_depth_m', 1000, 'mm'),
                                       ('CMJ_BrakingTime', 'braking_time_s', 1, 's'),
                                       ('CMJ_PropulsionTime', 'propulsion_time_s', 1, 's')]:
            if not sdk.set_analysis_parameter(vicon, subject, name, metrics[key]*scale, unit):
                raise RuntimeError('Could not write Nexus parameter '+name)
    message = sdk.result_text(metrics)
    print('Trial: '+trial+' | Subject: '+subject)
    print('Device channels: current Nexus processing state; no additional force filtering')
    print('Mass source: '+str(mass_source or 'quiet standing'))
    print(message)
    if show_popup:
        sdk.show_popup(message)
    return response


if __name__ == '__main__':
    run()
