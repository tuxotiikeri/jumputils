"""Measurement metadata used by both CMJ report formats."""

from datetime import datetime
from pathlib import Path
import re


def source_date(path):
    path = Path(path)
    # Prefer trial-specific acquisition metadata; never select an unrelated
    # session history file merely because it happens to be in the folder.
    for suffix in ('.Trial.enf', '.enf', '.history', '.History.xml'):
        candidate = path.with_name(path.stem+suffix)
        if not candidate.is_file():
            continue
        text = candidate.read_text(encoding='utf-8-sig', errors='replace')
        match = re.search(r'(?im)^\s*(?:MeasurementDate|CaptureDate|CreationDate|Date)\s*=\s*(.+)$', text)
        if match:
            value = match.group(1).strip()
            for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y', '%Y%m%d'):
                try:
                    return datetime.strptime(value[:10] if fmt != '%Y%m%d' else value[:8], fmt).date(), candidate.name
                except ValueError:
                    pass
    if path.exists():
        # Match the existing DJ date fallback. File creation time on Windows
        # often records a copy/export date rather than the measurement itself.
        return datetime.fromtimestamp(path.stat().st_mtime).date(), path.suffix.upper().lstrip('.')+' modified date'
    return None, 'Unavailable'


def measurement_metadata(results, override=None):
    if override:
        day = datetime.strptime(override, '%Y-%m-%d').date()
        return day.strftime('%d.%m.%Y'), 'Provided measurement date'
    dates = [source_date(r.source_path) for r in results]
    days = sorted({day for day, _ in dates if day is not None})
    label = '-' if not days else days[0].strftime('%d.%m.%Y')
    if len(days) > 1:
        label += ' - '+days[-1].strftime('%d.%m.%Y')
    return label, '; '.join(sorted({source for _, source in dates}))


def filter_metadata(results, cfg):
    c3d = any('C3D' in r.provenance.get('force_source', '') for r in results)
    csv = any('CSV' in r.provenance.get('force_source', '') for r in results)
    force = 'C3D: Nexus 15 Hz Butterworth' if c3d else 'CSV: unfiltered force'
    if c3d and csv and any('explicit source' in r.provenance.get('force_source', '') for r in results):
        force += ' / raw CSV'
    extra = 'No additional force filtering' if cfg.cmj.force_filter_hz == 0 else f'Additional force filter: {cfg.cmj.force_filter_hz:g} Hz'
    events = 'Events: raw CSV' if csv else 'Events: available force signal'
    return [force, extra, events]
