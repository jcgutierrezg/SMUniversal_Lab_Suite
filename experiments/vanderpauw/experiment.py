"""
Van der Pauw sheet-resistance measurement.

The measurement sequence, its arithmetic, and its saved-file format are
carried over unchanged from the original script. What changed is only
who they talk to: instead of writing SCPI strings inline, this calls
driver methods, so the same sequence runs on any SMU with a driver.

Sequence per run:
    1. Confirm the switch-box position with the user
    2. Configure the SMU (current source, 4-wire, ranges, compliance)
    3. Output ON
    4. Measure a block at +I, then a block at -I
    5. Average the two into one Rave row
    6. Output OFF

One deliberate deviation from the original is flagged at
set_source_delay() below - see the comment there.
"""
import datetime
import math
from tkinter import messagebox

from core.calculation import (
    CalculationInput,
    CalculationRefused,
    InputValue,
    ProvidedValue,
    SourceRow,
    derive,
    require_set,
    signature,
    validate,
)
from core.gui.corner_diagram import paint_corner_roles
from core.gui.widgets import (
    apply_high_z,
    apply_nplc,
    parse_nplc,
    refresh_high_z,
    refresh_nplc,
)
from core.identity import reading_id
from core.limits import format_amps, parse_si
from core.parameters import VanDerPauwParameters
from core.ranges import AUTO, RangePlan
from core.run_store import Run
from core.units import um_to_m
from core.validation import ValidationError, positive_number, whole_number
from experiments.base_experiment import Experiment

from .panels.action_panel import build_action_panel
from .panels.calc_panel import build_calc_panel
from .panels.diagram_panel import build_diagram_panel
from .panels.positions_panel import build_positions_panel
from .panels.results_panel import build_results_panel
from .panels.setup_panel import build_setup_panel
from .vdp_math import resistivity, solve_vdp_sheet_resistance

# Which corner plays which role, per switch-box position. Drives the
# diagram; unchanged from the original.
CORNER_ROLES = {
    1: {1: "I,H", 2: "I,L", 3: "V,L", 4: "V,H"},
    2: {1: "V,H", 2: "V,L", 3: "I,L", 4: "I,H"},
    3: {1: "V,H", 2: "I,H", 3: "I,L", 4: "V,L"},
    4: {1: "I,H", 2: "V,H", 3: "V,L", 4: "I,L"},
}


