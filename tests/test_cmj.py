"""CMJ physical invariants, phase boundaries, data coverage and C3D workflow."""

from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import ezc3d
import numpy as np

from app.analysis.cmj import integral, lowpass, process_cmj_trial, waveform_profile, force_peak_times
from app.analysis.cmj_models import CMJSignals
from app.c3d.cmj import csv_point_offset, moment_scale, read_cmj_trial
from app.c3d.reader import scan_trial_files
from app.config import Config
from app.protocols.cmj import TRIAL_CMJ
from app.protocols.common import classify_trial, contact_key_for_trial
from app.reporting.cmj_exports import write_cmj_report
from app.reporting.cmj_html import render_cmj_report_html, sample_summary


def synthetic_cmj(name='CMJ_1', fs=1000, point_rate=200):
    """Known acceleration: -.8 m/s at 1.4 s, bottom at 1.6 s,
    3 m/s take-off at 1.9 s, 16 cm depth (up to sampling error)."""
    cfg = Config()
    cfg.cmj.baseline_start_s = 0
    cfg.cmj.force_filter_hz = 0
    cfg.cmj.kinematic_filter_hz = 0
    g, mass = cfg.cmj.gravity, 75.
    t = np.arange(0, 2.5+1/fs/2, 1/fs)
    acc = np.zeros_like(t)
    acc[(t >= 1.2) & (t < 1.4)] = -4
    acc[(t >= 1.4) & (t < 1.6)] = 4
    acc[(t >= 1.6) & (t < 1.9)] = 10
    force = mass*(g+acc)
    force[(t >= 1.9) & (t < 2.4)] = 0
    pt = np.arange(0, 2.5+1/point_rate/2, 1/point_rate)
    angles, moments = {}, {}
    # Constant -1 rad/s permits independent analytic power/energy checks.
    for side in ['L', 'R']:
        for joint, peak in [('Hip', 1.67), ('Knee', 1.73), ('Ankle', 1.8)]:
            key = side+'_'+joint
            angles[key] = 100 - np.rad2deg(pt)
            moments[key] = np.where(pt < 1.6, 2., -2.-np.maximum(0, 1-np.abs(pt-peak)/.04))
    angles['Thorax'] = 20 - np.rad2deg(pt)*.2
    s = CMJSignals(name, Path(name+'.c3d'), t, force, pt, angles, moments,
                   mass, 'synthetic Newton force', {'moments': 'synthetic internal Nm/kg'})
    return s, cfg


def write_synthetic_c3d(path, signals, first_frame=0, with_moments=True):
    c = ezc3d.c3d()
    c['parameters']['POINT']['RATE']['value'] = [200.]
    keys = [k for k in signals.angles_deg if k.startswith(('L_', 'R_'))]
    labels = [k.replace('_', '')+'Angles' for k in keys]
    if with_moments:
        labels += [k.replace('_', '')+'Moment' for k in keys]
    c['parameters']['POINT']['LABELS']['value'] = labels
    points = np.zeros((4, len(labels), len(signals.point_time_s)))
    for i, key in enumerate(keys):
        points[0, i] = signals.angles_deg[key]
        if with_moments:
            # Nexus external Nmm/kg -> analysis internal Nm/kg.
            points[0, i+len(keys)] = -1000*signals.moments_nm_per_kg[key]
    c['data']['points'] = points
    c['header']['points']['first_frame'] = first_frame
    c.add_parameter('POINT', 'ANGLE_UNITS', ['deg'])
    c.add_parameter('POINT', 'MOMENT_UNITS', ['Nmm'])
    c.add_parameter('PROCESSING', 'Bodymass', [75.])
    c['parameters']['ANALOG']['RATE']['value'] = [1000.]
    c['parameters']['ANALOG']['LABELS']['value'] = [f'Force.F{axis}{plate}' for plate in (3, 4) for axis in 'xyz']
    c['parameters']['ANALOG']['UNITS']['value'] = ['N']*6
    analogs = np.zeros((1, 6, len(signals.point_time_s)*5))
    f = np.interp(np.arange(analogs.shape[2])/1000, signals.force_time_s, signals.vertical_force_n)
    analogs[0, 2] = analogs[0, 5] = -f/2
    c['data']['analogs'] = analogs
    c.write(str(path))


