"""
CMJ quick metrics for Vicon Nexus
---------------------------------
Uses vertical GRF from force plates 3 + 4 and calculates:
  - jump height from take-off velocity (impulse-momentum method)
  - RSI-mod
  - braking net impulse
  - propulsive net impulse
  - peak vertical GRF

Designed to be run as a Python operation from an open Nexus trial.
No force filtering is applied.

Mass priority:
  1) $Bodymass from a .mp file in the current trial folder (if available)
  2) a matching Nexus subject parameter (Bodymass / BodyMass / Mass)
  3) force-derived estimate from the initial quiet-standing period

A .mp file is completely optional. If it is missing, unreadable, or the trial
path is unavailable, the script continues and falls back to the Nexus subject
parameter or the force-derived quiet-standing estimate.

The subject should stand still on force plates 3 and 4 for at least ~1 s
at the beginning of the trial.
"""

import os
import re
import glob
import math
import numpy as np


# --------------------------- SETTINGS ---------------------------------------
FORCE_PLATE_NUMBERS = (3, 4)
G = 9.80665

WEIGHING_SECONDS = 1.0
TAKEOFF_THRESHOLD_N = 20.0
MIN_FLIGHT_SECONDS = 0.15
MOVEMENT_MIN_DURATION_SECONDS = 0.03

# Movement onset threshold uses the larger of:
#   3 x quiet-standing SD, 5% BW, or 20 N.
# This gives robust onset detection without filtering the force signal.
MOVEMENT_SD_MULTIPLIER = 3.0
MOVEMENT_BW_FRACTION = 0.05
MOVEMENT_MIN_THRESHOLD_N = 20.0

SHOW_POPUP = True
WRITE_ANALYSIS_PARAMETERS = True
# ---------------------------------------------------------------------------


def first_active_subject(vicon):
    names, templates, active = vicon.GetSubjectInfo()
    for name, is_active in zip(names, active):
        if is_active:
            return name
    if names:
        return names[0]
    raise RuntimeError("No subject found in the open Nexus trial.")


