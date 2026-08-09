"""
Ossila four-point probe: sheet resistance, resistivity, conductivity.

Ported from `Ossila_4PP_2611A.py`.

What the original did
---------------------
Sourced a set of currents through the outer two probes, measured the
voltage across the inner two, fitted a line to get resistance, then
multiplied by pi/ln2 and two correction factors to get sheet resistance.
The physics in `calculate_func()` was sound and is reproduced in
`fourpp_math.py` essentially unchanged.

Why this is a port and not a transcription
------------------------------------------
The original could not run. Two independent crashes sat on the Run path:

  * `run_func()` tested `if points <= 30:`, but `points` was the (70, 2)
    geometry meshgrid defined at module scope, not a sweep-point count.
    Comparing an array raises ValueError before any measurement starts.
  * `current_sweep()` opened with a loop calling `set_current()`,
    `measure_voltage()` and `save_data_point()`. None of the three is
    defined anywhere in the file. NameError on the first iteration.

Both look like one accident: a local name shadowed by a module-level
one, and a block of intended helpers left unwritten. The dead loop is
also the clearest surviving statement of intent - it alternated each
current's polarity eight times, which is thermoelectric-offset
cancellation. That is now implemented properly; see `_measure_current()`.

A third inconsistency: the buffer read sliced out "the middle sweep",
which only makes sense against the triangular shape built by
`generate_triangular_sweep_string()` - a function that was written and
never called. The visible GUI sourced eight flat current entries with no
leg structure, so that slice would have taken the wrong region. Both
shapes are offered here, chosen explicitly, and the slicing follows the
choice.

No temperature panel: this is a bench spot-check, not a stage run.
"""
import datetime

from tkinter import messagebox

import functools

from core.calculation import (CalculationInput, CalculationRefused,
                              InputValue, SourceRow, derive, signature,
                              validate)
from core.gui.plot_panel import build_plot_panel, draw_datasets
from core.identity import reading_id
from core.parameters import FourPointProbeParameters
from core.run_store import Run
from core.units import mm_to_m, um_to_m
from core.validation import (ValidationError, positive_number, si_level,
                             whole_number)
from experiments.base_experiment import Experiment

from . import fourpp_math as maths
from .panels.geometry_panel import build_geometry_panel
from .panels.sweep_panel import build_sweep_panel, MAX_CURRENTS
from .panels.action_panel import build_action_panel
from .panels.results_panel import build_results_panel
from .panels.calculation_panel import build_calculation_panel