class CMJPhysicsTests(unittest.TestCase):
    def test_force_integration_known_motion(self):
        s, c = synthetic_cmj()
        r = process_cmj_trial(s, c)
        self.assertAlmostEqual(r.metrics['takeoff_velocity_m_s'], 3, delta=.015)
        self.assertAlmostEqual(r.metrics['jump_height_m'], 9/(2*c.cmj.gravity), delta=.005)
        self.assertAlmostEqual(r.metrics['countermovement_depth_m'], .16, delta=.003)
        self.assertAlmostEqual(r.metrics['peak_downward_velocity_m_s'], -.8, delta=.01)
        self.assertAlmostEqual(r.events['com_bottom'], 1.6, delta=.003)
        self.assertAlmostEqual(r.metrics['time_to_takeoff_s'], .7, delta=.003)
        self.assertAlmostEqual(r.metrics['braking_time_s'], .2, delta=.003)
        self.assertAlmostEqual(r.metrics['propulsion_time_s'], .3, delta=.003)
        self.assertAlmostEqual(r.metrics['propulsive_impulse_ns'], 225, delta=1.2)
        self.assertAlmostEqual(r.metrics['braking_impulse_ns'], 60, delta=.8)

    def test_impulse_momentum_and_velocity_budget(self):
        s, c = synthetic_cmj()
        r = process_cmj_trial(s, c)
        self.assertAlmostEqual(r.metrics['propulsive_impulse_ns']/75, r.metrics['takeoff_velocity_m_s'], delta=1e-5)
        self.assertAlmostEqual(sum(v for k, v in r.metrics.items() if k.startswith('velocity_gain_') and k.endswith('_pct')), 100, places=8)
        self.assertAlmostEqual(r.metrics['rsi_mod_m_s'], r.metrics['jump_height_m']/r.metrics['time_to_takeoff_s'])

    def test_sampling_rate_independence(self):
        a, cfg = synthetic_cmj(fs=1000)
        b, _ = synthetic_cmj(fs=2000)
        ra, rb = process_cmj_trial(a, cfg), process_cmj_trial(b, cfg)
        self.assertAlmostEqual(ra.metrics['jump_height_m'], rb.metrics['jump_height_m'], delta=.003)

    def test_late_negative_acceleration_retains_negative_velocity_gain(self):
        s, c = synthetic_cmj()
        s.vertical_force_n[(s.force_time_s >= 1.6) & (s.force_time_s < 1.8)] = 75*(c.cmj.gravity+12)
        s.vertical_force_n[(s.force_time_s >= 1.8) & (s.force_time_s < 1.9)] = 75*(c.cmj.gravity-4)
        r = process_cmj_trial(s, c)
        self.assertLess(r.metrics['velocity_gain_75_100_pct'], 0)
        self.assertAlmostEqual(sum(v for k, v in r.metrics.items() if k.startswith('velocity_gain_') and k.endswith('_pct')), 100, places=8)

    def test_no_landing_still_has_takeoff_height(self):
        s, c = synthetic_cmj()
        s.vertical_force_n[s.force_time_s >= 1.9] = 0
        r = process_cmj_trial(s, c)
        self.assertNotIn('landing', r.events)
        self.assertGreater(r.metrics['jump_height_m'], 0)

    def test_force_only_is_valid_missing_joints_are_not_zero(self):
        s, c = synthetic_cmj()
        s.angles_deg, s.moments_nm_per_kg = {}, {}
        r = process_cmj_trial(s, c)
        self.assertEqual(r.joint_metrics, {})
        self.assertTrue(np.isnan(r.sequencing['bilateral']['Hip_to_Knee_ms']))

    def test_reject_invalid_or_truncated_records(self):
        for kind in ['missing', 'no_flight', 'bad_baseline', 'no_countermovement', 'wrong_support']:
            with self.subTest(kind=kind):
                s, c = synthetic_cmj()
                if kind == 'missing':
                    s.vertical_force_n[20] = np.nan
                elif kind == 'no_flight':
                    s.vertical_force_n[s.force_time_s >= 1.9] = 75*c.cmj.gravity
                elif kind == 'bad_baseline':
                    s.vertical_force_n[s.force_time_s < 1] += 100*np.sin(s.force_time_s[s.force_time_s < 1]*20)
                elif kind == 'no_countermovement':
                    s.vertical_force_n[s.force_time_s < 1.6] = 75*c.cmj.gravity
                else:
                    s.metadata_mass_kg = 150
                with self.assertRaises(ValueError):
                    process_cmj_trial(s, c)

    def test_auto_baseline_does_not_integrate_long_standing_drift(self):
        s, c = synthetic_cmj()
        c.cmj.baseline_start_s = None
        # Add five seconds of standing with a different small force offset.
        prefix = np.arange(0, 5, .001)
        s.force_time_s = np.r_[prefix, s.force_time_s+5]
        s.vertical_force_n = np.r_[np.full(len(prefix), 75*c.cmj.gravity+8), s.vertical_force_n]
        s.point_time_s += 5
        r = process_cmj_trial(s, c)
        self.assertGreater(r.events['baseline_start'], 4.9)
        self.assertAlmostEqual(r.metrics['jump_height_m'], 9/(2*c.cmj.gravity), delta=.005)


