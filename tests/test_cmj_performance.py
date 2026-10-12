"""Force-only inputs, native event sampling and Nexus operation integration."""

import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

from tests.test_cmj import synthetic_cmj
from app.analysis.cmj import process_cmj_trial
from app.c3d.cmj import read_cmj_csv
from app.nexus.cmj_quick_metrics import analyze_in_jumputils, run
from app.nexus.cmj_worker import analyze_payload
from app.reporting.cmj_metadata import measurement_metadata
from app.reporting.cmj_performance import best_trial, summary_rows, performance_force_figure, athlete_metadata


def force_csv(path, force, rate=1000):
    text = 'Devices\n'+str(rate)+'\n,,3 - Force,,,4 - Force,,\nFrame,Sub Frame,Fx,Fy,Fz,Fx,Fy,Fz\n,,N,N,N,N,N,N\n'
    text += ''.join(f'{i//5+1},{i%5},0,0,{-f/2},0,0,{-f/2}\n' for i, f in enumerate(force))
    path.write_text(text)


class CMJPerformanceTests(unittest.TestCase):
    def test_summary_values_are_plain_and_best_trial_is_height_selected(self):
        from copy import deepcopy
        s, c = synthetic_cmj()
        first = process_cmj_trial(s, c)
        second = deepcopy(first)
        second.trial_name = 'CMJ_2'
        second.metrics['jump_height_m'] += .1
        # A larger force in the other trial must not determine "best".
        first.metrics['peak_vertical_force_n'] *= 2
        self.assertIs(best_trial([first, second]), second)
        for row in summary_rows([first, second]):
            self.assertNotIn('<u>', row[2])
            self.assertNotIn('<u>', row[3])
        labels = [row[0] for row in summary_rows([first, second])]
        self.assertEqual(labels[4:6], ['Braking net impulse (N·s)', 'Propulsive net impulse (N·s)'])
        self.assertEqual(labels[8:10], ['Countermovement depth (cm)', 'Braking time (ms)'])
        self.assertNotIn('negative', labels[-1])

    def test_athlete_metadata_has_weight_and_trials_without_event_plumbing(self):
        s, c = synthetic_cmj()
        r = process_cmj_trial(s, c)
        metadata = dict(athlete_metadata([r], c, '2026-09-28'))
        self.assertEqual(metadata['Body mass'], '75,0 kg')
        self.assertEqual(metadata['Trials'], '1')
        self.assertNotIn('Events', metadata)
        self.assertEqual(metadata['Measurement date'], '28.09.2026')
        self.assertEqual(metadata['Force plates'], 'AMTI HPS400600 running at 1000 Hz.')

    def test_force_plot_shares_scales_and_stops_at_takeoff(self):
        import matplotlib.pyplot as plt
        s, c = synthetic_cmj()
        s.side_vertical_force_n = {'L': s.vertical_force_n*.45, 'R': s.vertical_force_n*.55}
        r = process_cmj_trial(s, c)
        fig = performance_force_figure([r])
        try:
            full, _, braking, propulsion = fig.axes
            self.assertEqual(full.get_ylim(), braking.get_ylim())
            self.assertEqual(full.get_ylim(), propulsion.get_ylim())
            self.assertEqual([line.get_label() for line in full.lines], ['Left', 'Right', 'Combined'])
            self.assertAlmostEqual(full.get_xlim()[1], (r.events['takeoff']-r.events['onset'])*1000)
            for line in full.lines:
                self.assertAlmostEqual(line.get_xdata()[0], 0)
                self.assertAlmostEqual(line.get_xdata()[-1], full.get_xlim()[1])
            for ax in (full, braking, propulsion):
                self.assertFalse(any(line.get_visible() for line in ax.get_xgridlines()+ax.get_ygridlines()))
            text = ' '.join(label.get_text() for label in full.texts)
            self.assertIn('Peak GRF', text)
            self.assertIn('Braking impulse', text)
            self.assertIn('Propulsive impulse', text)
            self.assertNotIn('Landing', text)
        finally:
            plt.close(fig)

    def test_performance_csv_mode_does_not_parse_matching_c3d(self):
        from app.cli import main
        s, _ = synthetic_cmj()
        with tempfile.TemporaryDirectory() as tmp:
            csv = Path(tmp)/'CMJ_1.csv'
            force_csv(csv, s.vertical_force_n)
            # Deliberately invalid C3D: its presence must not require motion
            # extraction for a raw-CSV performance-only session.
            csv.with_suffix('.c3d').write_bytes(b'not a C3D')
            argv = ['jumputils', tmp, '--protocol', 'cmj', '--cmj-report', 'performance',
                    '--cmj-force-source', 'csv', '--body-mass', '75', '--cmj-baseline-start', '0',
                    '--output', str(Path(tmp)/'report.pdf')]
            with patch('sys.argv', argv), patch('app.cli.read_cmj_trial', side_effect=AssertionError('C3D parsed')), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            self.assertTrue((Path(tmp)/'report.pdf').is_file())

    def test_csv_only_uses_same_force_dynamics(self):
        s, c = synthetic_cmj()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'CMJ_1.csv'
            force_csv(p, s.vertical_force_n)
            loaded = read_cmj_csv(p, c)
            r = process_cmj_trial(loaded, c)
            expected = process_cmj_trial(s, c)
            self.assertAlmostEqual(r.metrics['jump_height_m'], expected.metrics['jump_height_m'], places=10)
            self.assertEqual(r.angles_deg, {})
            self.assertEqual(r.joint_metrics, {})
            np.testing.assert_allclose(r.curves['force_l_n']+r.curves['force_r_n'], r.curves['force_n'], atol=1e-10)

    def test_native_event_grid_is_not_stretched_to_force_grid(self):
        s, c = synthetic_cmj(fs=1000)
        event, _ = synthetic_cmj(fs=2000)
        s.event_vertical_force_n = event.vertical_force_n
        s.event_time_s = event.force_time_s
        r = process_cmj_trial(s, c)
        expected = process_cmj_trial(event, c)
        self.assertAlmostEqual(r.events['takeoff'], expected.events['takeoff'], places=10)
        self.assertAlmostEqual(r.events['onset'], expected.events['onset'], places=10)
        self.assertEqual(r.provenance['event_rate_hz'], '2000')
        self.assertAlmostEqual(r.metrics['jump_height_m'], 9/(2*c.cmj.gravity), delta=.005)

    def test_side_forces_sum_to_combined_after_offset_and_filtering(self):
        s, c = synthetic_cmj()
        c.body_mass_override = 75
        s.vertical_force_n = s.vertical_force_n+10
        s.event_vertical_force_n = None
        s.side_vertical_force_n = {'L': s.vertical_force_n*.4, 'R': s.vertical_force_n*.6}
        c.cmj.force_filter_hz = 15
        r = process_cmj_trial(s, c)
        self.assertAlmostEqual(r.metrics['force_offset_n'], 10)
        np.testing.assert_allclose(r.curves['force_l_n']+r.curves['force_r_n'], r.curves['force_n'], atol=1e-9)

    def test_cli_default_uses_raw_csv_and_ignores_matching_c3d(self):
        s, _ = synthetic_cmj()
        from app.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'CMJ_1.c3d'
            p.write_bytes(b'C3D must not be read')
            force_csv(p.with_suffix('.csv'), s.vertical_force_n)
            argv = ['jumputils', tmp,
                    '--cmj-baseline-start', '0', '--output', str(Path(tmp)/'report.html')]
            with patch('sys.argv', argv), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            import json
            data = json.loads((Path(tmp)/'report_analysis.json').read_text(encoding='utf-8'))
            self.assertEqual(data['settings']['force_filter_hz'], 0)
            self.assertEqual(data['settings']['force_source'], 'csv')
            self.assertEqual(data['trials'][0]['joint_metrics'], {})
            np.testing.assert_allclose(data['trials'][0]['metrics']['jump_height_m'], 9/(2*9.80665), atol=.005)
            html = (Path(tmp)/'report.html').read_text(encoding='utf-8')
            self.assertIn('CMJ Performance Report', html)
            self.assertNotIn('Trial strategy', html)
            self.assertNotIn('Best jump height', html)
            self.assertNotIn('Skipped', html)
            self.assertNotIn('n = 1', html)
            self.assertTrue((Path(tmp)/'report.pdf').is_file())

    def test_missing_csv_does_not_fall_back_to_filtered_c3d(self):
        from app.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'CMJ_1.c3d').write_bytes(b'C3D must not be read')
            with patch('sys.argv', ['jumputils', tmp]), contextlib.redirect_stdout(io.StringIO()) as log:
                with self.assertRaises(SystemExit):
                    main()
            self.assertIn('CMJ raw force CSV missing', log.getvalue())

    def test_gui_opens_both_reports_for_mixed_session(self):
        from app.main import session_reports
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp)/'session.html'
            html.touch()
            cmj = Path(tmp)/'session_cmj.pdf'
            cmj.touch()
            self.assertEqual(session_reports(html), [html, cmj])
            cmj.unlink()
            pdf = html.with_suffix('.pdf')
            pdf.touch()
            self.assertEqual(session_reports(html), [pdf])

    def test_default_mixed_folder_creates_separate_dj_and_raw_cmj_reports(self):
        from datetime import datetime
        from types import SimpleNamespace
        from app.cli import main
        from app.models import TrialResult
        from dataclasses import fields
        s, _ = synthetic_cmj()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder/'DJ_1.c3d').touch()
            (folder/'CMJ_1.c3d').write_bytes(b'CMJ C3D must not be read')
            force_csv(folder/'CMJ_1.CSV', s.vertical_force_n)
            values = {f.name: 0.1 for f in fields(TrialResult)}
            values.update(trial_name='DJ_1', trial_type='DJ', file_date=datetime(2026, 9, 28),
                          contact_source='raw_csv', raw_csv_path=folder/'DJ_1.csv')
            dj = SimpleNamespace(**values)
            output = folder/'session.html'
            with patch('sys.argv', ['jumputils', tmp, '--output', str(output), '--cmj-baseline-start', '0']), \
                 patch('app.cli.read_c3d_trial', return_value=object()) as reader, \
                 patch('app.cli.process_trial', return_value=dj), \
                 patch('app.cli.render_report_html', return_value="<div class='brand-bar'></div>DJ report"), \
                 patch('app.cli.write_contact_csvs', return_value=(folder/'wide.csv', folder/'long.csv')), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            self.assertEqual(reader.call_count, 1)
            self.assertEqual(reader.call_args.args[0].stem, 'DJ_1')
            self.assertIn('session_cmj.pdf', output.read_text(encoding='utf-8'))
            self.assertTrue((folder/'session_cmj.pdf').is_file())
            import json
            manifest = json.loads((folder/'session_cmj_analysis.json').read_text(encoding='utf-8'))
            self.assertEqual(len(manifest['trials']), 1)
            self.assertEqual(manifest['settings']['force_source'], 'csv')

    def test_enf_date_precedes_file_timestamp(self):
        s, c = synthetic_cmj()
        r = process_cmj_trial(s, c)
        with tempfile.TemporaryDirectory() as tmp:
            r.source_path = Path(tmp)/'CMJ_1.c3d'
            r.source_path.touch()
            r.source_path.with_name('CMJ_1.Trial.enf').write_text('[TRIAL_INFO]\nDate=2026-08-26\n')
            label, source = measurement_metadata([r])
            self.assertEqual(label, '26.08.2026')
            self.assertEqual(source, 'CMJ_1.Trial.enf')
            self.assertEqual(measurement_metadata([r], '2026-08-25')[0], '25.08.2026')


