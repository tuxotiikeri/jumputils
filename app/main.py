#!/usr/bin/env python3
"""Small desktop launcher for the Jumputils drop-jump report."""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
CLI_MODULE = APP_DIR / "cli.py"
REPORTS_DIR = PROJECT_DIR / "reports"
DEFAULT_DATA_DIR = PROJECT_DIR / "data"


def safe_filename(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value.strip())
    value = re.sub(r"[\s_]+", "_", value)
    return value.strip(" ._") or "measured_person"


class JumputilsApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Jumputils – Create report")
        self.root.resizable(False, False)

        initial_data = DEFAULT_DATA_DIR if DEFAULT_DATA_DIR.exists() else PROJECT_DIR
        self.folder_var = tk.StringVar(value=str(initial_data))
        self.subject_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Select the measurement folder and enter a name.")

        frame = ttk.Frame(root, padding=22)
        frame.grid(sticky="nsew")
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="Drop Jump report", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 18)
        )

        ttk.Label(frame, text="Measurement folder").grid(row=1, column=0, columnspan=2, sticky="w")
        folder_entry = ttk.Entry(frame, textvariable=self.folder_var, width=62)
        folder_entry.grid(row=2, column=0, sticky="ew", pady=(4, 14), padx=(0, 8))
        ttk.Button(frame, text="Browse…", command=self.choose_folder).grid(row=2, column=1, pady=(4, 14))

        ttk.Label(frame, text="Measured person").grid(row=3, column=0, columnspan=2, sticky="w")
        subject_entry = ttk.Entry(frame, textvariable=self.subject_var, width=62)
        subject_entry.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 18))

        self.create_button = ttk.Button(frame, text="Create report", command=self.create_report)
        self.create_button.grid(row=5, column=0, columnspan=2, sticky="ew", ipady=5)

        ttk.Label(frame, textvariable=self.status_var, foreground="#53565a", wraplength=500).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(14, 0)
        )

        subject_entry.focus_set()
        root.bind("<Return>", lambda _event: self.create_report())

    def choose_folder(self) -> None:
        current = Path(self.folder_var.get().strip())
        initial = current if current.is_dir() else PROJECT_DIR
        selected = filedialog.askdirectory(title="Select measurement folder", initialdir=str(initial))
        if selected:
            self.folder_var.set(selected)

    def create_report(self) -> None:
        folder = Path(self.folder_var.get().strip())
        subject = self.subject_var.get().strip()

        if not folder.is_dir():
            messagebox.showerror("Folder not found", "Select an existing measurement folder.")
            return
        if not subject:
            messagebox.showerror("Name missing", "Enter the measured person's name.")
            return
        if not CLI_MODULE.is_file():
            messagebox.showerror("Program file missing", f"Could not find:\n{CLI_MODULE}")
            return

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        stem = f"{safe_filename(subject)}_dropjump_{stamp}"
        output_html = REPORTS_DIR / f"{stem}.html"
        summary_csv = REPORTS_DIR / f"{stem}_summary.csv"
        contact_csv = REPORTS_DIR / f"{stem}_contact_phases.csv"

        command = [
            sys.executable,
            "-m",
            "app.cli",
            str(folder),
            "--recursive",
            "--subject",
            subject,
            "--output",
            str(output_html),
            "--summary-csv",
            str(summary_csv),
            "--contact-csv",
            str(contact_csv),
        ]

        self.create_button.configure(state="disabled")
        self.status_var.set("Creating report… This may take a moment.")
        threading.Thread(
            target=self._run_report,
            args=(command, output_html),
            daemon=True,
        ).start()

    def _run_report(self, command: list[str], output_html: Path) -> None:
        try:
            completed = subprocess.run(
                command,
                cwd=PROJECT_DIR,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except Exception as exc:
            self.root.after(0, self._report_failed, str(exc))
            return

        if completed.returncode == 0 and output_html.is_file():
            self.root.after(0, self._report_finished, output_html)
            return

        details = (completed.stderr or completed.stdout or "Unknown error").strip()
        self.root.after(0, self._report_failed, details)

    def _report_finished(self, output_html: Path) -> None:
        self.create_button.configure(state="normal")
        self.status_var.set(f"Report created: {output_html}")
        webbrowser.open(output_html.resolve().as_uri())
        messagebox.showinfo("Report created", f"The report was saved to:\n{output_html}")

    def _report_failed(self, details: str) -> None:
        self.create_button.configure(state="normal")
        self.status_var.set("Report creation failed.")
        messagebox.showerror("Could not create report", details[-4000:])


def main() -> int:
    root = tk.Tk()
    JumputilsApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
