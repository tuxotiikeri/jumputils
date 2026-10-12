# CMJ strategy profile: methods and extension points

CMJ is separate from the DJ/SDJ contact-based pipeline. `app/protocols/cmj.py` holds protocol defaults; `app/c3d/cmj.py` adapts C3D/CSV data to `CMJSignals`; `app/analysis/cmj.py` computes results; `app/reporting/cmj_*` renders and exports them. Shared label matching, C3D accessors, force-CSV parsing, formatting, report cards, colors and figure embedding are reused. PDF reporting uses ReportLab; requirements are listed in the environment files.

## Force and events

1. Sum the upward-positive vertical forces from the two distinct selected plates. Force units must be Newtons. Performance reporting uses the raw CSV for both COM dynamics and events, with no added filter by default. The explicit extended motion-analysis mode can use Nexus-filtered C3D dynamics and a separate raw CSV event/QC signal. Do not duplicate a plate or use only one limb's load as whole-body force.
2. Quiet standing: by default find the last stable 1 s interval before the pre-peak unweighting trough of the first sustained flight. Candidate CV and force trend must each be ≤2% of BW; candidate mean must be within 1% of the preceding loaded median. A 100 ms guard (at least 80 ms available) must stay within max(10 N, 2.5% mean force, 3 × candidate SD). Search steps are 10 ms. No suitable interval means a rejected trial. `--cmj-baseline-start` selects an explicit interval instead. Baseline quality checks still apply. The minimum configurable duration is 0.2 s; short baselines require particular care.
3. Mass is mean standing Fz / 9.80665. When C3D/override mass is available, a disagreement >5% rejects the trial: incomplete support or a wrong plate must not silently create a CMJ. A valid explicit mass override uses that mass and removes the constant standing-force offset; the offset is recorded. Normalized joint moments retain the export's normalization mass; absolute moments require the C3D/override mass.
4. Movement onset: first deviation of the raw event force from BW greater than max(5 × raw baseline SD, 2.5% BW, 10 N), sustained for 30 ms. Integration starts at the end of quiet standing, so subthreshold acceleration preceding this onset is retained. Time to take-off uses the threshold-defined onset. Quiet standing is assigned zero velocity and displacement; no flight-end or pelvis-based drift correction is applied.
5. Acceleration is (Fz − mg)/m. Velocity and displacement use cumulative trapezoidal integration at force sampling rate. Within-sample velocity evaluates the exact integral of linearly interpolated acceleration so net impulse and velocity changes remain consistent at fractional event times.
6. Braking starts at minimum downward COM velocity (the nearby negative-to-positive acceleration crossing is interpolated). COM bottom is the upward velocity zero crossing solved within the original sample interval. Braking ends there. Propulsion is COM bottom to take-off. At least 0.05 m/s downward velocity, 5 mm countermovement depth and 30 ms propulsion are required. Invalid phase order, no upward reversal, missing force samples and a further downward reversal during propulsion reject the trial. In performance reporting, both events and COM dynamics use the raw CSV clock. In explicit C3D motion-analysis mode, event and COM source grids may differ; both sources and rates are recorded.
7. Take-off uses the raw total-force crossing below 20 N, followed by ≥80 ms unloading. Landing is optional and means return to the **selected** plates, not necessarily first contact with the floor. Walking away can produce additional unloadings. One CMJ is reported per file; repeated jumps should be separate trial files. The first loaded-standing-to-flight sequence is the intended input; remove unrelated steps/flights before the CMJ from the force recording.

For extended motion analysis, the C3D and raw CSV must use the same acquisition clock and point rate. Nexus CSV frames are one-based with zero-based subframes; ezc3d `first_frame` is zero-based. Dropped or incompatible timestamps are rejected. No guessed synchronization or alignment based on curve shape is used. Raw CSV events retain their native time grid even if it differs from the COM force grid. The COM-source record must include quiet standing through take-off; a cropped C3D that lacks standing is rejected rather than silently spliced with another force source. Explicit CSV dynamics (`--cmj-force-source csv`) can accompany cropped kinematics; affected joint-phase metrics remain unavailable when coverage is incomplete.

## Performance definitions

| Variable | Definition |
| --- | --- |
| Jump height | v_takeoff² / (2g): COM rise from take-off to ballistic apex |
| Take-off velocity | Integral of net vertical acceleration from quiet standing |
| Time to take-off | Take-off minus movement onset |
| RSI-mod | Jump height / time to take-off |
| Countermovement depth | Negative COM displacement at COM bottom, from quiet standing |
| Braking net impulse | ∫(Fz − mg)dt, peak downward velocity to COM bottom |
| Propulsive net impulse | ∫(Fz − mg)dt, COM bottom to take-off; equals m·v_takeoff |
| Peak vertical force | Maximum analysis Fz between onset and take-off (raw by default), N and N/kg |
| Peak force timing | Time of that maximum minus COM bottom, ms |
| Peak downward COM velocity | Signed negative minimum velocity, m/s |
| Velocity gain by propulsion quarter | Signed velocity change over 0–25, 25–50, 50–75, 75–100%; also % of v_takeoff |

