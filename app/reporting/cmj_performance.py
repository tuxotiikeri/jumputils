"""Athlete-facing CMJ performance PDF and HTML using the DJ report identity."""

from io import BytesIO
from html import escape
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.analysis.cmj import window
from app.reporting.cmj_html import PERFORMANCE, sample_summary
from app.reporting.cmj_metadata import measurement_metadata
from app.reporting.formatting import fmt_num
from app.reporting.html import figure_card_html, metric_card_html
from app.reporting.plots import fig_to_base64
from app.reporting.style import METROPOLIA_ORANGE, METROPOLIA_DARK, METROPOLIA_GREY

TITLE = 'CMJ Performance Report'
CARD_METRICS = [
    ('Jump height (cm)', 'jump_height_m', 100, 1),
    ('Take-off velocity (m/s)', 'takeoff_velocity_m_s', 1, 2),
    ('RSI-mod (m/s)', 'rsi_mod_m_s', 1, 2),
    ('Countermovement depth (cm)', 'countermovement_depth_m', 100, 1),
]
CALCULATION_NOTES = [
    'Jump height calculated as take-off velocity² / (2g).',
    'RSI-mod calculated as jump height / time from movement onset to take-off.',
]


def peak_label(index, count):
    return ('First Peak' if index == 0 else 'Second Peak') if count > 1 else 'Peak GRF'


def annotate_force_peak(ax, x, force, label):
    ax.scatter(x, force, s=26, facecolor='white', edgecolor=METROPOLIA_ORANGE, linewidth=1.3, zorder=5)
    ax.annotate(f'{label}: {fmt_num(force, 0)} N', (x, force), xytext=(0, -22),
                textcoords='offset points', ha='center', va='top', fontsize=8, color=METROPOLIA_ORANGE,
                arrowprops={'arrowstyle': '-', 'color': METROPOLIA_ORANGE, 'lw': .7})


def report_fonts():
    """The same embedded font in PDF text and figures; Arial matches the DJ UI."""
    import reportlab
    regular, bold = Path('C:/Windows/Fonts/arial.ttf'), Path('C:/Windows/Fonts/arialbd.ttf')
    if not regular.is_file() or not bold.is_file():
        directory = Path(reportlab.__file__).parent/'fonts'
        regular, bold = directory/'Vera.ttf', directory/'VeraBd.ttf'
    for name, path in [('JumputilsSans', regular), ('JumputilsSans-Bold', bold)]:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(path)))
    pdfmetrics.registerFontFamily('JumputilsSans', normal='JumputilsSans', bold='JumputilsSans-Bold')
    font_manager.fontManager.addfont(str(regular))
    font_manager.fontManager.addfont(str(bold))
    return font_manager.FontProperties(fname=str(regular)).get_name()


def best_trial(results):
    return max(results, key=lambda r: r.metrics['jump_height_m'])


def athlete_metadata(results, cfg, measurement_date=None):
    date, _ = measurement_metadata(results, measurement_date)
    mass = cfg.body_mass_override if cfg.body_mass_override is not None else float(np.mean([r.metrics['body_mass_kg'] for r in results]))
    c3d = any('C3D' in r.provenance.get('force_source', '') for r in results)
    filtering = '15 Hz Butterworth (Nexus)' if c3d else 'Unfiltered force'
    if cfg.cmj.force_filter_hz:
        filtering += f'; additional {cfg.cmj.force_filter_hz:g} Hz'
    rates = sorted({round(1/np.median(np.diff(r.force_time_s)), 6) for r in results})
    rate_label = ' / '.join(f'{rate:g}' for rate in rates)
    plates = f'{cfg.cmj.force_plate_model} running at {rate_label} Hz.'.strip()
    return [('Measurement date', date), ('Body mass', fmt_num(mass, 1)+' kg'),
            ('Trials', str(len(results))), ('Force plates', plates), ('Filtering', filtering)]


def summary_rows(results, block=None):
    """Keep results plain; the highest jump is marked only in its header."""
    block = results if block is None else block
    rows = []
    for label, key, scale, decimals in PERFORMANCE:
        cells = [escape(label), escape(sample_summary([r.metrics[key]*scale for r in results], decimals))]
        for r in block:
            value = escape(fmt_num(r.metrics[key]*scale, decimals))
            cells.append(value)
        rows.append(cells)
    return rows


