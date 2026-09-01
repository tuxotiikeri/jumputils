"""Matplotlib chart generation for report sections."""

import base64
import io
from typing import Optional, Sequence, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np

from app.analysis.averaging import aggregate_curves, aggregate_mean, grouped_pairs
from app.c3d.events import find_true_bouts
from app.models import TrialResult
from app.reporting.formatting import fmt_num
from app.reporting.style import (
    AXIS_LABEL_ANGLES,
    AXIS_LABEL_MOMENT,
    BAR_GREY,
    DECIMAL_FMT,
    GREY_DASH,
    LEFT_FILL,
    LEFT_RED,
    METROPOLIA_DARK,
    RIGHT_BLUE,
    RIGHT_FILL,
)


def nice_upper_limit(values: Sequence[float], default_upper: float, headroom: float) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float(default_upper)
    vmax = float(np.nanmax(arr))
    return float(default_upper if vmax <= default_upper else vmax + headroom)

def expand_ylim_to_data(default_ylim: Tuple[float, float], left: Optional[Tuple[np.ndarray, np.ndarray]], right: Optional[Tuple[np.ndarray, np.ndarray]], pad_fraction: float = 0.08) -> Tuple[float, float]:
    ymin, ymax = map(float, default_ylim)
    vals = []
    for item in (left, right):
        if item is None:
            continue
        mean_v, sd_v = item
        vals.append(np.asarray(mean_v, dtype=float) - np.asarray(sd_v, dtype=float))
        vals.append(np.asarray(mean_v, dtype=float) + np.asarray(sd_v, dtype=float))
    finite_vals = [v[np.isfinite(v)] for v in vals if np.isfinite(v).any()]
    if not finite_vals:
        return ymin, ymax
    arr = np.concatenate(finite_vals)
    data_min = float(np.nanmin(arr))
    data_max = float(np.nanmax(arr))
    if data_min < ymin:
        ymin = data_min - pad_fraction * max(abs(data_min), 1.0)
    if data_max > ymax:
        ymax = data_max + pad_fraction * max(abs(data_max), 1.0)
    return ymin, ymax

def get_default_ylim(title: str) -> Optional[Tuple[float, float]]:
    # Joint angles
    if title.startswith('Hip - Sagittal'):
        return (0.0, 80.0)
    if title.startswith('Hip - Frontal'):
        return (-13.0, 10.0)
    if title.startswith('Knee - Sagittal'):
        return (0.0, 85.0)
    if title.startswith('Knee - Frontal'):
        return (-6.0, 6.0)
    if title.startswith('Ankle - Sagittal'):
        return (-35.0, 35.0)

    # Joint moments
    if title.startswith('Hip moment - Sagittal'):
        return (-1.0, 5.0)
    if title.startswith('Knee moment - Sagittal'):
        return (-1.0, 5.0)
    if title.startswith('Ankle moment - Sagittal'):
        return (-1.0, 5.0)
    if title.startswith('Knee moment - Frontal'):
        return (-1.5, 1.5)

    # GRF is plotted as N/kg. The user-facing fixed scale request was in N-like magnitudes;
    # these defaults keep the normalized curves comparable and readable.
    if title.startswith('GRF vertical'):
        return (-2.0, 70.0)
    if title.startswith('GRF sagittal'):
        return (-5.0, 5.0)
    if title.startswith('GRF horizontal'):
        return (-5.0, 5.0)
    return None

def style_axis(ax, title: str, ylabel: str, ylim: Optional[Tuple[float, float]] = None) -> None:
    ax.set_title(title, fontsize=12, color=METROPOLIA_DARK, pad=9, fontweight='bold')
    ax.set_facecolor('white')
    ax.grid(False)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#8b8b8b')
    ax.spines['bottom'].set_color('#8b8b8b')
    ax.tick_params(colors=METROPOLIA_DARK, labelsize=10.5)
    ax.yaxis.set_major_formatter(DECIMAL_FMT)
    ax.xaxis.set_major_formatter(DECIMAL_FMT)
    ax.set_ylabel(ylabel, fontsize=10.5, color=METROPOLIA_DARK)
    if ylim is not None:
        ax.set_ylim(*ylim)

