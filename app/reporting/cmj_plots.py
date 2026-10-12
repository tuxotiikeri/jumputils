"""CMJ figures, sharing the DJ report's palette and PNG embedding."""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from app.analysis.cmj import JOINTS, window
from app.reporting.plots import fig_to_base64
from app.reporting.style import LEFT_RED, RIGHT_BLUE, METROPOLIA_ORANGE, METROPOLIA_DARK

COLORS = {'Hip': '#087f8c', 'Knee': '#7651a8', 'Ankle': METROPOLIA_ORANGE, 'Thorax': METROPOLIA_DARK}
EVENTS = [('onset', 'Onset', '#53565a'), ('braking_start', 'Braking', '#9f4770'),
          ('com_bottom', 'COM bottom', '#087f8c'), ('takeoff', 'Take-off', METROPOLIA_ORANGE)]


def _style(ax, ylabel):
    ax.set_ylabel(ylabel)
    ax.grid(alpha=.18)
    ax.spines[['top', 'right']].set_visible(False)
    ax.axhline(0, color='#aaaaaa', linewidth=.7)


def _events(ax, r, labels=False):
    bottom = r.events['com_bottom']
    for key, name, color in EVENTS:
        ax.axvline((r.events[key]-bottom)*1000, color=color, ls='--', lw=1,
                   label=name if labels else None)
    ax.axvspan((r.events['braking_start']-bottom)*1000, 0, color='#9f4770', alpha=.05)
    ax.axvspan(0, (r.events['takeoff']-bottom)*1000, color='#087f8c', alpha=.05)


def force_com_figure(r):
    fig, axes = plt.subplots(4, 1, figsize=(11, 10), sharex=True, layout='constrained')
    start, end = r.events['onset']-.12, r.events['takeoff']+.04
    mask = (r.force_time_s >= start) & (r.force_time_s <= end)
    x = (r.force_time_s[mask]-r.events['com_bottom'])*1000
    for ax, key, label, scale in zip(axes, ['force_n', 'acceleration_m_s2', 'velocity_m_s', 'displacement_m'],
                                    ['Vertical GRF (N)', 'COM acceleration (m/s²)', 'COM velocity (m/s)', 'COM displacement (cm)'],
                                    [1, 1, 1, 100]):
        ax.plot(x, r.curves[key][mask]*scale, color=METROPOLIA_DARK, lw=1.7)
        _style(ax, label)
        _events(ax, r, labels=ax is axes[0])
    axes[0].plot(x, r.curves['raw_force_n'][mask], color='#9a9a9a', alpha=.4, lw=.7, label='C3D force used for COM')
    if r.event_time_s is not None:
        raw_mask = (r.event_time_s >= start) & (r.event_time_s <= end)
        axes[0].plot((r.event_time_s[raw_mask]-r.events['com_bottom'])*1000, r.event_force_n[raw_mask],
                     color='#7651a8', alpha=.65, lw=.8, label='Event force (CSV when available)')
    axes[0].axhline(r.metrics['quiet_standing_force_n']-r.metrics['force_offset_n'], color='#888', ls=':', label='Body weight')
    axes[0].legend(loc='upper left', ncols=3, fontsize=8)
    axes[0].set_title('Force → acceleration → velocity → displacement', loc='left', fontweight='bold')
    axes[-1].set_xlabel('Time from COM bottom (ms)')
    return fig_to_base64(fig)


def power_figure(r):
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), layout='constrained')
    for joint in JOINTS:
        power = r.powers_w_per_kg.get(joint)
        if power is None:
            continue
        for ax, start, end, normalize in [(axes[0], r.events['onset'], r.events['takeoff'], False),
                                          (axes[1], r.events['com_bottom'], r.events['takeoff'], True)]:
            t, y = window(r.point_time_s, power, start, end)
            x = (t-r.events['com_bottom']) / r.metrics['propulsion_time_s']*100 if normalize else (t-r.events['com_bottom'])*1000
            ax.plot(x, y, color=COLORS[joint], label=joint, lw=2)
        entry = r.joint_metrics.get(joint, {})
        x = entry.get('peak_positive_timing_pct', np.nan)
        y = entry.get('peak_positive_power_w_kg', np.nan)
        if np.isfinite(x) and np.isfinite(y):
            axes[1].scatter(x, y, color=COLORS[joint], s=40, zorder=5)
            axes[1].axvline(x, color=COLORS[joint], alpha=.4, ls=':')
    for ax in axes:
        _style(ax, 'Joint power (W/kg)')
        if ax.lines and ax.get_legend_handles_labels()[0]:
            ax.legend(loc='upper left', ncols=3)
    _events(axes[0], r)
    axes[0].set_xlabel('Time from COM bottom (ms)')
    axes[0].set_title('Bilateral power: hip, knee and ankle (L + R)', loc='left', fontweight='bold')
    axes[1].set_xlabel('Propulsion (%) · COM bottom = 0% · take-off = 100%')
    axes[1].set_xlim(0, 100)
    axes[1].set_title('Peak positive power sequencing', loc='left')
    if not any(j in r.powers_w_per_kg for j in JOINTS):
        axes[0].text(.5, .5, 'Bilateral powers unavailable — inspect side-specific data', transform=axes[0].transAxes, ha='center')
    return fig_to_base64(fig)


