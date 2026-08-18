"""
Fixed sourcing vs time - hold one level, watch the other quantity.

New experiment; no original script. Everything here is a decision rather
than a port, and the ones that change what the measurement means are
recorded in `docs/experiments/fixed-source-vs-time.md` rather than only
in this file.

Sequence:
    1. Configure source function, level, compliance, ranges, sensing
    2. Output ON - and t = 0 is this instant
    3. Sample on a monotonic schedule until the duration elapses
    4. Output OFF
    5. Commit

What makes this different from a sweep
--------------------------------------
The independent variable is the clock, and the clock is not ours. A
sweep asks for N points and gets N points, because the instrument is
told each level explicitly. Here the operator asks for a *duration*, and
how many samples fit inside it depends on the instrument, the
integration time and the bus.

Three consequences run through everything below:

* **The time column is measured, never reconstructed.** `i * interval`
  would be fault 9 in a new place: it hides every reason the loop fell
  behind, in the one column you would look at to find out.
* **The schedule is a monotonic deadline, not a sleep.** Sleeping the
  interval accumulates each reading's cost as drift, so a nominal
  1 Hz run silently becomes 0.8 Hz. Fault 5, in a new place.
* **There is no `run.expect()`.** An exact expected count would fail
  every honest run on a slow instrument. The guard is a floor instead;
  see `_commit`.

Timing is host-stepped on every instrument in the suite. No driver here
exposes a hardware sample timer, so the interval is only as good as the
host and the bus - the same distinction `sweep_kind` records for sweeps,
and every run records `timebase` for the same reason.
"""
import threading
import time

from tkinter import messagebox

from core.gui.plot_panel import build_plot_panel
from core.gui.widgets import (apply_high_z, apply_nplc, apply_remote_sense,
                              parse_nplc, refresh_high_z, refresh_nplc,
                              refresh_remote_sense)
from core.identity import reading_id
from core.parameters import FixedSourceParameters
from core.ranges import RangePlan
from core.run_store import Run
from core.validation import (ValidationError, one_of, positive_number,
                             si_level)
from experiments.base_experiment import Experiment

from .panels.action_panel import build_action_panel
from .panels.results_panel import build_results_panel
from .panels.source_panel import (build_source_panel,
                                  FALLBACK_CURRENT_COMPLIANCE,
                                  FALLBACK_VOLTAGE_COMPLIANCE)
from .panels.timing_panel import build_timing_panel, LONG_RUN_WARNING_S
from .panels.trace_panel import build_trace_panel

#: Longest single wait inside the sampling loop. The loop waits in
#: slices rather than one call so that "Finish and save" is noticed
#: promptly on a run sampling every ten seconds. Cancellation does not
#: need this - `RunContext.sleep` wakes on the cancel event - but the
#: finish flag is a plain event the worker polls, and a flag polled once
#: per interval would make the button feel broken.
WAIT_SLICE_S = 0.05

#: How far past its deadline a sample may land before it counts as an
#: overrun. Half an interval: less than that is ordinary host jitter,
#: more than that means the requested rate is not being achieved.
OVERRUN_FRACTION = 0.5

#: Minimum gap between live plot redraws. A full redraw per sample is
#: imperceptible at 1 Hz and unusable at 100 Hz, and the plot is a
#: convenience - it must never be what limits the sample rate.
PLOT_THROTTLE_S = 0.25