class CMJJointTests(unittest.TestCase):
    def test_signed_work_splits_zero_crossing(self):
        t = np.array([0., 1.])
        y = np.array([-1., 1.])
        self.assertAlmostEqual(integral(t, y, 0, 1, 'positive'), .25)
        self.assertAlmostEqual(integral(t, y, 0, 1, 'negative'), -.25)
        self.assertAlmostEqual(integral(t, y, .25, .75, 'positive'), .0625)

    def test_power_uses_radians_and_signed_sequence(self):
        s, c = synthetic_cmj()
        r = process_cmj_trial(s, c)
        self.assertAlmostEqual(r.powers_w_per_kg['L_Hip'][334], 3., places=9)
        sequence = r.sequencing['bilateral']
        self.assertAlmostEqual(sequence['Hip_to_Knee_ms'], 60., delta=.01)
        self.assertAlmostEqual(sequence['Knee_to_Ankle_ms'], 70., delta=.01)
        self.assertAlmostEqual(sequence['Hip_to_Ankle_ms'], 130., delta=.01)
        self.assertAlmostEqual(sum(r.joint_metrics[j]['positive_work_contribution_pct'] for j in ['Hip', 'Knee', 'Ankle']), 100)
        # Reverse two power peaks: preserve a negative interval without scoring.
        s.moments_nm_per_kg['L_Hip'], s.moments_nm_per_kg['L_Ankle'] = s.moments_nm_per_kg['L_Ankle'], s.moments_nm_per_kg['L_Hip']
        r = process_cmj_trial(s, c)
        self.assertLess(r.sequencing['L_']['Hip_to_Ankle_ms'], 0)

    def test_bilateral_work_does_not_cancel_opposing_limb_power(self):
        s, c = synthetic_cmj()
        s.moments_nm_per_kg['L_Hip'][:] = -2
        s.moments_nm_per_kg['R_Hip'][:] = 2
        r = process_cmj_trial(s, c)
        np.testing.assert_allclose(r.powers_w_per_kg['Hip'], 0, atol=1e-10)
        self.assertAlmostEqual(r.joint_metrics['Hip']['propulsion_positive_work_j_kg'], 2*r.metrics['propulsion_time_s'])

    def test_missing_limb_does_not_create_partial_bilateral_share(self):
        s, c = synthetic_cmj()
        del s.moments_nm_per_kg['R_Ankle']
        r = process_cmj_trial(s, c)
        self.assertNotIn('Ankle', r.joint_metrics)
        self.assertTrue(np.isnan(r.joint_metrics['Hip']['positive_work_contribution_pct']))
        self.assertTrue(np.isfinite(r.joint_metrics['L_Hip']['positive_work_contribution_pct']))

    def test_gaps_and_cropped_points_do_not_extrapolate_work(self):
        for gap in (False, True):
            s, c = synthetic_cmj()
            if gap:
                s.moments_nm_per_kg['L_Hip'][340] = np.nan
            else:
                s.point_time_s -= .8
            r = process_cmj_trial(s, c)
            self.assertTrue(np.isnan(r.joint_metrics['L_Hip']['propulsion_positive_work_j_kg']))
            self.assertGreater(r.metrics['jump_height_m'], 0)

    def test_filter_preserves_missing_regions(self):
        t = np.arange(1000)/1000
        values = np.sin(t)
        values[400:450] = np.nan
        filtered = lowpass(values, t, 10)
        self.assertTrue(np.isnan(filtered[400:450]).all())
        self.assertTrue(np.isfinite(filtered[:400]).all())

    def test_unit_conversion(self):
        self.assertEqual(moment_scale('Nmm/kg', None), .001)
        self.assertEqual(moment_scale('Nm/kg', 75), 1)
        self.assertEqual(moment_scale('Nm', 75), 1/75)
        self.assertEqual(moment_scale('Nmm', 75), .001/75)
        with self.assertRaises(ValueError):
            moment_scale('Nm', None)