def compute_overlay_ylim(left: Optional[Tuple[np.ndarray, np.ndarray]], right: Optional[Tuple[np.ndarray, np.ndarray]]) -> Optional[Tuple[float, float]]:
    vals = []
    for item in (left, right):
        if item is None:
            continue
        mean_v, sd_v = item
        vals.append(np.asarray(mean_v, dtype=float) - np.asarray(sd_v, dtype=float))
        vals.append(np.asarray(mean_v, dtype=float) + np.asarray(sd_v, dtype=float))
    finite_vals = [v[np.isfinite(v)] for v in vals if np.isfinite(v).any()]
    if not finite_vals:
        return None
    arr = np.concatenate(finite_vals)
    ymin, ymax = float(np.min(arr)), float(np.max(arr))
    span = max(ymax - ymin, 1e-6)
    pad = 0.14 * span
    return ymin - pad, ymax + pad

def add_difference_bar(ax, left_mean: Optional[np.ndarray], right_mean: Optional[np.ndarray], threshold_pct: float = 10.0) -> None:
    if left_mean is None or right_mean is None:
        return
    l = np.asarray(left_mean, dtype=float)
    r = np.asarray(right_mean, dtype=float)
    scale = max(np.nanpercentile(np.abs(np.r_[l, r]), 95), 1e-6)
    denom = np.maximum(np.maximum(np.abs(l), np.abs(r)), 0.1 * scale)
    mask = 100.0 * np.abs(l - r) / denom > threshold_pct
    if not np.any(mask):
        return
    x = np.linspace(0, 100, len(l))
    ymin, ymax = ax.get_ylim()
    y = ymin + 0.04 * (ymax - ymin)
    for s, e in find_true_bouts(mask):
        ax.hlines(y, x[s], x[min(e - 1, len(x) - 1)], color='black', linewidth=4, zorder=6)

def plot_overlay(ax, left: Optional[Tuple[np.ndarray, np.ndarray]], right: Optional[Tuple[np.ndarray, np.ndarray]], title: str, ylabel: str, peak_left: Optional[float] = None, peak_right: Optional[float] = None, dashed_mode: str = 'none') -> None:
    style_axis(ax, title, ylabel)
    x = np.linspace(0, 100, 101)
    left_mean = None
    right_mean = None
    if left is not None:
        mean_l, sd_l = left
        left_mean = mean_l
        ax.fill_between(x, mean_l - sd_l, mean_l + sd_l, color=LEFT_FILL, linewidth=0)
        ax.plot(x, mean_l, color=LEFT_RED, linewidth=2.4)
    if right is not None:
        mean_r, sd_r = right
        right_mean = mean_r
        ax.fill_between(x, mean_r - sd_r, mean_r + sd_r, color=RIGHT_FILL, linewidth=0)
        ax.plot(x, mean_r, color=RIGHT_BLUE, linewidth=2.4)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    default_ylim = get_default_ylim(title)
    if default_ylim is not None:
        ax.set_ylim(*expand_ylim_to_data(default_ylim, left, right))
    else:
        ylim = compute_overlay_ylim(left, right)
        if ylim is not None:
            ax.set_ylim(*ylim)
    if dashed_mode == 'dj' and peak_left is not None and np.isfinite(peak_left):
        ax.axvline(peak_left, color=GREY_DASH, linestyle='--', linewidth=1.8, zorder=5)
    elif dashed_mode == 'sdj':
        if peak_left is not None and np.isfinite(peak_left):
            ax.axvline(peak_left, color=LEFT_RED, linestyle='--', linewidth=1.8, zorder=5)
        if peak_right is not None and np.isfinite(peak_right):
            ax.axvline(peak_right, color=RIGHT_BLUE, linestyle='--', linewidth=1.8, zorder=5)

def fig_to_base64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=180, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode('ascii')

def build_bar_figure_dj(results: Sequence[TrialResult], title: str = 'Drop Jump - Performance Values') -> str:
    fig, axes = plt.subplots(1, 3, figsize=(13.4, 4.6), facecolor='white')
    x = np.arange(len(results))
    labels = [f'#{i + 1}' for i in range(len(results))]
    gct_values = [r.contact_time_s * 1000.0 for r in results]
    jump_values = [r.jump_height_m * 100.0 for r in results]
    rsi_values = [r.rsi_m_per_s for r in results]
    specs = [
        ('Ground contact time (ms)', gct_values, (0, nice_upper_limit(gct_values, 400, 50)), 0),
        ('Jump height (cm)', jump_values, (0, nice_upper_limit(jump_values, 50, 5)), 1),
        ('Reactive Strength Index', rsi_values, (0, nice_upper_limit(rsi_values, 3.0, 0.5)), 2),
    ]
    for ax, (title, values, ylim, dec) in zip(axes, specs):
        style_axis(ax, title, '')
        ax.bar(x, values, color=BAR_GREY, width=0.72)
        ax.set_ylim(*ylim)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=10.5)
        ax.tick_params(axis='y', labelsize=10.5)
        for xi, yi in zip(x, values):
            ax.text(xi, yi + 0.025 * (ylim[1] - ylim[0]), fmt_num(yi, dec), ha='center', va='bottom', fontsize=10.5, color=METROPOLIA_DARK, fontweight='bold')
    fig.suptitle(title, fontsize=14, color=METROPOLIA_DARK, fontweight='bold', y=1.02)
    fig.tight_layout()
    return fig_to_base64(fig)

