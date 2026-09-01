"""HTML composition for the complete Drop Jump report."""

import html as html_lib
from typing import Sequence

import numpy as np

from app.analysis.averaging import aggregate_mean
from app.config import Config
from app.models import TrialResult
from app.reporting.formatting import fmt_mean_sd, fmt_num, infer_measurement_date
from app.reporting.plots import build_bar_figure_dj, build_bar_figure_sdj, build_biomech_figure
from app.reporting.style import METROPOLIA_DARK, METROPOLIA_GREY, METROPOLIA_ORANGE


def metric_card_html(title: str, value_html: str, sub_html: str = '') -> str:
    extra = f"<div class='metric-sub'>{sub_html}</div>" if sub_html else ''
    return f"<div class='metric-card'><div class='metric-label'>{title}</div><div class='metric-value'>{value_html}</div>{extra}</div>"

def compare_card_html(title: str, left_text: str, right_text: str, sub_html: str = '') -> str:
    value_html = f"<div class='stack-line'><span>Left</span><strong>{left_text}</strong></div><div class='stack-line'><span>Right</span><strong>{right_text}</strong></div>"
    return metric_card_html(title, value_html, sub_html)

def build_dj_cards(results: Sequence[TrialResult]) -> str:
    metrics = [
        ('Average ground contact time (ms)', [r.contact_time_s * 1000.0 for r in results], 0),
        ('Average jump height (cm)', [r.jump_height_m * 100.0 for r in results], 1),
        ('Average Reactive Strength Index (RSI)', [r.rsi_m_per_s for r in results], 2),
    ]
    cards = []
    for title, values, dec in metrics:
        sub = 'RSI = jump height / contact time' if 'Reactive Strength Index' in title else ''
        cards.append(metric_card_html(title, fmt_mean_sd(values, dec), sub))
    return "<div class='cards cards-three'>" + ''.join(cards) + "</div>"

def build_sdj_cards(left_results: Sequence[TrialResult], right_results: Sequence[TrialResult]) -> str:
    metrics = [
        ('Average ground contact time (ms)', [r.contact_time_s * 1000.0 for r in left_results], [r.contact_time_s * 1000.0 for r in right_results], 0),
        ('Average jump height (cm)', [r.jump_height_m * 100.0 for r in left_results], [r.jump_height_m * 100.0 for r in right_results], 1),
        ('Average Reactive Strength Index (RSI)', [r.rsi_m_per_s for r in left_results], [r.rsi_m_per_s for r in right_results], 2),
    ]
    cards = []
    for title, left_values, right_values, dec in metrics:
        sub = 'RSI = jump height / contact time' if 'Reactive Strength Index' in title else ''
        cards.append(compare_card_html(title, fmt_mean_sd(left_values, dec), fmt_mean_sd(right_values, dec), sub))

    l_mean = aggregate_mean([r.rsi_m_per_s for r in left_results])
    r_mean = aggregate_mean([r.rsi_m_per_s for r in right_results])
    if np.isfinite(l_mean) and np.isfinite(r_mean) and max(l_mean, r_mean) > 0:
        ref = 'Left' if l_mean >= r_mean else 'Right'
        lsi = 100.0 * min(l_mean, r_mean) / max(l_mean, r_mean)
        sub = f'Reference limb = {ref}; formula: lower mean RSI / higher mean RSI × 100'
    else:
        lsi = float('nan')
        sub = 'Formula: lower mean RSI / higher mean RSI × 100'
    cards.append(metric_card_html('Mean Limb Symmetry Index from RSI (%)', fmt_num(lsi, 1), sub))
    return "<div class='cards cards-sdj'>" + ''.join(cards) + "</div>"

def build_advanced_table_dj(results: Sequence[TrialResult]) -> str:
    rows = [
        ('Center of mass displacement (cm)', [r.peak_com_disp_m * 100.0 for r in results], 1),
        ('Vertical stiffness (kN/m)', [r.vertical_stiffness_kn_per_m for r in results], 1),
        ('Spring correlation', [r.spring_correlation for r in results], 2),
        ('Peak braking force timing (%)', [r.peak_braking_force_timing_pct for r in results], 1),
        ('Braking work (J/kg)', [r.braking_work_j_per_kg for r in results], 1),
        ('Propulsive work (J/kg)', [r.propulsive_work_j_per_kg for r in results], 1),
    ]
    body = ''.join(f"<tr><th>{label}</th><td>{fmt_mean_sd(values, dec)}</td></tr>" for label, values, dec in rows)
    return "<div class='table-card'><div class='table-title'>Advanced performance values</div><table class='metric-table'><thead><tr><th>Variable</th><th>Mean ± SD</th></tr></thead><tbody>" + body + "</tbody></table></div>"

