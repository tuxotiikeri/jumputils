"""Standalone, self-contained CMJ strategy report using shared report components."""

from html import escape
from urllib.parse import quote
import numpy as np

from app.analysis.cmj import JOINTS
from app.reporting.formatting import fmt_num
from app.reporting.html import figure_card_html, metric_card_html
from app.reporting.style import METROPOLIA_ORANGE, METROPOLIA_DARK, METROPOLIA_GREY
from app.reporting.cmj_plots import (
    force_com_figure, kinematics_figure, moments_figure, overlay_figure,
    power_figure, waveform_figure, baseline_figure,
)

PERFORMANCE = [
    ('Jump height (cm)', 'jump_height_m', 100, 1),
    ('Take-off velocity (m/s)', 'takeoff_velocity_m_s', 1, 2),
    ('Time to take-off (ms)', 'time_to_takeoff_s', 1000, 0),
    ('RSI-mod (m/s)', 'rsi_mod_m_s', 1, 2),
    ('Braking net impulse (N·s)', 'braking_impulse_ns', 1, 1),
    ('Propulsive net impulse (N·s)', 'propulsive_impulse_ns', 1, 1),
    ('Peak vertical force (N)', 'peak_vertical_force_n', 1, 0),
    ('Peak vertical force (N/kg)', 'peak_vertical_force_n_kg', 1, 1),
    ('Countermovement depth (cm)', 'countermovement_depth_m', 100, 1),
    ('Braking time (ms)', 'braking_time_s', 1000, 0),
    ('Propulsion time (ms)', 'propulsion_time_s', 1000, 0),
    ('Peak downward COM velocity (m/s)', 'peak_downward_velocity_m_s', 1, 2),
]

REFERENCES = [
    ('Linthorne (2001) · force-platform integration and jump height', 'https://doi.org/10.1119/1.1397460'),
    ('McMahon et al. (2018) · CMJ force-time phases', 'https://doi.org/10.1519/SSC.0000000000000375'),
    ('Anicic et al. (2023) · multidimensional CMJ reporting', 'https://doi.org/10.3390/life13010190'),
    ('Harry et al. (2020) · joint-power and force-based phase definitions', 'https://pubmed.ncbi.nlm.nih.gov/31688643/'),
    ('Chiu et al. (2014) · proximal-to-distal sequencing', 'https://doi.org/10.1519/JSC.0000000000000388'),
    ('Bobbert & van Ingen Schenau (1988) · coordination in vertical jumping', 'https://doi.org/10.1016/0021-9290(88)90175-3'),
    ('Hubley & Wells (1983) · joint work contributions', 'https://doi.org/10.1007/BF00422163'),
    ('Vanrenterghem et al. (2008) · trunk inclination and joint power', 'https://doi.org/10.1519/JSC.0b013e3181636c6c'),
    ('Kennedy & Drake (2018) · propulsion force waveform', 'https://doi.org/10.3390/sports6020036'),
    ('Vicon · Nexus moment normalization and external-moment convention', 'https://help.vicon.com/download/attachments/406490967/Plug-in%20Gait%20Reference%20Guide.pdf'),
]


def table(headers, rows, title=''):
    head = ''.join(f'<th scope="col">{escape(str(h))}</th>' for h in headers)
    def cell(i, value):
        tag = 'th' if i == 0 else 'td'
        scope = ' scope="row"' if i == 0 else ''
        return f'<{tag}{scope}>{escape(str(value))}</{tag}>'
    body = ''.join('<tr>'+''.join(cell(i, v) for i, v in enumerate(row))+'</tr>' for row in rows)
    return (f'<div class="table-card"><div class="table-title">{escape(title)}</div>'
            f'<div class="table-scroll"><table class="metric-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div></div>')


def sample_summary(values, decimals=1):
    values = np.asarray(values, float)
    values = values[np.isfinite(values)]
    if not len(values):
        return '-'
    sd = np.std(values, ddof=1) if len(values) > 1 else float('nan')
    return f'{fmt_num(np.mean(values), decimals)} ± {fmt_num(sd, decimals)}'