def performance_force_figure(results):
    family = report_fonts()
    selected = best_trial(results)
    with plt.rc_context({'font.family': family, 'font.size': 8.5}):
        fig = plt.figure(figsize=(7.4, 4.6), layout='constrained')
        grid = fig.add_gridspec(3, 2, height_ratios=[1.35, .16, 1.25])
        full = fig.add_subplot(grid[0, :])
        legend_ax = fig.add_subplot(grid[1, :])
        legend_ax.axis('off')
        braking, propulsion = fig.add_subplot(grid[2, 0]), fig.add_subplot(grid[2, 1])
        onset = selected.events['onset']
        takeoff = selected.events['takeoff']
        time, force = window(selected.force_time_s, selected.curves['force_n'], onset, takeoff)
        for side, label, color in [('l', 'Left', '#2379b5'), ('r', 'Right', '#cc5353')]:
            key = f'force_{side}_n'
            if key in selected.curves:
                st, sf = window(selected.force_time_s, selected.curves[key], onset, takeoff)
                full.plot((st-onset)*1000, sf, color=color, lw=1.1, alpha=.48, label=label)
        full.plot((time-onset)*1000, force, color='#858585', lw=2.3, label='Combined')
        phase_colors = [('Braking', selected.events['braking_start'], selected.events['com_bottom'],
                         '#edf3fb', '#42698c', 'braking_impulse_ns'),
                        ('Propulsive', selected.events['com_bottom'], takeoff,
                         '#fff0e4', '#a64e12', 'propulsive_impulse_ns')]
        for label, start, finish, fill, ink, key in phase_colors:
            left, right = (start-onset)*1000, (finish-onset)*1000
            full.axvspan(left, right, color=fill, zorder=0)
            full.text((left+right)/2, .94, f'{label} impulse\n{fmt_num(selected.metrics[key], 0)} N·s',
                      transform=full.get_xaxis_transform(), color=ink, fontsize=7.8, ha='center', va='top')
        peak_index = int(np.argmax(force))
        peak = float(force[peak_index])
        peaks = selected.waveform.get('braking_propulsion_peak_times_s', [float(time[peak_index])])
        for index, stamp in enumerate(peaks):
            peak_x = (stamp-onset)*1000
            value = float(np.interp(stamp, selected.force_time_s, selected.curves['force_n']))
            annotate_force_peak(full, peak_x, value, peak_label(index, len(peaks)))
        full.set_xlim(0, (takeoff-onset)*1000)
        full.set_title(f'Best jump: {selected.trial_name}  |  {fmt_num(selected.metrics["jump_height_m"]*100)} cm',
                       loc='left', fontsize=10.5, fontweight='bold', color=METROPOLIA_DARK)
        full.set_xlabel('Time from movement onset (ms)')
        full.legend(frameon=False, fontsize=9, loc='upper left', ncols=3, handlelength=1.5)
        colors = plt.cm.tab10(np.linspace(0, .9, max(1, len(results))))
        maximum = max(peak, 1.)
        minimum = min(float(np.min(force)), 0.)
        for r, color in zip(results, colors):
            for ax, start, finish in [(braking, r.events['braking_start'], r.events['com_bottom']),
                                       (propulsion, r.events['com_bottom'], r.events['takeoff'])]:
                pt, pf = window(r.force_time_s, r.curves['force_n'], start, finish)
                maximum = max(maximum, float(np.max(pf)))
                minimum = min(minimum, float(np.min(pf)))
                ax.plot((pt-start)/(finish-start)*100, pf, color=color, lw=1.1, label=r.trial_name)
        for key in ('force_l_n', 'force_r_n'):
            if key in selected.curves:
                _, sf = window(selected.force_time_s, selected.curves[key], onset, takeoff)
                maximum = max(maximum, float(np.max(sf)))
                minimum = min(minimum, float(np.min(sf)))
        for ax in (full, braking, propulsion):
            ax.set_ylabel('GRF (N)' if ax is full else 'Combined GRF (N)', fontsize=8.5)
            ax.set_ylim(minimum, maximum*1.35)
            ax.grid(False)
            ax.spines[['top', 'right']].set_visible(False)
            ax.tick_params(labelsize=7.8)
        for ax, label in [(braking, 'Braking'), (propulsion, 'Propulsion')]:
            ax.set_title(label, loc='left', fontsize=9.5, fontweight='bold')
            ax.set_xlabel('Phase duration (%)', fontsize=8.5)
            ax.set_xlim(0, 100)
        for index, stamp in enumerate(peaks):
            bottom = selected.events['com_bottom']
            ax, start, finish = ((braking, selected.events['braking_start'], bottom)
                                 if stamp < bottom else (propulsion, bottom, takeoff))
            x = (stamp-start)/(finish-start)*100
            value = float(np.interp(stamp, selected.force_time_s, selected.curves['force_n']))
            annotate_force_peak(ax, x, value, peak_label(index, len(peaks)))
        handles, labels = braking.get_legend_handles_labels()
        legend_ax.legend(handles, labels, ncols=min(6, len(results)), fontsize=7.4,
                         frameon=False, loc='center', handlelength=1.3, columnspacing=1.4)
    return fig