def kinematics_figure(r):
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), sharex=True, layout='constrained')
    for col, side in enumerate(['L', 'R']):
        for name in ('Thorax', *JOINTS):
            key = name if name == 'Thorax' else side+'_'+name
            for row, values in enumerate([r.angles_deg.get(key), r.angular_velocity_deg_s.get(key)]):
                if values is None:
                    continue
                t, y = window(r.point_time_s, values, r.events['onset'], r.events['takeoff'])
                axes[row, col].plot((t-r.events['com_bottom'])*1000, y if row == 0 else -y,
                                    color=COLORS[name], lw=1.6, label=name)
        axes[0, col].set_title(f'{"Left" if side == "L" else "Right"} joints + thorax', loc='left', fontweight='bold')
        if axes[0, col].get_legend_handles_labels()[0]:
            axes[0, col].legend(ncols=2, fontsize=8)
        for row, label in enumerate(['Flexion / forward tilt (°)', 'Extension / plantarflexion speed (°/s)']):
            _style(axes[row, col], label)
            _events(axes[row, col], r)
        axes[1, col].set_xlabel('Time from COM bottom (ms)')
    return fig_to_base64(fig)


def moments_figure(r):
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8), layout='constrained')
    for ax, joint in zip(axes, JOINTS):
        for side, color in [('L', LEFT_RED), ('R', RIGHT_BLUE)]:
            moment = r.moments_nm_per_kg.get(side+'_'+joint)
            if moment is not None:
                t, y = window(r.point_time_s, moment, r.events['onset'], r.events['takeoff'])
                ax.plot((t-r.events['com_bottom'])*1000, y, color=color, label=side)
        _style(ax, 'Internal moment (Nm/kg)')
        _events(ax, r)
        ax.set_title(joint)
        ax.set_xlabel('From COM bottom (ms)')
        if ax.get_legend_handles_labels()[0]:
            ax.legend()
    return fig_to_base64(fig)


def waveform_figure(r):
    fig, ax = plt.subplots(figsize=(11, 3.8), layout='constrained')
    bottom, takeoff = r.events['com_bottom'], r.events['takeoff']
    duration = takeoff-bottom
    t, y = window(r.force_time_s, r.curves['force_n'], bottom, takeoff)
    ax.plot((t-bottom)/duration*100, y, color=METROPOLIA_DARK, label='Propulsion GRF')
    for key, marker, color, label in [('peak_times_s', 'o', METROPOLIA_ORANGE, 'Resolved peak'),
                                     ('dip_times_s', 'v', '#7651a8', 'Local force / acceleration dip')]:
        stamps = np.asarray(r.waveform[key])
        ax.scatter((stamps-bottom)/duration*100, np.interp(stamps, t, y), marker=marker, color=color, label=label, zorder=4)
    ax.axhline(r.metrics['quiet_standing_force_n']-r.metrics['force_offset_n'], ls=':', color='#888', label='Body weight / zero acceleration')
    ax.set_title(r.waveform['description']+' · descriptive waveform', loc='left', fontweight='bold')
    ax.set_xlabel('Propulsion (%)')
    _style(ax, 'Vertical GRF (N)')
    ax.legend(fontsize=8, ncols=2)
    ax.set_xlim(0, 100)
    return fig_to_base64(fig)


def overlay_figure(results, best):
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8), layout='constrained')
    for r in results:
        for ax, key, label, scale in zip(axes, ['force_n', 'velocity_m_s', 'displacement_m'],
                                        ['GRF (N)', 'COM velocity (m/s)', 'COM displacement (cm)'], [1, 1, 100]):
            t, y = window(r.force_time_s, r.curves[key], r.events['com_bottom'], r.events['takeoff'])
            ax.plot((t-r.events['com_bottom'])/r.metrics['propulsion_time_s']*100, y*scale,
                    label=r.trial_name+(' · best height' if r is best else ''), lw=2.5 if r is best else 1)
            _style(ax, label)
            ax.set_xlabel('Propulsion (%)')
    axes[0].legend(fontsize=8)
    return fig_to_base64(fig)


def baseline_figure(r):
    fig, ax = plt.subplots(figsize=(11, 3.2), layout='constrained')
    mask = r.force_time_s <= r.events['takeoff']
    ax.plot(r.force_time_s[mask], r.curves['raw_force_n'][mask], color='#888', lw=.6, label='C3D force used for COM')
    if r.event_time_s is not None:
        raw_mask = r.event_time_s <= r.events['takeoff']
        ax.plot(r.event_time_s[raw_mask], r.event_force_n[raw_mask], color='#7651a8', lw=.7, label='Event force (CSV when available)')
    ax.axvspan(r.events['baseline_start'], r.events['baseline_end'], color='#087f8c', alpha=.2, label='Quiet-standing baseline')
    ax.axvline(r.events['onset'], color=METROPOLIA_ORANGE, ls='--', label='Detected onset')
    ax.set_xlabel('Force-record time (s)')
    ax.set_title('Baseline selection and movement onset', loc='left')
    _style(ax, 'Vertical GRF (N)')
    ax.legend(fontsize=8, ncols=3)
    return fig_to_base64(fig)