def joint_table(r, phase, scope=''):
    negative = phase == 'braking'
    sign = 'negative' if negative else 'positive'
    headers = ['Joint', f'{sign.title()} work (J/kg)', f'Peak {sign} power (W/kg)', 'From COM bottom (ms)', 'Propulsion time (%)']
    if not negative:
        headers.append('Positive work contribution (%)')
    rows = []
    for joint in JOINTS:
        entry = r.joint_metrics.get(scope+joint, {})
        keys = [f'{phase}_{sign}_work_j_kg', f'peak_{sign}_power_w_kg', f'peak_{sign}_timing_ms', f'peak_{sign}_timing_pct']
        if not negative:
            keys.append('positive_work_contribution_pct')
        rows.append([joint]+[fmt_num(entry.get(k, np.nan), 2 if 'work_j' in k else 1) for k in keys])
    return table(headers, rows, (scope.replace('_', '') or 'Bilateral L + R')+' · '+phase.title())


def sequence_table(r, scope='bilateral'):
    sequence = r.sequencing.get(scope, {})
    rows = [[f'{j} peak positive power', fmt_num(sequence.get(j+'_peak_ms', np.nan)),
             fmt_num(sequence.get(j+'_peak_pct', np.nan))] for j in JOINTS]
    rows += [[f'Δt {a} → {b}', fmt_num(sequence.get(f'{a}_to_{b}_ms', np.nan)),
              fmt_num(sequence.get(f'{a}_to_{b}_pct', np.nan))] for a, b in [('Hip', 'Knee'), ('Knee', 'Ankle'), ('Hip', 'Ankle')]]
    return table(['Power sequence', 'From bottom / difference (ms)', 'Propulsion time / difference (%)'], rows,
                 'Bilateral L + R' if scope == 'bilateral' else scope[0])