class Ossila4PPExperiment(Experiment):
    NAME = "Ossila 4-point probe - sheet resistance"

    # Found in Wave 3 and pre-existing: 4PP was the only experiment that
    # never overrode these, so it inherited the base defaults. Two
    # consequences, both quiet. Saved files were named
    # `<sample>_run.csv` rather than `<sample>_ossila_4pp.csv`, and the
    # CSV header said "Lab measurement suite" instead of naming the
    # measurement. Wave 1 then made the slug the run-id prefix as well,
    # so run identifiers read `run-0001-...` and did not say which
    # experiment produced them - which is exactly what a run id is for.
    #
    # Note for the bench: saved filenames change with this. Files
    # already on disk are untouched.
    CSV_SLUG = "ossila_4pp"
    CSV_TITLE = "Ossila 4-point probe - sheet resistance"

    ROLES = {"source": "Source SMU"}

    PANELS = [
        build_geometry_panel,     # col_left  - what the sample is
        build_sweep_panel,        # col_mid   - what to run
        build_action_panel,       # col_mid   - Run / Stop / OFF
        build_results_panel,      # col_right - what came out
        build_calculation_panel,  # col_right - what it means
        # Shorter figure than the IV sweep's default: this column has
        # an extra panel in it. A 4PP run is a handful of points, so it
        # loses far less to a short figure than a 200-point sweep would.
        functools.partial(build_plot_panel, figsize=(4.5, 2.1)),
    ]

    def __init__(self, app):
        super().__init__(app)
        # `measuring` and `_stop_requested` are gone (Wave 3, issue A6).
        # They were one pair of flags shared by every consecutive run,
        # which is precisely what review §10 warns about: a worker that
        # outlives its run and wakes during the next one reads the new
        # run's cleared flag as permission to carry on. State now lives
        # on the run itself - `self.run_in_progress()` for the UI, and a
        # per-run cancellation token for the worker.
        #
        # Keyed by tree item id, not a flat list, so the plot can be
        # filtered by what is ticked - the same shape the IV sweep uses.
        self._datasets = {}
        self._calculated = {}
        # item id -> full-precision fitted resistance. The tree stores a
        # rounded string for display; this keeps the real number.
        self._run_resistance = {}

        # ---- Wave 4: calculation provenance and staleness ----
        # The issued result, or None if nothing has been calculated.
        self._calc_result = None
        # Where the resistance in the box came from, if it was copied
        # from a measured run rather than typed. Held alongside the
        # value it belongs to: if the box no longer holds that number,
        # the provenance no longer applies and the calculation is
        # honestly recorded as hand-entered. That pairing is why there
        # is no trace clearing this - a flag set by one trace and read
        # by another is exactly the kind of two-writer state Wave 3 took
        # out of the run path.
        self._calc_source = None
        self._calc_source_value = None
        # Warnings from the correction tables for the current result.
        self._calc_notes = ()

    # ---- driver-aware setup ----
    def on_panels_built(self):
        """Watch the calculation's inputs so a result can go stale (§18).

        Read-only observers: they compare signatures and grey a label.
        Nothing here writes a Tk variable, so there is no trace that can
        fire another trace, and no ordering to get wrong.

        `sample_name_var` is in the list because changing which sample
        the panel refers to invalidates a result exactly as much as
        changing a thickness does - and it is the more dangerous of the
        two, because none of the displayed numbers move when it happens.
        """
        for var in (self.calc_r_var, self.width_var, self.length_var,
                    self.thickness_var, self.sample_name_var):
            var.trace_add("write", self._on_calc_input_changed)
    def on_connected(self, role, driver):
        self.log(f"Ranges loaded from {driver.DISPLAY_NAME}")

    def on_sweep_mode_changed(self):
        """Swap which mode-specific block is visible.

        Refused mid-run for the same reason the IV sweep refuses a mode
        change: the shape of what is being sourced must not change while
        the output is live.
        """
        if self.run_in_progress():
            messagebox.showwarning(
                "Measurement running",
                "Stop the measurement before changing sweep mode.")
            return

        mode = self.sweep_mode_var.get()
        if mode == "triangular":
            self.list_frame.pack_forget()
            self.triangular_frame.pack(fill="x")
        else:
            self.triangular_frame.pack_forget()
            self.list_frame.pack(fill="x")
        self.log(f"Sweep mode: {mode}")

    # ---- input parsing ----
    def _sweep_params(self):
        """Read the whole form into an immutable snapshot. Main thread.

        Everything the worker will need is captured here, at the Run
        press, on the thread that owns the widgets - the review's §14
        rule. After this returns, nothing typed into the window can
        reach the run in flight.

        Raises `ValidationError` (a `ValueError`, so the existing dialog
        path catches it) naming the offending field.

        Wave 3 replaced four `int(float(...))` and bare `float(...)`
        reads with `core.validation`. The one that mattered: `points`
        and `reversals` used to accept `2.5` and silently run 2, so a
        decimal in an integer box produced a different experiment from
        the one requested with nothing in the data to say so.
        """
        mode = self.sweep_mode_var.get()

        if mode == "triangular":
            start = si_level(self.tri_start_var.get(), "Start current",
                             unit="A")
            stop = si_level(self.tri_stop_var.get(), "Stop current", unit="A")
            points = whole_number(
                self.tri_points_var.get(), "Points",
                minimum=2, maximum=MAX_CURRENTS,
                reason="A sweep needs at least two points to fit a line.")
            if start >= 0 or stop <= 0:
                raise ValidationError(
                    "Start and stop currents",
                    "a triangular sweep runs from a negative start current "
                    "to a positive stop current.\n\n"
                    "Use the current list for single-polarity measurements.")
            currents, middle_start, middle_len = maths.triangular_current_list(
                start, stop, points)
        else:
            currents = []
            for index, var in enumerate(self.current_vars):
                text = var.get().strip()
                if not text:
                    continue          # blank entries are skipped, as labelled
                currents.append(si_level(text, f"Current I{index}", unit="A"))
            if len(currents) < 2:
                raise ValidationError(
                    "Current list",
                    "enter at least two currents to fit a resistance.")
            if len(set(currents)) < 2:
                raise ValidationError(
                    "Current list", "the currents must not all be the same.")
            middle_start, middle_len = 0, len(currents)

            # The ceiling applies to what was asked for, not to the
            # expanded list. A triangular sweep of 21 middle points
            # generates about 41 levels once its approach and return
            # legs are added, and rejecting that would make the limit
            # mean something different in each mode.
            #
            # The original's limit guarded the length of the TSP
            # list-sweep string it built. Sourcing point by point, that
            # constraint is gone; what is left is a sanity bound on run
            # length, since each point costs `reversals` readings.
            if len(currents) > MAX_CURRENTS:
                raise ValidationError(
                    "Current list",
                    f"{len(currents)} currents entered; the maximum is "
                    f"{MAX_CURRENTS}.")

        delay_s = positive_number(self.delay_var.get(), "Delay",
                                  allow_zero=True)
        reversals = whole_number(
            self.reversals_var.get(), "Reversals",
            minimum=1, even_above_one=True,
            reason="An odd count weights the average towards whichever "
                   "polarity came first, which defeats the cancellation.")
        compliance_v = si_level(self.compliance_var.get(), "Voltage limit",
                                unit="V", minimum_exclusive=0.0)

        # Snapshot the geometry here, with the rest of the form, rather
        # than reading it again when the run finishes.
        #
        # _finish_run() used to re-read the entry boxes after the sweep.
        # Anything typed into W, L or t while the measurement ran would
        # be picked up instead - and if a box was mid-edit or empty, the
        # validation raised and the completed run was discarded with it.
        # The numbers that describe the sample must be the ones that
        # were true when it was measured. This was fixed by hand once;
        # the snapshot is what makes it structural.
        width_m, length_m, thickness_m = self._geometry_params()

        return FourPointProbeParameters(
            sample=self.current_sample_ref(),
            dataset=(self.dataset_var.get() or "run").strip(),
            mode=mode,
            currents_a=currents,
            middle_start_n=middle_start,
            middle_len_n=middle_len,
            delay_s=delay_s,
            reversals_n=reversals,
            compliance_v=compliance_v,
            width_m=width_m,
            length_m=length_m,
            thickness_m=thickness_m,
        )

    def _geometry_params(self):
        """Sample dimensions as `(width_m, length_m, thickness_m)`.

        The panel asks for W and L in millimetres and t in micrometres
        because that is what a caliper and a profilometer read. This is
        the boundary where those become SI, per house rule 5 - beyond
        this point the suite holds metres, and the only conversion back
        out is `FourPointProbeParameters.as_math_geometry()`, because
        the Ossila correction tables are published in mm and um.

        Raises `ValidationError`.
        """
        width_mm = positive_number(self.width_var.get(), "Short side W")
        length_mm = positive_number(self.length_var.get(), "Long side L")
        thickness_um = positive_number(self.thickness_var.get(), "Thickness t")

        if length_mm < width_mm:
            raise ValidationError(
                "Long side L",
                f"({length_mm:g} mm) is shorter than W ({width_mm:g} mm).\n\n"
                f"W is the short side and L the long side - see the "
                f"diagram. The geometry correction is indexed by L/W and "
                f"is wrong if they are swapped.")

        return mm_to_m(width_mm), mm_to_m(length_mm), um_to_m(thickness_um)

    def _check_limits(self, params):
        """Check every current in the list against the instrument.

        Before anything is claimed or energised: a point outside the
        instrument's envelope should be refused while the operator is
        still looking at the form, not eight points into a run.
        """
        for current in params.currents_a:
            self.app.check_source_point(
                "source", current=current, voltage=params.compliance_v)

    # ---- run ----
    def run_pressed(self):
        if not self._ready_to_run():
            return
        try:
            params = self._sweep_params()
            self._check_limits(params)
        except ValueError as e:
            # ValidationError is a ValueError, so both the field
            # validators and the geometry rule land here with a message
            # already written for a dialog.
            messagebox.showerror("Invalid setup", str(e))
            return
        except Exception as e:
            self.log("Refused:", e)
            messagebox.showerror("Outside instrument limits", str(e))
            return

        self.app.run_in_background(
            self.app.guard_run(lambda: self._do_run(params)))

    def _ready_to_run(self):
        """Refuse a second run while the first is still unwinding.

        `run_in_progress()` is true until instrument ownership has been
        released, which is later than "the worker thread finished". That
        is deliberate: an instrument that has not been handed back is
        not free, whatever the thread is doing.
        """
        if self.run_in_progress():
            return False
        if self.app.instruments.get("source") is None:
            messagebox.showerror(
                "Not connected", "Connect the source SMU first.")
            return False
        return True

    def _enter_run_ui(self):
        """Buttons and lamp for a run that has just started. Main thread."""
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

        There is one control, not two. Stop *is* the OFF button - it
        cancels, the worker's cleanup puts the output away, and the
        provisional readings never reach the results table. Review §8
        asks for exactly this and states the rule plainly: all cancelled
        runs are discarded regardless of progress.

        Two things make this safe that a bare flag would not:

        * `request_cancel` sets a token belonging to *this* run. A
          worker that outlives its run cannot mistake a later run's
          fresh token for permission to continue (issue A6).
        * nothing here talks to the instrument. The cancellation is
          instant and cannot fail; the output-off is done by the worker
          in its own cleanup, on the thread that already owns the
          session. That is what removes the old race, where OFF sent
          `safe_output_off()` from a second thread while the worker was
          mid-`measure()` on the same transport - two threads, one VISA
          session, interleaved SCPI.

        The cost is latency: the worker notices at its next checkpoint,
        which with the settle delay delegated to the instrument means
        after the reading in progress returns. `test_4pp_lifecycle.py`
        measures that bound rather than asserting it.
        """
        if self.cancel_run("operator pressed Stop"):
            self.progress_var.set("Stopping - discarding this run...")
            self.log("Stop pressed: cancelling, output off, data discarded")

    # ---- the measurement ----
    def _do_run(self, params):
        """Source each current, measure voltage, fit. Background thread.

        Point by point rather than as an instrument sweep, deliberately.
        Reversal averaging needs several readings at each current with
        the polarity flipped between them, then combined - that is a
        different shape from a sweep, and a hardware sweep would hand
        back a flat buffer with the grouping lost. The per-point cost is
        irrelevant here: at most thirty currents, against a settle delay
        that dominates anyway.

        The lifecycle, added in Wave 3
        ------------------------------
        The whole sequence sits inside `begin_run()`. That block owns
        the ending: whether this returns normally, raises, or is
        cancelled, the same four things happen in the same order -
        record a terminal status, discard anything not committed,
        release the instrument, return to idle.

        `run.checkpoint()` is placed before every operation that could
        energise or alter the output, which is the list review §8 gives:
        before output-on, before a source-function change, before each
        new level, before each polarity flip, after every long wait, and
        immediately before the commit. A cancelled run raises
        `RunCancelled` from whichever checkpoint sees it first, and that
        exception is a control-flow signal, not an error - the context
        manager swallows it so pressing Stop does not put a traceback in
        the console.

        Readings are **provisional**. They live on the run context and
        nowhere else until `run.commit()` succeeds, so a cancelled run
        cannot leave half a sweep in the results table.
        """
        with self.begin_run(parameters=params) as run:
            # Registered before the claim, so it unwinds *after* it:
            # an ExitStack unwinds in reverse, and the UI must not say
            # "idle" until the instrument has actually been handed back.
            # Registered before anything can raise, so a refused claim
            # still leaves the buttons usable.
            run.on_cleanup(lambda: self.app.ui(self._end_run))

            # Ownership first, before a single command is issued. The
            # claim is entered into the run's cleanup stack, so it is
            # released after the terminal status is recorded and before
            # the controller returns to idle - which is what makes
            # "idle" mean "the instrument is free".
            run.enter(self.app.claim_instrument("source", run.run_id))
            smu = self.instrument("source")
            self.app.ui(self._enter_run_ui)

            # One reading per current, whatever the reversal count: the
            # reversals are averaged into a single value per level.
            # Declared up front so the gate checks against what was
            # requested rather than against whatever arrived - a sweep
            # that returns a third of its points and fits a beautiful
            # line is a real failure mode on this bench.
            run.expect(params.points_n)

            try:
                self._configure(run, smu, params)
                currents, voltages, offsets = self._sweep(run, smu, params)
            finally:
                # Always bring the source down, whatever went wrong -
                # including a cancellation. This is the only place the
                # output is turned off, and it runs on the thread that
                # owns the session.
                report = run.confirm_shutdown(smu, log=self.log)
                self.app.ui(self.set_lamp, False)
                if report.uncertain:
                    self.app.report_uncertain_shutdown("source", report)

            self._fit_and_commit(run, params, currents, voltages, offsets)

    def _configure(self, run, smu, params):
        """Put the instrument into the state this run needs.

        Every per-run setting is applied on every run rather than once
        at connect - house rule: the instrument may have been touched by
        another window, another program, or a front-panel knob since.
        """
        run.checkpoint("configuring source")
        smu.set_source_function("current")
        smu.set_voltage_limit(params.compliance_v)
        smu.set_voltage_range(params.compliance_v)
        smu.set_current_range(max(abs(c) for c in params.currents_a))
        smu.set_source_delay(params.delay_s)
        smu.set_remote_sense(True)     # a 4PP head is 4-wire by definition

        smu.set_current_level(0.0)

        # The last gate before the output goes live. §8 names this one
        # explicitly: the race it prevents is Stop pressed during
        # configuration, followed by the worker energising anyway.
        run.checkpoint("before output on")
        smu.output_on()
        self.app.ui(self.set_lamp, True)
        run.start()

    def _sweep(self, run, smu, params):
        """Walk the current list. Returns three parallel lists."""
        currents, voltages, offsets = [], [], []
        total = params.points_n

        for index, current in enumerate(params.currents_a, start=1):
            run.checkpoint(f"point {index}/{total}")
            self.app.ui(self.progress_var.set,
                        f"Point {index}/{total}: {current:.3g} A")

            voltage, offset = self._measure_current(
                run, smu, current, params.reversals_n)
            if voltage is None:
                # Not a skip. A level that produced no reading leaves
                # the run short, and a short run that still fits a line
                # is the failure §7's completion gate exists to catch -
                # so it is recorded as an error, the gate refuses the
                # commit, and the data is discarded rather than quietly
                # fitted.
                run.record_error(
                    f"no reading at {current:.3g} A")
                self._report(f"{params.dataset}: no reading at "
                             f"{current:.3g} A - run will be discarded")
                continue

            currents.append(current)
            voltages.append(voltage)
            offsets.append(offset)

        return currents, voltages, offsets

    def _fit_and_commit(self, run, params, currents, voltages, offsets):
        """Fit, build the record, and put it through the commit gate."""
        label = params.dataset

        if len(currents) < 2:
            run.record_error(
                f"only {len(currents)} point(s) measured; a fit needs 2")
            self._report(f"{label}: not enough points to fit")
            return

        # Triangular runs record only the middle leg - the outer legs
        # exist to bring the sample to the start current and back to
        # zero, not to be measured. In list mode this is the whole set.
        if params.mode == "triangular":
            fit_currents = currents[params.middle_slice]
            fit_voltages = voltages[params.middle_slice]
            if len(fit_currents) < 2:      # the middle leg came up short
                fit_currents, fit_voltages = currents, voltages
        else:
            fit_currents, fit_voltages = currents, voltages

        slope, intercept, r_squared = maths.fit_resistance(
            fit_currents, fit_voltages)

        # Spread of the per-current resistances. On an ohmic sample
        # these agree to well within a percent; a systematic drift with
        # current is the signature of self-heating or non-ohmic
        # contacts, and is invisible in the fitted slope alone.
        point_r = [v / c for c, v in zip(fit_currents, fit_voltages) if c]
        if len(point_r) > 1:
            spread = (max(point_r) - min(point_r)) / abs(
                sum(point_r) / len(point_r))
            if spread > 0.02:
                self._report(
                    f"{label}: resistance varies {spread * 100:.1f}% across "
                    f"the current range ({min(point_r):.4g} to "
                    f"{max(point_r):.4g} \u03a9) - check for self-heating or "
                    f"non-ohmic contacts before trusting the fit")

        worst_offset = max((abs(o) for o in offsets), default=0.0)
        if params.reversals_n > 1 and worst_offset > 0:
            self._report(
                f"{label}: largest cancelled offset "
                f"{worst_offset:.3g} V")

        self._finish_run(run, params, currents, voltages, offsets,
                         fit_currents, fit_voltages,
                         slope, intercept, r_squared)

    def _measure_current(self, run, smu, current, reversals):
        """One current, with polarity reversal averaging.

        Returns (voltage, offset). The offset is the common-mode part
        that cancelled out - reported because a large one usually means
        a warm or poorly seated probe, which is worth knowing before
        trusting the sheet resistance.

        The checkpoint sits before each level change, which is the
        finest granularity available: the settle wait itself happens
        inside the driver's `measure()`, because the delay was handed to
        the instrument with `set_source_delay()`. Cancellation therefore
        cannot preempt a reading in progress - it lands at the next
        polarity flip. That bound is measured in
        `test_4pp_lifecycle.py` rather than assumed.

        A cancelled reversal set raises rather than returning a partial
        average. Averaging three of a requested four reversals would
        weight the result towards whichever polarity ran twice, which is
        the exact error the reversal count exists to remove.
        """
        readings = []
        for level in maths.reversal_pattern(current, reversals):
            run.checkpoint(f"level {level:.3g} A")
            smu.set_current_level(level)
            volts, _amps = smu.measure()
            if volts is not None:
                readings.append(volts)

        if not readings:
            return None, 0.0
        if reversals == 1:
            return readings[0], 0.0
        return maths.average_reversals(readings)

    def _finish_run(self, run, params, currents, voltages, offsets,
                    fit_currents, fit_voltages,
                    slope, intercept, r_squared):
        """Build the run record and put it through the commit gate."""
        label = params.dataset
        timestamp = datetime.datetime.now().isoformat()
        meas_num = self.app.take_meas_number()

        # The single conversion out of SI, named and in one place. The
        # correction tables are published in mm and um; everything above
        # this line is in metres.
        width_mm, length_mm, thickness_um = params.as_math_geometry()

        derived = maths.sheet_resistance(
            slope, width_mm, length_mm, thickness_um)

        readings = []
        for index, (current, voltage, offset) in enumerate(
                zip(currents, voltages, offsets), start=1):
            # Resistance at *this* current, not just the slope across
            # all of them.
            #
            # Salvaged from the working version of the original, which
            # measured each current as its own block of reversals and
            # fitted each block separately - giving one resistance per
            # current instead of one for the run. Mathematically its
            # per-block fit is identical to the reversal averaging here
            # (both recover the signal and reject the offset), but its
            # output shape showed something this one otherwise loses:
            # whether R depends on current. A film that self-heats, or
            # has non-ohmic contacts, gives a resistance that drifts
            # with drive level, and a single fitted slope hides that
            # inside its R².
            #
            # Costs nothing - the numbers are already here - and the
            # spread is reported below.
            readings.append({
                "point": index,
                "timestamp": timestamp,
                "current_A": current,
                "voltage_V": voltage,
                "cancelled_offset_V": offset,
                "resistance_at_point_ohm": (voltage / current
                                            if current else ""),
            })

        # The sample name comes from the snapshot, not from the entry
        # box. Reading `self.sample_name_var` here would be a Tk read
        # from a worker thread (issue B2) *and* would pick up a rename
        # made while the run was in flight.
        record = Run(
            sample=params.sample.slug,
            metadata={
                "meas_number": meas_num,
                # Identity, added in Wave 3. The label is what the
                # operator reads; the id is what a later result points
                # at, and it survives a rename.
                "sample_id": params.sample_id,
                "sample_label": params.sample_label,
                "run_id": run.run_id,
                "dataset": label,
                "sweep_mode": params.mode,
                "points": len(currents),
                "points_fitted": len(fit_currents),
                "reversals": params.reversals_n,
                "delay_s": params.delay_s,
                "voltage_limit_V": params.compliance_v,
                "probe_spacing_mm": maths.PROBE_SPACING_MM,
                "width_mm": width_mm,
                "length_mm": length_mm,
                "thickness_um": thickness_um,
                "fit_slope_ohm": slope,
                "fit_intercept_V": intercept,
                "fit_r_squared": r_squared,
                "resistance_ohm": slope,
                "thickness_factor": derived["thickness_factor"],
                "geometry_factor": derived["geometry_factor"],
                "sheet_resistance_ohm_sq":
                    derived["sheet_resistance_ohm_sq"],
                "resistivity_ohm_m": derived["resistivity_ohm_m"],
                "conductivity_S_per_m": derived["conductivity_S_per_m"],
                "notes": "; ".join(derived["notes"]),
            },
            readings=readings,
        )

        for note in derived["notes"]:
            self._report(f"{label}: {note}")

        # Everything above built a candidate. This is the gate that
        # decides whether it becomes a result.
        #
        # `commit` re-checks cancellation and the completion policy
        # under the controller's lock, so Stop pressed one instruction
        # earlier cannot slip between the check and the handover. The
        # sink only posts to the UI thread - the lock is held while it
        # runs, so it must not do I/O.
        #
        # Readings staged on `run` are provisional until this returns.
        # If it raises - cancelled, short, or with an unconfirmed
        # shutdown - they are discarded and nothing reaches the table.
        run.readings.extend(readings)
        run.commit(record, lambda result: self.app.ui(
            self._record_run, result, params, slope, r_squared,
            derived, fit_currents, fit_voltages, intercept))

    def _record_run(self, record, params, slope, r_squared, derived,
                    fit_currents, fit_voltages, intercept):
        """Insert the row, store the run, refresh the plot. Main thread."""
        label = params.dataset
        item = self.tree.insert(
            "", "end", text="☐",
            values=(label,
                    "triangular" if params.mode == "triangular" else "list",
                    len(record.readings),
                    f"{slope:.6g}",
                    f"{r_squared:.5f}",
                    f"{derived['sheet_resistance_ohm_sq']:.6g}"))
        self.run_store.add(item, record)
        self._run_resistance[item] = slope

        self._datasets[item] = {
            "label": label,
            "x": list(fit_currents),
            "y": list(fit_voltages),
            "fit": (slope, intercept, r_squared),
            "resistance": slope,
        }
        self.refresh_plot()
        self._report(
            f"{label}: R = {slope:.6g} Ω, "
            f"Rs = {derived['sheet_resistance_ohm_sq']:.6g} Ω/□, "
            f"R² = {r_squared:.5f}")

    # ---- calculation ----
    def calculate(self):
        """Recompute the derived quantities from the resistance box.

        Separate from the run so a resistance measured earlier - or one
        typed in by hand from another instrument - can be pushed through
        the same corrections after the geometry is corrected.
        """
        try:
            resistance = si_level(self.calc_r_var.get(), "Measured R",
                                  unit="\u03a9")
        except ValueError as e:
            messagebox.showerror("Invalid input", str(e))
            return

        try:
            width_m, length_m, thickness_m = self._geometry_params()
        except ValueError as e:
            messagebox.showerror("Invalid geometry", str(e))
            return

        # Main thread only, and only here: `current_sample_ref()` reads a
        # Tk variable and mints an identifier for an unseen label. It is
        # deliberately not called from the input traces, which fire on
        # every keystroke and would mint a sample per character typed.
        try:
            sample = self.current_sample_ref()
        except ValueError as e:
            messagebox.showerror("Invalid sample name", str(e))
            return

        # Provenance applies only while the box still holds the number
        # that was copied into it. Edit a digit and the result becomes
        # what it now honestly is - a hand-entered value with no source
        # run - rather than inheriting the lineage of a measurement it
        # no longer represents.
        sources = ()
        if (self._calc_source is not None
                and self._calc_source_value == resistance):
            sources = (self._calc_source,)

        # Structured input, built before any arithmetic (§53). Every
        # number is SI and carries the text it was typed as, so the
        # header can report `180` while the calculation uses the metre
        # value - see the note on the lossy round trip in
        # `core/calculation.py`.
        calc = CalculationInput(
            method="fourpp_sheet_resistance",
            sample_id=sample.sample_id,
            sample_label=sample.label,
            values={
                "resistance_ohm": InputValue(resistance, "\u03a9",
                                             self.calc_r_var.get().strip()),
                "width_m": InputValue(width_m, "m",
                                      self.width_var.get().strip()),
                "length_m": InputValue(length_m, "m",
                                       self.length_var.get().strip()),
                "thickness_m": InputValue(thickness_m, "m",
                                          self.thickness_var.get().strip()),
            },
            sources=sources,
            required=("resistance_ohm", "width_m", "length_m", "thickness_m"),
        )

        # The §16 gate. Refused before a single multiplication, and the
        # message names the specific incompatibility rather than saying
        # "invalid input" - a mixed-sample calculation is arithmetically
        # perfect, so the operator has nothing else to go on.
        try:
            validate(calc)
        except CalculationRefused as e:
            self._clear_calc_outputs()
            self.log("Calculation refused:", e.reason)
            messagebox.showerror("Cannot calculate", str(e))
            return

        # Same boundary as a run takes, so a resistance typed in by hand
        # and one measured by the instrument go through an identical
        # conversion. The correction tables are published in mm and um;
        # everything above this line is in metres.
        width_mm, length_mm = width_m * 1e3, length_m * 1e3
        thickness_um = thickness_m * 1e6

        try:
            derived = maths.sheet_resistance(
                resistance, width_mm, length_mm, thickness_um)
        except ValueError as e:
            self._clear_calc_outputs()
            messagebox.showerror("Cannot calculate", str(e))
            return

        self.result_vars["sheet"].set(
            f"{derived['sheet_resistance_ohm_sq']:.6g}")
        self.result_vars["resistivity"].set(
            f"{derived['resistivity_ohm_m']:.6g}")
        self.result_vars["conductivity"].set(
            f"{derived['conductivity_S_per_m']:.6g}")
        self.result_vars["f_thickness"].set(
            f"{derived['thickness_factor']:.4f}")
        self.result_vars["f_geometry"].set(
            f"{derived['geometry_factor']:.4f}")
        self._calc_notes = tuple(derived["notes"])

        # The certificate, issued by the same operation that computed
        # the number so the two cannot be separated (§17). It carries
        # the method and its version, so a result saved today stays
        # interpretable after the corrections are revised (§28).
        self._calc_result = derive(
            calc,
            outputs={
                "sheet_resistance_ohm_sq": derived["sheet_resistance_ohm_sq"],
                "resistivity_ohm_m": derived["resistivity_ohm_m"],
                "conductivity_S_per_m": derived["conductivity_S_per_m"],
                "thickness_factor": derived["thickness_factor"],
                "geometry_factor": derived["geometry_factor"],
            },
            notes=derived["notes"],
        )

        # Provenance block first, then the numbers in the units the
        # bench works in. The mm/um values stay: this file is read by
        # people holding a caliper, and dropping them to be pure about
        # SI would make the header harder to check against the sample.
        self._calculated = dict(self._calc_result.to_metadata())
        self._calculated.update({
            "Measured R (ohm)": resistance,
            "W (mm)": width_mm,
            "L (mm)": length_mm,
            "t (um)": thickness_um,
            "Probe spacing (mm)": maths.PROBE_SPACING_MM,
            "Thickness factor": derived["thickness_factor"],
            "Geometry factor": derived["geometry_factor"],
            "Sheet resistance (ohm/sq)":
                derived["sheet_resistance_ohm_sq"],
            "Resistivity (ohm.m)": derived["resistivity_ohm_m"],
            "Conductivity (S/m)": derived["conductivity_S_per_m"],
        })

        self._set_calc_stale(False)
        self.log(f"{self._calc_result.method_tag} -> "
                 f"{self._calc_result.result_id}")
        for note in derived["notes"]:
            self.log(note)

    # ---- calculation staleness (§18) ----
    def _calc_signature(self):
        """Fingerprint of the inputs as the widgets currently hold them.

        Raw text, not parsed values: this runs on every keystroke, when
        the box may hold `18` on the way to `180` or nothing at all.
        `core.calculation.signature` normalises anything numeric, so
        `180` and `180.0` are the same input and retyping the same
        number does not falsely mark a result stale.
        """
        return signature({
            "resistance_ohm": self.calc_r_var.get().strip(),
            "width_m": self.width_var.get().strip(),
            "length_m": self.length_var.get().strip(),
            "thickness_m": self.thickness_var.get().strip(),
            "_sample": self.sample_name_var.get().strip(),
        })

    def _on_calc_input_changed(self, *_args):
        """Tk trace: mark the displayed result stale if it no longer
        follows from what is on screen."""
        if self._calc_result is None:
            return
        self._set_calc_stale(self._calc_result.is_stale(self._calc_signature()))

    def _set_calc_stale(self, stale):
        """Grey the readouts and say so, or restore them.

        Greying rather than blanking is deliberate. The previous number
        is still useful - it is what you compare the new one against
        when you change a dimension to see how much it mattered - and
        blanking it would make the panel flicker empty on every
        keystroke. What must not happen is a stale number reaching a
        file, and that is prevented in `calculated_fields()` rather
        than here, because a colour is a hint and a file is a record.
        """
        colour = "#999999" if stale else ""
        for widget in getattr(self, "result_labels", {}).values():
            widget.configure(foreground=colour)
        for widget in getattr(self, "result_unit_labels", {}).values():
            widget.configure(foreground="#bbbbbb" if stale else "gray")
        self._refresh_calc_status(stale)

    def _refresh_calc_status(self, stale):
        """Compose the one status line under the results.

        Priority, worst news first: staleness, then any warning from the
        correction tables, then the provenance of a good result. They
        share a line because a second one broke the landscape layout -
        see the note in `panels/calculation_panel.py`.
        """
        result = self._calc_result
        if result is None:
            self.calc_status_var.set(" ".join(self._calc_notes))
            self.calc_status_label.configure(foreground="#a05000")
            return

        if stale:
            self.calc_status_var.set(
                "Stale - the inputs have changed since this was "
                "calculated. Press Calculate; it will not be saved as it "
                "stands.")
            self.calc_status_label.configure(foreground="#a05000")
            return

        if result.source_run_ids:
            origin = "from " + ", ".join(result.source_run_ids)
        else:
            origin = "resistance typed by hand - no source run"
        provenance = (f"{result.method_tag} \u00b7 "
                      f"{result.sample_label_at_calculation} \u00b7 {origin}")

        if self._calc_notes:
            self.calc_status_var.set(
                " ".join(self._calc_notes) + "\n" + provenance)
            self.calc_status_label.configure(foreground="#a05000")
        else:
            self.calc_status_var.set(provenance)
            self.calc_status_label.configure(foreground="#777777")

    def _clear_calc_outputs(self):
        """Blank the readouts after a refusal.

        A refused calculation must not leave the previous sample's
        numbers sitting under the message - that is §18's failure in its
        most direct form, and unlike an edited input it is not a hint
        situation: the answer is not stale, it is wrong for what the
        panel now describes.
        """
        self._calc_result = None
        self._calculated = {}
        self._calc_notes = ()
        for var in self.result_vars.values():
            var.set("-")
        self._set_calc_stale(False)

    # ---- results table plumbing ----
    def toggle_row(self, event):
        """Tick or untick the row under the pointer."""
        if self.tree.identify_region(event.x, event.y) != "tree":
            return
        item = self.tree.identify_row(event.y)
        if item:
            ticked = self.tree.item(item, "text") == "☑"
            self.tree.item(item, text="☐" if ticked else "☑")
            # Redraw immediately: ticking is how the plot is narrowed,
            # so it has to be visible straight away rather than waiting
            # for a button press.
            self.refresh_plot()

    def ticked_items(self):
        return [i for i in self.tree.get_children()
                if self.tree.item(i, "text") == "☑"]

    def copy_over(self):
        """Copy the ticked row's resistance into the calculation box."""
        items = self.ticked_items()
        if not items:
            messagebox.showinfo("Nothing ticked",
                                "Tick a row to copy its resistance.")
            return
        if len(items) > 1:
            messagebox.showinfo(
                "Tick one row",
                "The calculation takes one resistance at a time.")
            return
        # Full precision, not the table's 6-significant-figure display
        # string. Copying what is on screen loses digits and quietly
        # shifts the derived sheet resistance - the same trap that made
        # test_hall_handoff fail intermittently on high-resistance
        # samples. The table is for reading; this is for computing.
        resistance = self._run_resistance.get(items[0])
        if resistance is None:
            return

        # Wave 4: carry the run's identity across with its number (§17).
        # Without this the calculation knows what it is computing from
        # and not *which measurement* that was, which is the difference
        # between a result and a result you can defend.
        #
        # Every reading of the run is named, not one: the resistance is
        # a fit across all of them and is not attributable to any single
        # point.
        self._calc_source = None
        self._calc_source_value = None
        record = self.run_store.get(items[0])
        if record is not None:
            run_id = record.metadata.get("run_id", "")
            self._calc_source = SourceRow(
                run_id=run_id,
                sample_id=record.metadata.get("sample_id", ""),
                sample_label=record.metadata.get("sample_label", ""),
                row_ids=tuple(reading_id(run_id, i)
                              for i in range(len(record.readings))),
            )
            self._calc_source_value = resistance

        # repr() round-trips a float exactly; .12g does not, and this
        # value is about to be multiplied through the corrections.
        self.calc_r_var.set(repr(resistance))
        self.calculate()

    def delete_ticked(self):
        items = self.ticked_items()
        if not items:
            return
        labels = [self.tree.item(i, "values")[0] for i in items]
        self.run_store.remove(items)
        for item in items:
            self.tree.delete(item)
            self._run_resistance.pop(item, None)
            self._datasets.pop(item, None)
        self.refresh_plot()
        self.log(f"Deleted {len(items)} run(s)")

    def clear_output(self):
        if self.run_store.has_unsaved and not messagebox.askyesno(
                "Unsaved runs",
                "There are unsaved runs. Clear them anyway?"):
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.run_store.clear()
        self._run_resistance = {}
        self._datasets = {}
        self._calculated = {}
        # The runs the result pointed at have just been deleted, so the
        # provenance chain would name rows that no longer exist.
        self._calc_source = None
        self._calc_source_value = None
        self._clear_calc_outputs()
        self.refresh_plot()
        self.log("Cleared")

    # ---- plot ----
    def refresh_plot(self):
        """Redraw the axes from the ticked rows. Main thread only.

        Ticked rows narrow the plot rather than gate it: with nothing
        ticked the most recent run is drawn anyway, because a run that
        finishes and leaves the axes blank looks like a failure. The
        overlap toggle then decides whether several ticked runs share
        the axes or only the newest is shown.
        """
        if not hasattr(self, "plot_ax"):
            return

        datasets = []
        if hasattr(self, "tree"):
            ticked = [i for i in self.ticked_items() if i in self._datasets]
            if not ticked:
                rows = [i for i in self.tree.get_children()
                        if i in self._datasets]
                ticked = rows[-1:]
            datasets = [self._datasets[i] for i in ticked]
            if not self.plot_overlap_var.get() and datasets:
                datasets = datasets[-1:]

        draw_datasets(self, datasets,
                      xlabel="Current [A]", ylabel="Voltage [V]",
                      show_fit=True)

    # ---- misc ----
    def _report(self, text):
        """Log from a background thread."""
        self.app.ui(self.log, text)

    def set_lamp(self, on):
        self.lamp_canvas.itemconfig(self.lamp_id,
                                    fill="#7de368" if on else "gray")

    def calculated_fields(self):
        """Extra block written into the CSV header by save_runs().

        Returns nothing at all when the result is stale. This is the
        §18 acceptance criterion - "no calculated value remains
        displayed as current after its source selection or sample
        context becomes invalid" - enforced where it actually matters.
        The grey text on the panel is advice the operator can ignore;
        this cannot be ignored, because a stale number is structurally
        unable to reach the file. The raw data still saves.
        """
        if self._calc_result is None:
            return {}
        if self._calc_result.is_stale(self._calc_signature()):
            self.log("Calculation is stale - the inputs changed since it "
                     "was computed. Saving raw data only; press Calculate "
                     "and save again to include it.")
            return {}
        return self._calculated

    def calculated_sample_id(self):
        """Which sample the calculation panel's result belongs to."""
        return None if self._calc_result is None else self._calc_result.sample_id
