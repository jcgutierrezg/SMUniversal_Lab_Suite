"""
Hall-effect measurement.

Ported from Hall_v4.ipynb. The sequence, the arithmetic, and the saved
file layout are carried over unchanged; what changed is who they talk to.
Instead of writing SCPI strings down a raw socket, this calls driver
methods, so the same sequence runs on any SMU with a driver.

Sequence per run:
    1. Confirm the switch-box position AND the magnet polarity
    2. Configure the SMU (current source, 4-wire, ranges, compliance)
    3. Output ON
    4. Measure an averaged block at +I, then one at -I
    5. Record V+ and V- as a row
    6. Output OFF

Four runs make a full dataset - Pos1+, Pos1-, Pos2+, Pos2- - and those
four rows feed the eight voltages the calculation needs.

Relationship to Van der Pauw
----------------------------
The two share their instrument setup, their polarity-reversal habit, and
their corner diagram, and the shared parts have been factored out
(core/gui/corner_diagram.py, core/gui/temp_panel.py, core.limits.parse_si).

What is *not* shared is what they do with the readings, and that is the
real difference between them. Van der Pauw averages the two polarities
into one resistance. Hall keeps them apart, because reversing the current
is one of the two reversals its eight-term average depends on - averaging
them here would cancel exactly the signal being measured.

Two deliberate deviations from the original are flagged at
_measure_polarity() and run_pressed() below.
"""
import math
import datetime
import os
import time
import tkinter as tk
from tkinter import messagebox, filedialog

from experiments.base_experiment import Experiment
from core.calculation import (CalculationInput, CalculationRefused,
                              InputValue, SourceRow, derive, require_set,
                              signature, tag, validate)
from core.identity import reading_id
from core.parameters import HallParameters
from core.units import um_to_m
from core.validation import (ValidationError, one_of, positive_number,
                             whole_number)
from core.limits import format_amps, parse_si
from core.gui.corner_diagram import paint_corner_roles
from core import vdp_result
from core.gui.widgets import (refresh_nplc, parse_nplc, apply_nplc,
                              refresh_high_z, apply_high_z)
from core.run_store import Run

from . import hall_math
from .panels.diagram_panel import build_diagram_panel
from .panels.positions_panel import build_positions_panel
from .panels.setup_panel import build_setup_panel
from .panels.action_panel import build_action_panel
from .panels.results_panel import build_results_panel
from .panels.calc_panel import build_calc_panel

# Which corner carries current and which senses voltage, per switch-box
# position. Unchanged from the original: the two positions swap the roles
# of the two diagonals.
CORNER_ROLES = {
    1: {1: "I", 2: "V", 3: "I", 4: "V"},
    2: {1: "V", 2: "I", 3: "V", 4: "I"},
}

# How a (position, B polarity) run maps onto the calculation boxes.
# V+ is the reading at +I, V- the reading at -I; swapping the digits in
# the name is what "current reversed" means. Straight from the original's
# copy_over().
COPY_MAP = {
    (1, "+"): ("v13p_var", "v31p_var"),
    (1, "-"): ("v13n_var", "v31n_var"),
    (2, "+"): ("v24p_var", "v42p_var"),
    (2, "-"): ("v24n_var", "v42n_var"),
}

DEFAULT_LEVEL_A = 100e-6
DEFAULT_DELAY_MS = 50.0

# Significant figures used when a measured voltage is written into the
# results table and then into the calculation boxes.
#
# This is not cosmetic. The Hall voltage rides on a resistive offset that
# is routinely 100-1000x larger, and the eight-term average recovers it
# by subtracting nearly-equal numbers. Every digit dropped on the way in
# is a digit lost from the *signal*, not from the offset:
#
#     offset/signal     %.6g error     %.9g error
#          100x           0.011%         0.000%
#         1000x           0.136%         0.000%
#
# The original script used 6 significant figures throughout, which put a
# floor of roughly 0.1% on V_H before the physics was even reached. Nine
# costs nothing and moves that floor below the measurement noise.
#                                                       # DEVIATION 2
VOLTAGE_FIGURES = 9