def trial_section(r, index, best):
    name = escape(r.trial_name)
    warnings = '<ul>'+''.join(f'<li>{escape(w)}</li>' for w in r.warnings)+'</ul>' if r.warnings else '<p>No analysis warnings.</p>'
    positions = [
        ['COM depth (cm)', fmt_num(r.metrics['countermovement_depth_m']*100), ''],
        ['Thorax forward inclination (°)', fmt_num(r.bottom_position.get('Thorax', np.nan)), ''],
        ['Trunk relative to pelvis (°)', fmt_num(r.bottom_position.get('TrunkRelativePelvis', np.nan)), ''],
    ] + [[j+(' dorsiflexion (°)' if j == 'Ankle' else ' flexion (°)'),
          fmt_num(r.bottom_position.get('L_'+j, np.nan)), fmt_num(r.bottom_position.get('R_'+j, np.nan))] for j in JOINTS]
    gains = [[f'{a}–{b}%', fmt_num(r.metrics[f'velocity_gain_{a}_{b}_m_s'], 3),
              fmt_num(r.metrics[f'velocity_gain_{a}_{b}_pct'], 1)] for a, b in [(0, 25), (25, 50), (50, 75), (75, 100)]]
    whole_work = [[j]+[fmt_num(r.joint_metrics.get(j, {}).get(key, np.nan), 2)
                       for key in ['movement_negative_work_j_kg', 'movement_positive_work_j_kg']]
                  for j in JOINTS]
    extension_rows = []
    for key in ['Thorax', 'L_Hip', 'R_Hip', 'L_Knee', 'R_Knee', 'L_Ankle', 'R_Ankle']:
        entry = r.sequencing.get(key+'_extension', {})
        extension_rows.append([key.replace('_', ' ')]+[fmt_num(entry.get(k, np.nan)) for k in ['peak_deg_s', 'timing_ms', 'timing_pct']])
    timing_rows = [[label, fmt_num(value, 4), fmt_num((value-r.events['com_bottom'])*1000, 1)] for label, value in r.events.items()]
    dip_rows = [[fmt_num((t-r.events['com_bottom'])*1000), fmt_num(force, 0), fmt_num(acc, 2)]
                for t, force, acc in zip(r.waveform['dip_times_s'], r.waveform['dip_forces_n'], r.waveform['dip_accelerations_m_s2'])]
    provenance = ''.join(f'<dt>{escape(k)}</dt><dd>{escape(v)}</dd>' for k, v in r.provenance.items())
    return f'''<details class="trial" id="trial-{index}" {'open' if r is best else ''}>
      <summary>{name} <span class="trial-stat">{fmt_num(r.metrics['jump_height_m']*100)} cm · {"Best jump height" if r is best else "Trial strategy profile"}</span></summary>
      <div class="trial-body">
      <h3>2. Force &amp; COM strategy</h3>
      <p>Upward motion is positive. COM displacement is relative to quiet standing. Dashed lines synchronize the phase events.</p>
      {figure_card_html('Synchronized vertical GRF, COM acceleration, velocity and displacement', force_com_figure(r))}
      {table(['Propulsion interval', 'Net velocity gain (m/s)', 'Share of take-off velocity (%)'], gains, 'Where take-off velocity accumulates')}
      <p class="muted">Signed net gains can be negative when acceleration falls below zero; contributions are not forced to increase monotonically.</p>
      <h3>3. Position at COM bottom</h3>
      {table(['Position', 'Left / whole body', 'Right'], positions)}
      <h3>4. Eccentric / braking strategy</h3>
      <p>Braking starts at peak downward COM velocity and ends at COM bottom. Negative values indicate net joint energy absorption. Individual joints can generate power while the whole body is braking.</p>
      {joint_table(r, 'braking')}
      <details><summary>Left and right braking results</summary>{joint_table(r, 'braking', 'L_')}{joint_table(r, 'braking', 'R_')}</details>
      <h3>5. Propulsion strategy</h3>
      <p>COM bottom = 0%, take-off = 100%. Work sums left and right limb contributions before calculating joint shares. Peak powers refer to the summed bilateral power curve.</p>
      {joint_table(r, 'propulsion')}
      <details><summary>Left and right propulsion results</summary>{joint_table(r, 'propulsion', 'L_')}{joint_table(r, 'propulsion', 'R_')}</details>
      {table(['Joint', 'Negative work (J/kg)', 'Positive work (J/kg)'], whole_work, 'Whole movement · onset to take-off')}
      <p class="muted">Work shares use only hip + knee + ankle positive work in propulsion, and require both limbs for all three joints. They do not describe the fraction of total-body or muscle work.</p>
      {figure_card_html('Internal sagittal hip knee ankle moments for left and right limbs', moments_figure(r))}
      <h3>6. Sequencing</h3>
      {figure_card_html('Hip knee ankle power peaks and propulsion sequencing', power_figure(r))}
      {sequence_table(r)}
      <details><summary>Left and right power sequences</summary>{sequence_table(r, 'L_')}{sequence_table(r, 'R_')}</details>
      <p>Positive Δt means that the second joint peaks later; negative Δt means it peaks earlier. These are descriptions of coordination, with no preferred timing score.</p>
      {figure_card_html('Thorax and sagittal joint angles and extension angular velocities', kinematics_figure(r))}
      {table(['Segment / joint', 'Peak extension speed (°/s)', 'From COM bottom (ms)', 'Propulsion time (%)'], extension_rows, 'Kinematic sequence · extension / plantarflexion positive')}
      <p class="muted">Thorax timing uses peak forward-tilt reversal speed (extension), not joint power. Kinematic and power peak sequences measure different events. Trunk relative to pelvis follows the source convention shown below.</p>
      <h3>7. GRF waveform</h3>
      {figure_card_html('Propulsion GRF peaks and local force acceleration dips', waveform_figure(r))}
      <p>Peak GRF over onset to take-off: <strong>{fmt_num(r.metrics['peak_vertical_force_n'], 0)} N</strong>, at <strong>{fmt_num(r.metrics['peak_force_timing_ms'])} ms</strong> from COM bottom. Propulsion waveform: <strong>{escape(r.waveform['description'])}</strong>.</p>
      {table(['Dip from COM bottom (ms)', 'Force (N)', 'COM acceleration (m/s²)'], dip_rows or [['None resolved', '-', '-']], 'Propulsion force / acceleration dips')}
      <p class="muted">Peak prominence ≥ {fmt_num(r.waveform['prominence_n'])} N; minimum peak separation {fmt_num(r.waveform['minimum_peak_distance_ms'], 0)} ms. COM-bottom boundary peaks are included. Shape depends on filtering and detection settings; one or two peaks are not automatically good or bad.</p>
      <details class="quality"><summary>Trial data quality, events and calculation sources</summary>
      {warnings}
      {figure_card_html('Quiet-standing baseline and detected movement onset', baseline_figure(r))}
      {table(['Event', 'Recording time (s)', 'From COM bottom (ms)'], timing_rows)}
      {table(['Baseline / normalization', 'Value'], [[k, fmt_num(r.metrics[k], 3)] for k in ['body_mass_kg', 'quiet_standing_force_n', 'baseline_sd_n', 'force_offset_n', 'onset_threshold_n']])}
      <dl>{provenance}</dl>
      </details>
      </div></details>'''