class CMJWorkflowTests(unittest.TestCase):
    def test_force_peaks_include_braking_peak_and_late_propulsion_peak(self):
        _, c = synthetic_cmj()
        t = np.arange(0, 1.001, .001)
        force = 800+1000*np.exp(-((t-.3)/.07)**2)+1300*np.exp(-((t-.8)/.08)**2)
        peaks = force_peak_times(t, force, 0, 1, 800, c)
        np.testing.assert_allclose(peaks, [.3, .8], atol=.002)

    def test_force_peaks_do_not_invent_second_peak_on_plateau_or_noise(self):
        _, c = synthetic_cmj()
        t = np.arange(0, 1.001, .001)
        for force in (800+1000*np.maximum(0, 1-np.abs(t-.5)/.3)+3*np.sin(2*np.pi*100*t),
                      800+1000*((t >= .3) & (t <= .7))):
            self.assertEqual(len(force_peak_times(t, force, 0, 1, 800, c)), 1)

    def test_cropped_c3d_stays_aligned_to_full_csv(self):
        s, c = synthetic_cmj()
        cropped = deepcopy(s)
        mask = s.point_time_s >= 1.25
        cropped.point_time_s = s.point_time_s[mask]
        force_mask = s.force_time_s >= 1.25
        cropped.force_time_s = s.force_time_s[force_mask]
        cropped.vertical_force_n = s.vertical_force_n[force_mask]
        cropped.angles_deg = {k: v[mask] for k, v in s.angles_deg.items()}
        cropped.moments_nm_per_kg = {k: v[mask] for k, v in s.moments_nm_per_kg.items()}
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'CMJ_1.c3d'
            write_synthetic_c3d(p, cropped, first_frame=250)
            text = 'Devices\n1000\n,,3 - Force,,,4 - Force,,\nFrame,Sub Frame,Fx,Fy,Fz,Fx,Fy,Fz\n,,N,N,N,N,N,N\n'
            text += ''.join(f'{i//5+1},{i%5},0,0,{-f/2},0,0,{-f/2}\n' for i, f in enumerate(s.vertical_force_n))
            p.with_suffix('.csv').write_text(text)
            loaded = read_cmj_trial(p, c)
            self.assertAlmostEqual(loaded.point_time_s[0], 1.25)
            self.assertAlmostEqual(loaded.force_time_s[0], 1.25)
            self.assertEqual(len(loaded.event_vertical_force_n), len(loaded.event_time_s))
            self.assertAlmostEqual(loaded.event_time_s[0], 0)
            self.assertGreater(len(loaded.event_time_s), len(loaded.force_time_s))
            self.assertIn('raw CSV', loaded.provenance['force_source'])
            # Explicit raw-CSV dynamics can support cropped kinematics, while
            # preserving the raw event clock and complete force baseline.
            c.cmj.force_source = 'csv'
            loaded = read_cmj_trial(p, c)
            r = process_cmj_trial(loaded, c)
            self.assertAlmostEqual(r.sequencing['bilateral']['Hip_to_Knee_ms'], 60, delta=.01)
            self.assertTrue(np.isnan(r.joint_metrics['Hip']['movement_positive_work_j_kg']))
            self.assertTrue(np.isfinite(r.joint_metrics['Hip']['propulsion_positive_work_j_kg']))

    def test_cli_discovers_all_cmjs_and_reports_invalid_trial(self):
        from app.cli import main
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            folder = Path(tmp)/'nested'
            folder.mkdir()
            for i in range(1, 5):
                s, _ = synthetic_cmj(f'CMJ_{i}')
                s.vertical_force_n[(s.force_time_s >= 1.6) & (s.force_time_s < 1.9)] += i*100
                if i == 4:
                    s.vertical_force_n[:] = 0
                write_synthetic_c3d(folder/f'CMJ_{i}.c3d', s)
            (folder/'WALK_1.c3d').touch()
            (folder/'DJ_1.c3d').touch()  # protocol filter must exclude it
            for name in ['force_com_figure', 'kinematics_figure', 'moments_figure', 'overlay_figure', 'power_figure', 'waveform_figure', 'baseline_figure']:
                stack.enter_context(patch('app.reporting.cmj_html.'+name, return_value=''))
            output = Path(tmp)/'report.html'
            stack.enter_context(patch('sys.argv', ['jumputils', tmp, '--recursive', '--protocol', 'cmj', '--cmj-report', 'extended', '--output', str(output), '--cmj-baseline-start', '0', '--cmj-force-filter-hz', '0', '--cmj-kinematic-filter-hz', '0']))
            stack.enter_context(patch('builtins.print'))
            self.assertEqual(main(), 0)
            manifest = json.loads(output.with_name('report_analysis.json').read_text(encoding='utf-8'))
            self.assertEqual(len(manifest['trials']), 3)
            self.assertEqual(len(manifest['skipped_files']), 1)
            self.assertEqual(manifest['best_trial_id'], 3)

    def test_cmj_discovery_does_not_capture_rebound_or_sdj(self):
        for stem in ['CMJ_1', 'cmj-2', 'CMJ 3', 'CMJ']:
            self.assertEqual(classify_trial(stem), TRIAL_CMJ)
        for stem in ['CMJR_1', 'NOT_CMJ_1', 'WALK_1']:
            self.assertIsNone(classify_trial(stem))
        with self.assertRaises(ValueError):
            contact_key_for_trial(TRIAL_CMJ)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'CMJ_1.C3D'
            p.touch()
            self.assertEqual(scan_trial_files(Path(tmp)), [p])

    def test_real_c3d_adapter_and_nexus_moment_sign(self):
        s, c = synthetic_cmj()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'CMJ_1.c3d'
            write_synthetic_c3d(p, s)
            loaded = read_cmj_trial(p, c)
            np.testing.assert_allclose(loaded.moments_nm_per_kg['L_Hip'], s.moments_nm_per_kg['L_Hip'], atol=1e-7)
            r = process_cmj_trial(loaded, c)
            self.assertAlmostEqual(r.metrics['jump_height_m'], 9/(2*c.cmj.gravity), delta=.005)
            self.assertNotIn('Thorax', loaded.angles_deg)

    def test_csv_frame_alignment_and_gap_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'CMJ_1.csv'
            p.write_text('Devices\n1000\n,,3 - Force\nFrame,Sub Frame,Fz\n1,0,-1\n1,1,-1\n1,2,-1\n1,3,-1\n1,4,-1\n2,0,-1\n')
            self.assertEqual(csv_point_offset(p, 1000, 200, 100, 6), .5)
            p.write_text(p.read_text().replace('1,2,-1\n', ''))
            with self.assertRaises(ValueError):
                csv_point_offset(p, 1000, 200, 100, 5)

    def test_duplicate_plate_rejected(self):
        s, c = synthetic_cmj()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'CMJ_1.c3d'
            write_synthetic_c3d(p, s)
            c.plate_left = c.plate_right
            with self.assertRaisesRegex(ValueError, 'distinct'):
                read_cmj_trial(p, c)

    def test_waveform_two_peaks_and_bottom_boundary(self):
        s, c = synthetic_cmj()
        t = np.arange(1001)/1000
        force = 800 + 400*np.exp(-((t-.25)/.09)**2) + 500*np.exp(-((t-.7)/.1)**2)
        wave = waveform_profile(t, force, 0, 1, 800, c)
        self.assertEqual(wave['description'], 'Two resolved peaks')
        self.assertEqual(len(wave['dip_times_s']), 1)
        force = 800+500*np.exp(-(t/.15)**2)
        wave = waveform_profile(t, force, 0, 1, 800, c)
        self.assertTrue(wave['bottom_boundary_peak'])

    def test_sample_sd_and_single_trial(self):
        self.assertEqual(sample_summary([1, 3], 2), '2,00 ± 1,41')
        self.assertEqual(sample_summary([1], 1), '1,0 ± -')

    def test_exports_escape_names_and_retain_every_trial(self):
        s, c = synthetic_cmj('<CMJ&1>')
        c.subject_name = '<script>alert(1)</script>'
        first = process_cmj_trial(s, c)
        second = deepcopy(first)
        second.trial_name = 'CMJ_2'
        second.metrics['jump_height_m'] += .1
        # Plot rendering is exercised separately on the real CMJ sample set.
        functions = ['force_com_figure', 'kinematics_figure', 'moments_figure', 'overlay_figure', 'power_figure', 'waveform_figure', 'baseline_figure']
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            for name in functions:
                stack.enter_context(patch('app.reporting.cmj_html.'+name, return_value=''))
            output = Path(tmp)/'cmj.html'
            write_cmj_report([first, second], c, output, ['bad<trial>: no baseline'])
            html = output.read_text(encoding='utf-8')
            self.assertIn('&lt;script&gt;', html)
            self.assertNotIn('<script>alert', html)
            self.assertIn('&lt;CMJ&amp;1&gt;', html)
            self.assertNotIn('Skipped', html)
            extended = output.with_name('cmj_extended.html').read_text(encoding='utf-8')
            self.assertIn('bad&lt;trial&gt;', extended)
            manifest = json.loads(output.with_name('cmj_analysis.json').read_text(encoding='utf-8'))
            self.assertEqual(len(manifest['trials']), 2)
            self.assertEqual(manifest['best_trial_id'], 2)
            self.assertNotIn('NaN', output.with_name('cmj_analysis.json').read_text())


if __name__ == '__main__':
    unittest.main()
