# Report templates

This directory is reserved for external HTML/CSS templates. The current report
markup remains in `app/reporting/html.py` so the refactor preserves the validated
report output byte for byte. Future visual redesigns can move the static markup
here without mixing it with C3D reading or jump-metric calculations.