The net velocity gains may be negative and are never made monotonic. Jump height is not flight-time height or a pelvis displacement measurement. Small baseline-force errors affect integrated velocity, displacement, and which trial is highest; inspect the baseline figure and recorded settings when comparing sessions. The automatic settings are method choices, not universal laboratory validation.

## Sagittal joints and trunk

Direct hip/knee/ankle `Angles` and `Moment` POINT outputs use component X. Subject prefixes and common Theia labels use the shared matcher. Angles are degrees, flexion and ankle dorsiflexion positive. With missing direct joint angles, Theia parent-child ROTATION transforms use the existing sagittal XYZ sign convention. No new inverse-dynamics solver is included: Theia kinematics alone cannot supply joint moments. Missing moments leave force/COM and kinematics available.

The **default Nexus profile** assumes exported **external** moments in Nmm/kg. The three explicit moment sign multipliers are −1, converting to **internal**, flexion/dorsiflexion-positive moments. `--cmj-moment-unit` supports Nmm/kg, Nm/kg, Nmm and Nm. Absolute units require a valid mass. No units or signs are inferred from signal magnitudes, and they are not flipped to make propulsion power positive. The profile and source metadata appear in the report. Confirm the reaction frame and convention for custom exports before using them.

Angles are unwrapped within finite runs. No additional force filter is applied by default. The performance report uses raw CSV; explicit C3D motion analysis uses the already Nexus-filtered 15 Hz export. A user-selected additional force cutoff is recorded. The raw CSV event signal is always used without additional filtering. Angles and moments receive a zero-lag fourth-order Butterworth filter at 10 Hz; zero disables it. Missing samples are retained; finite runs too short for the filter remain unavailable. Angular velocity is the time derivative of the filtered angle. Joint power is internal sagittal moment × sagittal angular velocity in radians/s. This is an explicit sagittal approximation, not full 3D moment-vector dot angular-velocity-vector power.

Work uses the physical time grid, interpolated event boundaries and inserted power zero crossings:

- negative work: ∫min(P,0)dt (signed negative, J/kg);
- positive work: ∫max(P,0)dt (J/kg);
- braking negative work: minimum downward COM velocity → COM bottom;
- propulsion positive work: COM bottom → take-off;
- whole-movement signed work is additionally reported for onset → take-off, retaining absorption/generation during unweighting.

Bilateral joint work sums the two limbs' **separately integrated** work. Clipping summed bilateral power would incorrectly cancel simultaneous generation on one side and absorption on the other. Bilateral peak timing, by contrast, uses the actual **sum of the left and right power curves**. Side-specific work, peaks and sequences remain available. Contributions are normalized to the sum of hip/knee/ankle propulsion positive work in the same scope (L, R, or bilateral). All three joints must be present and finite in that scope; partial sums are not renormalized to 100%.

Peak positive joint powers and their delays are reported in ms from COM bottom and % of propulsion. Braking negative peaks have negative times on this same COM-bottom origin. If there is no power of the requested sign, work/peak magnitude can be zero, but peak timing is undefined. Peaks use available point samples plus interpolated phase boundaries; apparent sub-sample timing precision does not imply sub-frame measurement accuracy. No fixed proximal-to-distal order is imposed.

Thorax uses a valid direct `ThoraxAngles`/`LThoraxAngles`/`RThoraxAngles`/`TrunkAngles` channel. A relative trunk/pelvis angle uses a valid spine-angle channel when available. Otherwise, thorax/torso ROTATION local longitudinal z is projected onto the configured lab forward/vertical plane. `--cmj-forward-axis x|y` and `--cmj-forward-sign -1|1` apply only to this fallback. A projected thorax–pelvis inclination difference is explicitly labeled as a projection, not a 3D spine angle. Verify facing direction. Missing/invalid transforms are not replaced with zero angles.

Thorax extension-speed peak timing is compared on the same time axis to hip/knee/ankle angular velocities, and is tabulated separately from joint power timing. Negative joint work cannot be interpreted directly as tendon energy. Net joint mechanics do not identify individual muscles or muscle activation.

## Waveform and reporting

The propulsion force curve uses local-peak prominence 5% BW and minimum peak separation 50 ms. A sufficiently descending COM-bottom boundary peak can count, because ordinary peak finding omits endpoints. Interior local force minima also locate acceleration minima, since acceleration is an affine transform of force. Their force, acceleration and timing are reported. These settings produce descriptive resolved-peak counts; they are not an independently validated physiological unimodal/bimodal classifier or a good/bad score.