def build_advanced_table_sdj(left_results: Sequence[TrialResult], right_results: Sequence[TrialResult]) -> str:
    rows = [
        ('Center of mass displacement (cm)', [r.peak_com_disp_m * 100.0 for r in left_results], [r.peak_com_disp_m * 100.0 for r in right_results], 1),
        ('Vertical stiffness (kN/m)', [r.vertical_stiffness_kn_per_m for r in left_results], [r.vertical_stiffness_kn_per_m for r in right_results], 1),
        ('Spring correlation', [r.spring_correlation for r in left_results], [r.spring_correlation for r in right_results], 2),
        ('Peak braking force timing (%)', [r.peak_braking_force_timing_pct for r in left_results], [r.peak_braking_force_timing_pct for r in right_results], 1),
        ('Braking work (J/kg)', [r.braking_work_j_per_kg for r in left_results], [r.braking_work_j_per_kg for r in right_results], 1),
        ('Propulsive work (J/kg)', [r.propulsive_work_j_per_kg for r in left_results], [r.propulsive_work_j_per_kg for r in right_results], 1),
    ]
    body = ''.join(f"<tr><th>{label}</th><td>{fmt_mean_sd(lvals, dec)}</td><td>{fmt_mean_sd(rvals, dec)}</td></tr>" for label, lvals, rvals, dec in rows)
    return "<div class='table-card'><div class='table-title'>Advanced performance values</div><table class='metric-table'><thead><tr><th>Variable</th><th>Left mean ± SD</th><th>Right mean ± SD</th></tr></thead><tbody>" + body + "</tbody></table></div>"

def figure_card_html(alt: str, image_b64: str) -> str:
    if not image_b64:
        return ''
    return f"<div class='figure-card'><img alt='{alt}' src='data:image/png;base64,{image_b64}'></div>"

def render_dj_section(dj_results: Sequence[TrialResult]) -> str:
    if not dj_results:
        return ''
    dj_bars = build_bar_figure_dj(dj_results, title='Drop Jump (30 cm platform) - Performance Values')
    dj_graphs = build_biomech_figure('Drop Jump (30 cm platform) - Biomechanical Graphs', dj_results, dj_results, mode='dj')
    dj_adv_table = build_advanced_table_dj(dj_results)
    return f"""
  <h2 class='section-title'>Drop Jump results (30 cm platform)</h2>
  {build_dj_cards(dj_results)}
  {dj_adv_table}
  {figure_card_html('Drop Jump performance values', dj_bars)}
  {figure_card_html('Drop Jump biomechanical graphs', dj_graphs)}
"""

def render_sdj_section(title: str, left_results: Sequence[TrialResult], right_results: Sequence[TrialResult], platform_cm: int) -> str:
    if not left_results and not right_results:
        return ''
    label = f'Single-Leg Drop Jump ({platform_cm} cm platform)'
    sdj_bars = build_bar_figure_sdj(left_results, right_results, title=f'{label} - Performance Values')
    sdj_graphs = build_biomech_figure(f'{label} - Biomechanical Graphs', left_results, right_results, mode='sdj')
    sdj_adv_table = build_advanced_table_sdj(left_results, right_results)
    return f"""
  <h2 class='section-title'>{title}</h2>
  {build_sdj_cards(left_results, right_results)}
  {sdj_adv_table}
  {figure_card_html(f'{label} performance values', sdj_bars)}
  {figure_card_html(f'{label} biomechanical graphs', sdj_graphs)}
"""