def draw_card(canvas, x, y, width, height):
    """Rounded orange cap follows the curved white inset down both shoulders."""
    canvas.saveState()
    canvas.setStrokeColor(HexColor('#ececec'))
    canvas.setLineWidth(.65)
    canvas.setFillColor(HexColor(METROPOLIA_ORANGE))
    canvas.roundRect(x, y, width, height, 11, fill=1, stroke=1)
    canvas.setFillColor(HexColor('#ffffff'))
    canvas.roundRect(x, y, width, height-3.4, 11, fill=1, stroke=0)
    canvas.roundRect(x, y, width, height, 11, fill=0, stroke=1)
    canvas.restoreState()


def write_performance_pdf(results, cfg, path, measurement_date=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    report_fonts()
    canvas = Canvas(str(path), pagesize=A4)
    canvas.setTitle(TITLE)
    width, height = A4
    margin, available = 32, width-64
    blocks = [results[i:i+6] for i in range(0, len(results), 6)]
    dark, orange, grey = (HexColor(c) for c in (METROPOLIA_DARK, METROPOLIA_ORANGE, METROPOLIA_GREY))
    body = ParagraphStyle('body', fontName='JumputilsSans', fontSize=8.5, leading=10.5, textColor=dark)
    label_style = ParagraphStyle('label', parent=body, fontName='JumputilsSans-Bold', alignment=TA_LEFT)
    number_style = ParagraphStyle('number', parent=body, alignment=TA_RIGHT)
    head_style = ParagraphStyle('head', parent=number_style, fontName='JumputilsSans-Bold')
    for page, block in enumerate(blocks, 1):
        canvas.setFillColor(orange)
        canvas.roundRect(margin, height-37, available, 5, 2.5, fill=1, stroke=0)
        canvas.setFont('JumputilsSans-Bold', 29)
        canvas.drawString(margin, height-75, 'Metropolia')
        canvas.setFillColor(dark)
        canvas.setFont('JumputilsSans-Bold', 12)
        canvas.drawString(margin+pdfmetrics.stringWidth('Metropolia', 'JumputilsSans-Bold', 29)+12,
                          height-75, 'Movement Laboratory')
        canvas.setFont('JumputilsSans-Bold', 18)
        canvas.drawString(margin, height-126, TITLE)
        canvas.setFont('JumputilsSans', 10)
        canvas.setFillColor(grey)
        canvas.drawString(margin, height-146, cfg.subject_name or 'Not specified')
        meta_x, meta_y, meta_w = width-margin-174, height-153, 174
        canvas.setStrokeColor(HexColor('#ececec'))
        canvas.setLineWidth(.65)
        canvas.roundRect(meta_x, meta_y, meta_w, 104, 12, fill=0, stroke=1)
        meta = '<br/>'.join('<b>'+escape(label)+':</b> '+escape(value)
                            for label, value in athlete_metadata(results, cfg, measurement_date))
        paragraph = Paragraph(meta, ParagraphStyle('meta', parent=body, fontSize=7.7, leading=12))
        _, mh = paragraph.wrap(meta_w-24, 90)
        paragraph.drawOn(canvas, meta_x+12, meta_y+104-15-mh)
        card_y, card_w = height-219, (available-3*8)/4
        for i, (label, key, scale, decimals) in enumerate(CARD_METRICS):
            x = margin+i*(card_w+8)
            draw_card(canvas, x, card_y, card_w, 62)
            card_label = Paragraph(escape(label), ParagraphStyle('cardlabel', parent=body, fontSize=7.7, leading=9.2, textColor=grey))
            _, lh = card_label.wrap(card_w-18, 25)
            card_label.drawOn(canvas, x+9, card_y+48-lh)
            canvas.setFillColor(dark)
            canvas.setFont('JumputilsSans-Bold', 13.5)
            canvas.drawString(x+9, card_y+23, sample_summary([r.metrics[key]*scale for r in results], decimals))
            canvas.setFont('JumputilsSans', 7.6)
            canvas.setFillColor(grey)
            canvas.drawString(x+9, card_y+9, 'Mean ± SD')
        canvas.setFillColor(dark)
        canvas.setFont('JumputilsSans-Bold', 12)
        canvas.drawString(margin, card_y-25, 'Summary')
        selected = best_trial(results)
        data = [[Paragraph('Variable', label_style), Paragraph('Mean ± SD', head_style)]
                +[Paragraph((f'<font color="{METROPOLIA_ORANGE}" size="7">Best Jump</font><br/>'
                             if r is selected else '')+escape(r.trial_name), head_style) for r in block]]
        data += [[Paragraph(row[0], label_style)]+[Paragraph(cell, number_style) for cell in row[1:]]
                 for row in summary_rows(results, block)]
        summary = Table(data, colWidths=[179, 77]+[(available-256)/len(block)]*len(block))
        summary.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('VALIGN', (0, 0), (-1, 0), 'BOTTOM'),
            ('LINEBELOW', (0, 0), (-1, -1), .4, HexColor('#ececec')),
            ('TOPPADDING', (0, 0), (-1, -1), 3.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        _, table_h = summary.wrap(available, height)
        summary.drawOn(canvas, margin, card_y-35-table_h)
        fig = performance_force_figure(results)
        png = BytesIO()
        fig.savefig(png, format='png', dpi=200)
        plt.close(fig)
        png.seek(0)
        graph_top = card_y-47-table_h
        graph_h = max(1, min(325, graph_top-47))
        canvas.drawImage(ImageReader(png), margin, graph_top-graph_h, width=available, height=graph_h,
                         preserveAspectRatio=True, anchor='c')
        canvas.setFillColor(grey)
        canvas.setFont('JumputilsSans', 8)
        for index, note in enumerate(CALCULATION_NOTES):
            canvas.drawString(margin, 33-index*11, note)
        if len(blocks) > 1:
            canvas.drawRightString(width-margin, 33, f'{page} / {len(blocks)}')
        canvas.showPage()
    canvas.save()


def render_performance_html(results, cfg, pdf_path, extended_path=None, measurement_date=None):
    from urllib.parse import quote
    selected = best_trial(results)
    header = '<tr><th>Variable</th><th>Mean ± SD</th>'+''.join(
        '<th>'+('<span class="best-jump">Best Jump</span><br/>' if r is selected else '')
        +escape(r.trial_name)+'</th>' for r in results)+'</tr>'
    rows = ''.join('<tr><th>'+row[0]+'</th>'+''.join('<td>'+cell+'</td>' for cell in row[1:])+'</tr>'
                   for row in summary_rows(results))
    cards = ''.join(metric_card_html(label, sample_summary([r.metrics[key]*scale for r in results], decimals), 'Mean ± SD')
                    for label, key, scale, decimals in CARD_METRICS)
    image = fig_to_base64(performance_force_figure(results))
    extended = f'<a href="{quote(extended_path.name)}">Extended movement analysis</a>' if extended_path else ''
    meta = '<br/>'.join('<b>'+escape(label)+':</b> '+escape(value)
                        for label, value in athlete_metadata(results, cfg, measurement_date))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{TITLE}</title>
    <meta name="viewport" content="width=device-width,initial-scale=1"><style>
    body{{font-family:Arial,Helvetica,sans-serif;color:{METROPOLIA_DARK};margin:0}}main{{max-width:1180px;padding:28px;margin:auto}}
    .bar{{height:10px;border-radius:9px;background:{METROPOLIA_ORANGE}}}.header{{display:flex;justify-content:space-between;gap:24px;margin:24px 0}}
    .wordmark{{margin:0;font-size:2rem;font-weight:700;letter-spacing:-.02em}}.wordmark span{{color:{METROPOLIA_ORANGE}}}
    .meta{{font-size:.88rem;border:1px solid #eee;border-radius:16px;padding:16px;line-height:1.9;min-width:230px}}
    .cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
    .metric-card{{border:1px solid #eee;border-top:4px solid {METROPOLIA_ORANGE};border-radius:16px;padding:14px}}
    .metric-value{{font-weight:bold;font-size:1.4rem;margin:8px 0}}.metric-label,.metric-sub{{color:#53565a;font-size:.85rem}}
    .table-scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-size:.92rem}}
    th,td{{padding:9px;border-bottom:1px solid #eee;text-align:right}}th:first-child{{text-align:left}}img{{width:100%;height:auto}}
    a{{color:#b83a00}}h1{{font-size:1.4rem}}.best-jump{{color:{METROPOLIA_ORANGE};font-size:.78rem}}
    @media(max-width:700px){{.header{{display:block}}.cards{{grid-template-columns:repeat(2,1fr)}}}}
    </style></head><body><main><div class="bar"></div><div class="header"><div><p class="wordmark"><span>Metropolia</span> Movement Laboratory</p>
    <h1>{TITLE}</h1><p>{escape(cfg.subject_name or 'Not specified')}</p></div><div class="meta">{meta}</div></div>
    <p><a href="{quote(pdf_path.name)}">Open PDF</a> {extended}</p><div class="cards">{cards}</div><h2>Summary</h2>
    <div class="table-scroll"><table><thead>{header}</thead><tbody>{rows}</tbody></table></div>
    {figure_card_html('Best jump GRF and normalized phase overlays',image)}
    <p>{'<br/>'.join(escape(note) for note in CALCULATION_NOTES)}</p></main></body></html>'''