def render_cmj_report_html(results, cfg, errors=(), downloads=(), measurement_date=None):
    from app.reporting.cmj_metadata import measurement_metadata, filter_metadata
    date_text, date_source = measurement_metadata(results, measurement_date)
    if not results:
        raise ValueError('Cannot render a CMJ report without valid trials')
    best = max(results, key=lambda r: r.metrics['jump_height_m'])
    rows, cards = [], []
    for label, key, scale, decimals in PERFORMANCE:
        values = [r.metrics[key]*scale for r in results]
        rows.append([label, sample_summary(values, decimals)]+[fmt_num(v, decimals) for v in values])
        if key in {'jump_height_m', 'takeoff_velocity_m_s', 'rsi_mod_m_s', 'countermovement_depth_m'}:
            cards.append(metric_card_html(escape(label), sample_summary(values, decimals), 'Mean ± SD'))
    errors_html = ('<aside class="notice"><strong>Skipped files</strong><ul>'+''.join(f'<li>{escape(e)}</li>' for e in errors)+'</ul></aside>') if errors else ''
    sections = ''.join(trial_section(r, i, best) for i, r in enumerate(results, 1))
    links = ' · '.join(f'<a href="#trial-{i}">{escape(r.trial_name)}</a>' for i, r in enumerate(results, 1))
    downloads_html = ' · '.join(f'<a href="{quote(path.name)}" download>{escape(label)}</a>' for label, path in downloads)
    refs = ''.join(f'<li><a href="{url}">{escape(label)}</a></li>' for label, url in REFERENCES)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(cfg.subject_name or 'Measured person')} · CMJ performance report</title>
    <style>
    :root {{ --orange:{METROPOLIA_ORANGE}; --dark:{METROPOLIA_DARK}; --grey:{METROPOLIA_GREY}; --line:#ececec; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:white; color:var(--dark); font-family:Inter,Arial,Helvetica,sans-serif; line-height:1.5; }}
    .page {{ max-width:1180px; margin:auto; padding:28px; }}
    .brand-bar {{ height:10px; background:var(--orange); border-radius:999px; margin-bottom:24px; }}
    .header {{ display:grid; grid-template-columns:1.5fr 1fr; gap:24px; align-items:start; }}
    .wordmark {{ font-size:1.65rem; font-weight:700; letter-spacing:-.02em; margin:0; }}
    .accent {{ color:var(--orange); }} h1 {{ font-size:1.65rem; margin:8px 0; }}
    h2 {{ font-size:1.45rem; margin:30px 0 14px; }} h3 {{ font-size:1.2rem; margin:30px 0 12px; }}
    .muted,.metric-sub {{ color:var(--grey); font-size:.88rem; }}
    .meta-box,.table-card,.figure-card {{ border:1px solid var(--line); border-radius:16px; padding:16px; margin:14px 0; }}
    .cards {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:20px 0; }}
    .metric-card {{ border:1px solid var(--line); border-top:4px solid var(--orange); border-radius:16px; padding:14px; }}
    .metric-label {{ color:var(--grey); font-size:.85rem; }} .metric-value {{ font-size:1.35rem; font-weight:700; margin:8px 0; }}
    .metric-sub {{ font-size:.78rem; }} .table-title {{ font-weight:700; margin-bottom:10px; }}
    .table-scroll {{ overflow-x:auto; }} .metric-table {{ width:100%; border-collapse:collapse; font-size:.86rem; }}
    th,td {{ border-top:1px solid var(--line); padding:9px 10px; text-align:right; }}
    th:first-child,td:first-child {{ text-align:left; }} thead th {{ color:var(--grey); border-top:0; }}
    .figure-card img {{ width:100%; height:auto; display:block; }}
    details {{ margin:12px 0; }} summary {{ cursor:pointer; font-weight:700; padding:12px 0; }}
    details.trial {{ border:1px solid var(--line); border-radius:18px; margin:20px 0; }}
    .trial>summary {{ padding:18px; background:#fafafa; border-radius:18px; font-size:1.1rem; }}
    .trial-stat {{ display:block; font-weight:400; color:var(--grey); font-size:.9rem; margin-left:20px; }}
    .trial-body {{ padding:0 18px 18px; }} a {{ color:#b83a00; text-underline-offset:3px; }}
    .notice {{ background:#fff7ee; border-left:4px solid var(--orange); padding:14px 18px; margin:16px 0; }}
    .quality {{ border-top:1px solid var(--line); }} dt {{ font-weight:700; margin-top:12px; }} dd {{ margin:4px 0; overflow-wrap:anywhere; font-size:.85rem; }}
    footer {{ border-top:1px solid var(--line); margin-top:28px; padding-top:16px; font-size:.9rem; }}
    @media(max-width:800px) {{ .header {{ grid-template-columns:1fr; }} .cards {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .page {{ padding:16px; }} .trial-body {{ padding:0 10px 12px; }} }}
    @media(max-width:420px) {{ .cards {{ grid-template-columns:1fr; }} }}
    @media print {{ .page {{ max-width:none; padding:0; }} details.trial>summary {{ break-after:avoid; }} .figure-card,.table-card {{ break-inside:avoid; }} }}
    </style></head><body><main class="page"><div class="brand-bar"></div>
    <header class="header"><div><p class="wordmark"><span class="accent">Metropolia</span> Movement Laboratory</p>
    <h1>CMJ performance report</h1><p class="muted">Extended movement analysis</p></div>
    <div class="meta-box"><strong>Measured person</strong><br>{escape(cfg.subject_name or 'Not specified')}<br><br>
    <strong>Included trials</strong><br>{len(results)}<br><br>
    <strong>Measurement date</strong><br>{date_text}<br><br><strong>Filtering</strong><br>{'<br>'.join(escape(t) for t in filter_metadata(results,cfg))}<br>
    Kinematics: {cfg.cmj.kinematic_filter_hz:g} Hz</div></header>
    <h2>1. Performance</h2><div class="cards">{''.join(cards)}</div>
    {table(['Variable', 'Mean ± SD']+[r.trial_name for r in results], rows, 'Summary')}
    <p class="muted">Sample SD uses n − 1; SD is unavailable for one trial. Jump height = v² / (2g), measured from take-off COM height to the ballistic apex. RSI-mod = jump height / movement-onset-to-take-off time.</p>
    {figure_card_html('Propulsion overlay across every CMJ trial, best height emphasized', overlay_figure(results, best))}
    <h2>Trial strategy profiles</h2><p>Open a trial below to inspect its full profile. The best trial is open initially. {links}</p>
    {sections}
    <footer><h2>Methods &amp; interpretation</h2>
      <p>Whole-body COM comes from the selected C3D force plates: a = (ΣFz − mg) / m; velocity and displacement use trapezoidal integration from quiet standing with v = 0 and displacement = 0. The C3D force is assumed to be the Nexus-filtered signal. When a matching CSV is present, its raw force is retained separately for event detection and quality control; it is not used for COM integration and is not filtered again. No pelvis displacement is used as whole-body COM.</p>
    <p>Quiet-standing interval: {cfg.cmj.baseline_duration_s:g} s; {'automatic stable-interval selection' if cfg.cmj.baseline_start_s is None else 'manual start'}.
    Movement onset is the first force deviation exceeding max({cfg.cmj.onset_sd:g} × baseline SD, {cfg.cmj.onset_bw_fraction*100:g}% body weight, 10 N), sustained for {cfg.cmj.onset_hold_s*1000:g} ms. Take-off is the raw total-force crossing below {cfg.threshold_n:g} N followed by at least {cfg.cmj.flight_hold_s*1000:g} ms unloaded. Braking begins at minimum downward COM velocity; COM bottom is the interpolated upward velocity zero crossing. Propulsion ends at take-off. Both reported impulses are net impulses ∫(Fz − mg)dt.</p>
    <p>Sagittal joint power = internal moment × sagittal angular velocity (radians/s). This is a sagittal approximation, not full 3D vector power. Negative work = ∫min(P,0)dt; positive work = ∫max(P,0)dt, with zero crossings and phase boundaries included. Braking work covers braking only; the whole-movement table additionally covers unweighting. Missing phase coverage yields unavailable values, never zero or an extrapolated curve.</p>
    <p>Negative joint work is not a direct estimate of tendon elastic energy. Net joint moments and powers do not isolate individual muscles. Waveform shape and proximal-to-distal timing describe strategy; this report provides no automatic coaching diagnosis or good/bad score. Thorax angular-velocity timing is reported separately from lower-limb power timing.</p>
    <p>Small quiet-standing force errors influence integrated displacement, velocity and height. Inspect the reported baseline and event times when comparing trials. Filtering, moment units, sign conversion and source channels are recorded separately for each trial.</p>
    <p><strong>Data exports:</strong> {downloads_html}</p><details><summary>Research and export conventions</summary><ul>{refs}</ul><p>Date source: {escape(date_source)}</p>{errors_html}</details>
    </footer></main></body></html>'''
