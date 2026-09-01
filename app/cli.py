"""Command-line orchestration for report generation."""

import argparse
import re
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

from app.analysis.jump_metrics import process_trial
from app.c3d.reader import read_c3d_trial, scan_trial_files
from app.config import Config
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
from app.utils import ensure_parent


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate a Metropolia DJ/SDJ/SDJ30 report from C3D files and raw force CSV files.')
    parser.add_argument('folder', type=Path)
    parser.add_argument('--recursive', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('dropjump_report.html'))
    parser.add_argument('--subject', default='', help='Measured person shown on the report.')
    parser.add_argument('--summary-csv', type=Path, default=None, help='Optional summary CSV path. Default: output folder / dropjump_summary.csv')
    parser.add_argument('--contact-csv', type=Path, default=None, help='Optional raw contact CSV path. Default: output folder / contact_phases_wide.csv')
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
    args = parser.parse_args()

    output_html = args.output
    summary_csv = args.summary_csv if args.summary_csv is not None else output_html.parent / 'dropjump_summary.csv'
    contact_csv = args.contact_csv if args.contact_csv is not None else output_html.parent / 'contact_phases_wide.csv'

    cfg = Config(
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
    if not files:
        raise SystemExit('No DJ/SDJ/SDJ30 C3D files found')

    results: List[TrialResult] = []
    errors: List[str] = []
    for path in files:
        ttype = classify_trial(path.stem)
        if ttype is None:
            continue
        try:
            signals = read_c3d_trial(path, ttype, cfg)
            results.append(process_trial(signals, cfg))
        except Exception as exc:
            errors.append(f'{path.name}: {exc}')

    if errors:
        print('Warnings / skipped files:')
        for err in errors:
            print(' -', err)

    if not results:
        raise SystemExit('No trials were processed successfully. Check that matching raw CSV files exist for the C3D files.')

    dj_results = [r for r in results if r.trial_type == TRIAL_DJ]
    sdj_l_results = [r for r in results if r.trial_type == TRIAL_SDJ_L]
    sdj_r_results = [r for r in results if r.trial_type == TRIAL_SDJ_R]
    sdj30_l_results = [r for r in results if r.trial_type == TRIAL_SDJ30_L]
    sdj30_r_results = [r for r in results if r.trial_type == TRIAL_SDJ30_R]

    html = render_report_html(dj_results, sdj_l_results, sdj_r_results, sdj30_l_results, sdj30_r_results, cfg)
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