The main athlete-facing report is a one-page A4 PDF for up to six trials, with an HTML preview. PDF text and figures share embedded Arial (a bundled sans-serif font is used on platforms without Arial). The Metropolia header and curved orange card borders follow the DJ identity. Summary variable labels and trial headings are bold; headings and results share a right edge. The maximum-height trial header has an orange Best Jump label; results are not underlined. Other metrics are not independently ranked as better/worse.

The same maximum-height trial supplies the GRF chart, from movement onset to take-off, with colored left/right forces (when recorded) and gray combined force. The chart marks the overall GRF maximum and, when resolved, one additional peak across braking and propulsion, labeled First Peak/Second Peak in chronological order with Newton values and leader lines. The existing 5% BW prominence and 50 ms separation thresholds apply; the global maximum is retained, and the second candidate with greatest prominence is selected. A flat maximum counts as one peak. These are descriptive waveform landmarks, not a quality score. Shaded braking/propulsion backgrounds show net impulses. Braking means minimum downward COM velocity to COM bottom. Normalized braking and propulsion overlays retain every trial, with identical force limits across all three axes and no grids. Any total-force baseline correction is split equally between sides for visualization, so their sum matches combined GRF; it is not a per-leg body-weight estimate. Additional pages retain detail for more trials. The metadata box contains date, body mass, trial count, force-plate model and actual force sample rate, and filtering. The laboratory model defaults to AMTI HPS400600 and can be changed with `--cmj-force-plate-model`; CSV does not identify the hardware model. Sampling rate is read from the record, so other rates are not labeled 1200 Hz. Event-source plumbing and date-provenance explanations remain in analysis exports rather than the athlete-facing footer. The footer states jump height = take-off velocity squared / (2g) and RSI-mod = jump height / time from movement onset to take-off. The best-trial peak markers are repeated on the corresponding normalized braking/propulsion overlays, at that trial's phase percentage.

`--cmj-baseline-max-cv` exposes the existing baseline CV/trend tolerance without changing its 2% default. The `tom_28_09_2026` raw-CSV test run uses 81 kg, a 1 s baseline and an explicit 5% tolerance because of pre-jump settling/sway. This tolerance and baseline statistics are saved in JSON; heights and depths remain sensitive to baseline selection. `--cmj-report performance --cmj-force-source csv` bypasses matching C3D files entirely in a force-only session.

The optional `_extended.html` keeps joint/trunk strategies and opens the maximum-height trial initially (first in discovery order if tied); it is generated only when motion channels exist. Stable numeric `trial_id` distinguishes repeated basenames in different subfolders. Exports retain source paths, events, signs, filters, baseline, warnings and all metrics; unavailable JSON values are `null`. Native CSV event samples remain on their own timestamps, with event hold durations computed at that source's rate; no stretching of timestamps or resampling is used for detection. A separate `_raw_event_curves.csv` preserves them. The display overlay in the force/COM CSV is explicitly interpolated to the COM grid. Force/COM curve exports end at take-off. Actual subject data and generated reports remain under ignored `data/` and `reports/` folders.

## Research basis

These sources inform the organization and biomechanical definitions, rather than automatic normative scores:

- [Linthorne (2001)](https://doi.org/10.1119/1.1397460): force-platform mechanics and take-off-velocity height.
- [McMahon et al. (2018)](https://doi.org/10.1519/SSC.0000000000000375): force-time phases. The implementation uses force-derived whole-body phases throughout.
- [Anicic et al. (2023)](https://doi.org/10.3390/life13010190): reporting performance together with timing and strategy.
- [Harry et al. (2020)](https://pubmed.ncbi.nlm.nih.gov/31688643/): joint-power versus force phase distinctions; whole-body braking need not mean every joint absorbs energy.
- [Hubley & Wells (1983)](https://doi.org/10.1007/BF00422163): joint work contributions, without identifying individual muscles in this report.
- [Bobbert & van Ingen Schenau (1988)](https://doi.org/10.1016/0021-9290(88)90175-3), [Chiu et al. (2014)](https://doi.org/10.1519/JSC.0000000000000388): coordination and sequencing. This implementation explicitly distinguishes power-peak timing from angular-velocity timing.
- [Vanrenterghem et al. (2008)](https://doi.org/10.1519/JSC.0b013e3181636c6c): trunk participation in joint-power strategy.
- [Kennedy & Drake (2018)](https://doi.org/10.3390/sports6020036): propulsion waveform; no automatic quality conclusion is adopted.
- [Vicon Plug-in Gait reference, pp. 44–46 and 111–112](https://help.vicon.com/download/attachments/406490967/Plug-in%20Gait%20Reference%20Guide.pdf): external moment description and mass-normalized C3D units despite generic unit metadata.

## Validation and extension

`python -m unittest discover -v` includes known-acceleration CMJs, impulse–momentum consistency, fractional-event integration, negative velocity gains, sample-rate changes, radians and signs, work zero crossings, bilateral cancellation, missing limbs/gaps, sample SD, actual synthetic C3D/CSV parsing and synchronization, native event-rate differences, force-only CSV analysis, ENF date selection, CLI zero-filter defaults, per-trial exports, and HTML escaping. Nexus tests exercise the actual subprocess bridge and a simulated SDK, including opposite plate signs, physical plate-name resolution, parameter creation/update, mismatched channels and write failures. Existing DJ/SDJ protocol tests remain in place. Real `data/kuura/CMJ_1`–`CMJ_4` trials exercise the PDF and extended report, with DJ/SDJ report generation checked separately. This is engineering validation on the available recordings, not external biomechanical validation or a live Nexus operation against an open subject trial.

The Nexus operation `app/nexus/cmj_quick_metrics.py` reads the current SDK device channels, uses optional `.mp`/subject mass, delegates numerical work to `app/nexus/cmj_worker.py` under the repository Python, then creates or updates Analysis Parameters. It applies no additional force filter. For truly raw device data, run the operation before Nexus filtering; post-filter channels cannot be restored to raw data merely by reading them through the SDK. The familiar v3 entry point delegates to this operation; its earlier calculation is retained only as an explicitly named legacy reference.

For performance reporting the primary height is take-off-velocity flight height, `v_takeoff²/(2g)`. Correct whole-body `COM_apex - COM_takeoff` describes the same height and can provide a motion-analysis cross-check. `COM_apex - COM_standing` includes push-off elevation and is a different variable. A single pelvis segment is not a substitute for whole-body COM. The impulse method avoids relying on a segment proxy, but still depends on good weighing, force calibration, initial velocity and take-off detection; it is not automatically superior to every valid whole-body COM measurement. See also the [2023 systematic review of jump-height methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC10115716/).

Future additions can supply another `CMJSignals` adapter (e.g. another export convention), extend `CMJConfig` with a validated event detector, or add new strategy metrics and figures without changing DJ/SDJ. Frontal-plane analysis, coaching diagnoses, normative thresholds and reconstruction of inverse dynamics are outside this first version.


## Folder reporting defaults

The desktop launcher and CLI default to separate DJ/SDJ HTML and CMJ performance PDF reports when both protocols exist in a folder. The desktop opens both and surfaces analysis errors even when some trials succeed. CMJ performance uses the matching raw Nexus CSV for all force dynamics and events, never the filtered C3D analog signal as a fallback. It does not parse kinematics. No additional software filtering is applied by default. A CSV-only folder is also supported. Explicit `extended` retains the original C3D/CSV motion-analysis adapter; `both` requires CSV force and reads joint channels from C3D.

## Evidence for force filtering

For performance-only CMJ analysis, good-quality raw force is a defensible default. Harry et al. (2022), *Low-Pass Filter Effects on Metrics of Countermovement Vertical Jump Performance*, found no significant differences between raw and 50 Hz processing for the assessed variables in 21 collegiate basketball players. More restrictive signal-power-based cutoffs changed several COM-derived metrics. This does not prove equivalence for every dataset or justify using the kinematic cutoff for force-only reports. DOI: https://doi.org/10.1519/JSC.0000000000003611

Merrigan et al., *Analyzing Force-Time Curves: Comparison of Commercially Available Automated Software and Custom MATLAB Analyses*, report unfiltered Bertec force analyses in ForceDecks and Hawkin, while noting a 50 Hz default for Hawkin's own plates at the time. These are version- and hardware-specific findings, not a claim about current vendor defaults. Source: https://www.hawkindynamics.com/hubfs/Analyzing%20Force-Time%20Curves%20Agreement%20Among%20Commercially%20Available%20Automated%20Software%20and%20Custom%20MATLAB%20Analyses.pdf

Zanoni and O'Reilly's 2026 SportRxiv preprint compared raw, 50 Hz and 100 Hz force signals from CMJ and drop jumps (six participants, 30 trials per protocol). They found no statistical differences from raw in the investigated 100 Hz conditions. The study includes landing impacts and is not yet peer-reviewed; this is support for testing 100 Hz when filtering is needed, not a guarantee of unchanged CMJ peaks or jump heights. Source: https://doi.org/10.51224/SportRxiv.744

A 100 Hz sampling rate and a 100 Hz low-pass cutoff are different settings. Filtering decisions should specify sample rate, cutoff, order, phase response and affected metrics. In this application, clean raw CSV remains the performance default; matching force/kinematic filtering belongs to the separate inverse-dynamics workflow.
