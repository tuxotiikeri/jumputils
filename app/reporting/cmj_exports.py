"""Machine-readable CMJ results and source-resolution curves alongside HTML."""

from dataclasses import asdict
from pathlib import Path
import json
import numpy as np
import pandas as pd

from app.reporting.cmj_html import render_cmj_report_html
from app.utils import ensure_parent


def _finite_json(value):
    if isinstance(value, dict):
        return {k: _finite_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_json(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    return value


def write_cmj_report(results, cfg, output: Path, errors=(), report_mode='both', measurement_date=None):
    """One report per folder; stable trial_id disambiguates duplicate basenames."""
    ensure_parent(output)
    best = max(results, key=lambda r: r.metrics['jump_height_m'])
    summary, joints, events, force_curves, joint_curves, manifest, event_curves = [], [], [], [], [], [], []
    for index, r in enumerate(results, 1):
        identity = {'trial_id': index, 'trial_name': r.trial_name, 'source_path': str(r.source_path)}
        summary.append({**identity, 'subject_name': cfg.subject_name, 'is_best_height': r is best, **r.metrics})
        joints += [{**identity, 'joint': key, **metrics} for key, metrics in r.joint_metrics.items()]
        events += [{**identity, 'event': key, 'time_s': time,
                    'from_com_bottom_ms': (time-r.events['com_bottom'])*1000} for key, time in r.events.items()]
        # Keep force data only through take-off: post-take-off support on other
        # plates cannot be interpreted as whole-body dynamics.
        mask = (r.force_time_s >= r.events['baseline_start']) & (r.force_time_s <= r.events['takeoff'])
        force_curves.append(pd.DataFrame({**identity, 'time_s': r.force_time_s[mask],
                                         **{k: v[mask] for k, v in r.curves.items()}}))
        if r.event_time_s is not None:
            event_mask = (r.event_time_s >= r.events['baseline_start']) & (r.event_time_s <= r.events['takeoff'])
            event_curves.append(pd.DataFrame({**identity, 'time_s': r.event_time_s[event_mask],
                                              'event_force_n': r.event_force_n[event_mask]}))
        point_mask = (r.point_time_s >= r.events['baseline_start']) & (r.point_time_s <= r.events['takeoff'])
        point_data = {}
        for suffix, data in [('angle_deg', r.angles_deg), ('angular_velocity_deg_s', r.angular_velocity_deg_s),
                             ('moment_nm_kg', r.moments_nm_per_kg), ('power_w_kg', r.powers_w_per_kg)]:
            point_data.update({f'{key}_{suffix}': values[point_mask] for key, values in data.items()})
        joint_curves.append(pd.DataFrame({**identity, 'time_s': r.point_time_s[point_mask], **point_data}))
        manifest.append({**identity, 'events': r.events, 'metrics': r.metrics, 'bottom_position': r.bottom_position,
                         'joint_metrics': r.joint_metrics, 'sequencing': r.sequencing, 'waveform': r.waveform,
                         'provenance': r.provenance, 'warnings': r.warnings})
    exports = []
    if event_curves:
        event_path = output.with_name(output.stem+'_raw_event_curves.csv')
        pd.concat(event_curves, ignore_index=True).to_csv(event_path, index=False)
        exports.append(('Native event-force curves CSV', event_path))
    for suffix, label, data in [('summary', 'Performance CSV', pd.DataFrame(summary)),
                               ('joints', 'Joint work & power CSV', pd.DataFrame(joints)),
                               ('events', 'Events CSV', pd.DataFrame(events)),
                               ('force_curves', 'Force & COM curves CSV', pd.concat(force_curves, ignore_index=True)),
                               ('joint_curves', 'Joint curves CSV', pd.concat(joint_curves, ignore_index=True))]:
        path = output.with_name(output.stem+'_'+suffix+'.csv')
        data.to_csv(path, index=False)
        exports.append((label, path))
    manifest_path = output.with_name(output.stem+'_analysis.json')
    from app.reporting.cmj_metadata import measurement_metadata
    date_label, date_source = measurement_metadata(results, measurement_date)
    manifest_path.write_text(json.dumps(_finite_json({
        'schema_version': 2, 'protocol': 'CMJ', 'subject': cfg.subject_name,
        'measurement_date': date_label, 'measurement_date_source': date_source,
        'settings': asdict(cfg.cmj), 'takeoff_threshold_n': cfg.threshold_n,
        'best_trial_id': next(i for i, r in enumerate(results, 1) if r is best),
        'skipped_files': list(errors), 'trials': manifest,
    }), ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    exports.append(('Complete analysis JSON', manifest_path))
    from app.reporting.cmj_performance import write_performance_pdf, render_performance_html
    pdf_path = output.with_suffix('.pdf')
    html_path = output.with_suffix('.html')
    extended_path = output.with_name(output.stem+'_extended.html')
    has_motion = any(r.angles_deg or r.joint_metrics for r in results)
    include_extended = report_mode in {'both', 'extended'} and has_motion
    if include_extended:
        extended_path.write_text(render_cmj_report_html(results, cfg, errors, exports,
                                                       measurement_date=measurement_date), encoding='utf-8')
    if report_mode in {'both', 'performance'}:
        write_performance_pdf(results, cfg, pdf_path, measurement_date)
        html_path.write_text(render_performance_html(results, cfg, pdf_path,
                                                      extended_path if include_extended else None,
                                                      measurement_date), encoding='utf-8')
        exports.append(('CMJ performance PDF', pdf_path))
    elif include_extended:
        html_path.write_text(extended_path.read_text(encoding='utf-8'), encoding='utf-8')
    else:
        raise ValueError('Extended CMJ reporting requires motion-analysis channels; use performance reporting for force-only data')
    return exports