def build_bar_figure_sdj(left_results: Sequence[TrialResult], right_results: Sequence[TrialResult], title: str = 'Single-Leg Drop Jump - Performance Values') -> str:
    fig, axes = plt.subplots(1, 3, figsize=(13.4, 4.6), facecolor='white')
    keys, left_pairs, right_pairs = grouped_pairs(left_results, right_results)
    x = np.arange(len(keys))
    width = 0.48
    all_gct_values = [v for pair in (left_pairs, right_pairs) for r in pair for v in ([r.contact_time_s * 1000.0] if r else [])]
    all_jump_values = [v for pair in (left_pairs, right_pairs) for r in pair for v in ([r.jump_height_m * 100.0] if r else [])]
    all_rsi_values = [v for pair in (left_pairs, right_pairs) for r in pair for v in ([r.rsi_m_per_s] if r else [])]
    specs = [
        ('Ground contact time (ms)', lambda r: r.contact_time_s * 1000.0 if r else np.nan, (0, nice_upper_limit(all_gct_values, 400, 50)), 0),
        ('Jump height (cm)', lambda r: r.jump_height_m * 100.0 if r else np.nan, (0, nice_upper_limit(all_jump_values, 30, 5)), 1),
        ('Reactive Strength Index', lambda r: r.rsi_m_per_s if r else np.nan, (0, nice_upper_limit(all_rsi_values, 1.5, 0.5)), 2),
    ]
    for ax, (title, getter, ylim, dec) in zip(axes, specs):
        style_axis(ax, title, '')
        lvals = [getter(r) for r in left_pairs]
        rvals = [getter(r) for r in right_pairs]
        ax.bar(x - width/2, lvals, width=width, color=LEFT_RED)
        ax.bar(x + width/2, rvals, width=width, color=RIGHT_BLUE)
        ax.set_ylim(*ylim)
        ax.set_xticks(x)
        ax.set_xticklabels(keys, fontsize=10.5)
        ax.tick_params(axis='y', labelsize=10.5)
        for xi, yi in zip(x - width/2, lvals):
            if np.isfinite(yi):
                ax.text(xi, yi + 0.025 * (ylim[1] - ylim[0]), fmt_num(yi, dec), ha='center', va='bottom', fontsize=10.2, color=METROPOLIA_DARK, fontweight='bold')
        for xi, yi in zip(x + width/2, rvals):
            if np.isfinite(yi):
                ax.text(xi, yi + 0.025 * (ylim[1] - ylim[0]), fmt_num(yi, dec), ha='center', va='bottom', fontsize=10.2, color=METROPOLIA_DARK, fontweight='bold')
    handles = [Patch(facecolor=LEFT_RED, edgecolor='none', label='Left'), Patch(facecolor=RIGHT_BLUE, edgecolor='none', label='Right')]
    fig.legend(handles=handles, loc='upper center', frameon=False, ncol=2, bbox_to_anchor=(0.5, 1.03), fontsize=10.5)
    fig.suptitle(title, fontsize=14, color=METROPOLIA_DARK, fontweight='bold', y=1.10)
    fig.tight_layout()
    return fig_to_base64(fig)