class HallExperiment(Experiment):
    NAME = "Hall effect - carrier density and mobility"
    TAB_NAME = "Hall effect"

    ROLES = {"source": "SMU"}

    CSV_SLUG = "hall"
    CSV_TITLE = "Hall effect - carrier density and mobility"

    # Wave 5b: shared with Van der Pauw in the combined window. The
    # thickness in particular - a carrier density computed from one
    # thickness while the sheet resistance came from another is wrong in
    # a way that looks entirely reasonable on screen.
    USES_TEMP_STAGE = True
    SESSION_FIELDS = ("sample", "thickness")

    PANELS = [
        build_diagram_panel,
        build_positions_panel,
        build_setup_panel,
        build_action_panel,
        build_results_panel,
        build_calc_panel,
    ]

    def __init__(self, app):
        super().__init__(app)
        # Kept only as the "Set" button's confirmation of what it
        # accepted. Nothing reads it: the run and the calculation both
        # take the thickness from the entry box through a validator, so
        # a forgotten "Set" press cannot leave a run using last week's
        # value.
        self.thickness_um = 1.0
        # `measuring` is gone (Wave 5a-ii, A6). It was a flag shared by
        # every consecutive run - a worker that outlived its run and
        # woke during the next one read the new run's cleared flag as
        # permission to continue. State lives on the run now.
        #
        # Where the sheet resistance came from, if it was loaded rather
        # than typed. Recorded in saved files so a Hall result can be
        # traced back to the Van der Pauw run behind it. Wave 5c
        # replaces this file path with the VdP `DerivedResult` itself.
        self.rs_source_path = None
        # Last successful calculation, embedded in the CSV header on save.
        self._calculated = {}

        # ---- Wave 4 calculation layer, wired here in Wave 5a-ii ----
        self._calc_result = None
        # Voltage box name -> the run that supplied it, when it was
        # copied rather than typed, held alongside the value it belongs
        # to so a typed-over box honestly loses its lineage.
        self._calc_sources = {}
        self._calc_source_values = {}

    def on_panels_built(self):
        """Paint the corner diagram, and watch the calculation inputs.

        Read-only observers: they compare signatures and grey labels.
        Nothing here writes a Tk variable, so no trace can fire another
        and there is no ordering to get wrong.
        """
        self.on_pos_changed()
        watched = [getattr(self, name) for name in (
            "v13p_var", "v31p_var", "v24p_var", "v42p_var",
            "v13n_var", "v31n_var", "v24n_var", "v42n_var",
            "calc_B_var", "calc_Rs_var", "calc_I_var",
            "sample_type_var", "thickness_entry_var", "sample_name_var")]
        for var in watched:
            var.trace_add("write", self._on_calc_input_changed)

    # ---- driver-aware setup ----
    def on_connected(self, role, driver):
        """Offer the connected instrument's ranges as suggestions.

        Note the difference from Van der Pauw: there the current list is
        a locked dropdown, because only those exact values are wanted.
        Here it stays editable and the instrument's ranges are only
        *hints*, since Hall routinely wants a level between range steps.
        The limit gate, not the widget, is what keeps the request legal.
        """
        # Ahead of the early return below: NPLC support is declared
        # separately from LIMITS, so a driver with no declared ranges
        # can still have an integration-time control.
        refresh_nplc(self.nplc_combo, self.nplc_var, driver, self.log)
        refresh_high_z(self.high_z_check, self.high_z_var, driver, self.log)

        limits = driver.LIMITS
        if limits is None:
            return

        levels = [format_amps(a) for a in sorted(limits.current_ranges, reverse=True)]
        self.level_combo["values"] = levels

        v_labels = ["AUTO"] + [self._volt_label(v) for v in sorted(limits.voltage_ranges)]
        self.volt_range_combo["values"] = v_labels
        if self.volt_range_var.get() not in v_labels:
            self.volt_range_var.set("AUTO")

        self.log(f"Ranges loaded from {driver.DISPLAY_NAME}")

    @staticmethod
    def _volt_label(volts):
        """Label a voltage range for the dropdown."""
        return f"{volts*1000:g} mV" if volts < 1 else f"{volts:g} V"

    # ---- input parsing ----
    def get_level_amps(self):
        """Source current from the entry box, in amps.

        Falls back to the original's 100 µA default on unparseable input,
        rather than refusing, so a typo doesn't lose a run that's already
        been set up at the bench.
        """
        text = self.level_var.get()
        try:
            return parse_si(text)
        except (ValueError, TypeError):
            self.log(f"Could not parse current '{text}', using 100 µA")
            self.level_var.set("100 µA")
            return DEFAULT_LEVEL_A

    def get_voltage_range(self):
        """Voltage range from the dropdown, in volts, or None for AUTO."""
        text = self.volt_range_var.get()
        return None if text.upper() == "AUTO" else parse_si(text)

    def get_vlim_volts(self):
        """Voltage compliance from its entry box, in volts. AUTO keeps
        the original's 0.3 V fallback."""
        text = (self.vlim_var.get() or "").strip()
        if text.upper() == "AUTO":
            return 0.3
        return parse_si(text)

    def parse_delay(self):
        """Settle delay in seconds, from the ms entry box. Falls back to
        the original's 50 ms default on bad input."""
        text = (self.delay_ms_var.get() or "").strip()
        try:
            ms = float(text)
            if ms <= 0:
                raise ValueError
        except ValueError:
            ms = DEFAULT_DELAY_MS
            self.log(f"Invalid delay '{text}', using {ms} ms")
            self.delay_ms_var.set(f"{ms:g}")
        return ms / 1000.0

    def set_thickness(self):
        """Validate and store the sample thickness in µm."""
        try:
            val = float(self.thickness_entry_var.get())
            if val <= 0:
                raise ValueError("thickness must be > 0")
            self.thickness_um = val
            self.log(f"Thickness set to {val:g} µm")
        except ValueError as e:
            messagebox.showerror("Invalid thickness",
                                 f"Enter a positive number in µm. ({e})")

    # ---- setup-panel actions ----
    def on_set_level(self):
        """Set level button: validate, then push the level to the
        instrument if one is connected.

        The check runs even when nothing is connected, so a bad entry is
        caught at the desk rather than at the moment of sourcing.
        """
        try:
            level = parse_si(self.level_var.get())
        except (ValueError, TypeError) as e:
            messagebox.showerror("Invalid current",
                                 f"Could not read '{self.level_var.get()}'. ({e})")
            return

        if not self.app.is_connected("source"):
            self.log(f"Level set locally to {level:g} A (no instrument connected)")
            return

        try:
            self.app.check_source_point("source", current=level,
                                        voltage=self.get_vlim_volts())
        except Exception as e:
            self.log("Refused:", e)
            messagebox.showerror("Outside instrument limits", str(e))
            return

        def task():
            smu = self.instrument("source")
            smu.set_current_range(None)
            smu.set_current_level(level)
            self.log(f"Applied level {level:g} A to instrument")

        self.app.run_in_background(self.app.guard_run(task))

    def on_volt_range_changed(self):
        """Voltage range dropdown.

        Setting the range also fills VLIM to match, which is what the
        original did - on this instrument the compliance is rarely wanted
        above the range you've just chosen to sense. Retained because
        it's a genuine convenience, and the box stays editable if you
        disagree with the suggestion.
        """
        text = self.volt_range_var.get()
        self.vlim_var.set("0.3" if text.upper() == "AUTO" else f"{parse_si(text):g}")
        self.log(f"Voltage range {text}, VLIM now {self.vlim_var.get()} V")

    # ---- diagram ----
    def on_pos_changed(self):
        """Recolour the corner diagram for the selected position."""
        paint_corner_roles(self, CORNER_ROLES.get(int(self.pos_var.get()), {}))
        self.log(f"Selected Pos{self.pos_var.get()} "
                 f"(B polarity {self.field_sign_var.get()})")

    # ---- the run ----
    def _run_params(self):
        """Snapshot the form at the Run press. Main thread only.

        Every Tk variable this run depends on is read here, once, and
        frozen. The field sign is in it for a reason worth stating: a
        Hall run is defined by the pair (position, B sign), and the
        calculation is a difference between the two field directions.
        A run whose recorded sign did not match the magnet is not a
        slightly-wrong run, it is an uninterpretable one.
        """
        return HallParameters(
            sample=self.current_sample_ref(),
            dataset=f"Pos{int(self.pos_var.get())}"
                    f"{self.field_sign_var.get()}",
            position=whole_number(self.pos_var.get(), "Position",
                                  minimum=1, maximum=2),
            field_sign=one_of(self.field_sign_var.get(), "B polarity",
                              ("+", "-")),
            level_a=self.get_level_amps(),
            points_n=whole_number(self.points_var.get(), "Points", minimum=1),
            delay_s=self.parse_delay(),
            compliance_v=self.get_vlim_volts(),
            voltage_range_v=self.get_voltage_range(),
            nplc=parse_nplc(self.nplc_var),
            high_z=bool(self.high_z_var.get()),
            thickness_m=um_to_m(positive_number(
                self.thickness_entry_var.get(), "Thickness")),
        )

    def run_pressed(self):
        """Run button: confirm the bench setup, then measure."""
        if not self._ready_to_run():
            return

        try:
            params = self._run_params()
        except (ValidationError, ValueError) as e:
            messagebox.showerror("Invalid setup", str(e))
            return

        # After validation, before anything is claimed: no point sending
        # the operator to the magnet if the form is going to be refused.
        if not messagebox.askokcancel(
                "Confirm setup",
                f"Set the switch box to position {params.position} "
                f"and the magnet to B polarity {params.field_sign}."
                f"\n\nClick OK to start."):
            self.log("User cancelled run")
            return

        # The hard gate: refuse before anything is sourced. It matters
        # more here than in Van der Pauw, because the level box is
        # free-form - it is the only check on a mistyped level.
        try:
            self.app.check_source_point("source", current=params.level_a,
                                        voltage=params.compliance_v)
        except Exception as e:
            self.log("Refused:", e)
            messagebox.showerror("Outside instrument limits", str(e))
            return

        self.app.run_in_background(
            self.app.guard_run(lambda: self._do_run(params)))

    def _ready_to_run(self):
        """Refuse a second run while the first is still unwinding.

        `run_in_progress()` stays true until instrument ownership has
        been released, which is later than "the worker thread finished".
        """
        if self.run_in_progress():
            return False
        # Wave 5b: the Van der Pauw tab may hold the SMU. Asked here
        # rather than at the claim, so the refusal lands before the
        # operator is sent to the switch box and the magnet.
        if self.refuse_if_sibling_busy():
            return False
        if not self.app.is_connected("source"):
            messagebox.showwarning("Not connected", "Connect the SMU first.")
            return False
        return True

    def _enter_run_ui(self):
        """Buttons for a run that has just started. Main thread."""
        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

    def _end_run(self):
        """Back to idle. Main thread, and safe to call twice."""
        try:
            self.run_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.set_lamp(False)
            self.progress_var.set("Idle")
        except Exception:
            pass

    def stop_pressed(self):
        """Cancel the run in flight: discard its data and de-energise.

        Nothing here talks to the instrument. Cancellation sets a token
        belonging to *this* run, so a worker that outlives its run
        cannot mistake a later run's fresh token for permission to carry
        on (A6). The output-off happens in the worker's own cleanup, on
        the thread that owns the session.
        """
        if self.cancel_run("operator pressed Stop"):
            self.progress_var.set("Stopping - discarding this run...")
            self.log("Stop pressed: cancelling, output off, data discarded")

    def _do_run(self, params):
        """Measure both current polarities at one (position, B sign).

        Background thread. The lifecycle is the one Wave 3 established
        and Wave 5a-i repeated: the sequence sits inside `begin_run()`,
        which owns the ending - terminal status, discard, release
        ownership, back to idle, in that order.

        Readings are provisional until `run.commit()`. That matters more
        here than anywhere else in the suite: a Hall row that reached the
        table from a cancelled run would be indistinguishable from the
        seven good ones around it, and the eight-term average would
        silently include it.
        """
        with self.begin_run(parameters=params) as run:
            # Registered before the claim so it unwinds after it - the UI
            # must not say "idle" until the instrument is handed back.
            run.on_cleanup(lambda: self.app.ui(self._end_run))

            run.enter(self.app.claim_instrument("source", run.run_id))
            smu = self.instrument("source")
            self.app.ui(self._enter_run_ui)
            run.expect(params.readings_n)

            try:
                self._configure(run, smu, params)
                v_plus, i_plus = self._measure_polarity(run, smu, params, +1)
                v_minus, i_minus = self._measure_polarity(run, smu, params, -1)
            finally:
                # Always bring the source down, whatever went wrong,
                # including a cancellation. On the thread that owns the
                # session, and the only place the output is turned off.
                report = run.confirm_shutdown(smu, log=self.log)
                self.app.ui(self.set_lamp, False)
                if report.uncertain:
                    self.app.report_uncertain_shutdown("source", report)

            self._finish_run(run, params, v_plus, i_plus, v_minus, i_minus)

    def _configure(self, run, smu, params):
        """Put the instrument into the state this run needs.

        Applied every run rather than once at connect: otherwise the
        instrument keeps whatever the last experiment left it in, and
        the same sample reads differently depending on history.
        """
        run.checkpoint("configure")
        smu.set_source_function("current")
        smu.set_current_range(None)             # auto
        smu.set_voltage_range(params.voltage_range_v)
        smu.set_remote_sense(True)
        smu.set_voltage_limit(params.compliance_v)
        smu.set_source_delay(params.delay_s)

        applied_nplc = apply_nplc(smu, params.nplc, self.log)
        applied_high_z = apply_high_z(smu, params.high_z, self.log)
        run.set_metadata(
            nplc=applied_nplc if applied_nplc is not None else "",
            output_off_mode=("high-Z" if applied_high_z
                             else ("normal" if applied_high_z is not None
                                   else "")))

        # The last gate before the output goes live. §8 names this race:
        # Stop pressed during configuration, worker energises anyway.
        run.checkpoint("before output on")
        smu.output_on()
        self.log("Output ON")
        self.app.ui(self.set_lamp, True)
        run.start()

    def _measure_polarity(self, run, smu, params, polarity):
        """Source `level * polarity`, settle, read, return (mean V, mean I).

        Averaging is unchanged from the original: V and I are averaged
        *independently* across the block. This differs from Van der
        Pauw, which averages the per-reading ratio V/I. Both are
        faithful to their own original script, and the difference is
        deliberate - Hall wants the voltage itself, not a resistance.

        One deviation from the original is retained: it issued no
        host-side wait between readings and sent :SOUR:DEL in
        microseconds where the 2450 family takes seconds. The delay now
        goes through the driver in seconds, and the host-side settle
        after a polarity switch is kept - it is what dominated.

        The readings go onto the run context rather than being returned
        for the caller to hold. A cancelled run's readings are discarded
        with it, so there is no attribute left holding the last block a
        previous run managed.
        """
        signed = params.level_a * polarity
        label = "pos" if polarity > 0 else "neg"

        run.checkpoint(f"{label} polarity")
        smu.set_source_delay(params.delay_s)
        smu.set_current_range(None)
        smu.set_current_level(signed)

        # `run.sleep` rather than `time.sleep`: it wakes early when
        # cancelled, so Stop during a long settle is felt at once.
        if params.delay_s > 0:
            self.log(f"Settling {params.delay_s:.3f} s at {label} polarity")
            run.sleep(params.delay_s, stage=f"settle {label}")

        v_values = []
        i_values = []
        for n in range(params.points_n):
            run.checkpoint(f"{label} point {n + 1}")
            if not self.app.is_connected("source"):
                break
            try:
                v, current = smu.measure()
            except Exception as e:
                self.log(f"Point {n+1}/{params.points_n} [{label}] error: {e}")
                run.add_reading({"point": n + 1, "current_polarity": label,
                                 "timestamp": datetime.datetime.now().isoformat(),
                                 "voltage_V": "", "current_A": "",
                                 "error": str(e)})
                run.record_error(str(e))
                continue
            ts = datetime.datetime.now().isoformat()
            self.log(f"Point {n+1}/{params.points_n} [{label}] V={v} I={current}")
            run.add_reading({"point": n + 1, "current_polarity": label,
                             "timestamp": ts, "voltage_V": v,
                             "current_A": current, "error": ""})
            if v is not None:
                v_values.append(v)
            if current is not None:
                i_values.append(current)
            self.app.ui(self.progress_var.set,
                        f"{label} polarity: {n + 1}/{params.points_n}")

        v_avg = math.fsum(v_values) / len(v_values) if v_values else None
        i_avg = math.fsum(i_values) / len(i_values) if i_values else None
        return v_avg, i_avg

    def _finish_run(self, run, params, v_plus, i_plus, v_minus, i_minus):
        """Build the record and put it through the commit gate.

        No averaging across polarities here, unlike Van der Pauw. The
        two voltages are kept separate and both reach the table, because
        the calculation downstream needs them apart - averaging them
        would destroy exactly the quantity being measured.
        """
        run.checkpoint("commit")
        current_shown = (abs(i_plus) if i_plus is not None
                         else abs(params.level_a))

        run.set_metadata(
            position=params.position,
            b_polarity=params.field_sign,
            level_A=params.level_a,
            points_requested=params.points_n,
            delay_s=params.delay_s,
            thickness_um=params.thickness_m * 1e6,
            V_plus_V=v_plus if v_plus is not None else "",
            V_minus_V=v_minus if v_minus is not None else "",
            I_mean_pos_A=i_plus if i_plus is not None else "",
            I_mean_neg_A=i_minus if i_minus is not None else "",
            stage_temp_C=self._stage_temperature() or "",
        )

        row = (
            params.sample_label,
            f"Pos{params.position}",
            params.field_sign,
            f"{current_shown:.6g}",
            f"{v_plus:.{VOLTAGE_FIGURES}g}" if v_plus is not None else "-",
            f"{v_minus:.{VOLTAGE_FIGURES}g}" if v_minus is not None else "-",
        )

        metadata = dict(params.to_metadata())
        metadata.update(run.metadata)
        metadata["run_id"] = run.run_id
        metadata["meas_number"] = self.app.take_meas_number()

        record = Run(sample=params.sample.slug, metadata=metadata,
                     readings=list(run.readings))
        run.commit(record, lambda committed: self.app.ui(
            self._record_run, row, committed))

    def _record_run(self, row, run):
        """Add a finished run to the table and the store together, keyed
        on the Treeview item id so the two can't drift apart."""
        item = self.tree.insert("", "end", text="☐", values=row)
        self.run_store.add(item, run)

    def _stage_temperature(self):
        """Current stage temperature, or None when there's no usable
        reading. Recorded per run because carrier density and mobility
        are strongly temperature-dependent."""
        if not self.temp_ctrl.is_connected():
            return None
        status = self.temp_ctrl.status()
        if status.is_stale or status.fault or status.temp_c is None:
            return None
        return round(status.temp_c, 1)

    def calculated_fields(self):
        """Hall results plus the inputs they depend on, for the saved
        CSV header.

        B, Rs and the current are included alongside the outputs on
        purpose: without them the carrier density can't be checked or
        recomputed later, and a number nobody can re-derive is a number
        nobody can trust.
        """
        if self._calc_result is not None and \
                self._calc_result.is_stale(self._calc_signature()):
            self.log("Calculation is stale - the inputs changed since it "
                     "was computed. Saving raw data only; press Calculate "
                     "and save again to include it.")
            for line in self._calc_result.stale_because(self._calc_signature()):
                self.log("  ", line)
            return {}
        fields = dict(self._calculated)
        if self.rs_source_path:
            fields["Rs_source"] = self.rs_source_path
        return fields

    def calculated_sample_id(self):
        """Which sample the calculation belongs to (§17).

        With this override the last `current_sample_name()` comparison
        in `save_runs()` is gone from the three ported experiments: all
        of them now file a derived result against the sample identity
        that produced it rather than against the text box.
        """
        return None if self._calc_result is None else self._calc_result.sample_id

    def set_lamp(self, on):
        """Colour the output indicator."""
        self.lamp_canvas.itemconfig(self.lamp_id, fill="green" if on else "gray")

    # ---- results table ----
    def toggle_row(self, event):
        """Click in the checkbox column toggles that row's ☑/☐."""
        if self.tree.identify("region", event.x, event.y) != "tree":
            return
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        current = self.tree.item(row_id, "text") or ""
        self.tree.item(row_id, text="☐" if current == "☑" else "☑")

    def copy_over(self):
        """Copy the four ticked rows' V+/V- into the calculation boxes.

        Requires exactly {Pos1+, Pos1-, Pos2+, Pos2-} - one run per
        position-and-field combination. Anything else is refused rather
        than half-filled, because a partly-populated calculation panel
        still holding values from a previous sample is the kind of
        mistake that produces a plausible wrong answer.

        Four ticked rows, eight boxes: each run carries a V+ and a V-,
        the readings at +I and -I. So `require_set()` checks the four
        *runs*, and the eight voltages are what they populate.

        B, Rs and I are left alone on purpose - see calc_panel.py.
        """
        ticked = [i for i in self.tree.get_children()
                  if (self.tree.item(i, "text") or "") == "☑"]
        if len(ticked) != 4:
            messagebox.showerror(
                "Copy error",
                "Tick exactly 4 rows - Pos1+, Pos1-, Pos2+, Pos2-.")
            return

        by_combo = {}
        sources = {}
        for item in ticked:
            values = self.tree.item(item, "values")
            if len(values) < 6:
                messagebox.showerror("Copy error", "Unexpected table row format.")
                return
            try:
                pos_num = int(str(values[1]).strip().replace("Pos", ""))
            except ValueError:
                messagebox.showerror("Copy error",
                                     f"Unexpected position value: {values[1]}")
                return
            sign = str(values[2]).strip()
            by_combo[(pos_num, sign)] = values

            record = self.run_store.get(item)
            if record is not None:
                run_id = record.metadata.get("run_id", "")
                sources[(pos_num, sign)] = SourceRow(
                    run_id=run_id,
                    sample_id=record.metadata.get("sample_id", ""),
                    sample_label=record.metadata.get("sample_label", ""),
                    row_ids=tuple(reading_id(run_id, i)
                                  for i in range(len(record.readings))),
                    position=f"Pos{pos_num}",
                    polarity=sign,
                )

        if set(by_combo) != set(COPY_MAP):
            messagebox.showerror(
                "Copy error",
                "Ticked rows must be exactly one each of "
                "Pos1+, Pos1-, Pos2+, Pos2-.")
            return

        # §27's shared check, over the *runs* rather than the table rows.
        #
        # Conditional on all four being traceable, and deliberately so.
        # The row check above is the authoritative completeness gate and
        # always applies; this one additionally catches two ticked rows
        # that resolve to the same run, which the row check cannot see.
        # A row with no stored run is legitimate - the table can be
        # populated before a run store exists, and tests do exactly that
        # - so an untraceable row loses its provenance rather than
        # blocking the copy.
        if len(sources) == len(COPY_MAP):
            try:
                require_set(list(sources.values()),
                            {f"Pos{p}{s}" for p, s in COPY_MAP}, what="both")
            except CalculationRefused as e:
                self.log("Copy refused:", e.reason)
                messagebox.showerror("Copy error", str(e))
                return

        # Parse everything before writing anything, so a bad row cannot
        # leave the panel half-updated.
        parsed = {}
        missing = []
        for combo, (v_plus_attr, v_minus_attr) in COPY_MAP.items():
            values = by_combo[combo]
            for attr, cell in ((v_plus_attr, values[4]), (v_minus_attr, values[5])):
                try:
                    parsed[attr] = float(str(cell).strip())
                except ValueError:
                    missing.append(f"Pos{combo[0]}{combo[1]}")

        if missing:
            messagebox.showerror(
                "Copy error",
                "These rows have no numeric V+/V- values: "
                + ", ".join(sorted(set(missing))))
            return

        self._calc_sources = {}
        self._calc_source_values = {}
        for combo, (v_plus_attr, v_minus_attr) in COPY_MAP.items():
            for attr in (v_plus_attr, v_minus_attr):
                value = parsed[attr]
                getattr(self, attr).set(f"{value:.{VOLTAGE_FIGURES}g}")
                # Both boxes from one run share its provenance: the run
                # measured both polarities, and neither voltage is
                # attributable without the other.
                if combo in sources:
                    self._calc_sources[attr] = sources[combo]
                    self._calc_source_values[attr] = float(
                        f"{value:.{VOLTAGE_FIGURES}g}")

        self.log("Copied 4 rows into the calculation fields "
                 "- B, Rs and I left unchanged")
        self.update_differences()

    # ---- calculation ----
    def update_differences(self):
        """Fill the Δ column: each P voltage minus its N counterpart.

        Display only - the calculation doesn't use these. They're a quick
        visual check that the four deltas are of comparable magnitude.
        """
        pairs = [("dv13_var", "v13p_var", "v13n_var"),
                 ("dv31_var", "v31p_var", "v31n_var"),
                 ("dv24_var", "v24p_var", "v24n_var"),
                 ("dv42_var", "v42p_var", "v42n_var")]
        for delta_attr, p_attr, n_attr in pairs:
            p = _float_or_none(getattr(self, p_attr).get())
            n = _float_or_none(getattr(self, n_attr).get())
            getattr(self, delta_attr).set(
                "-" if p is None or n is None else f"{p - n:.6g}")

    # ---- calculation state (Wave 4 layer) ----
    VOLTAGE_ATTRS = ("v13p_var", "v31p_var", "v24p_var", "v42p_var",
                     "v13n_var", "v31n_var", "v24n_var", "v42n_var")

    def _calc_signature(self):
        """Fingerprint of the calculation inputs as the boxes hold them.

        Raw text: this runs from a Tk trace on every keystroke, when a
        box may hold `1.0e-` on the way to `1.0e-3`.

        Every field the result depends on is here, including the ones
        the operator is most likely to change without thinking - B, Rs
        and the sample type. Changing "Thin film" to "Bulk" alters which
        carrier density is reported by a factor of the thickness, and
        none of the eight voltages move when it happens.
        """
        items = {name: getattr(self, name).get().strip()
                 for name in self.VOLTAGE_ATTRS}
        items.update({
            "field_t": self.calc_B_var.get().strip(),
            "sheet_resistance": self.calc_Rs_var.get().strip(),
            "current_a": self.calc_I_var.get().strip(),
            "sample_type": (self.sample_type_var.get() or "").strip(),
            "thickness_m": self.thickness_entry_var.get().strip(),
            "_sample": self.sample_name_var.get().strip(),
        })
        return signature(items)

    def _on_calc_input_changed(self, *_args):
        """Tk trace: mark the result stale if it no longer follows from
        what is on screen (§18)."""
        if self._calc_result is None:
            return
        self._set_calc_stale(self._calc_result.is_stale(self._calc_signature()))

    def _set_calc_stale(self, stale):
        """Grey the readouts and say so, or restore them.

        The carrier-type label keeps its own colour when fresh - it is
        n-type blue or p-type red, and that colour carries meaning - so
        it is greyed with the rest and restored by `calculate_hall()`
        rather than being repainted here.
        """
        colour = "#999999" if stale else ""
        for widget in getattr(self, "calc_result_labels", {}).values():
            widget.configure(foreground=colour)
        if stale and hasattr(self, "carrier_type_label"):
            self.carrier_type_label.configure(foreground="#999999")
        self._refresh_calc_status(stale)

    def _refresh_calc_status(self, stale):
        """Compose the one status line under the calculation."""
        result = self._calc_result
        if result is None:
            self.calc_status_var.set("")
            return

        if stale:
            self.calc_status_var.set(
                "Stale - the inputs have changed since this was "
                "calculated. Press Calculate; it will not be saved as it "
                "stands.")
            self.calc_status_label.configure(foreground="#a05000")
            return

        traced = len(result.source_run_ids)
        if traced == 4:
            origin = "voltages from 4 measured runs"
        elif traced:
            origin = f"voltages from {traced} of 4 measured runs, rest typed"
        else:
            origin = "voltages typed by hand - no source runs"
        self.calc_status_var.set(
            f"{result.method_tag} \u00b7 "
            f"{result.sample_label_at_calculation} \u00b7 {origin}")
        self.calc_status_label.configure(foreground="#777777")

    def _clear_calc_outputs(self):
        """Blank the readouts after a refusal."""
        self._calc_result = None
        self._calculated = {}
        for var in (self.ns_var, self.mu_var, self.rho_var,
                    self.carrier_type_var):
            var.set("-")
        self._set_calc_stale(False)

    def calculate_hall(self):
        """V_H from the eight voltages, then n_s, mobility and rho.

        Arithmetic unchanged from the original. What is new is around
        it: the inputs are checked as a coherent set before any of it
        runs, and the result comes back as a `DerivedResult` naming the
        runs behind it.
        """
        voltages = {}
        missing = []
        for attr in self.VOLTAGE_ATTRS:
            value = _float_or_none(getattr(self, attr).get())
            if value is None:
                missing.append(attr.replace("_var", "").upper())
            voltages[attr] = value

        if missing:
            messagebox.showerror("Invalid inputs",
                                 "Enter numeric values for: " + ", ".join(missing))
            return

        field = _float_or_none(self.calc_B_var.get())
        sheet_r = _float_or_none(self.calc_Rs_var.get())
        if field is None or sheet_r is None:
            # V_H alone is still worth showing - it is the measurement,
            # and it needs neither B nor Rs. Only the derived quantities
            # are blocked.
            vh_only = hall_math.hall_voltage(
                *(voltages[a] for a in self.VOLTAGE_ATTRS))
            self.vh_var.set(f"{vh_only:.6g}")
            self.update_differences()
            messagebox.showerror(
                "Invalid inputs",
                "Enter numeric B (T) and sheet resistance Rs (\u03a9/\u25a1) "
                "to compute carrier density and mobility.")
            self._clear_calc_outputs()
            return

        try:
            thickness_m = um_to_m(positive_number(
                self.thickness_entry_var.get(), "Thickness"))
            sample = self.current_sample_ref()
        except (ValidationError, ValueError) as e:
            messagebox.showerror("Invalid setup", str(e))
            return

        # Current from the calc box if given, otherwise the instrument's
        # nominal level - the original's fallback, kept because the two
        # legitimately differ when compliance clamps the source.
        current_typed = _float_or_none(self.calc_I_var.get())
        if current_typed is None:
            current = abs(self.get_level_amps())
            self.log(f"Using instrument level current for calculation: {current:g} A")
        else:
            current = abs(current_typed)
            self.log(f"Using entered current for calculation: {current:g} A")

        # A run keeps its provenance only while **both** of the boxes it
        # filled still hold the numbers it produced.
        #
        # All-or-nothing per run, not per box, and the difference is not
        # pedantic. Each run supplies a V+ and a V-; claiming the run as
        # a source when one of the two has been typed over would put a
        # run id in the header against a pair of voltages the run did not
        # both produce. A provenance chain that is half true reads
        # exactly like one that is wholly true.
        by_run = {}
        for attr, source in self._calc_sources.items():
            by_run.setdefault(source.run_id, [source, []])[1].append(attr)
        sources = tuple(
            source for source, attrs in by_run.values()
            if all(self._calc_source_values.get(a) == voltages[a]
                   for a in attrs))

        values = {attr: InputValue(voltages[attr], "V",
                                   getattr(self, attr).get().strip())
                  for attr in self.VOLTAGE_ATTRS}
        values.update({
            "field_t": InputValue(field, "T", self.calc_B_var.get().strip()),
            "sheet_resistance": InputValue(
                sheet_r, "\u03a9/\u25a1", self.calc_Rs_var.get().strip()),
            "current_a": InputValue(current, "A",
                                    self.calc_I_var.get().strip()),
            "sample_type": InputValue(
                0.0, "", (self.sample_type_var.get() or "Thin film").strip()),
            "thickness_m": InputValue(
                thickness_m, "m", self.thickness_entry_var.get().strip()),
        })

        calc = CalculationInput(
            method="hall_sheet_carrier_density",
            sample_id=sample.sample_id,
            sample_label=sample.label,
            values=values,
            sources=sources,
            required=(*self.VOLTAGE_ATTRS, "field_t", "sheet_resistance",
                      "current_a", "thickness_m"),
        )

        # §16. Refused before any arithmetic, with both sample names in
        # the message - a Hall calculation run against another sample's
        # sheet resistance is arithmetically perfect and physically
        # meaningless, so the operator has nothing else to go on.
        try:
            validate(calc, distinct_runs=True)
        except CalculationRefused as e:
            self._clear_calc_outputs()
            self.log("Calculation refused:", e.reason)
            messagebox.showerror("Cannot calculate", str(e))
            return

        vh = hall_math.hall_voltage(
            *(voltages[a] for a in self.VOLTAGE_ATTRS))
        self.vh_var.set(f"{vh:.6g}")
        self.log(f"V_H = {vh:.6g} V")
        self.update_differences()

        try:
            ns_cm2 = hall_math.sheet_carrier_density(current, field, vh)
            mobility = hall_math.hall_mobility(ns_cm2, sheet_r)
            thickness_cm = thickness_m * 1e2
            rho = hall_math.resistivity(sheet_r, thickness_cm)
        except ZeroDivisionError as e:
            self.carrier_type_var.set(hall_math.INDETERMINATE)
            for var in (self.ns_var, self.mu_var, self.rho_var):
                var.set("ERR")
            self._calc_result = None
            self._calculated = {}
            self.log("Calculation error:", e)
            messagebox.showerror("Calculation error", str(e))
            return
        except ValueError as e:
            for var in (self.ns_var, self.mu_var, self.rho_var):
                var.set("ERR")
            self._calc_result = None
            self._calculated = {}
            self.log("Calculation error:", e)
            messagebox.showerror("Invalid thickness", str(e))
            return

        # The sign of n_s and mobility is not a magnitude - it is the
        # carrier type, and a negative carrier density is meaningless as
        # a count. So the two are separated: type gets its own readout,
        # and the densities are shown as magnitudes.
        #
        # This differs from the original notebook, which printed the
        # signed value and left the reader to interpret it. Drop the
        # abs() calls below to go back to that.
        carrier = hall_math.carrier_type(vh)
        self.carrier_type_var.set(carrier)
        if hasattr(self, "carrier_type_label"):
            colour = {hall_math.N_TYPE: "#1565c0",
                      hall_math.P_TYPE: "#c62828"}.get(carrier, "#777777")
            self.carrier_type_label.configure(foreground=colour)

        is_bulk = (self.sample_type_var.get() or "Thin film").strip() == "Bulk"
        density = None
        if is_bulk:
            density = hall_math.bulk_carrier_density(ns_cm2, thickness_cm)
            self.ns_var.set(f"{abs(density):.6g} cm^-3")
            self.mu_var.set(f"{abs(mobility):.6g} cm^2/Vs (bulk)")
            self.rho_var.set(f"{rho:.6g} \u03a9\u00b7cm (bulk)")
        else:
            self.ns_var.set(f"{abs(ns_cm2):.6g} cm^-2")
            self.mu_var.set(f"{abs(mobility):.6g} cm^2/Vs")
            self.rho_var.set(f"{rho:.6g} \u03a9\u00b7cm")

        outputs = {
            "V_H_V": vh,
            "carrier_type": carrier,
            "sheet_density_cm2": ns_cm2,
            "mobility_cm2_Vs": mobility,
            "resistivity_ohm_cm": rho,
        }
        if is_bulk:
            outputs["bulk_density_cm3"] = density

        # One result, several registered methods. `hall_voltage:1`,
        # `hall_sheet_carrier_density:1`, `hall_mobility:1` and
        # `hall_resistivity:1` all contributed, and the result is named
        # for the one the operator came for. The rest are recorded in
        # `contributing_methods` so a stored number can still be traced
        # to every formula behind it - which is what §28 is for.
        self._calc_result = derive(calc, outputs=outputs)

        # The signed values still go to the console, so nothing is
        # hidden and an old result can be compared with the original.
        self._calculated = dict(self._calc_result.to_metadata())
        self._calculated.update({
            "contributing_methods": " ".join(
                tag(m) for m in ("hall_voltage", "hall_sheet_carrier_density",
                                 "hall_mobility", "hall_resistivity")
                + (("hall_bulk_carrier_density",) if is_bulk else ())),
            "V_H_V": f"{vh:.9g}",
            "carrier_type": carrier,
            "carrier_density_cm-2": f"{abs(ns_cm2):.9g}",
            "carrier_density_cm-3": (f"{abs(density):.9g}" if is_bulk else ""),
            "mobility_cm2_Vs": f"{abs(mobility):.9g}",
            "resistivity_ohm_cm": f"{rho:.9g}",
            "sample_type": "Bulk" if is_bulk else "Thin film",
            "B_T": f"{field:.9g}",
            "Rs_ohm_per_sq": f"{sheet_r:.9g}",
            "I_A": f"{current:.9g}",
            "thickness_um": f"{thickness_m * 1e6:.6g}",
        })

        self._set_calc_stale(False)
        self.log(f"{carrier}: n={self.ns_var.get()}, mu={self.mu_var.get()}, "
                 f"rho={self.rho_var.get()}")
        self.log(f"  (signed: n_s={ns_cm2:.6g}, mu={mobility:.6g})")
        self.log(f"{self._calc_result.method_tag} -> "
                 f"{self._calc_result.result_id}")

    def load_rs_from_vdp(self):
        """Fill the Rs box from a saved Van der Pauw result file.

        Hall needs a sheet resistance it cannot measure itself, so in
        practice a Van der Pauw run on the same sample comes first. This
        reads that run's result rather than having it retyped - retyping
        a five-digit number between two windows is a transcription error
        waiting to happen, and it loses the record of where the number
        came from.

        The loaded path is remembered and written into subsequent Hall
        data files, so a result can be traced back to the run that
        supplied its Rs.
        """
        path = filedialog.askopenfilename(
            title="Open a saved Van der Pauw CSV",
            initialdir=self.app.storage_path,
            filetypes=[("Van der Pauw CSV", "*_vanderpauw*.csv"),
                       ("CSV files", "*.csv"),
                       ("Text files", "*.txt"),
                       ("All files", "*.*")])
        if not path:
            return

        try:
            sheet_r, fields = vdp_result.read_result(path)
        except (OSError, ValueError) as e:
            self.log("Could not load Rs:", e)
            messagebox.showerror("Could not load Rs", str(e))
            return

        self.calc_Rs_var.set(f"{sheet_r:.9g}")
        self.rs_source_path = path
        self.log(f"Loaded Rs = {sheet_r:.6g} Ω/□ from {os.path.basename(path)}")

        self._warn_on_mismatch(fields, path)

    def _warn_on_mismatch(self, fields, path):
        """Flag a loaded result that looks like it came from a different
        sample or a different set-up.

        Nothing here blocks the load - the operator may have good reason.
        But an Rs measured on a 1 µm film silently applied to a 200 µm
        substrate would give a resistivity out by a factor of 200, and
        the number would look perfectly plausible.
        """
        warnings = []

        vdp_thickness = fields.get("thickness_um")
        if vdp_thickness is not None:
            try:
                value = float(vdp_thickness)
                if abs(value - self.thickness_um) > 1e-9:
                    warnings.append(
                        f"Thickness differs: the VdP run used "
                        f"{value:g} µm, this panel is set to "
                        f"{self.thickness_um:g} µm.")
            except ValueError:
                pass

        vdp_sample = fields.get("sample")
        current_sample = (self.sample_name_var.get() or "").strip().replace(" ", "_")
        if vdp_sample and current_sample and vdp_sample != current_sample:
            warnings.append(
                f"Sample name differs: the VdP run was '{vdp_sample}', "
                f"this one is '{current_sample}'.")

        vdp_temp = fields.get("stage_temp_C")
        if vdp_temp and self.temp_ctrl.is_connected():
            status = self.temp_ctrl.status()
            try:
                if (status.temp_c is not None
                        and abs(float(vdp_temp) - status.temp_c) > 1.0):
                    warnings.append(
                        f"Stage temperature differs: the VdP run was at "
                        f"{float(vdp_temp):.1f} °C, the stage now reads "
                        f"{status.temp_c:.1f} °C.")
            except ValueError:
                pass

        if not warnings:
            return

        for line in warnings:
            self.log("Note:", line)
        messagebox.showwarning(
            "Check this is the right run",
            "Rs was loaded, but this file doesn't match the current "
            "set-up:\n\n- " + "\n- ".join(warnings)
            + "\n\nThe value has been filled in anyway.")

    def on_close(self):
        """Cancel any run in flight before the app tears connections
        down. The stage is handled by Experiment.shutdown_devices().

        Cancelling rather than clearing a flag: the worker owns the
        instrument and must be the one to put the output away, so the
        close path asks it to stop and lets its cleanup run.
        """
        self.cancel_run("application closing")


def _float_or_none(text):
    """float() that returns None instead of raising, for optional or
    possibly-blank entry boxes."""
    try:
        return float(str(text).strip())
    except (ValueError, TypeError):
        return None