class FixedSourceExperiment(Experiment):
    NAME = "Fixed sourcing vs time - hold a level and watch"
    TAB_NAME = "Fixed source"

    ROLES = {"source": "SMU"}

    CSV_SLUG = "fixed_source"
    CSV_TITLE = "Fixed sourcing vs time"

    # The stage is app-level: one window, one serial port, one
    # controller. Declared here so the window builds the panel, and used
    # per *sample* rather than per run - see `_stage_temperature`.
    USES_TEMP_STAGE = True

    SESSION_FIELDS = ("sample",)

    PANELS = [
        build_source_panel,      # col_left  - what the SMU sources
        build_timing_panel,      # col_mid   - how long, how often
        build_action_panel,      # col_mid   - Run / Finish / Stop
        build_results_panel,     # col_right - what came out
        build_plot_panel,        # col_right - what came out, drawn
        build_trace_panel,       # col_right - what the plot shows
    ]

    def __init__(self, app):
        super().__init__(app)
        # Treeview item id -> plot trace, keyed the same way the run
        # store is, so deleting a row drops its trace from the plot too.
        self._traces = {}
        # The live trace being built by the run in flight, or None.
        self._live = None
        # Set by "Finish and save". Replaced with a fresh event at the
        # start of every run, so a press that lands between runs cannot
        # end the next one before it starts.
        self._finish_now = threading.Event()
        # Second y-axis for the sourced quantity. Built lazily on first
        # use and reused, because `twinx()` on every redraw stacks a new
        # axis on the figure until the labels are unreadable.
        self._twin_ax = None

    # ---- setup once the widgets exist ----
    def on_panels_built(self):
        self.plot_title_var.set("Fixed sourcing vs time")
        self.on_mode_changed()
        self.on_timing_changed()

    # ---- driver-aware setup ----
    def on_connected(self, role, driver):
        """Repopulate the per-instrument controls from what connected."""
        self._refresh_compliance_values(driver)
        refresh_nplc(self.nplc_combo, self.nplc_var, driver, self.log)
        refresh_high_z(self.high_z_check, self.high_z_var, driver, self.log)
        refresh_remote_sense(self.remote_sense_check, self.remote_sense_var,
                             driver, self.log)

        if driver.supports_ovp():
            self.ovp_combo.config(values=list(driver.OVP_CHOICES),
                                  state="readonly")
            self.ovp_var.set(driver.OVP_CHOICES[0])
        else:
            self.ovp_combo.config(values=["n/a"], state="disabled")
            self.ovp_var.set("n/a")

        if driver.compliance_tripped() is None:
            # Said once, at connect, rather than per run. An instrument
            # that cannot answer "did the limit clamp?" is not the same
            # as one answering "no", and the file records the
            # difference - but the operator should know before they set
            # up a run near the limit, not after.
            self.log(f"{driver.DISPLAY_NAME}: cannot report a compliance "
                     f"trip. The compliance column will be blank.")

    def _refresh_compliance_values(self, driver=None):
        """Offer the connected instrument's own range list."""
        driver = driver or self.app.instruments.get("source")
        mode = self.mode_var.get()
        limits = getattr(driver, "LIMITS", None) if driver else None

        if limits is not None:
            ranges = (limits.current_ranges if mode == "voltage"
                      else limits.voltage_ranges)
            values = [f"{r:g}" for r in ranges]
        else:
            values = (FALLBACK_CURRENT_COMPLIANCE if mode == "voltage"
                      else FALLBACK_VOLTAGE_COMPLIANCE)
        self.compliance_combo.config(values=values)

    # ---- form reactions ----
    def on_mode_changed(self):
        """Relabel the level and compliance fields for the new mode.

        Refused while a run is in flight: the source function is fixed
        for the life of a run, and a label that disagreed with what the
        instrument is doing would be worse than a greyed-out control.
        """
        if self.run_in_progress():
            messagebox.showwarning(
                "Measurement in progress",
                "The source function cannot change while a run is going.")
            self.mode_var.set(self._active_mode)
            return

        mode = self.mode_var.get()
        self._active_mode = mode
        if mode == "voltage":
            self.level_label.config(text="Level (V):")
            self.compliance_label.config(text="Current compliance (A):")
        else:
            self.level_label.config(text="Level (A):")
            self.compliance_label.config(text="Voltage compliance (V):")
        self._refresh_compliance_values()
        self.refresh_plot()

    #: Mirrors mode_var, so a refused change can be put back without
    #: reading the widget that was just changed.
    _active_mode = "voltage"

    def on_timing_changed(self):
        """Show what the duration and interval imply, as they are typed.

        Nominal, and labelled as such. The instrument decides the real
        answer, and this box has no way to ask it.
        """
        try:
            duration = float(self.duration_var.get())
            interval = float(self.interval_var.get())
        except (TypeError, ValueError):
            self.nominal_var.set("")
            return
        if duration <= 0 or interval <= 0:
            self.nominal_var.set("")
            return
        count = int(duration / interval) + 1
        self.nominal_var.set(f"~{count} samples if the instrument keeps up")

    # ---- reading the form ----
    def _params(self):
        """Read and validate the whole form into a frozen snapshot.

        Everything the worker needs is read here, on the main thread, at
        the Run press. After this the worker cannot see the window at
        all, so retyping a field mid-run cannot reach the measurement.
        """
        mode = one_of(self.mode_var.get(), "Source function",
                      ("voltage", "current"))
        unit = "V" if mode == "voltage" else "A"

        # Zero is a legitimate level: holding a sample at 0 V and
        # watching the current is a real measurement (leakage, or the
        # relaxation after a bias). So this is `si_level`, not
        # `positive_number` - the only thing refused is a level the
        # instrument cannot reach, which `check_source_point` decides.
        level = si_level(self.level_var.get(), "Level", unit=unit)

        compliance = si_level(
            self.compliance_var.get(), "Compliance",
            unit="A" if mode == "voltage" else "V", minimum_exclusive=0.0)

        duration = positive_number(self.duration_var.get(), "Duration")
        interval = positive_number(self.interval_var.get(), "Sample every")
        if interval > duration:
            raise ValidationError(
                "Sample every",
                f"is longer than the duration ({duration:g} s), so the run "
                f"would take one sample and stop. Shorten the interval or "
                f"lengthen the run.")

        ovp = (self.ovp_var.get() or "").strip()
        if not ovp or ovp.lower() == "n/a":
            ovp = None

        return FixedSourceParameters(
            sample=self.current_sample_ref(),
            dataset=(self.dataset_var.get() or "run").strip(),
            mode=mode,
            level=level,
            compliance=compliance,
            duration_s=duration,
            interval_s=interval,
            nplc=parse_nplc(self.nplc_var),
            high_z=bool(self.high_z_var.get()),
            ovp=ovp,
            remote_sense=bool(self.remote_sense_var.get()),
        )

    def _check_limits(self, params):
        """One level, checked against the instrument's envelope.

        One check rather than a sweep's two, because there is one level.
        That is the whole simplification this experiment buys.
        """
        if params.mode == "voltage":
            self.app.check_source_point("source", voltage=params.level,
                                        current=params.compliance)
        else:
            self.app.check_source_point("source", current=params.level,
                                        voltage=params.compliance)

    # ---- the buttons ----
    def run_pressed(self):
        if not self._ready_to_run():
            return
        try:
            params = self._params()
            self._check_limits(params)
        except ValueError as e:
            messagebox.showerror("Invalid setup", str(e))
            return
        except Exception as e:
            self.log("Refused:", e)
            messagebox.showerror("Outside instrument limits", str(e))
            return

        if not self._confirm_long_run(params):
            return

        # Watch-compliance is read here rather than inside the snapshot
        # because it changes what the run *records*, not what it does to
        # the sample. It still travels with the run, in metadata.
        self._watch_compliance = bool(self.watch_compliance_var.get())

        self.app.run_in_background(
            self.app.guard_run(lambda: self._do_run(params)))

    _watch_compliance = True

    def _confirm_long_run(self, params):
        """Ask before a run that will hold the sample live for a while.

        Not a cap. A long bias-stress run is a real experiment and the
        software has no business refusing one; what it can do is make an
        extra zero visible before the output goes on rather than an hour
        later.
        """
        if params.duration_s <= LONG_RUN_WARNING_S:
            return True
        minutes = params.duration_s / 60.0
        unit = "V" if params.mode == "voltage" else "A"
        return messagebox.askyesno(
            "Long run",
            f"This will hold the sample at {params.level:g} {unit} for "
            f"{minutes:.1f} minutes with the output on.\n\n"
            f"The output is switched off when the run ends, and "
            f"'Finish and save' stops it early and keeps the data.\n\n"
            f"Start the run?")

    def _ready_to_run(self):
        if self.run_in_progress():
            return False
        if self.app.instruments.get("source") is None:
            messagebox.showerror("Not connected", "Connect the SMU first.")
            return False
        if self.refuse_if_sibling_busy():
            return False
        if not self._summary_collision_ok():
            return False
        return True

    def finish_pressed(self):
        """End sampling now and keep what has been collected.

        The one control in this suite that stops a run without
        discarding it, and it is legitimate here for a reason that does
        not generalise: these readings are independent samples of a
        sample's behaviour over time, so twenty minutes of an hour is
        twenty real minutes. Half an IV curve is not.

        Nothing here talks to the instrument. It sets a flag; the worker
        sees it at its next loop boundary and de-energises on the thread
        that owns the session. That is the same discipline Stop follows,
        and the reason neither button can interleave SCPI with a
        `measure()` in flight.
        """
        if not self.run_in_progress():
            return
        self._finish_now.set()
        self.log("Finish pressed: sampling stops after the current reading, "
                 "output off, data kept")

    def stop_pressed(self):
        """Cancel the run: discard its data and de-energise.

        The house Stop, unchanged from every other tab. Kept identical
        on purpose - an operator who has pressed Stop a hundred times on
        Van der Pauw must not discover that it means something else
        here.
        """
        if self.cancel_run("operator pressed Stop and discard"):
            self.log("Stop pressed: cancelling, output off, data discarded")

    def _enter_run_ui(self):
        self.run_btn.config(state="disabled")
        self.finish_btn.config(state="normal")
        self.stop_btn.config(state="normal")

    def _end_run(self):
        """Back to idle. Main thread, and safe to call twice."""
        try:
            self.run_btn.config(state="normal")
            self.finish_btn.config(state="disabled")
            self.stop_btn.config(state="disabled")
            self.set_lamp(False)
            self.progress_var.set("Idle")
            self._live = None
        except Exception:
            pass

    # ---- the measurement ----
    def _do_run(self, params):
        """Hold the level and sample the clock. Background thread."""
        # A fresh flag per run. The old one may have been set by a press
        # that arrived as the previous run was already unwinding.
        self._finish_now = threading.Event()

        with self.begin_run(parameters=params) as run:
            run.on_cleanup(lambda: self.app.ui(self._end_run))
            run.enter(self.app.claim_instrument("source", run.run_id))
            smu = self.instrument("source")
            self.app.ui(self._enter_run_ui)

            # Deliberately no `run.expect()`. See `_commit` for the
            # floor that replaces it and why an equality check would
            # fail every honest run on a slow instrument.
            run.set_metadata(timebase="host")

            try:
                started = self._configure(run, smu, params)
                outcome = self._sample(run, smu, params, started)
            finally:
                report = run.confirm_shutdown(smu, log=self.log)
                self.app.ui(self.set_lamp, False)
                if report.uncertain:
                    self.app.report_uncertain_shutdown("source", report)

            self._commit(run, params, outcome)

    def _configure(self, run, smu, params):
        """Everything before the output goes on. Returns t=0.

        House rule 12: every configuration command precedes the
        output-on transition, and nothing is reconfigured while the
        sample is energised. That is easy to honour here and worth
        stating anyway - after `output_on()` below, this experiment
        issues nothing but reads.

        Two choices in here are specific to this measurement:

        **The level is set before the output goes on**, not after. That
        is what makes the energising a step from nothing to the full
        level, so the turn-on transient is inside the data rather than
        before it. Setting it afterwards would put an unmeasured ramp of
        unknown length between t=0 and the first sample.

        **The source delay is set to zero, explicitly.** It is a
        per-level settle, and there is only one level; leaving it
        inherited would add somebody else's sweep delay to every reading
        and silently lower the achievable sample rate (fault 17).
        """
        run.checkpoint("configuring source")

        smu.set_source_function(params.mode)

        # Range before limit (fault 15): a compliance is clamped to the
        # range active when it arrives on at least one instrument here,
        # and *RST leaves the smallest range selected. The source range
        # is fixed to the one level this run will ever source, which
        # also removes any chance of a range change part way through -
        # the step in the data that house rule 12 is really about.
        ranges = RangePlan.for_sourcing(params.mode,
                                        source_range=abs(params.level),
                                        measure_range=params.compliance)
        run.set_metadata(ranges=smu.apply_ranges(ranges, log=self.log))

        if params.mode == "voltage":
            smu.set_current_limit(params.compliance)
            smu.set_voltage_level(params.level)
        else:
            smu.set_voltage_limit(params.compliance)
            smu.set_current_level(params.level)

        smu.set_source_delay(0.0)

        run.set_metadata(
            sensing=apply_remote_sense(smu, params.remote_sense, self.log),
            nplc=apply_nplc(smu, params.nplc, self.log),
            high_z_off=apply_high_z(smu, params.high_z, self.log))

        if params.ovp is not None and smu.supports_ovp():
            smu.set_voltage_protection(params.ovp)

        # The last gate before the output goes live: Stop pressed during
        # configuration must not be followed by the worker energising
        # anyway.
        run.checkpoint("before output on")
        smu.output_on()
        started = time.monotonic()
        self.app.ui(self.set_lamp, True)
        run.start()
        return started

    def _sample(self, run, smu, params, started):
        """The sampling loop. Returns everything the commit needs.

        The schedule is absolute: sample `i` is due at `started + i *
        interval`. Waiting for the *remaining* time to each deadline is
        what stops each reading's cost accumulating as drift - sleeping
        the interval between readings would turn a nominal 1 Hz run into
        0.8 Hz with nothing recorded to say so.

        What is recorded per sample is measured, not derived: `time_s`
        is when the reading was asked for and `read_s` is how long it
        took. Those two together also bound the one thing this
        experiment cannot fix from up here - on an instrument that reads
        voltage and current in two round trips, the pair in a row are
        not from the same instant, and `read_s` is how far apart they
        could be.
        """
        readings = []
        overruns = 0
        worst_overrun = 0.0
        trips = 0
        blanks = 0
        ended_by = "duration"
        error_detail = ""
        last_plot = 0.0
        index = 0

        while True:
            # Two ways this run ends, and they are not the same thing.
            #
            # The **grid** ends a run that is keeping up, after the
            # sample due at exactly `duration`. Its tolerance is the one
            # `nominal_readings` needs and for the same reason:
            # `3 * 0.1` is `0.30000000000000004`, which is greater than
            # `0.3`, so an exact comparison silently drops the last
            # sample of any run whose duration is not a binary-friendly
            # multiple of its interval.
            due = index * params.interval_s
            if due > params.duration_s + params.interval_s * 1e-9:
                break

            # The **clock** is the ceiling, and it needs a grace of one
            # interval. Its job is to stop an instrument slower than the
            # requested rate from walking the nominal grid at its own
            # pace - a 60 s run at 5 ms on a 50 ms instrument would
            # otherwise hold the output on for ten minutes, which is the
            # one thing the timer exists to prevent.
            #
            # Without the grace it also does something it was never
            # meant to: it drops the final sample. That sample is due at
            # exactly `duration`, so any lateness at all in the last
            # wait puts the clock past the ceiling before the sample due
            # inside it has been taken. Windows CI found this; its
            # default timer granularity is about 15.6 ms, so a 10 ms
            # final wait overshoots by 5 ms and an eleven-sample run
            # returns ten. Linux, with a finer timer, could not
            # reproduce it - and the run looked entirely healthy, one
            # sample short, well inside the shortfall floor.
            #
            # This is the same fault as the float-division one above
            # arriving through a different door: the last sample of a
            # well-behaved run vanishing because a comparison was
            # exactly on a boundary. Both are fixed the same way, by
            # deciding what the boundary is *for*. A sample due at
            # `duration` is inside the window the operator agreed to; a
            # run that has fallen a whole interval behind that window is
            # in the runaway case the ceiling is aimed at.
            #
            # The cost is bounded and worth stating: a run may exceed
            # its requested duration by up to one interval.
            if (time.monotonic() - started
                    >= params.duration_s + params.interval_s):
                break

            if not self._wait_until(run, started + due):
                ended_by = "operator"
                break

            run.checkpoint(f"sample {index + 1}")

            t_start = time.monotonic() - started
            late = t_start - due
            if index and late > params.interval_s * OVERRUN_FRACTION:
                overruns += 1
                worst_overrun = max(worst_overrun, late)

            try:
                volts, amps = smu.measure()
            except Exception as exc:
                # A read that fails mid-series is not a point to skip.
                # On at least one instrument here a timed-out read
                # leaves its reply in the buffer and puts every reading
                # after it one step out of phase - the trace stays
                # perfectly plausible and is wrong about *when*,
                # everywhere after the glitch. So sampling stops, and
                # what was collected before it is kept and labelled.
                ended_by = "read_error"
                error_detail = f"{type(exc).__name__}: {exc}"
                self._report(f"Read failed after {t_start:.3f} s "
                             f"({error_detail}); sampling stopped, "
                             f"{len(readings)} sample(s) kept")
                break
            t_end = time.monotonic() - started

            tripped = None
            if self._watch_compliance:
                try:
                    tripped = smu.compliance_tripped()
                except Exception:
                    tripped = None
                if tripped:
                    trips += 1
                    if trips == 1:
                        # Once, not per sample. A warning repeated three
                        # thousand times is a warning nobody reads, and
                        # the count is in the metadata anyway.
                        self._report(
                            "Compliance tripped - the instrument is "
                            "clamping. Readings continue and every "
                            "sample records whether it was clamped.")

            measured = amps if params.mode == "voltage" else volts
            if measured is None:
                blanks += 1

            reading = {
                "sample_index": index + 1,
                "reading_id": reading_id(run.run_id, index),
                "time_s": round(t_start, 6),
                "read_s": round(t_end - t_start, 6),
                # Sentinels are already None by the time they get here,
                # and a None is written as an empty cell **in place**
                # rather than dropped: omitting a value shifts every
                # later column left, which promotes the current into the
                # voltage's position - a number of the right shape,
                # wrong by a factor of the resistance.
                "voltage_V": "" if volts is None else volts,
                "current_A": "" if amps is None else amps,
                "compliance": "" if tripped is None
                              else ("yes" if tripped else "no"),
            }
            temperature = self._stage_temperature()
            if temperature is not None:
                # Per sample rather than per run, because on a
                # temperature ramp a single run-level number would be a
                # lie by the third minute. The key is absent - so the
                # column does not exist at all - when no stage is
                # connected or the board has gone quiet.
                reading["stage_temp_C"] = temperature

            readings.append(reading)
            run.add_reading(reading)

            now = time.monotonic()
            if now - last_plot >= PLOT_THROTTLE_S:
                last_plot = now
                self._push_live(params, readings)

            self.app.ui(self.progress_var.set,
                        f"{len(readings)} samples, t = {t_start:.1f} s "
                        f"of {params.duration_s:g} s")

            if self._finish_now.is_set():
                ended_by = "operator"
                break

            index += 1

        self._push_live(params, readings)
        return {"readings": readings, "ended_by": ended_by,
                "error_detail": error_detail, "overruns": overruns,
                "worst_overrun_s": worst_overrun, "trips": trips,
                "blanks": blanks}

    def _wait_until(self, run, deadline):
        """Wait for a monotonic deadline. False if Finish was pressed.

        Sliced rather than one long wait. Cancellation would not need
        it - `RunContext.sleep` wakes on the cancel event - but the
        finish flag is a plain event the worker polls, and polling it
        once per interval would make the button feel broken on a run
        sampling every ten seconds.

        Raises `RunCancelled` if Stop was pressed, from the checkpoint
        inside `run.sleep`.
        """
        while True:
            if self._finish_now.is_set():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                run.checkpoint()
                return True
            run.sleep(min(remaining, WAIT_SLICE_S))

    def _stage_temperature(self):
        """Stage temperature, or None when there is nothing to ask.

        None covers all three ways there is no answer: no controller, no
        port open, and a board that has stopped talking. A stale reading
        recorded as a live one would be the same class of fault as a
        reconstructed time axis.
        """
        controller = self.temp_ctrl
        if controller is None or not controller.is_connected():
            return None
        status = controller.status()
        if status.is_stale or status.fault or status.temp_c is None:
            return None
        return round(status.temp_c, 2)

    # ---- committing ----
    def _commit(self, run, params, outcome):
        """Build the run record and offer it to the commit gate.

        The floor that replaces `expect()`
        ----------------------------------
        A run that ran its full duration and came back with a third of
        the samples the interval implies did not measure what was asked
        for: the instrument could not keep up, and a trace at an unknown
        third of the requested rate is worse than no trace. That is
        refused.

        A run the *operator* ended early is a different thing entirely.
        They chose the length, so the only floor is the one that makes
        the data a time series at all - two points. Same for a run cut
        short by a read error: what was collected before the glitch is
        real, and the record says where it stopped.
        """
        readings = outcome["readings"]
        ended_by = outcome["ended_by"]

        floor = (params.minimum_readings if ended_by == "duration" else 2)
        if len(readings) < floor:
            run.record_error(
                f"{len(readings)} sample(s) collected; at least {floor} "
                f"were needed (nominal {params.nominal_readings} at "
                f"{params.interval_s:g} s)")

        if readings and outcome["blanks"] == len(readings):
            run.record_error(
                f"no sample returned a {params.measured_quantity} reading")
        elif outcome["blanks"]:
            self._report(f"{outcome['blanks']} sample(s) returned no "
                         f"{params.measured_quantity} reading; those cells "
                         f"are blank in the file")

        achieved = self._achieved_interval(readings)
        if outcome["overruns"]:
            self._report(
                f"{outcome['overruns']} sample(s) landed more than half an "
                f"interval late, worst {outcome['worst_overrun_s'] * 1000:.0f}"
                f" ms. Requested {params.interval_s:g} s; achieved "
                f"{achieved:.4g} s.")

        # Claimed once, here, under the app's lock - not read off the
        # display variable. `take_meas_number()` is the only thing that
        # advances it, so two tabs finishing at the same instant cannot
        # be handed the same number.
        meas_num = self.app.take_meas_number()
        record = Run(
            sample=params.sample.slug,
            metadata={
                "meas_number": meas_num,
                "sample_id": params.sample_id,
                "sample_label": params.sample_label,
                "run_id": run.run_id,
                "dataset": params.dataset,
                "source_mode": params.mode,
                "measured_quantity": params.measured_quantity,
                "level": params.level,
                "compliance": params.compliance,
                "duration_requested_s": params.duration_s,
                "interval_requested_s": params.interval_s,
                "interval_achieved_s": achieved,
                "samples_nominal": params.nominal_readings,
                "samples_collected": len(readings),
                "overruns": outcome["overruns"],
                "worst_overrun_s": round(outcome["worst_overrun_s"], 6),
                # Three different statements, kept apart on purpose:
                # trips seen, watching switched off, and an instrument
                # that cannot answer. "0" and "not watched" must never
                # collapse into the same cell.
                "compliance_watched": "yes" if self._watch_compliance else "no",
                "compliance_trips": (outcome["trips"]
                                     if self._watch_compliance else ""),
                "no_reading_n": outcome["blanks"],
                "ended_by": ended_by,
                "ended_detail": outcome["error_detail"],
                "timebase": "host",
                **run.metadata,
            },
            readings=readings,
        )

        run.commit(record, lambda result: self.app.ui(
            self._record_run, result, params, outcome, achieved))

    @staticmethod
    def _achieved_interval(readings):
        """Mean gap actually achieved, from the measured timestamps.

        Measured rather than requested, and mean rather than nominal:
        this is the number that says whether the instrument kept up, so
        deriving it from the request would make it incapable of
        disagreeing.
        """
        if len(readings) < 2:
            return 0.0
        span = readings[-1]["time_s"] - readings[0]["time_s"]
        return span / (len(readings) - 1)

    def _record_run(self, record, params, outcome, achieved):
        """Insert the row, store the run, refresh the plot. Main thread."""
        unit = "V" if params.mode == "voltage" else "A"
        item = self.tree.insert(
            "", "end", text="☐",
            values=(params.dataset,
                    params.mode,
                    f"{params.level:g} {unit}",
                    f"{len(record.readings)}/{params.nominal_readings}",
                    f"{achieved:.4g}",
                    outcome["ended_by"]))
        self.run_store.add(item, record)
        self._traces[item] = self._trace_of(params, record.readings)
        self._live = None
        self.refresh_plot()
        self._report(
            f"{params.dataset}: {len(record.readings)} samples over "
            f"{record.readings[-1]['time_s']:.1f} s, "
            f"ended by {outcome['ended_by']}")

    def _report(self, text):
        """Console line from a worker thread."""
        self.app.ui(self.log, text)

    # ---- plotting ----
    def _trace_of(self, params, readings):
        """One plot trace from a list of readings."""
        measured_key = ("current_A" if params.mode == "voltage"
                        else "voltage_V")
        source_key = ("voltage_V" if params.mode == "voltage"
                      else "current_A")
        times, measured, sourced = [], [], []
        for reading in readings:
            value = reading.get(measured_key, "")
            if value == "" or value is None:
                # A blank is a gap in the trace, not a zero. Dropping the
                # point leaves the line to jump the gap, which is honest
                # about the values and quiet about the hole; plotting a
                # zero would be neither.
                continue
            times.append(reading["time_s"])
            measured.append(float(value))
            other = reading.get(source_key, "")
            sourced.append(None if other in ("", None) else float(other))
        return {
            "label": params.dataset,
            "x": times,
            "y": measured,
            "source": sourced,
            "measured_unit": "A" if params.mode == "voltage" else "V",
            "source_unit": "V" if params.mode == "voltage" else "A",
        }

    def _push_live(self, params, readings):
        """Hand the trace so far to the main thread for drawing.

        A copy, built here on the worker, because the list keeps growing
        underneath. Handing the live list across would let the drawing
        code iterate it while it is being appended to.
        """
        trace = self._trace_of(params, readings)
        self.app.ui(self._draw_live, trace)

    def _draw_live(self, trace):
        """Main thread: show the run in flight."""
        self._live = trace
        self.refresh_plot()

    def refresh_plot(self):
        """Redraw the axes. Main thread only."""
        if not hasattr(self, "plot_ax"):
            return

        if self._live is not None:
            traces = [self._live]
        elif hasattr(self, "tree"):
            ticked = [i for i in self.ticked_items() if i in self._traces]
            if not ticked:
                # Nothing ticked shows the newest run: a run that
                # finished and left the axes empty reads as a failure.
                # Ticking narrows the plot; it is not a precondition for
                # seeing anything.
                rows = [i for i in self.tree.get_children()
                        if i in self._traces]
                ticked = rows[-1:]
            traces = [self._traces[i] for i in ticked]
            if not self.plot_overlap_var.get() and traces:
                traces = traces[-1:]
        else:
            traces = []

        self._draw(traces)

    def _draw(self, traces):
        """Draw time series onto the shared plot widget.

        Local rather than `core.gui.plot_panel.draw_datasets`, for one
        reason that is not cosmetic: the sourced quantity goes on a
        second y-axis, and the shared function neither builds one nor
        knows to clear it. A twin axis created per redraw stacks a new
        set of ticks on the figure every time until the labels are
        unreadable, so the one here is built once and reused.
        """
        ax = self.plot_ax
        ax.clear()
        twin = self._twin_ax
        if twin is not None:
            twin.clear()
            twin.set_visible(False)

        show_source = bool(getattr(self, "show_source_var", None)
                           and self.show_source_var.get())

        if not traces or not any(t["x"] for t in traces):
            ax.set(title=self.plot_title_var.get(), xlabel="Time [s]",
                   ylabel="Measured")
            ax.text(0.5, 0.5, "No runs yet", transform=ax.transAxes,
                    ha="center", va="center", color="gray", fontsize=9)
        else:
            unit = traces[0]["measured_unit"]
            for trace in traces:
                ax.plot(trace["x"], trace["y"], "-", linewidth=1,
                        label=trace["label"])

            if show_source:
                if twin is None:
                    twin = self._twin_ax = ax.twinx()
                twin.set_visible(True)
                for trace in traces:
                    points = [(x, s) for x, s in zip(trace["x"],
                                                     trace["source"])
                              if s is not None]
                    if not points:
                        continue
                    twin.plot([p[0] for p in points], [p[1] for p in points],
                              "--", linewidth=1, alpha=0.6,
                              label=f"{trace['label']} (sourced)")
                twin.set_ylabel(f"Sourced [{traces[0]['source_unit']}]")

            ax.set(title=self.plot_title_var.get(), xlabel="Time [s]",
                   ylabel=f"Measured [{unit}]")
            ax.legend(loc="upper left", fontsize=7)
            ax.grid(True, alpha=0.25)

        try:
            self.plot_fig.tight_layout()
        except Exception:
            pass
        self.plot_canvas.draw_idle()

    # ---- table interactions ----
    def toggle_row(self, event):
        """Click in the checkbox column toggles that row's ☑/☐."""
        if self.tree.identify("region", event.x, event.y) != "tree":
            return
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        current = self.tree.item(row_id, "text") or ""
        self.tree.item(row_id, text="☐" if current == "☑" else "☑")
        self.refresh_plot()

    def copy_over(self):
        """Draw the ticked rows - the house 'copy ticked' action."""
        if not self.ticked_items():
            messagebox.showinfo("Nothing ticked",
                                "Tick the runs you want on the plot.")
            return
        self.refresh_plot()

    def delete_ticked(self):
        """Inherited behaviour, plus dropping the traces from the plot."""
        ticked = list(self.ticked_items())
        super().delete_ticked()
        remaining = set(self.tree.get_children())
        for item in ticked:
            if item not in remaining:
                self._traces.pop(item, None)
        self.refresh_plot()

    def clear_output(self):
        """Inherited behaviour, plus clearing the plot."""
        super().clear_output()
        if not self.tree.get_children():
            self._traces.clear()
        self.refresh_plot()

    def set_lamp(self, on):
        self.lamp_canvas.itemconfig(self.lamp_id,
                                    fill="green" if on else "gray")

    def on_close(self):
        """Cancel any run in flight before connections are torn down.

        Cancel, not finish. A window being closed is not an operator
        deciding they have enough data, and committing a run into a
        results table that is about to be destroyed would write nothing
        anywhere useful. The worker de-energises on its own thread
        either way, which is the part that matters for the sample.
        """
        self.cancel_run("window closing")