def normalize_param_name(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def read_mass_from_nexus_subject_param(vicon, subject):
    """Return (mass_kg, parameter_name) or (None, None)."""
    try:
        names = vicon.GetSubjectParamNames(subject)
    except Exception:
        return None, None

    preferred = {"bodymass", "bodymasskg", "mass"}
    for name in names:
        if normalize_param_name(name) in preferred:
            try:
                value, has_value = vicon.GetSubjectParam(subject, name)
                value = float(value)
                if has_value and 20.0 <= value <= 300.0:
                    return value, name
            except Exception:
                pass
    return None, None


def parse_bodymass_from_mp(mp_path):
    pattern = re.compile(
        r"^\s*\$Bodymass\s*=\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)",
        re.IGNORECASE,
    )
    try:
        with open(mp_path, "r", encoding="utf-8-sig", errors="ignore") as f:
            for line in f:
                match = pattern.match(line)
                if match:
                    value = float(match.group(1))
                    if 20.0 <= value <= 300.0:
                        return value
    except Exception:
        pass
    return None


def read_mass_from_mp(trial_path, subject):
    """Return (mass_kg, mp_path) or (None, None).

    The .mp file is optional. Any missing/invalid trial path or file-system
    problem is treated as "mass not available from .mp" rather than an error.
    """
    if not trial_path:
        return None, None

    try:
        mp_pattern = os.path.join(str(trial_path), "*.mp")
        mp_files = glob.glob(mp_pattern)
    except (TypeError, ValueError, OSError):
        return None, None

    if not mp_files:
        return None, None

    subject_norm = normalize_param_name(subject)

    # Prefer a file whose base name matches the subject name.
    matching = []
    for path in mp_files:
        base = normalize_param_name(os.path.splitext(os.path.basename(path))[0])
        if base == subject_norm:
            matching.append(path)

    candidates = matching if matching else mp_files
    found = []
    for path in candidates:
        mass = parse_bodymass_from_mp(path)
        if mass is not None:
            found.append((mass, path))

    if len(found) == 1:
        return found[0]

    # If several .mp files exist and only one of all files has a valid Bodymass,
    # that file is still unambiguous.
    if len(found) == 0 and candidates is not mp_files:
        for path in mp_files:
            mass = parse_bodymass_from_mp(path)
            if mass is not None:
                found.append((mass, path))
        if len(found) == 1:
            return found[0]

    # Do not silently select an arbitrary subject if multiple .mp files disagree.
    return None, None


def force_plate_devices(vicon):
    devices = []
    for device_id in vicon.GetDeviceIDs():
        try:
            name, device_type, rate, output_ids, forceplate, eyetracker = vicon.GetDeviceDetails(device_id)
            if str(device_type).lower() == "forceplate":
                devices.append(
                    {
                        "id": device_id,
                        "name": str(name).strip(),
                        "rate": float(rate),
                        "outputs": output_ids,
                    }
                )
        except Exception:
            pass
    return devices


def resolve_force_plate(vicon, plate_number):
    """
    Resolve Nexus force plate "3" / "4" robustly.

    Priority:
      1) device name == requested plate number / ends in that number
      2) device ID == requested plate number
      3) requested 1-based position among force-plate devices
    """
    devices = force_plate_devices(vicon)
    target = str(plate_number)

    for d in devices:
        name = d["name"]
        if name == target or re.search(r"(?:^|\D)%s$" % re.escape(target), name):
            return d

    for d in devices:
        if str(d["id"]) == target:
            return d

    if 1 <= plate_number <= len(devices):
        return devices[plate_number - 1]

    listing = ", ".join("ID=%s name='%s'" % (d["id"], d["name"]) for d in devices)
    raise RuntimeError(
        "Could not resolve force plate %s. Force plates found: %s"
        % (plate_number, listing or "none")
    )


def get_force_fz(vicon, plate_number):
    plate = resolve_force_plate(vicon, plate_number)
    device_id = plate["id"]

    try:
        force_output_id = vicon.GetDeviceOutputIDFromName(device_id, "Force")
        if not force_output_id:
            raise RuntimeError('Force output ID unavailable')
    except Exception:
        force_output_id = None
        for output_id in plate["outputs"]:
            details = vicon.GetDeviceOutputDetails(device_id, output_id)
            output_name = str(details[0]).strip().lower()
            if output_name == "force" or output_name.endswith("force"):
                force_output_id = output_id
                break
        if force_output_id is None:
            raise RuntimeError("No Force output found for force plate %s." % plate_number)

    try:
        fz_channel_id = vicon.GetDeviceChannelIDFromName(device_id, force_output_id, "Fz")
        if not fz_channel_id:
            raise RuntimeError('Fz channel ID unavailable')
    except Exception:
        details = vicon.GetDeviceOutputDetails(device_id, force_output_id)
        channel_names = details[4]
        channel_ids = details[5]
        fz_channel_id = None
        for name, channel_id in zip(channel_names, channel_ids):
            if str(name).strip().lower() == "fz":
                fz_channel_id = channel_id
                break
        if fz_channel_id is None:
            raise RuntimeError("No Fz channel found for force plate %s." % plate_number)

    # Global is preferable if available. Fall back to the regular channel call.
    try:
        data, ready, rate = vicon.GetDeviceChannelGlobal(device_id, force_output_id, fz_channel_id)
    except Exception:
        data, ready, rate = vicon.GetDeviceChannel(device_id, force_output_id, fz_channel_id)

    if not ready:
        raise RuntimeError("Force plate %s Fz channel is not ready." % plate_number)

    return np.asarray(data, dtype=float), float(rate), plate


def first_sustained_true(mask, min_samples, start=0, end=None):
    """Return the first index where mask stays True for at least min_samples."""
    if end is None:
        end = len(mask)
    start = max(0, int(start))
    end = min(len(mask), int(end))
    if end <= start:
        return None

    arr = np.asarray(mask[start:end], dtype=np.int8)
    edges = np.diff(np.concatenate(([0], arr, [0])))
    starts = np.where(edges == 1)[0]
    ends = np.where(edges == -1)[0]
    for a, b in zip(starts, ends):
        if (b - a) >= min_samples:
            return start + int(a)
    return None


def cumulative_trapezoid_from(y, fs, start, end):
    """Velocity-style cumulative trapezoidal integral, zero at start."""
    out = np.zeros(end - start + 1, dtype=float)
    if end <= start:
        return out
    dt = 1.0 / fs
    segment = y[start:end + 1]
    out[1:] = np.cumsum(0.5 * (segment[:-1] + segment[1:]) * dt)
    return out


def integrate_segment(y, fs, start, end):
    if end <= start:
        return 0.0
    segment = np.asarray(y[start:end + 1], dtype=float)
    dt = 1.0 / fs
    return float((0.5 * segment[0] + np.sum(segment[1:-1]) + 0.5 * segment[-1]) * dt)


def analyse_cmj(vertical_force_n, fs, mass_kg):
    """Compatibility API backed by the same engine as the Jumputils report."""
    import sys
    from pathlib import Path
    project = str(Path(__file__).resolve().parents[2])
    if project not in sys.path:
        sys.path.insert(0, project)
    from app.nexus.cmj_quick_metrics import analyze_in_jumputils
    return analyze_in_jumputils(vertical_force_n, fs, mass_kg)['metrics']


def legacy_analyse_cmj(vertical_force_n, fs, mass_kg):
    force = np.asarray(vertical_force_n, dtype=float).copy()
    if force.size < int(2.0 * fs):
        raise RuntimeError("Trial is too short for CMJ analysis.")

    weighing_n = max(1, min(force.size, int(round(WEIGHING_SECONDS * fs))))
    initial_mean = float(np.mean(force[:weighing_n]))

    # Make quiet standing positive regardless of Nexus plate orientation.
    sign = -1.0 if initial_mean < 0.0 else 1.0
    force *= sign

    baseline = force[:weighing_n]
    baseline_mean = float(np.mean(baseline))
    baseline_sd = float(np.std(baseline, ddof=1)) if weighing_n > 1 else 0.0
    estimated_mass_kg = baseline_mean / G

    bodyweight_n = mass_kg * G

    # Remove force-plate / weighing offset while retaining the chosen body mass.
    # After correction, the quiet-standing mean equals mass * g.
    force_corrected = force + (bodyweight_n - baseline_mean)
    net_force = force_corrected - bodyweight_n

    # Take-off = first sustained period below 20 N after the weighing phase.
    min_flight_samples = max(1, int(round(MIN_FLIGHT_SECONDS * fs)))
    takeoff = first_sustained_true(
        force_corrected < TAKEOFF_THRESHOLD_N,
        min_flight_samples,
        start=weighing_n,
    )
    if takeoff is None:
        raise RuntimeError(
            "Take-off not found. Check that the trial contains a CMJ and that plates 3 + 4 are correct."
        )

    # CMJ normally starts by unloading, so detect a sustained drop below BW.
    movement_threshold_n = max(
        MOVEMENT_SD_MULTIPLIER * baseline_sd,
        MOVEMENT_BW_FRACTION * bodyweight_n,
        MOVEMENT_MIN_THRESHOLD_N,
    )
    min_movement_samples = max(1, int(round(MOVEMENT_MIN_DURATION_SECONDS * fs)))
    movement_onset = first_sustained_true(
        force_corrected < (bodyweight_n - movement_threshold_n),
        min_movement_samples,
        start=weighing_n,
        end=takeoff,
    )
    if movement_onset is None:
        raise RuntimeError("Movement onset not found before take-off.")

    # COM acceleration and velocity from impulse-momentum.
    acceleration = net_force / mass_kg
    velocity_segment = cumulative_trapezoid_from(
        acceleration, fs, movement_onset, takeoff
    )

    # Indices in full signal coordinates.
    min_velocity_rel = int(np.argmin(velocity_segment))
    braking_start = movement_onset + min_velocity_rel

    # Propulsion starts when COM velocity returns to zero after peak negative velocity.
    after_min = velocity_segment[min_velocity_rel:]
    nonnegative = np.where(after_min >= 0.0)[0]
    if nonnegative.size == 0:
        raise RuntimeError("COM velocity did not return to zero before take-off.")
    propulsive_start = braking_start + int(nonnegative[0])

    takeoff_velocity_m_s = float(velocity_segment[-1])
    if takeoff_velocity_m_s <= 0:
        raise RuntimeError(
            "Calculated take-off velocity is not positive. Check force-plate selection and body mass."
        )

    jump_height_m = takeoff_velocity_m_s ** 2 / (2.0 * G)
    time_to_takeoff_s = (takeoff - movement_onset) / fs
    rsi_mod_m_s = jump_height_m / time_to_takeoff_s

    braking_impulse_ns = integrate_segment(
        net_force, fs, braking_start, propulsive_start
    )
    propulsive_impulse_ns = integrate_segment(
        net_force, fs, propulsive_start, takeoff
    )

    peak_force_n = float(np.max(force_corrected[movement_onset:takeoff + 1]))
    peak_force_n_kg = peak_force_n / mass_kg

    min_velocity_m_s = float(velocity_segment[min_velocity_rel])

    return {
        "mass_kg": float(mass_kg),
        "estimated_mass_kg": float(estimated_mass_kg),
        "baseline_force_n": baseline_mean,
        "baseline_sd_n": baseline_sd,
        "movement_threshold_n": movement_threshold_n,
        "movement_onset_s": movement_onset / fs,
        "braking_start_s": braking_start / fs,
        "propulsive_start_s": propulsive_start / fs,
        "takeoff_s": takeoff / fs,
        "time_to_takeoff_s": time_to_takeoff_s,
        "takeoff_velocity_m_s": takeoff_velocity_m_s,
        "min_velocity_m_s": min_velocity_m_s,
        "jump_height_m": jump_height_m,
        "rsi_mod_m_s": rsi_mod_m_s,
        "braking_impulse_ns": braking_impulse_ns,
        "propulsive_impulse_ns": propulsive_impulse_ns,
        "peak_force_n": peak_force_n,
        "peak_force_n_kg": peak_force_n_kg,
    }


def set_analysis_parameter(vicon, subject, name, value, unit="none"):
    try:
        existing = vicon.GetAnalysisParamNames(subject)
        if name in existing:
            vicon.SetAnalysisParam(subject, name, float(value))
        else:
            vicon.CreateAnalysisParam(subject, name, float(value), unit)
        # Nexus SDK writes can print an error without raising an exception.
        # Confirm the saved value instead of treating a returned call as success.
        stored, has_value = vicon.GetAnalysisParam(subject, name)
        if not has_value or not math.isclose(float(stored), float(value), rel_tol=1e-7, abs_tol=1e-7):
            raise RuntimeError('Nexus did not retain the requested analysis value')
        return True
    except Exception as exc:
        print("Could not write analysis parameter %s: %s" % (name, exc))
        return False


def write_results_to_nexus(vicon, subject, r):
    # Height is stored in mm because Nexus commonly supports mm as a standard unit.
    failures = []
    for name, key, scale, unit in [
        ('CMJ_Height', 'jump_height_m', 1000, 'mm'),
        ('CMJ_RSI_mod', 'rsi_mod_m_s', 1, 'none'),
        ('CMJ_BrakingImpulse', 'braking_impulse_ns', 1, 'none'),
        ('CMJ_PropulsiveImpulse', 'propulsive_impulse_ns', 1, 'none'),
        ('CMJ_PeakForce', 'peak_force_n', 1, 'none'),
        ('CMJ_TakeoffVelocity', 'takeoff_velocity_m_s', 1, 'none'),
        ('CMJ_TimeToTakeoff', 'time_to_takeoff_s', 1, 's')]:
        if not set_analysis_parameter(vicon, subject, name, r[key]*scale, unit):
            failures.append(name)
    return failures


def result_text(r):
    # Fixed-width columns. The popup uses a monospace font when Tkinter is
    # available, so the values stay neatly aligned.
    rows = [
        ("Jump height",          "%5.1f cm" % (r["jump_height_m"] * 100.0)),
        ("RSI-mod",              "%5.2f m/s" % r["rsi_mod_m_s"]),
        ("Braking impulse",      "%5.1f N.s" % r["braking_impulse_ns"]),
        ("Propulsive impulse",   "%5.1f N.s" % r["propulsive_impulse_ns"]),
        ("Peak force",           "%5.0f N  (%4.1f N/kg)" % (r["peak_force_n"], r["peak_force_n_kg"])),
        ("Take-off velocity",    "%5.2f m/s" % r["takeoff_velocity_m_s"]),
        ("Time to take-off",     "%5.3f s" % r["time_to_takeoff_s"]),
        ("Body mass",            "%5.1f kg" % r["mass_kg"]),
    ]

    label_width = max(len(label) for label, _ in rows)
    lines = ["CMJ RESULTS", ""]
    for i, (label, value) in enumerate(rows):
        if label == "Body mass":
            lines.append("")
        lines.append((label + ":").ljust(label_width + 2) + value)
    return "\n".join(lines)


def show_popup(message):
    if not SHOW_POPUP:
        return

    # MessageBox uses a proportional UI font, so space-padded columns do not
    # line up. Prefer a tiny Tkinter dialog with Consolas; fall back to the
    # standard Windows MessageBox if Tkinter is unavailable in Nexus Python.
    try:
        import tkinter as tk

        root = tk.Tk()
        root.title("CMJ quick metrics")
        root.resizable(False, False)
        root.attributes("-topmost", True)

        frame = tk.Frame(root, padx=18, pady=14)
        frame.pack(fill="both", expand=True)

        text = tk.Label(
            frame,
            text=message,
            font=("Consolas", 10),
            justify="left",
            anchor="w",
        )
        text.pack(anchor="w")

        button_frame = tk.Frame(frame)
        button_frame.pack(fill="x", pady=(12, 0))

        ok_button = tk.Button(button_frame, text="OK", width=10, command=root.destroy)
        ok_button.pack(side="right")
        ok_button.focus_set()

        root.bind("<Return>", lambda event: root.destroy())
        root.bind("<Escape>", lambda event: root.destroy())

        root.update_idletasks()
        width = root.winfo_width()
        height = root.winfo_height()
        x = max(0, (root.winfo_screenwidth() - width) // 2)
        y = max(0, (root.winfo_screenheight() - height) // 2)
        root.geometry("+%d+%d" % (x, y))
        root.mainloop()
        return
    except Exception:
        pass

    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, "CMJ quick metrics", 0x40)
    except Exception:
        pass

def main():
    # Keep this familiar Nexus operation entry point, but use the shared
    # Jumputils engine instead of maintaining a second CMJ calculation.
    import sys
    from pathlib import Path
    project = str(Path(__file__).resolve().parents[2])
    if project not in sys.path:
        sys.path.insert(0, project)
    from app.nexus.cmj_quick_metrics import run
    return run(plate_numbers=FORCE_PLATE_NUMBERS, show_popup=SHOW_POPUP,
               write_parameters=WRITE_ANALYSIS_PARAMETERS)


def legacy_main():
    """Original v3 workflow retained for reference; main() uses the shared engine."""
    from viconnexusapi import ViconNexus
    vicon = ViconNexus.ViconNexus()
    subject = first_active_subject(vicon)
    trial_path, trial_name = vicon.GetTrialName()

    fz3, fs3, plate3 = get_force_fz(vicon, FORCE_PLATE_NUMBERS[0])
    fz4, fs4, plate4 = get_force_fz(vicon, FORCE_PLATE_NUMBERS[1])

    if not math.isclose(fs3, fs4, rel_tol=0.0, abs_tol=1e-6):
        raise RuntimeError(
            "Force plates have different sampling rates: %.3f Hz vs %.3f Hz" % (fs3, fs4)
        )

    n = min(len(fz3), len(fz4))
    if n == 0:
        raise RuntimeError("No force data found on plates 3 and 4.")
    vertical_force = fz3[:n] + fz4[:n]
    fs = fs3

    # Estimate mass from quiet standing first. Sign is handled here independently.
    weighing_n = max(1, min(n, int(round(WEIGHING_SECONDS * fs))))
    raw_initial_mean = float(np.mean(vertical_force[:weighing_n]))
    force_estimated_mass = abs(raw_initial_mean) / G

    # 1) Optional .mp file. Missing .mp must never stop the analysis.
    try:
        mp_mass, mp_path = read_mass_from_mp(trial_path, subject)
    except Exception:
        mp_mass, mp_path = None, None

    # 2) Optional Nexus subject parameter.
    nexus_mass, nexus_param = read_mass_from_nexus_subject_param(vicon, subject)

    # 3) Fallback: estimate body mass directly from the initial quiet standing.
    if mp_mass is not None:
        mass_kg = mp_mass
    elif nexus_mass is not None:
        mass_kg = nexus_mass
    else:
        mass_kg = force_estimated_mass

    if not (20.0 <= mass_kg <= 300.0):
        raise RuntimeError("Implausible body mass: %.2f kg" % mass_kg)

    results = legacy_analyse_cmj(vertical_force, fs, mass_kg)

    if WRITE_ANALYSIS_PARAMETERS:
        write_results_to_nexus(vicon, subject, results)

    message = result_text(results)

    print("\n" + "=" * 60)
    print("Trial: %s" % trial_name)
    print("Subject: %s" % subject)
    print("Force plates: %s + %s" % (plate3["id"], plate4["id"]))
    print("Sampling rate: %.1f Hz" % fs)
    print(message)
    print("=" * 60 + "\n")

    show_popup(message)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        error_message = "CMJ analysis failed:\n\n%s" % exc
        print(error_message)
        show_popup(error_message)
        raise