def render_report_html(
    dj_results: Sequence[TrialResult],
    sdj_l_results: Sequence[TrialResult],
    sdj_r_results: Sequence[TrialResult],
    sdj30_l_results: Sequence[TrialResult],
    sdj30_r_results: Sequence[TrialResult],
    cfg: Config,
) -> str:
    all_results = list(dj_results) + list(sdj_l_results) + list(sdj_r_results) + list(sdj30_l_results) + list(sdj30_r_results)
    measurement_date = infer_measurement_date(all_results)
    point_rate = aggregate_mean([r.point_rate_hz for r in all_results])
    force_rate = aggregate_mean([r.raw_force_rate_hz for r in all_results])
    point_rate_text = fmt_num(point_rate, 0) if np.isfinite(point_rate) else '150'
    force_rate_text = fmt_num(force_rate, 0) if np.isfinite(force_rate) else '1200'
    subject_name = html_lib.escape(cfg.subject_name.strip()) if cfg.subject_name.strip() else 'Not specified'

    sections = ''.join([
        render_dj_section(dj_results),
        render_sdj_section('Single-Leg Drop Jump results (15 cm platform)', sdj_l_results, sdj_r_results, platform_cm=15),
        render_sdj_section('Single-Leg Drop Jump results (30 cm platform)', sdj30_l_results, sdj30_r_results, platform_cm=30),
    ])
    if not sections.strip():
        sections = "<p class='muted'>No successfully processed DJ, SDJ or SDJ30 trials were found.</p>"

    html = f"""<!doctype html>
<html lang='en'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>{subject_name} - Drop Jump Performance Report</title>
<style>
  :root {{
    --orange: {METROPOLIA_ORANGE};
    --grey: {METROPOLIA_GREY};
    --dark: {METROPOLIA_DARK};
    --bg: #ffffff;
    --line: #ececec;
  }}
  body {{ margin:0; background:var(--bg); color:var(--dark); font-family:Inter, Arial, Helvetica, sans-serif; line-height:1.4; }}
  .page {{ max-width:1180px; margin:0 auto; padding:28px 28px 40px; }}
  .brand-bar {{ height:10px; background:var(--orange); border-radius:999px; margin-bottom:20px; }}
  .header {{ display:grid; grid-template-columns:1.55fr 1fr; gap:18px; align-items:start; margin-bottom:24px; }}
  .wordmark {{ font-family:'Space Grotesk', Arial, Helvetica, sans-serif; font-weight:700; letter-spacing:-0.02em; font-size:2.02rem; margin:0 0 6px 0; }}
  .wordmark .accent {{ color:var(--orange); }}
  .subtitle {{ font-family:'Space Grotesk', Arial, Helvetica, sans-serif; font-size:1.18rem; font-weight:700; margin:0 0 10px 0; }}
  .muted {{ color:var(--grey); }}
  .meta-box {{ border:1px solid var(--line); border-radius:16px; padding:16px 18px; }}
  .meta-grid {{ display:grid; grid-template-columns:1fr; gap:10px; font-size:0.94rem; }}
  .meta-item strong {{ display:block; margin-bottom:2px; }}
  h2.section-title {{ font-family:'Space Grotesk', Arial, Helvetica, sans-serif; font-weight:700; font-size:1.45rem; letter-spacing:-0.02em; margin:28px 0 12px; }}
  .cards {{ display:grid; gap:12px; margin:12px 0 18px; }}
  .cards-three {{ grid-template-columns:repeat(3, minmax(0, 1fr)); }}
  .cards-sdj {{ grid-template-columns:repeat(4, minmax(0, 1fr)); }}
  .metric-card {{ border:1px solid var(--line); border-top:4px solid var(--orange); border-radius:16px; padding:12px 14px; min-height:92px; background:#fff; }}
  .metric-label {{ font-size:0.82rem; color:var(--grey); margin-bottom:8px; }}
  .metric-value {{ font-family:'Space Grotesk', Arial, Helvetica, sans-serif; font-weight:700; font-size:1.18rem; line-height:1.2; color:var(--dark); }}
  .metric-sub {{ margin-top:6px; font-size:0.8rem; color:var(--grey); }}
  .stack-line {{ display:flex; justify-content:space-between; gap:12px; margin:2px 0; font-size:1rem; }}
  .stack-line span {{ font-weight:500; color:var(--grey); }}
  .stack-line strong {{ font-weight:700; color:var(--dark); }}
  .figure-card {{ border:1px solid var(--line); border-radius:20px; padding:14px; background:#fff; margin-bottom:18px; }}
  .figure-card img {{ width:100%; height:auto; display:block; }}
  .table-card {{ border:1px solid var(--line); border-radius:18px; padding:14px 16px; background:#fff; margin:8px 0 18px; }}
  .table-title {{ font-family:'Space Grotesk', Arial, Helvetica, sans-serif; font-weight:700; font-size:1.02rem; margin-bottom:10px; }}
  .metric-table {{ width:100%; border-collapse:collapse; font-size:0.92rem; }}
  .metric-table th, .metric-table td {{ border-top:1px solid var(--line); padding:9px 10px; text-align:left; }}
  .metric-table thead th {{ border-top:none; color:var(--grey); font-weight:700; }}
  .metric-table tbody th {{ font-weight:600; color:var(--dark); width:48%; }}
  .footer {{ margin-top:28px; padding-top:16px; border-top:1px solid var(--line); font-size:0.88rem; color:var(--grey); }}
  @media (max-width: 900px) {{ .header {{ grid-template-columns:1fr; }} .cards-three, .cards-sdj {{ grid-template-columns:repeat(1, minmax(0, 1fr)); }} }}
</style>
</head>
<body>
<div class='page'>
  <div class='brand-bar'></div>
  <div class='header'>
    <div>
      <p class='wordmark'><span class='accent'>Metropolia</span> Movement Laboratory</p>
      <p class='subtitle'>Drop Jump Performance Report</p>
      <p class='muted' style='margin:0;'>Metropolia Movement Laboratory<br>Myllypurontie 1, 00920 Helsinki<br>liikelaboratorio@metropolia.fi</p>
    </div>
    <div class='meta-box'>
      <div class='meta-grid'>
        <div class='meta-item'><strong>Measured person</strong>{subject_name}</div>
        <div class='meta-item'><strong>Measurement date</strong>{measurement_date}</div>
        <div class='meta-item'><strong>Movement information</strong>Collected with 8 FLIR Blackfly S cameras running at {point_rate_text} Hz.</div>
        <div class='meta-item'><strong>Force plates</strong>AMTI HPS400600 running at {force_rate_text} Hz.</div>
        <div class='meta-item'><strong>Analysis software</strong>Analyzed with Theia3D Axiom and Vicon Nexus 2.19.</div>
        <div class='meta-item'><strong>Signal processing</strong>All force signals and trajectories were low-pass filtered at 15 Hz using a zero-lag 4th order Butterworth filter.</div>
      </div>
    </div>
  </div>

{sections}

  <div class='footer'>
    <strong>Report notes and variable definitions.</strong> Ground contact is identified from raw force-plate CSV data when the vertical force exceeds {fmt_num(cfg.threshold_n, 0)} N and ends when it falls below {fmt_num(cfg.threshold_n, 0)} N. For bilateral drop jumps, the reported contact phase starts from the first limb contact and ends at the last limb take-off. Jump height is calculated from the vertical displacement of the center of mass (CoM) from raw-force-defined take-off to the first peak during flight. Peak CoM displacement timing is identified from the lowest CoM position reached during the raw-force-defined ground-contact phase and reported as a percentage of contact time. Whole-curve black difference bars are not shown because recent drop-jump literature does not provide a single robust clinical threshold for interpreting side-to-side curve differences across joint angles, moments, and GRF variables.<br><br>
    <strong>Reactive Strength Index (RSI).</strong> RSI is calculated as jump height divided by raw-force contact time. It describes how effectively the athlete transitions from landing to take-off; higher values generally indicate better reactive performance (Kipp et al. 2018; Struzik et al. 2016).<br><br>
    <strong>Limb Symmetry Index (LSI).</strong> LSI compares left and right limb performance. In this report, the Mean Limb Symmetry Index from RSI is calculated by dividing the lower mean RSI by the higher mean RSI and multiplying by 100. Values closer to 100% indicate more symmetrical performance.<br><br>
    <strong>Center of mass displacement.</strong> Center of mass displacement describes the maximal downward movement of the CoM during contact and helps describe the landing strategy used during the drop jump (Pedley et al. 2025; Kipp et al. 2018).<br><br>
    <strong>Vertical stiffness.</strong> Vertical stiffness expresses the relationship between peak vertical force and CoM displacement, reflecting spring-like behaviour of the lower limbs (Kipp et al. 2018; Horiuchi et al. 2022). Higher values usually indicate a stiffer and quicker spring-like response, whereas lower values indicate greater compliance.<br><br>
    <strong>Spring correlation.</strong> Spring correlation describes how closely the vertical force-time profile follows the CoM displacement profile during contact and has been used as a movement strategy variable in recent drop-jump work (Pedley et al. 2025; Kumar et al. 2025). Values closer to 1,00 indicate a more spring-like pattern, whereas lower values suggest a less consistent coupling between loading and CoM motion.<br><br>
    <strong>Peak braking force timing.</strong> Peak braking force timing indicates when the maximal braking force occurs within the contact phase and helps describe how quickly the athlete arrests downward motion after landing (Horiuchi et al. 2022; Pedley et al. 2025). Earlier timing may reflect a rapid braking strategy and a stiffer landing, while later timing may reflect a more prolonged absorption phase. Interpretation should always be made in relation to the athlete, the task, and the other variables in the report.<br><br>
    <strong>Braking work.</strong> Braking work reflects energy absorption during landing (Kipp et al. 2018; Pedley et al. 2025). Higher values indicate that more energy is absorbed during the braking phase.<br><br>
    <strong>Propulsive work.</strong> Propulsive work reflects energy generation during push-off (Kipp et al. 2018; Pedley et al. 2025). Higher values indicate greater positive work during the propulsion phase. Braking work and propulsive work should be interpreted together: higher braking work with relatively low propulsive work may indicate that more energy is absorbed than returned, while higher propulsive work relative to braking work suggests more effective push-off after landing.
  </div>
</div>
</body>
</html>
"""
    return html