class VanDerPauwExperiment(Experiment):
    NAME = "Van der Pauw - sheet resistance"
    TAB_NAME = "Van der Pauw"

    ROLES = {"source": "SMU"}

    CSV_SLUG = "vanderpauw"
    CSV_TITLE = "Van der Pauw - sheet resistance"

    # The stage and the sample identity belong to the window,
    # not to this measurement. `build_temp_panel` has left PANELS for
    # that reason, and the sample-name and thickness boxes have left the
    # setup panel - a Van der Pauw run and the Hall run that follows it
    # are the same film, so they read the same two variables.
    USES_TEMP_STAGE = True
    SESSION_FIELDS = ("sample", "thickness")

    # What the Hall tab can ask this one for. See
    # `Experiment.PROVIDES` for why this is a string and not a class.
    PROVIDES = ("sheet_resistance",)

    # The headline numbers this experiment puts in a sample
    # summary. Keys match `calculated_fields()`.
    SUMMARY_QUANTITIES = (
        ("Rs_ohm_per_sq", "Sheet resistance", "\u03a9/\u25a1"),
        ("rho_ohm_cm", "Resistivity", "\u03a9\u00b7cm"),
    )

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
        # accepted. Nothing reads it any more: the run and the
        # calculation both take the thickness from the entry box via a
        # validator, so there is one source of truth and no way for a
        # forgotten "Set" press to leave a run using last week's value.
        self.thickness_um = 1.0
        # `measuring` and `polling` are gone. They were flags shared
        # by every consecutive run, which is the failure per-run
        # cancellation tokens exist for: a worker that outlives its
        # run and
        # wakes during the next one reads the new run's cleared flag as
        # permission to carry on. State lives on the run itself now -
        # `self.run_in_progress()` for the UI, a per-run cancellation
        # token for the worker.
        self._calculated = {}

        # ---- the calculation layer ----
        self._calc_result = None
        # Pos label -> the run that supplied that box's number, when it
        # was copied rather than typed. Held alongside the value it
        # belongs to, so a typed-over box honestly loses its lineage
        # instead of keeping a source run it no longer represents.
        self._calc_sources = {}
        self._calc_source_values = {}
        self._calc_notes = ()

    def on_panels_built(self):
        """Paint the corner diagram, and watch the calculation inputs.

        The traces are read-only observers: they compare signatures and
        grey a label. Nothing here writes a Tk variable, so no trace can
        fire another trace and there is no ordering to get wrong.
        """
        self.on_pos_changed()
        for var in (*self.pos_vars, self.thickness_entry_var,
                    self.sample_name_var):
            var.trace_add("write", self._on_calc_input_changed)

    # ---- driver-aware setup ----
    def on_connected(self, role, driver):
        """Repopulate the range dropdowns from the instrument that just
        connected, so the user can only pick values it can reach.

        This is the payoff of drivers declaring their limits: connect a
        2450 and the current list runs to 1 A; connect something smaller
        and the impossible entries simply aren't offered.
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
        if self.level_var.get() not in levels:
            # keep the original 100 µA default when the instrument has it
            self.level_var.set("100 µA" if "100 µA" in levels else levels[0])

        v_labels = ["AUTO"] + [self._volt_label(v) for v in sorted(limits.voltage_ranges)]
        self.volt_range_combo["values"] = v_labels
        if self.volt_range_var.get() not in v_labels:
            self.volt_range_var.set("AUTO")

        self.log(f"Ranges loaded from {driver.DISPLAY_NAME}")

    @staticmethod
    def _volt_label(volts):
        """Label a voltage range for the dropdown."""
        return f"{volts*1000:g} mV" if volts < 1 else f"{volts:g} V"

    # ---- unit parsing (unchanged behaviour, now instrument-agnostic) ----
    def get_level_amps(self):
        """Current level from the dropdown, in amps."""
        return _parse_si(self.level_var.get())

    def get_voltage_range(self):
        """Voltage range from the dropdown, in volts, or None for AUTO."""
        text = self.volt_range_var.get()
        return None if text.upper() == "AUTO" else _parse_si(text)

    def get_vlim_volts(self):
        """Voltage compliance from its entry box, in volts. AUTO keeps
        the original's 0.3 V fallback."""
        text = (self.vlim_var.get() or "").strip()
        if text.upper() == "AUTO":
            return 0.3
        return _parse_si(text)

    def parse_delay(self):
        """Settle delay in seconds, from the ms entry box.

        The box is milliseconds and the driver wants seconds; the
        original mixed the two.                          # DEVIATION 1
        """
        text = (self.delay_ms_var.get() or "").strip()
        try:
            ms = float(text)
            if ms <= 0:
                raise ValueError
        except ValueError:
            ms = 50.0
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

    # ---- diagram ----
    def on_pos_changed(self):
        """Recolour the corner diagram for the selected position."""
        paint_corner_roles(self, CORNER_ROLES.get(int(self.pos_var.get()), {}))
        self.log(f"Selected Pos{self.pos_var.get()}")

    # ---- the run ----
    def _run_params(self):
        """Snapshot the form at the Run press. Main thread only.

        Every Tk variable this run depends on is read here, once, and
        frozen. After this returns, the operator can retype the delay or
        click the position spinner and the run in flight is unaffected -
        it is the run it said it was when it started.

        Validators rather than bare `float()`: `whole_number` refuses
        `2.5` points instead of truncating it to 2, which is the silent
        decimal truncation these validators exist for.
        """
        return VanDerPauwParameters(
            sample=self.current_sample_ref(),
            dataset=f"Pos{int(self.pos_var.get())}",
            position=whole_number(self.pos_var.get(), "Position",
                                  minimum=1, maximum=4),
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
        """Run button: confirm the switch-box position, then measure."""
        if not self._ready_to_run():
            return

        try:
            params = self._run_params()
        except ValidationError as e:
            messagebox.showerror("Invalid setup", str(e))
            return
        except ValueError as e:
            messagebox.showerror("Invalid setup", str(e))
            return

        # After validation, before anything is claimed: no point asking
        # the operator to go and set the switch box if the form is going
        # to be refused anyway.
        if not messagebox.askokcancel(
                "Confirm position",
                f"Set the switch box to position {params.position}.\n\n"
                f"Click OK to start."):
            self.log("User cancelled run")
            return

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
        An instrument that has not been handed back is not free,
        whatever the thread is doing.
        """
        if self.run_in_progress():
            return False
        # The other tab may hold the SMU. Asked here rather
        # than at the claim, so the refusal lands before the operator is
        # sent to the switch box.
        if self.refuse_if_sibling_busy():
            return False
        if not self.app.is_connected("source"):
            messagebox.showwarning("Not connected", "Connect the SMU first.")
            return False
        if not self._summary_collision_ok():
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
        on. The output-off is done by the worker in its own
        cleanup, on the thread that already owns the session - which is
        what removes the old OFF-button race described in
        `panels/action_panel.py`.

        The cost is latency: the worker notices at its next checkpoint,
        which on this experiment means after the reading in progress
        returns. `test_vdp_lifecycle.py` measures that bound rather than
        asserting it.
        """
        if self.cancel_run("operator pressed Stop"):
            self.progress_var.set("Stopping - discarding this run...")
            self.log("Stop pressed: cancelling, output off, data discarded")

    def _do_run(self, params):
        """Measure both polarities at one position. Background thread.

        The lifecycle
        -------------
        The whole sequence sits inside `begin_run()`. That block owns
        the ending: whether this returns normally, raises, or is
        cancelled, the same four things happen in the same order -
        record a terminal status, discard anything not committed,
        release the instrument, return to idle.

        `run.checkpoint()` sits before every operation that could
        energise or alter the output, which is the list in
        `docs/architecture/run-lifecycle.md`:
        before output-on, before a source-function change, before each
        polarity flip, after every long wait, and immediately before the
        commit. A cancelled run raises `RunCancelled` from whichever
        checkpoint sees it first; that is a control-flow signal, not an
        error, and the context manager swallows it so pressing Stop does
        not put a traceback in the console.

        Readings are **provisional** - they live on the run context and
        nowhere else until `run.commit()` succeeds, so a cancelled run
        cannot leave one polarity's block in the results table to be
        averaged against nothing.
        """
        with self.begin_run(parameters=params) as run:
            # Registered before the claim so it unwinds after it: an
            # ExitStack unwinds in reverse, and the UI must not say
            # "idle" until the instrument has actually been handed back.
            run.on_cleanup(lambda: self.app.ui(self._end_run))

            run.enter(self.app.claim_instrument("source", run.run_id))
            smu = self.instrument("source")
            self.app.ui(self._enter_run_ui)

            # Both polarities' worth. Declared up front so the
            # completion gate compares against what was asked for
            # rather than against whatever arrived.
            run.expect(params.readings_n)

            try:
                self._configure(run, smu, params)
                r_pos = self._polarity_block(run, smu, params, +1)
                r_neg = self._polarity_block(run, smu, params, -1)
            finally:
                # Always bring the source down, whatever went wrong,
                # including a cancellation. The only place the output is
                # turned off, on the thread that owns the session.
                report = run.confirm_shutdown(smu, log=self.log)
                self.app.ui(self.set_lamp, False)
                if report.uncertain:
                    self.app.report_uncertain_shutdown("source", report)

            self._finish_run(run, params, r_pos, r_neg)

    def _configure(self, run, smu, params):
        """Put the instrument into the state this run needs.

        Applied every run rather than once at connect, for the same
        reason as remote sense: otherwise the instrument keeps whatever
        the last experiment left it in, and the same sample reads
        differently depending on history.
        """
        run.checkpoint("configure")
        smu.set_source_function("current")
        # Sized to the largest magnitude this run will source, and set
        # once, before the output goes on. Matches Ossila 4PP and IV
        # sweep, so all four experiments now range the same way.
        #
        # This used to be `None` (autorange), re-sent at the top of each
        # polarity block - i.e. while the sample was live. Two problems
        # with that. It broke house rule 12, and a range change part way
        # through a run leaves a step in the data where the two segments
        # were sourced with different gain and offset errors; a straight
        # line fitted across that step absorbs it as slope, and slope is
        # resistance. No error, excellent R-squared, wrong answer.
        #
        # A fixed range also stops the instrument spending resolution
        # where it is not wanted: passing through zero does not mean
        # microamp resolution is useful on a run sourcing milliamps.
        #
        # Every driver in the suite rounds *up* - the U2722A and miniSMU
        # pick the smallest range that still fits, and the SCPI and TSP
        # range commands select a range that accommodates the value - so
        # sizing to the level itself cannot clamp it.
        #
        # Side effect worth noting: `set_current_range(None)` raises
        # NotImplementedError on the U2722A, which has no autorange. An
        # explicit level works there.
        # Ranging, all four axes, stated once before the output goes on
        # Van der Pauw sources current and measures
        # voltage, so:
        #
        #   source current   the level being driven, +/- level_a
        #   source voltage   AUTO - nothing sources voltage here
        #   measure current  the same current, read back per point
        #   measure voltage  the operator's chosen voltage range
        #
        # The source-current axis is new. Until now this experiment set
        # only `set_current_range()`, which sent a *measure* command on
        # five of the nine drivers and a *source* command on two - so
        # the source range was left autoranging on most instruments. It
        # gave the right answer anyway only because the sourced and
        # measured currents are the same number here. That coincidence
        # is what the ranging contract removes.
        # The form uses None for "let it autorange"; the plan spells
        # that AUTO. Converted here, at the boundary, which is where
        # RangePlan insists such conversions happen - a plan accepting
        # None would be treating the shape of an unset variable as a
        # deliberate choice.
        #
        # Note what is NOT here: a measurement range for current. This
        # experiment sources current, and the measured current is read
        # back from the source, so it has no separate measure range -
        # `for_sourcing` is what keeps that axis out of reach.
        ranges = RangePlan.for_sourcing(
            "current",
            source_range=abs(params.level_a),
            measure_range=(AUTO if params.voltage_range_v is None
                           else params.voltage_range_v))
        run.set_metadata(ranges=smu.apply_ranges(ranges, log=self.log))
        smu.set_remote_sense(True)
        smu.set_voltage_limit(params.compliance_v)
        smu.set_source_delay(params.delay_s)

        applied_nplc = apply_nplc(smu, params.nplc, self.log)
        applied_high_z = apply_high_z(smu, params.high_z, self.log)
        # Recorded on the run rather than on `self`: what the instrument
        # actually accepted can differ from what was asked for, and it
        # belongs to this run, not to the experiment.
        run.set_metadata(
            nplc=applied_nplc if applied_nplc is not None else "",
            output_off_mode=("high-Z" if applied_high_z
                             else ("normal" if applied_high_z is not None
                                   else "")))

        # The last gate before the output goes live. The race it
        # prevents is Stop pressed during configuration, followed by
        # the worker energising anyway.
        run.checkpoint("before output on")
        smu.output_on()
        self.log("Output ON")
        self.app.ui(self.set_lamp, True)
        # PREPARING -> RUNNING. Setup succeeded and the sample is live;
        # from here a cancellation has something to discard.
        run.start()

    def _polarity_block(self, run, smu, params, polarity):
        """Source `level * polarity`, settle, take the readings, and
        return their averaged resistance.

        Arithmetic unchanged from the original: R for each reading is
        V/I from that reading, and the block result is the plain mean of
        the valid R values.

        The readings go onto the run context rather than onto
        `self._block_readings`. That attribute was a second place the
        same data lived, and a cancelled run left it holding the last
        block it managed - which the next run would then pick up if it
        failed before reassigning. Provisional storage on the run has no
        such carry-over: a discarded run's readings are discarded with it.
        """
        signed = params.level_a * polarity
        label = "pos" if polarity > 0 else "neg"

        run.checkpoint(f"{label} polarity")
        # Source delay and current range are set once in `_configure`,
        # before the output goes on. They were re-sent here on every
        # polarity with identical arguments, which configured the
        # instrument while the sample was live for no gain.
        smu.set_current_level(signed)

        # Host-side settle as well as instrument-side - the original did
        # both, and the host wait is what actually dominated.
        # `run.sleep()` rather than `time.sleep()`: it wakes early when
        # cancelled, so Stop during a long settle is felt immediately
        # instead of after the full delay.
        if params.delay_s > 0:
            self.log(f"Settling {params.delay_s:.3f} s at {label} polarity")
            run.sleep(params.delay_s, stage=f"settle {label}")

        r_values = []
        for i in range(params.points_n):
            run.checkpoint(f"{label} point {i + 1}")
            if not self.app.is_connected("source"):
                break
            try:
                v, current = smu.measure()
            except Exception as e:
                self.log(f"Point {i+1}/{params.points_n} [{label}] error: {e}")
                run.add_reading({"point": i + 1, "polarity": label,
                                 "timestamp": datetime.datetime.now().isoformat(),
                                 "voltage_V": "", "current_A": "",
                                 "resistance_ohm": "", "error": str(e)})
                run.record_error(str(e))
                continue
            ts = datetime.datetime.now().isoformat()
            self.log(f"Point {i+1}/{params.points_n} [{label}] V={v} I={current}")
            resistance = v / current if (v is not None and current) else ""
            run.add_reading({"point": i + 1, "polarity": label, "timestamp": ts,
                             "voltage_V": v, "current_A": current,
                             "resistance_ohm": resistance, "error": ""})
            if resistance != "":
                r_values.append(resistance)
            self.app.ui(self.progress_var.set,
                        f"{label} polarity: {i + 1}/{params.points_n}")
            run.sleep(0.04, stage=f"{label} pacing")

        return math.fsum(r_values) / len(r_values) if r_values else None

    def _finish_run(self, run, params, r_pos, r_neg):
        """Average the two polarities and commit. Background thread.

        Van der Pauw averages the polarities, unlike Hall, which must
        keep them separate - the whole point there is the difference
        between them. Same instrument, same sequence, opposite treatment,
        which is why the two experiments do not share this step.
        """
        rave = None
        if r_pos is not None and r_neg is not None:
            rave = (r_pos + r_neg) / 2.0

        run.checkpoint("commit")
        run.set_metadata(
            position=params.position,
            level_A=params.level_a,
            points_requested=params.points_n,
            delay_s=params.delay_s,
            thickness_um=params.thickness_m * 1e6,
            R_pos_ohm=r_pos if r_pos is not None else "",
            R_neg_ohm=r_neg if r_neg is not None else "",
            R_ave_ohm=rave if rave is not None else "",
            stage_temp_C=self._stage_temperature() or "",
        )

        row = (
            params.sample_label,
            params.position_label,
            f"{r_pos:.6g}" if r_pos is not None else "-",
            f"{r_neg:.6g}" if r_neg is not None else "-",
            f"{rave:.6g}" if rave is not None else "",
        )

        metadata = dict(params.to_metadata())
        metadata.update(run.metadata)
        metadata["run_id"] = run.run_id
        metadata["meas_number"] = self.app.take_meas_number()

        record = Run(sample=params.sample.slug, metadata=metadata,
                     readings=list(run.readings))
        run.commit(record, lambda committed: self.app.ui(
            self._record_run, row, committed))

    def calculated_fields(self):
        """Sheet resistance and friends, for the saved CSV header.

        Returns nothing at all when the result is stale, which is
        where the staleness rule is enforced. The grey text
        on the panel is advice the operator can ignore; this cannot be,
        because a stale number becomes structurally unable to reach the
        file. The raw data still saves.
        """
        if self._calc_result is None:
            return dict(self._calculated)
        if self._calc_result.is_stale(self._calc_signature()):
            self.log("Calculation is stale - the inputs changed since it "
                     "was computed. Saving raw data only; press Calculate "
                     "and save again to include it.")
            for line in self._calc_result.stale_because(self._calc_signature()):
                self.log("  ", line)
            return {}
        return dict(self._calculated)

    def calculated_sample_id(self):
        """Which sample the calculation belongs to."""
        return None if self._calc_result is None else self._calc_result.sample_id

    # ---- what this experiment hands to the Hall tab ----
    RS_OUTPUT = "Rs_ohm_per_sq"

    def provide(self, name):
        """The sheet resistance, as the result it came out of.

        Three refusals, in the order they are likely:

        1. nothing calculated yet - the panel has boxes filled and no
           result behind them, which is the state the operator is in
           when they press the Hall button too early;
        2. the result is stale - the inputs moved after it was
           computed. This one matters most. A stale result already
           cannot reach *this* experiment's CSV; without this check it
           could still walk into Hall's arithmetic through the side
           door and come back out as a carrier density;
        3. the result has no sheet resistance in it, which would be a
           programming fault rather than an operator one and says so.

        Refusing rather than warning, and refusing here rather than at
        the far end, because the experiment that owns the number is the
        only one that knows whether it is still true.
        """
        if name != "sheet_resistance":
            raise NotImplementedError(
                f"{type(self).__name__} does not provide {name!r}")

        result = self._calc_result
        if result is None:
            raise CalculationRefused(
                "Van der Pauw has no sheet resistance yet.",
                "Copy the four positions into the calculation boxes and "
                "press Calculate on the Van der Pauw tab first.")

        current = self._calc_signature()
        if result.is_stale(current):
            raise CalculationRefused(
                "The Van der Pauw sheet resistance is out of date.",
                "Its inputs have changed since it was calculated:\n\n- "
                + "\n- ".join(result.stale_because(current))
                + "\n\nPress Calculate on the Van der Pauw tab, then try "
                  "again.")

        value = result.outputs.get(self.RS_OUTPUT)
        if value is None or not isinstance(value, (int, float)) \
                or not math.isfinite(float(value)):
            raise CalculationRefused(
                "The Van der Pauw result has no usable sheet resistance.",
                f"Expected an output named {self.RS_OUTPUT!r}; this is a "
                f"fault in the software rather than in the measurement.")

        return ProvidedValue(
            name="sheet_resistance",
            value=float(value),
            unit="\u03a9/\u25a1",
            result=result,
            stage_temps_c=self._stage_temps_for(result),
        )

    def _stage_temps_for(self, result):
        """Stage temperature recorded by each run behind `result`.

        Handed over with the value rather than fetched by the caller:
        Hall has no business reaching into this experiment's run store,
        and a run that has since been deleted from the table simply
        contributes nothing instead of raising.
        """
        wanted = set(result.source_run_ids)
        temps = []
        for run in self.run_store.all_runs():
            if run.metadata.get("run_id") not in wanted:
                continue
            try:
                temps.append(float(run.metadata.get("stage_temp_C")))
            except (TypeError, ValueError):
                continue          # no stage connected for that run
        return tuple(temps)

    def _record_run(self, row, run):
        """Add a finished run to the table and the store together.

        Both keyed on the Treeview item id, so a row and its raw data
        can't drift apart - deleting one deletes the other.
        """
        item = self.tree.insert("", "end", text="☐", values=row)
        self.run_store.add(item, run)

    def _stage_temperature(self):
        """Current stage temperature, or None when there's no usable
        reading. Recorded per run because sheet resistance depends on
        it."""
        if not self.temp_ctrl.is_connected():
            return None
        status = self.temp_ctrl.status()
        if status.is_stale or status.fault or status.temp_c is None:
            return None
        return round(status.temp_c, 1)

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
        """Copy the four ticked rows' R(ave) into the Pos1-4 boxes.

        Requires exactly one row per position - and now says so through
        `require_set()`, the complete-set check the whole suite shares
        rather than a rule re-written here. Each box also remembers
        which run supplied its number, so the calculation that follows
        can name its four source measurements.
        """
        ticked = [i for i in self.tree.get_children()
                  if (self.tree.item(i, "text") or "") == "☑"]
        if len(ticked) != 4:
            messagebox.showerror("Copy error",
                                 "Tick exactly 4 rows - one per position.")
            return

        sources = []
        by_pos = {}
        for item in ticked:
            values = self.tree.item(item, "values")
            label = str(values[1]).strip()
            by_pos[label] = str(values[4]).strip()
            record = self.run_store.get(item)
            if record is None:
                continue
            run_id = record.metadata.get("run_id", "")
            sources.append(SourceRow(
                run_id=run_id,
                sample_id=record.metadata.get("sample_id", ""),
                sample_label=record.metadata.get("sample_label", ""),
                row_ids=tuple(reading_id(run_id, i)
                              for i in range(len(record.readings))),
                position=label,
            ))

        try:
            require_set(sources, {"Pos1", "Pos2", "Pos3", "Pos4"})
        except CalculationRefused as e:
            self.log("Copy refused:", e.reason)
            messagebox.showerror("Copy error", str(e))
            return

        try:
            values = [float(by_pos[f"Pos{n}"]) for n in (1, 2, 3, 4)]
        except (KeyError, ValueError):
            messagebox.showerror("Copy error",
                                 "R(ave) must be numeric for all 4 rows.")
            return

        self._calc_sources = {s.position: s for s in sources}
        self._calc_source_values = {}
        for n, (var, value) in enumerate(zip(self.pos_vars, values), start=1):
            # Full precision, not the table's six figures. The displayed
            # string is for reading; this number goes into a solver.
            var.set(repr(value))
            self._calc_source_values[f"Pos{n}"] = value

        self.log("Copied R(ave) into calculation boxes")
        self.calculate_vdp()

    # ---- the calculation ----
    def _calc_signature(self):
        """Fingerprint of the calculation inputs as the boxes hold them.

        Raw text, because this runs from a Tk trace on every keystroke,
        when a box may hold `45` on the way to `4532`.
        """
        items = {f"Pos{n}": var.get().strip()
                 for n, var in enumerate(self.pos_vars, start=1)}
        items["thickness_m"] = self.thickness_entry_var.get().strip()
        items["_sample"] = self.sample_name_var.get().strip()
        return signature(items)

    def _on_calc_input_changed(self, *_args):
        """Tk trace: mark the result stale if it no longer follows from
        what is on screen."""
        if self._calc_result is None:
            return
        self._set_calc_stale(self._calc_result.is_stale(self._calc_signature()))

    def _set_calc_stale(self, stale):
        """Grey the readouts and say so, or restore them.

        Greying rather than blanking: the previous Rs is what you
        compare the new one against when you change a thickness to see
        how much it mattered. What must not happen is a stale number
        reaching a file, and `calculated_fields()` prevents that -
        a colour is a hint, a file is a record.
        """
        colour = "#999999" if stale else ""
        for widget in getattr(self, "calc_result_labels", {}).values():
            widget.configure(foreground=colour)
        self._refresh_calc_status(stale)

    def _refresh_calc_status(self, stale):
        """Compose the one status line under the calculation."""
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

        traced = len(result.source_run_ids)
        if traced == 4:
            origin = "from 4 measured runs"
        elif traced:
            origin = f"{traced} of 4 from measured runs, {4 - traced} typed"
        else:
            origin = "values typed by hand - no source runs"
        self.calc_status_var.set(
            f"{result.method_tag} \u00b7 "
            f"{result.sample_label_at_calculation} \u00b7 {origin}")
        self.calc_status_label.configure(foreground="#777777")

    def _clear_calc_outputs(self):
        """Blank the readouts after a refusal.

        A refused calculation must not leave the previous sample's
        numbers under the message. Unlike an edited input this is not a
        hint situation - the answer is not stale, it is wrong for what
        the panel now describes.
        """
        self._calc_result = None
        self._calculated = {}
        self._calc_notes = ()
        for var in (self.rh_var, self.rv_var, self.rs_var, self.rho_var):
            var.set("-")
        self._set_calc_stale(False)

    def calculate_vdp(self):
        """Rh/Rv from the four positions, solve for Rs, convert to rho.

        Arithmetic unchanged: Rh is the mean of Pos1 and Pos2, Rv the
        mean of Pos3 and Pos4, and rho = Rs * thickness in cm. What is
        new is everything around it - the inputs are checked as a set
        before the solver runs, and the result comes back as a
        `DerivedResult` naming the four runs it came from.
        """
        try:
            values = [positive_number(var.get(), f"Pos{n}")
                      for n, var in enumerate(self.pos_vars, start=1)]
        except ValidationError as e:
            messagebox.showerror("Invalid inputs", str(e))
            return

        try:
            thickness_m = um_to_m(positive_number(
                self.thickness_entry_var.get(), "Thickness"))
            sample = self.current_sample_ref()
        except (ValidationError, ValueError) as e:
            messagebox.showerror("Invalid setup", str(e))
            return

        # A box keeps its provenance only while it still holds the
        # number that was copied into it.
        sources = tuple(
            source for label, source in sorted(self._calc_sources.items())
            if self._calc_source_values.get(label)
            == values[int(label[-1]) - 1])

        calc = CalculationInput(
            method="vdp_sheet_resistance",
            sample_id=sample.sample_id,
            sample_label=sample.label,
            values={
                f"Pos{n}": InputValue(value, "\u03a9",
                                      self.pos_vars[n - 1].get().strip())
                for n, value in enumerate(values, start=1)
            } | {
                "thickness_m": InputValue(
                    thickness_m, "m",
                    self.thickness_entry_var.get().strip()),
            },
            sources=sources,
            required=("Pos1", "Pos2", "Pos3", "Pos4", "thickness_m"),
        )

        # `require_set` is *not* called here, deliberately. It runs at
        # copy time, where the question is "are these four ticked rows
        # one per position". Here the question is different: are there
        # four usable numbers. An operator may legitimately type one in
        # - a position remeasured on another day, a value from a
        # colleague's notebook - and refusing that would be enforcing
        # provenance rather than correctness. The typed box simply
        # arrives with no source run, and the status line says so.
        #
        # `distinct_runs` still applies: one run may not back two
        # positions, because that is not a choice anyone makes on
        # purpose.
        try:
            validate(calc, distinct_runs=True)
        except CalculationRefused as e:
            self._clear_calc_outputs()
            self.log("Calculation refused:", e.reason)
            messagebox.showerror("Cannot calculate", str(e))
            return

        rh = 0.5 * (values[0] + values[1])
        rv = 0.5 * (values[2] + values[3])
        self.rh_var.set(f"{rh:.6g}")
        self.rv_var.set(f"{rv:.6g}")
        self.log(f"Rh={rh:.6g} \u03a9, Rv={rv:.6g} \u03a9")

        try:
            rs = solve_vdp_sheet_resistance(rh, rv)
        except Exception as e:
            self._clear_calc_outputs()
            self.rs_var.set("ERR")
            self.log("Solver error:", e)
            messagebox.showerror("Solver error", str(e))
            return

        # The single conversion out of SI, named and in one place.
        thickness_cm = thickness_m * 1e2
        rho = resistivity(rs, thickness_cm)

        self.rs_var.set(f"{rs:.6g}")
        self.rho_var.set(f"{rho:.6g}")
        self._calc_notes = ()

        self._calc_result = derive(
            calc,
            outputs={
                "Rh_ohm": rh,
                "Rv_ohm": rv,
                "Rs_ohm_per_sq": rs,
                "rho_ohm_cm": rho,
            },
        )

        # `Rs_ohm_per_sq` is now load-bearing in two places at once, and
        # they are not the same place. `RS_OUTPUT` names the key that
        # `provide()` reads out of the *result* to hand to the Hall tab;
        # the copy below goes into the saved CSV header, where
        # `test_saving.py` asserts it. Nothing parses the header back -
        # The round trip is gone - so the two can be spelled
        # differently, but there is no reason to and one fewer name to
        # get wrong this way.
        self._calculated = dict(self._calc_result.to_metadata())
        self._calculated.update({
            "Rh_ohm": f"{rh:.9g}",
            "Rv_ohm": f"{rv:.9g}",
            "Rs_ohm_per_sq": f"{rs:.9g}",
            "rho_ohm_cm": f"{rho:.9g}",
            "thickness_um": f"{thickness_m * 1e6:.6g}",
        })

        self._set_calc_stale(False)
        self.log(f"Rs={rs:.6g} \u03a9/\u25a1, \u03c1={rho:.6g} \u03a9\u00b7cm")
        self.log(f"{self._calc_result.method_tag} -> "
                 f"{self._calc_result.result_id}")

    # `on_close()` is inherited. It cancelled the run in flight and
    # nothing else, which is now what `Experiment.on_close()` does for
    # every experiment - see the note there about the tab that had no
    # override at all.


def _parse_si(text):
    """Kept as a module-level name because the unit tests import it.
    The implementation now lives in core/limits.py, shared with Hall."""
    return parse_si(text)