def build_biomech_figure(title: str, left_results: Sequence[TrialResult], right_results: Sequence[TrialResult], mode: str) -> str:
    fig = plt.figure(figsize=(13.2, 13.6), facecolor='white')
    gs = GridSpec(4, 3, figure=fig, hspace=0.52, wspace=0.38)

    def kin_extractor_factory(joint: str, axis_idx: int):
        def _extractor(res: TrialResult, side: str):
            arr = res.normalized_kinematics.get(side, {}).get(joint)
            if arr is None or axis_idx >= arr.shape[1]:
                return None
            return arr[:, axis_idx]
        return _extractor

    def moment_extractor_factory(joint: str, axis_idx: int):
        def _extractor(res: TrialResult, side: str):
            arr = res.normalized_moments.get(f'{side}_{joint}')
            if arr is None or axis_idx >= arr.shape[1]:
                return None
            return arr[:, axis_idx]
        return _extractor

    def force_extractor_factory(axis_idx: int):
        def _extractor(res: TrialResult, side: str):
            arr = res.normalized_forces.get(side)
            if arr is None:
                return None
            vals = arr[:, axis_idx].copy()
            # Flip right ML/horizontal force for easier magnitude comparison.
            if axis_idx == 1 and side == 'R':
                vals = -vals
            return vals
        return _extractor

    peak_left = aggregate_mean([r.peak_com_disp_time_pct for r in left_results])
    peak_right = aggregate_mean([r.peak_com_disp_time_pct for r in right_results])

    plot_specs = [
        ('Hip - Sagittal (degrees)', 'Hip', 0, 'angle', AXIS_LABEL_ANGLES['X']),
        ('Hip - Frontal (degrees)', 'Hip', 1, 'angle', AXIS_LABEL_ANGLES['Y']),
        ('Hip moment - Sagittal (Nm/kg)', 'Hip', 0, 'moment', AXIS_LABEL_MOMENT['X']),
        ('Knee - Sagittal (degrees)', 'Knee', 0, 'angle', AXIS_LABEL_ANGLES['X']),
        ('Knee - Frontal (degrees)', 'Knee', 1, 'angle', AXIS_LABEL_ANGLES['Y']),
        ('Knee moment - Sagittal (Nm/kg)', 'Knee', 0, 'moment', AXIS_LABEL_MOMENT['X']),
        ('Ankle - Sagittal (degrees)', 'Ankle', 0, 'angle', AXIS_LABEL_ANGLES['X']),
        ('Knee moment - Frontal (Nm/kg)', 'Knee', 1, 'moment', AXIS_LABEL_MOMENT['Y']),
        ('Ankle moment - Sagittal (Nm/kg)', 'Ankle', 0, 'moment', AXIS_LABEL_MOMENT['X']),
        ('GRF vertical (N/kg)', None, 2, 'force', ''),
        ('GRF sagittal (N/kg)', None, 0, 'force', ''),
        ('GRF horizontal (N/kg)', None, 1, 'force', ''),
    ]

    for idx, (ptitle, joint, axis_idx, kind, ylabel) in enumerate(plot_specs):
        r, c = divmod(idx, 3)
        ax = fig.add_subplot(gs[r, c])
        if kind == 'angle':
            left = aggregate_curves(left_results, 'L', kin_extractor_factory(joint, axis_idx))
            right = aggregate_curves(right_results, 'R', kin_extractor_factory(joint, axis_idx))
            plot_overlay(ax, left, right, ptitle, ylabel)
        elif kind == 'moment':
            left = aggregate_curves(left_results, 'L', moment_extractor_factory(joint, axis_idx))
            right = aggregate_curves(right_results, 'R', moment_extractor_factory(joint, axis_idx))
            plot_overlay(ax, left, right, ptitle, ylabel)
        else:
            left = aggregate_curves(left_results, 'L', force_extractor_factory(axis_idx))
            right = aggregate_curves(right_results, 'R', force_extractor_factory(axis_idx))
            if ptitle.startswith('GRF vertical'):
                if mode == 'dj':
                    plot_overlay(ax, left, right, ptitle, ylabel, peak_left, None, 'dj')
                else:
                    plot_overlay(ax, left, right, ptitle, ylabel, peak_left, peak_right, 'sdj')
            else:
                plot_overlay(ax, left, right, ptitle, ylabel)
        if r == 3:
            ax.set_xlabel('Ground Contact (%)', fontsize=10.5, color=METROPOLIA_DARK)

    handles = [
        Line2D([0], [0], color=LEFT_RED, lw=2.4, label='Left mean'),
        Patch(facecolor=LEFT_FILL, edgecolor='none', label='Left ±1 SD'),
        Line2D([0], [0], color=RIGHT_BLUE, lw=2.4, label='Right mean'),
        Patch(facecolor=RIGHT_FILL, edgecolor='none', label='Right ±1 SD'),
    ]
    if mode == 'dj':
        handles.append(Line2D([0], [0], color=GREY_DASH, linestyle='--', lw=1.8, label='Peak CoM displacement timing'))
    else:
        handles.append(Line2D([0], [0], color=LEFT_RED, linestyle='--', lw=1.8, label='Peak CoM displacement timing - Left'))
        handles.append(Line2D([0], [0], color=RIGHT_BLUE, linestyle='--', lw=1.8, label='Peak CoM displacement timing - Right'))
    fig.legend(handles=handles, loc='upper center', frameon=False, ncol=4, bbox_to_anchor=(0.5, 1.02), fontsize=10)
    fig.suptitle(title, fontsize=15, color=METROPOLIA_DARK, fontweight='bold', y=1.065)
    return fig_to_base64(fig)
