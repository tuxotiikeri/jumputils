"""Command-line orchestration for report generation."""

import argparse
from html import escape
import re
from pathlib import Path
from typing import List
from urllib.parse import quote

import numpy as np
import pandas as pd

from app.analysis.jump_metrics import process_trial
from app.analysis.cmj import process_cmj_trial
from app.c3d.cmj import read_cmj_trial, read_cmj_csv
from app.c3d.reader import read_c3d_trial, scan_trial_files
from app.config import Config
from app.protocols.cmj import CMJConfig, TRIAL_CMJ
from app.models import TrialResult
from app.protocols.common import (
    TRIAL_DJ,
    TRIAL_SDJ_L,
    TRIAL_SDJ_R,
    TRIAL_SDJ30_L,
    TRIAL_SDJ30_R,
    classify_trial,
    platform_cm_for_trial,
    trial_family_label,
)
from app.reporting.exports import write_contact_csvs
from app.reporting.formatting import fmt_date
from app.reporting.html import render_report_html
from app.reporting.cmj_exports import write_cmj_report
from app.utils import ensure_parent


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate Metropolia DJ/SDJ and CMJ reports from C3D and force-plate data.')
    parser.add_argument('folder', type=Path)
    parser.add_argument('--recursive', action='store_true')
    parser.add_argument('--protocol', choices=['auto', 'dj', 'cmj'], default='auto', help='Auto writes separate DJ/SDJ and CMJ reports when both are present.')
    parser.add_argument('--cmj-report', choices=['performance', 'extended', 'both'], default='performance', help='Default: raw-CSV performance PDF. Motion analysis requires an explicit extended/both selection.')
    parser.add_argument('--measurement-date', default=None, help='Override measurement date (YYYY-MM-DD).')
    parser.add_argument('--output', type=Path, default=Path('dropjump_report.html'))
    parser.add_argument('--subject', default='', help='Measured person shown on the report.')
    parser.add_argument('--summary-csv', type=Path, default=None, help='DJ/SDJ summary CSV path. Default: output folder / dropjump_summary.csv. CMJ exports use the CMJ HTML filename stem.')
    parser.add_argument('--contact-csv', type=Path, default=None, help='DJ/SDJ raw contact CSV path. Default: output folder / contact_phases_wide.csv. CMJ exports its own event table.')
    parser.add_argument('--raw-csv-folder', type=Path, default=None, help='Optional folder for raw Nexus force CSV files. Default: same folder as each C3D file.')
    parser.add_argument('--plate-left', type=int, default=4)
    parser.add_argument('--plate-right', type=int, default=3)
    parser.add_argument('--threshold', type=float, default=20.0)
    parser.add_argument('--min-contact', type=float, default=0.08)
    parser.add_argument('--merge-gap', type=float, default=0.02)
    parser.add_argument('--phase-points', type=int, default=101)
    parser.add_argument('--pelvis-tz-unit', choices=['mm', 'm'], default='mm')
    parser.add_argument('--force-sign-x', type=float, default=1.0)
    parser.add_argument('--force-sign-y', type=float, default=-1.0)
    parser.add_argument('--force-sign-z', type=float, default=-1.0)
    parser.add_argument('--filter-hz', type=float, default=15.0)
    parser.add_argument('--filter-order', type=int, default=4)
    parser.add_argument('--body-mass', type=float, default=None, help='Optional body mass override in kg. Used only if C3D body mass is missing or intentionally overridden.')
    parser.add_argument('--cmj-force-source', choices=['auto', 'csv', 'c3d'], default='auto', help='Performance reporting always uses raw CSV; auto/C3D dynamics are available only for explicit motion-analysis reports.')
    parser.add_argument('--cmj-force-plate-model', default='AMTI HPS400600', help='Force-plate model shown in CMJ metadata; sample rate is read from the actual force record.')
    parser.add_argument('--cmj-baseline-start', type=float, default=None, help='Quiet-standing start in seconds from force-record start; default auto-selects a stable interval before movement.')
    parser.add_argument('--cmj-baseline-duration', type=float, default=1.0)
    parser.add_argument('--cmj-baseline-max-cv', type=float, default=0.02, help='Quiet-standing force CV and trend limit; default 0.02 (2%).')
    parser.add_argument('--cmj-force-filter-hz', type=float, default=0.0, help='Additional force filter; default 0 preserves Nexus-filtered C3D or raw CSV.')
    parser.add_argument('--cmj-kinematic-filter-hz', type=float, default=10.0, help='CMJ angle/moment filter before differentiation; 0 disables.')
    parser.add_argument('--cmj-moment-unit', choices=['Nmm/kg', 'Nm/kg', 'Nmm', 'Nm'], default='Nmm/kg', help='Nexus laboratory profile is Nmm/kg even if C3D metadata says Nmm.')
    parser.add_argument('--cmj-moment-signs', nargs=3, type=float, choices=[-1.0, 1.0], default=[-1.0, -1.0, -1.0], metavar=('HIP', 'KNEE', 'ANKLE'), help='Convert exported moments to internal flexion/dorsiflexion-positive moments. Nexus external moments: -1 -1 -1.')
    parser.add_argument('--cmj-forward-axis', choices=['x', 'y'], default='x', help='Laboratory forward axis for rotation-only thorax fallback.')
    parser.add_argument('--cmj-forward-sign', type=float, choices=[-1.0, 1.0], default=1.0)
    args = parser.parse_args()
    if args.cmj_report != 'extended':
        if args.cmj_force_source == 'c3d':
            parser.error('CMJ performance reporting requires raw force CSV. C3D force is available only with --cmj-report extended.')
        args.cmj_force_source = 'csv'
    if args.measurement_date:
        from datetime import datetime
        try:
            datetime.strptime(args.measurement_date, '%Y-%m-%d')
        except ValueError:
            parser.error('--measurement-date must be YYYY-MM-DD')

    output_html = args.output
    summary_csv = args.summary_csv if args.summary_csv is not None else output_html.parent / 'dropjump_summary.csv'
    contact_csv = args.contact_csv if args.contact_csv is not None else output_html.parent / 'contact_phases_wide.csv'

    cfg = Config(
        cmj=CMJConfig(force_source=args.cmj_force_source, baseline_start_s=args.cmj_baseline_start,
                      force_plate_model=args.cmj_force_plate_model,
                      baseline_duration_s=args.cmj_baseline_duration,
                      baseline_max_cv=args.cmj_baseline_max_cv,
                      force_filter_hz=args.cmj_force_filter_hz, kinematic_filter_hz=args.cmj_kinematic_filter_hz,
                      moment_unit=args.cmj_moment_unit, moment_signs=tuple(args.cmj_moment_signs),
                      forward_axis=args.cmj_forward_axis, forward_sign=args.cmj_forward_sign),
        output_html=output_html,
        subject_name=args.subject,
        summary_csv=summary_csv,
        contact_csv=contact_csv,
        raw_csv_folder=args.raw_csv_folder,
        recursive=args.recursive,
        plate_left=args.plate_left,
        plate_right=args.plate_right,
        threshold_n=args.threshold,
        min_contact_s=args.min_contact,
        merge_gap_s=args.merge_gap,
        phase_points=args.phase_points,
        pelvis_tz_unit=args.pelvis_tz_unit,
        force_signs=np.array([args.force_sign_x, args.force_sign_y, args.force_sign_z], dtype=float),
        filter_hz=args.filter_hz,
        filter_order=args.filter_order,
        body_mass_override=args.body_mass,
    )

    files = scan_trial_files(args.folder, recursive=cfg.recursive)
    csv_candidates = args.folder.rglob('*') if cfg.recursive else args.folder.glob('*')
    c3d_stems = {(p.parent, p.stem.casefold()) for p in files}
    files += sorted(p for p in csv_candidates if p.suffix.lower() == '.csv'
                    and classify_trial(p.stem) == TRIAL_CMJ
                    and (p.parent, p.stem.casefold()) not in c3d_stems)
    if args.protocol != 'auto':
        files = [p for p in files if (classify_trial(p.stem) == TRIAL_CMJ) == (args.protocol == 'cmj')]
    if not files:
        raise SystemExit('No matching DJ/SDJ/CMJ C3D files found')

    results: List[TrialResult] = []
    cmj_results = []
    cmj_errors = []
    errors: List[str] = []
    for path in files:
        ttype = classify_trial(path.stem)
        if ttype is None:
            continue
        try:
            if ttype == TRIAL_CMJ:
                if path.suffix.lower() == '.c3d' and args.cmj_force_source == 'csv' and args.cmj_report == 'performance':
                    csv_path = (cfg.raw_csv_folder/path.with_suffix('.csv').name
                                if cfg.raw_csv_folder else path.with_suffix('.csv'))
                    if not csv_path.is_file() and csv_path.parent.is_dir():
                        csv_path = next((p for p in csv_path.parent.iterdir()
                                         if p.name.casefold() == csv_path.name.casefold()), csv_path)
                    if not csv_path.is_file():
                        raise ValueError(f'CMJ raw force CSV missing: {csv_path}. Export the unfiltered Nexus force data with the same trial name.')
                    signals = read_cmj_csv(csv_path, cfg)
                else:
                    reader = read_cmj_csv if path.suffix.lower() == '.csv' else read_cmj_trial
                    signals = reader(path, cfg)
                cmj_results.append(process_cmj_trial(signals, cfg))
                continue
            signals = read_c3d_trial(path, ttype, cfg)
            results.append(process_trial(signals, cfg))
        except Exception as exc:
            message = f'{path}: {exc}'
            errors.append(message)
            if ttype == TRIAL_CMJ:
                cmj_errors.append(message)

    if errors:
        print('Warnings / skipped files:')
        for err in errors:
            print(' -', err)

    if not results and not cmj_results:
        raise SystemExit('No trials were processed successfully. See the skipped-file reasons above; check force sources, CMJ quiet standing and plate selection.')
    if results and output_html.suffix.lower() == '.pdf':
        output_html = output_html.with_suffix('.html')
        cfg.output_html = output_html

    # Keep the requested output as the primary report; mixed folders get a
    # companion CMJ report, linked from the existing DJ page.
    cmj_output = None
    if cmj_results:
        cmj_output = output_html.with_name(output_html.stem + '_cmj.html') if results else output_html
        write_cmj_report(cmj_results, cfg, cmj_output, cmj_errors,
                         report_mode=args.cmj_report, measurement_date=args.measurement_date)
        print(f'Wrote CMJ report to {cmj_output.with_suffix(".pdf") if args.cmj_report != "extended" else cmj_output}')
        print(f'CMJ: {len(cmj_results)} trials; best height: {max(cmj_results, key=lambda r: r.metrics["jump_height_m"]).trial_name}')
    if not results:
        return 0

    dj_results = [r for r in results if r.trial_type == TRIAL_DJ]
    sdj_l_results = [r for r in results if r.trial_type == TRIAL_SDJ_L]
    sdj_r_results = [r for r in results if r.trial_type == TRIAL_SDJ_R]
    sdj30_l_results = [r for r in results if r.trial_type == TRIAL_SDJ30_L]
    sdj30_r_results = [r for r in results if r.trial_type == TRIAL_SDJ30_R]

    html = render_report_html(dj_results, sdj_l_results, sdj_r_results, sdj30_l_results, sdj30_r_results, cfg)
    if cmj_output is not None:
        link = f'<p class="meta-box"><a href="{quote(cmj_output.with_suffix(".pdf").name if args.cmj_report != "extended" else cmj_output.name)}">Open CMJ performance report · {len(cmj_results)} trials</a></p>'
        html = html.replace("<div class='brand-bar'></div>", "<div class='brand-bar'></div>" + link, 1)
    elif cmj_errors:
        note = '<div class="meta-box"><strong>CMJ files could not be analyzed</strong><ul>'+''.join('<li>'+escape(e)+'</li>' for e in cmj_errors)+'</ul></div>'
        html = html.replace("<div class='brand-bar'></div>", "<div class='brand-bar'></div>" + note, 1)
    ensure_parent(cfg.output_html)
    cfg.output_html.write_text(html, encoding='utf-8')

    if cfg.summary_csv:
        rows = []
        for r in results:
            rows.append({
                'subject_name': cfg.subject_name,
                'trial_type': r.trial_type,
                'trial_family': trial_family_label(r.trial_type),
                'platform_cm': platform_cm_for_trial(r.trial_type),
                'jump': re.sub(r'^(.*?)(\d+)$', r'#\2', r.trial_name),
                'trial_name': r.trial_name,
                'measurement_date': fmt_date(r.file_date),
                'contact_source': r.contact_source,
                'raw_csv': str(r.raw_csv_path),
                'raw_force_rate_hz': round(r.raw_force_rate_hz, 3),
                'contact_start_s': round(r.contact_start_s, 6),
                'takeoff_s': round(r.takeoff_s, 6),
                'ground_contact_ms': round(r.contact_time_s * 1000.0, 2),
                'jump_height_cm': round(r.jump_height_m * 100.0, 1),
                'rsi': round(r.rsi_m_per_s, 2),
                'com_displacement_cm': round(r.peak_com_disp_m * 100.0, 1),
                'vertical_stiffness_kn_per_m': round(r.vertical_stiffness_kn_per_m, 1),
                'spring_correlation': round(r.spring_correlation, 2),
                'peak_braking_force_timing_pct': round(r.peak_braking_force_timing_pct, 1),
                'braking_work_j_per_kg': round(r.braking_work_j_per_kg, 1),
                'propulsive_work_j_per_kg': round(r.propulsive_work_j_per_kg, 1),
            })
        ensure_parent(cfg.summary_csv)
        pd.DataFrame(rows).to_csv(cfg.summary_csv, index=False)

    if cfg.contact_csv:
        wide_path, long_path = write_contact_csvs(results, cfg.contact_csv, cfg.threshold_n)
        print(f'Wrote raw contact CSV to {wide_path}')
        print(f'Wrote raw contact long CSV to {long_path}')

    print(f'Wrote HTML report to {cfg.output_html}')
    if cfg.summary_csv:
        print(f'Wrote summary CSV to {cfg.summary_csv}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