class FakeNexus:
    def __init__(self, force, rate=1000):
        self.force = force
        self.rate = rate
        self.params = {}
    def GetSubjectInfo(self): return ['Athlete'], ['Model'], [True]
    def GetTrialName(self): return '', 'CMJ_1'
    def GetSubjectParamNames(self, subject): return ['Bodymass']
    def GetSubjectParam(self, subject, name): return 75., True
    def GetDeviceIDs(self): return [3, 4]
    def GetDeviceDetails(self, device): return str(device), 'ForcePlate', self.rate, [1], None, None
    def GetDeviceOutputIDFromName(self, device, name): return 1
    def GetDeviceChannelIDFromName(self, device, output, name): return 3
    def GetDeviceChannelGlobal(self, device, output, channel):
        # Opposite plate orientations must be corrected before summation.
        return self.force/2*(-1 if device == 3 else 1), True, self.rate
    def GetAnalysisParamNames(self, subject): return list(self.params)
    def GetAnalysisParam(self, subject, name): return self.params.get(name, (0, 'none'))[0], name in self.params
    def CreateAnalysisParam(self, subject, name, value, unit): self.params[name] = (value, unit)
    def SetAnalysisParam(self, subject, name, value): self.params[name] = (value, self.params[name][1])


class NexusCMJTests(unittest.TestCase):
    def test_physical_plate_name_takes_priority_over_device_id(self):
        from app.analysis.CMJ_quick_metrics_v3 import resolve_force_plate
        s, _ = synthetic_cmj()
        nexus = FakeNexus(s.vertical_force_n)
        nexus.GetDeviceIDs = lambda: [3, 7]
        nexus.GetDeviceDetails = lambda device: ('ForcePlate1' if device == 3 else 'ForcePlate3', 'ForcePlate', 1000, [1], None, None)
        self.assertEqual(resolve_force_plate(nexus, 3)['id'], 7)
    def test_worker_physics_and_standalone_process(self):
        s, c = synthetic_cmj()
        payload = {'force_n': s.vertical_force_n.tolist(), 'sample_rate_hz': 1000,
                   'mass_kg': 75, 'baseline_start_s': 0}
        result = analyze_payload(payload)
        bridged = analyze_in_jumputils(s.vertical_force_n, 1000, 75, baseline_start=0)
        self.assertAlmostEqual(result['metrics']['jump_height_m'], bridged['metrics']['jump_height_m'], places=10)
        self.assertAlmostEqual(result['metrics']['jump_height_m'], 9/(2*c.cmj.gravity), delta=.005)
        self.assertAlmostEqual(result['metrics']['propulsive_impulse_ns']/75, result['metrics']['takeoff_velocity_m_s'], places=9)

    def test_operation_writes_and_updates_nexus_analysis_parameters(self):
        s, c = synthetic_cmj()
        nexus = FakeNexus(s.vertical_force_n)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run(nexus, show_popup=False)
            run(nexus, show_popup=False)
        self.assertAlmostEqual(nexus.params['CMJ_Height'][0], result['metrics']['jump_height_m']*1000)
        self.assertEqual(nexus.params['CMJ_Height'][1], 'mm')
        self.assertIn('CMJ_Depth', nexus.params)
        self.assertIn('CMJ_PropulsiveImpulse', nexus.params)
        self.assertIn('CMJ_TakeoffVelocity', nexus.params)

    def test_operation_does_not_truncate_mismatched_plate_signals(self):
        s, _ = synthetic_cmj()
        nexus = FakeNexus(s.vertical_force_n)
        original = nexus.GetDeviceChannelGlobal
        def channel(device, output, axis):
            force, ready, rate = original(device, output, axis)
            return (force[:-1] if device == 4 else force), ready, rate
        nexus.GetDeviceChannelGlobal = channel
        with self.assertRaisesRegex(RuntimeError, 'identical rates and lengths'):
            run(nexus, show_popup=False)
        self.assertEqual(nexus.params, {})

    def test_write_failure_is_not_reported_as_success(self):
        s, _ = synthetic_cmj()
        nexus = FakeNexus(s.vertical_force_n)
        def fails(*args): raise RuntimeError('SDK write failed')
        nexus.CreateAnalysisParam = fails
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'Could not write Nexus parameters'):
            run(nexus, show_popup=False)

    def test_silent_sdk_write_failure_is_detected_by_readback(self):
        s, _ = synthetic_cmj()
        nexus = FakeNexus(s.vertical_force_n)
        nexus.CreateAnalysisParam = lambda *args: None
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'Could not write Nexus parameters'):
            run(nexus, show_popup=False)


if __name__ == '__main__':
    unittest.main()
