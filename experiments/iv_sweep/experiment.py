"""
IV sweep - linear voltage or current sweeps, with optional long bias.

This is the three IV scripts merged into one experiment:

    IV_Meas_2611A_-_Basic.py         voltage_sweep
    IV_Meas_2611A_-_Development.py   + linear fit (resistance, R²)
    IV_Meas_2611A_-_Improved.py      byte-identical to Development
    IV_Meas_2611A_-_Long_bias.py     + current_sweep, bias modes,
                                       periodic runs

They were additive versions of one program, not three different
measurements, so they collapse into one experiment with optional panels
rather than three subclasses. Remove build_periodic_panel from PANELS
and what's left is Basic; the sequencing code doesn't change either way.

Sequence per sweep:
    1. Configure source function, compliance and range for the mode
    2. Output ON (skipped if a bias hold already has it on)
    3. Fire the instrument's own linear sweep into its buffer
    4. Poll the buffer until every point has landed
    5. Read back the sourced levels and the measured values
    6. Fit a line, derive resistance and R²
    7. Output OFF (skipped if a bias hold should keep it on)

Deviations from the originals are marked `# DEVIATION` and listed in
docs/rules/07-run-is-a-transaction.md. The significant one is step 4.
"""
import datetime
import time
from tkinter import messagebox

from core.gui.plot_panel import build_plot_panel, draw_datasets
from core.gui.widgets import (
    apply_high_z,
    apply_nplc,
    apply_remote_sense,
    parse_nplc,
    refresh_high_z,
    refresh_nplc,
    refresh_remote_sense,
)
from core.limits import parse_si
from core.ranges import RangePlan
from core.run_store import Run
from experiments.base_experiment import Experiment

from .iv_math import fit_sweep
from .panels.action_panel import build_action_panel
from .panels.mode_panel import build_mode_panel
from .panels.periodic_panel import build_periodic_panel
from .panels.results_panel import build_results_panel
from .panels.setup_panel import build_setup_panel

# How long to wait for a sweep beyond its nominal duration before giving
# up. The nominal duration is points x delay; instruments add ranging and
# settling on top, and the original applied a flat 1.30 factor to cover
# it. That factor is kept as the *expected* time for progress reporting,
# but the hard ceiling is deliberately looser - a sweep that runs 20%
# long should finish, not be abandoned one point from the end.
SWEEP_TIMEOUT_FACTOR = 4.0
SWEEP_TIMEOUT_FLOOR_S = 30.0

# Cap on how often the buffer is polled. Fast enough to feel responsive,
# slow enough not to flood a GPIB link during a long sweep.
MIN_POLL_INTERVAL_S = 0.1
MAX_POLL_INTERVAL_S = 1.0

# Host-side settle at the start level before the sweep is fired. The
# originals slept a flat 2 s here and it is kept at that. Named rather
# than inline so a test can shorten it without editing the sequence.
PRE_SWEEP_SETTLE_S = 2.0


class IVSweepExperiment(Experiment):
    NAME = "IV sweep - voltage/current sweeps and long bias"

    ROLES = {"source": "SMU"}

    CSV_SLUG = "iv_sweep"
    CSV_TITLE = "IV sweep"

    # The hot/cold stage is app-level from Wave 5b: one window, one
    # serial port, one controller. `build_temp_panel` is no longer in
    # PANELS for that reason.
    USES_TEMP_STAGE = True

    PANELS = [
        build_mode_panel,        # col_left  - what the SMU sources
        build_setup_panel,       # col_mid   - what to run
        build_periodic_panel,    # col_mid   - optional: long bias
        build_action_panel,      # col_mid   - Run / Stop / OFF
        build_results_panel,     # col_right - what came out
        build_plot_panel,        # col_right - what came out, drawn
    ]

    def __init__(self, app):
        super().__init__(app)
        # Mirrors mode_var, so a mode change refused mid-run can be put
        # back without reading the widget that was just changed.
        self._active_mode = "voltage"
        # Treeview item id -> plot dataset. Keyed the same way the run
        # store is, so deleting a row drops its curve from the plot too.
        self._datasets = {}
        self._calculated = {}

    # ---- setup once the widgets exist ----
    def on_panels_built(self):
        """Apply the initial mode labelling and draw the empty axes."""
        self.on_mode_changed()
        self.on_standby_changed()

    # ---- driver-aware setup ----
    def on_connected(self, role, driver):
        """Repopulate compliance choices from the connected instrument,
        and check up front that it can sweep at all.

        Checking here rather than at Run means an instrument without a
        sweep implementation says so while you're still setting up,
        instead of failing after you've committed a sample to it.
        """
        kind = driver.sweep_kind()
        if kind == "hardware":
            self.log(f"{driver.DISPLAY_NAME}: hardware sweep "
                     f"(instrument timebase)")
        else:
            self.log(f"{driver.DISPLAY_NAME}: software sweep - levels are "
                     f"set point by point from the PC, so per-point timing "
                     f"depends on bus latency. Levels and readings are "
                     f"unaffected.")

        # Some drivers work out their sweep kind by asking the
        # instrument rather than declaring it, and have something to say
        # about how that went. Optional, so absence isn't an error.
        note = getattr(driver, "sweep_note", None)
        if callable(note):
            try:
                text = note()
            except Exception:
                text = ""
            if text:
                self.log(f"{driver.DISPLAY_NAME}: {text}")

        self._refresh_compliance_values(driver)
        self._refresh_capabilities(driver)
        self.log(f"Ranges loaded from {driver.DISPLAY_NAME}")

    def _refresh_capabilities(self, driver=None):
        """Enable or grey out the optional controls according to what
        the connected instrument actually has.

        Greying out rather than hiding: a control that vanishes leaves
        the operator wondering whether they imagined it, whereas a
        disabled one reading 'n/a' says plainly that this instrument
        has no such setting.
        """
        if driver is None:
            driver = self.app.instruments.get("source")
        if driver is None:
            return

        refresh_nplc(self.nplc_combo, self.nplc_var, driver, self.log)
        refresh_high_z(self.high_z_check, self.high_z_var, driver, self.log)
        refresh_remote_sense(self.remote_sense_check, self.remote_sense_var,
                             driver, self.log)

        if driver.supports_ovp():
            self.ovp_combo.config(state="readonly")
            self.ovp_combo["values"] = list(driver.OVP_CHOICES)
            if self.ovp_var.get() not in driver.OVP_CHOICES:
                # First entry is the safe default by convention.
                self.ovp_var.set(driver.OVP_CHOICES[0])
        else:
            self.ovp_combo.config(state="disabled")
            self.ovp_var.set("n/a")

    def _refresh_compliance_values(self, driver=None):
        """Fill the compliance dropdown with values the connected
        instrument can actually reach, in the units the current mode
        needs."""
        if driver is None:
            driver = self.app.instruments.get("source")
        if driver is None or driver.LIMITS is None:
            return

        limits = driver.LIMITS
        if self.mode_var.get() == "voltage":
            # sourcing volts -> compliance is a current
            values = [f"{a:g}" for a in sorted(limits.current_ranges)]
        else:
            values = [f"{v:g}" for v in sorted(limits.voltage_ranges)]
        self.compliance_combo["values"] = values
        if self.compliance_var.get() not in values and values:
            self.compliance_var.set(values[len(values) // 2])

    # ---- mode handling ----
    def on_mode_changed(self):
        """Relabel every field that means a different quantity in the
        other mode, and reset the plot axes.

        Refused mid-run: changing the source function while the output
        is live is exactly the transition the original's mode lock was
        trying to prevent.
        """
        if self.run_in_progress():
            messagebox.showwarning(
                "Measurement running",
                "Stop the measurement before changing sweep mode.")
            # put the radio button back where it was
            self.mode_var.set(self._active_mode)
            return

        mode = self.mode_var.get()
        self._active_mode = mode

        if mode == "voltage":
            self.start_label.config(text="Start voltage (V):")
            self.stop_label.config(text="Stop voltage (V):")
            self.compliance_label.config(text="Current compliance (A):")
        else:
            self.start_label.config(text="Start current (A):")
            self.stop_label.config(text="Stop current (A):")
            self.compliance_label.config(text="Voltage compliance (V):")

        self._refresh_compliance_values()
        self.on_standby_changed()
        self.refresh_plot()
        self.log(f"Sweep mode: source {mode}")

    def on_standby_changed(self):
        """Relabel the bias entry for the selected standby mode."""
        if not hasattr(self, "bias_label"):
            return
        standby = self.standby_var.get()
        if standby == "Bias voltage":
            self.bias_label.config(text="Bias level (V):")
        elif standby == "Bias current":
            self.bias_label.config(text="Bias level (A):")
        else:
            self.bias_label.config(text="Bias level (unused):")

    # ---- input parsing ----
    def _sweep_params(self):
        """Read and validate the sweep form.

        Returns a dict, or raises ValueError with a message meant for a
        dialog. Validating in one place means the periodic run and the
        single run can't disagree about what counts as valid.
        """
        try:
            start = float(parse_si(self.start_var.get()))
            stop = float(parse_si(self.stop_var.get()))
        except Exception:
            raise ValueError("Start and stop must be numbers.") from None

        if start == stop:
            # The originals had a whole second code path for this: a
            # single-point 'sweep' that just measured once. It is
            # dropped. A one-point IV curve is not a sweep, the branch
            # was reachable only by accident, and Development's version
            # of it crashed on a float/string concatenation the moment
            # anyone tried.                                # DEVIATION 5
            raise ValueError(
                "Start and stop must differ.\n\n"
                "Use Van der Pauw or Hall for single-point measurements.")

        try:
            points = int(float(self.points_var.get()))
        except Exception:
            raise ValueError("Points must be a whole number.") from None
        if points < 2:
            raise ValueError("A sweep needs at least 2 points.")

        try:
            delay = float(self.delay_var.get())
        except Exception:
            raise ValueError("Delay must be a number.") from None
        if delay < 0:
            raise ValueError("Delay cannot be negative.")

        try:
            repeats = int(float(self.runs_var.get()))
        except Exception:
            raise ValueError("Repeats must be a whole number.") from None
        if repeats < 1:
            raise ValueError("Repeats must be at least 1.")

        try:
            compliance = float(parse_si(self.compliance_var.get()))
        except Exception:
            raise ValueError("Compliance must be a number.") from None
        if compliance <= 0:
            raise ValueError("Compliance must be positive.")

        # Both optional: the field reads "n/a" when the connected
        # instrument has no such control, and None here means "leave the
        # instrument alone" rather than "send a default", which would
        # overwrite whatever the operator set on the front panel.
        nplc = parse_nplc(self.nplc_var)
        high_z = bool(self.high_z_var.get())

        ovp = self.ovp_var.get().strip()
        if not ovp or ovp.lower() == "n/a":
            ovp = None

        return {
            "mode": self.mode_var.get(),
            # Captured here, on the main thread, at the Run press - not
            # read again when each sweep finishes.
            #
            # It used to be read at the end of every sweep, by
            # `_finish_sweep` calling `current_sample_name()` on the
            # worker. That is §17's fault, which Wave 4 fixed for 4PP
            # and Wave 5 for Van der Pauw and Hall; the IV sweep was
            # never migrated. Two things were wrong with it:
            #
            #   * a Tk variable was being read from a worker thread,
            #     which usually works and then does not;
            #   * retyping the sample-name box mid-run re-filed the
            #     remaining sweeps under the new name. A periodic run
            #     could put its cycles under two different samples, with
            #     nothing logged and no error. House rule 11 exists
            #     because operators do retype that box.
            #
            # A frozen `SampleRef` says what was true when the
            # measurement happened, which is the only thing a stored run
            # can honestly claim.
            "sample": self.current_sample_ref(),
            "start": start,
            "stop": stop,
            "points": points,
            "delay": delay,
            "repeats": repeats,
            "compliance": compliance,
            "dataset": (self.dataset_var.get() or "run").strip(),
            "remote_sense": bool(self.remote_sense_var.get()),
            "do_fit": bool(self.do_fit_var.get()),
            "nplc": nplc,
            "ovp": ovp,
            "high_z_off": high_z,
        }

    def _periodic_params(self):
        """Read and validate the periodic form. Raises ValueError."""
        try:
            cycles = int(float(self.cycles_var.get()))
        except Exception:
            raise ValueError("Cycles must be a whole number.") from None
        if cycles < 1:
            raise ValueError("Cycles must be at least 1.")

        try:
            period = float(self.period_var.get())
        except Exception:
            raise ValueError("Cycle period must be a number.") from None
        if period < 0:
            raise ValueError("Cycle period cannot be negative.")

        standby = self.standby_var.get()
        bias = 0.0
        if standby in ("Bias voltage", "Bias current"):
            try:
                bias = float(parse_si(self.bias_var.get()))
            except Exception:
                raise ValueError("Bias level must be a number.") from None

        return {"cycles": cycles, "period": period,
                "standby": standby, "bias": bias}

    # ---- the limit gate ----
    def _check_limits(self, params):
        """Run both ends of the sweep past the instrument's declared
        envelope before anything is sourced.

        Both ends, because a sweep from -1 V to +25 V is legal at the
        start and not at the end. Checking only the start value would
        pass it.
        """
        mode = params["mode"]
        for level in (params["start"], params["stop"]):
            if mode == "voltage":
                self.app.check_source_point(
                    "source", voltage=level, current=params["compliance"])
            else:
                self.app.check_source_point(
                    "source", current=level, voltage=params["compliance"])

    # ---- run: single ----
    def run_pressed(self):
        """Run button: validate, gate, then sweep on a background
        thread."""
        if not self._ready_to_run():
            return
        try:
            params = self._sweep_params()
            self._check_limits(params)
        except ValueError as e:
            messagebox.showerror("Invalid setup", str(e))
            return
        except Exception as e:
            self.log("Refused:", e)
            messagebox.showerror("Outside instrument limits", str(e))
            return

        self.app.run_in_background(
            self.app.guard_run(lambda: self._do_single(params)))

    def run_periodic_pressed(self):
        """Run periodic: the long-bias sequence."""
        if not self._ready_to_run():
            return
        try:
            params = self._sweep_params()
            periodic = self._periodic_params()
            self._check_limits(params)
            if periodic["standby"] == "Bias voltage":
                self.app.check_source_point("source", voltage=periodic["bias"])
            elif periodic["standby"] == "Bias current":
                self.app.check_source_point("source", current=periodic["bias"])
        except ValueError as e:
            messagebox.showerror("Invalid setup", str(e))
            return
        except Exception as e:
            self.log("Refused:", e)
            messagebox.showerror("Outside instrument limits", str(e))
            return

        if not self._confirm_bias_interruption(params, periodic):
            return

        total = self._estimate_total(params, periodic)
        minutes, seconds = divmod(int(total), 60)
        if not messagebox.askokcancel(
                "Start periodic run",
                f"{periodic['cycles']} cycles x {params['repeats']} sweep(s).\n"
                f"Standby: {periodic['standby']}\n\n"
                f"Estimated duration: {minutes} min {seconds} s.\n\n"
                "Start?"):
            self.log("User cancelled periodic run")
            return

        self.app.run_in_background(
            self.app.guard_run(lambda: self._do_periodic(params, periodic)))

    def _ready_to_run(self):
        """Common pre-flight checks shared by both Run buttons."""
        if self.run_in_progress():
            messagebox.showinfo("Already running",
                                "A measurement is already in progress.")
            return False
        if self.refuse_if_sibling_busy():
            return False
        if not self.app.is_connected("source"):
            messagebox.showwarning("Not connected", "Connect the SMU first.")
            return False
        driver = self.app.instruments.get("source")
        if driver is not None and not driver.supports_sweep():
            # Reachable only for an instrument that declares it cannot
            # sweep at all. Every driver gets the software fallback, so
            # this now means "genuinely incapable", not "unimplemented".
            messagebox.showerror(
                "No sweep support",
                f"{driver.DISPLAY_NAME} reports that it cannot run a "
                f"sweep.")
            return False
        if not self._summary_collision_ok():
            return False
        return True

    def _estimate_total(self, params, periodic):
        """Rough total duration of a periodic run, in seconds.

        Same shape as the original's estimate, including its 1.30 fudge
        factor for per-point overhead, plus the 2 s pre-sweep settle.
        """
        per_sweep = 2.0 + params["points"] * params["delay"] * 1.30
        return periodic["cycles"] * (periodic["period"]
                                     + per_sweep * params["repeats"] + 1.0)

    def _confirm_bias_interruption(self, params, periodic):
        """Warn, once, if the bias cannot be held across the boundary.

        Decision W6-3. Holding a device under bias and then sweeping it
        only means what the operator thinks it means while the source
        function stays the same. Sourcing volts for the standby and
        amps for the sweep requires a function change, and the output
        has to come down for it - so the device relaxes before every
        sweep.

        This is allowed rather than refused, because it is a legitimate
        thing to want. It is warned about because the resulting file is
        structurally identical to a continuously biased one, and three
        hours later nothing on screen would say which was which. The
        `bias_gap_s` column is the other half of that: the dialog is
        seen once, the column travels with the data.
        """
        standby = periodic["standby"]
        if standby not in ("Bias voltage", "Bias current"):
            return True
        standby_mode = "voltage" if standby == "Bias voltage" else "current"
        if standby_mode == params["mode"]:
            return True

        quantity = "voltage" if standby_mode == "voltage" else "current"
        swept = "voltage" if params["mode"] == "voltage" else "current"
        return messagebox.askokcancel(
            "Bias cannot be held continuously",
            f"Standby sources {quantity}, but the sweep sources {swept}.\n\n"
            f"Changing the source function needs the output off, so the "
            f"sample will be de-energised briefly at every cycle "
            f"boundary and will relax before each sweep.\n\n"
            f"The measured gap is recorded per sweep in the "
            f"'bias_gap_s' column.\n\n"
            f"Continue?")

    def _enter_run_ui(self):
        """Buttons for a run that has just started. Main thread."""
        self.run_btn.config(state="disabled")
        self.periodic_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

    def _end_run(self):
        """Back to idle. Main thread, and safe to call twice."""
        try:
            self.run_btn.config(state="normal")
            self.periodic_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.set_lamp(False)
            self.progress_var.set("Idle")
            self.eta_var.set("ETA: -")
        except Exception:
            pass

    def stop_pressed(self):
        """Cancel the run in flight: discard its data and de-energise.

        Wave 6, decision W6-1. Previously this set a flag, let the sweep
        in flight finish, and kept it - which made IV the only
        experiment where Stop preserved data. A periodic run can be an
        hour long and losing it hurts, but a rule that holds everywhere
        except one tab is a rule nobody can rely on, and the alternative
        needed a partial-file convention of its own.

        The worker notices at its next checkpoint and de-energises on
        the thread that already owns the session. That is what removed
        the OFF button; see panels/action_panel.py.
        """
        if self.cancel_run("operator pressed Stop"):
            self.progress_var.set("Stopping - discarding this run...")
            self.log("Stop pressed: cancelling, output off, data discarded")

    # ---- the measurement ----
    def _do_single(self, params):
        """One batch of repeats, output down between each. Background
        thread."""
        with self.begin_run(parameters=params) as run:
            run.on_cleanup(lambda: self.app.ui(self._end_run))
            run.enter(self.app.claim_instrument("source", run.run_id))
            smu = self.instrument("source")
            self.app.ui(self._enter_run_ui)

            # Declared up front so the completion gate compares against
            # what was asked for rather than against whatever arrived.
            run.expect(params["repeats"] * params["points"])

            sweeps = []
            try:
                self._prepare(run, smu, params, params["mode"],
                              params["compliance"])
                for index in range(params["repeats"]):
                    label = params["dataset"]
                    if params["repeats"] > 1:
                        label = f"{label} ({index + 1})"

                    run.checkpoint(f"before output on ({label})")
                    self._energise(smu)
                    # PREPARING -> RUNNING on the first output-on: the
                    # sample is live, so from here a cancellation has
                    # something to discard.
                    if index == 0:
                        run.start()
                    sweeps.append(
                        self._one_sweep(run, smu, params, label))
                    self._de_energise(smu)
            finally:
                report = run.confirm_shutdown(smu, log=self.log)
                self.app.ui(self.set_lamp, False)
                if report.uncertain:
                    self.app.report_uncertain_shutdown("source", report)

            self._commit_sweeps(run, sweeps)

    def _do_periodic(self, params, periodic):
        """Bias, sweep, repeat. Background thread.

        The output stays on across the standby-to-sweep boundary when
        the standby function matches the sweep function. That is what
        `alreadyOn` did in the original: dropping the output between
        holding a device under bias and measuring the result would
        discharge what is being measured.

        When the two functions differ the output is deliberately taken
        down for the change and brought back up (decisions W6-3 and
        W6-6). No manual in the suite states whether a source-function
        change drops the output on its own, so the sequence does it
        explicitly rather than depending on an answer nobody has.
        """
        standby = periodic["standby"]
        biased = standby in ("Bias voltage", "Bias current")
        standby_mode = ("voltage" if standby == "Bias voltage"
                        else "current" if standby == "Bias current" else None)
        # Continuous bias is only possible when nothing has to change at
        # the boundary. Recorded per run because it changes what the
        # measurement means, not just how it is sequenced.
        continuous = biased and standby_mode == params["mode"]

        cycles = periodic["cycles"]
        started = time.monotonic()
        total = self._estimate_total(params, periodic)

        with self.begin_run(parameters=params) as run:
            run.on_cleanup(lambda: self.app.ui(self._end_run))
            run.enter(self.app.claim_instrument("source", run.run_id))
            smu = self.instrument("source")
            self.app.ui(self._enter_run_ui)

            run.expect(cycles * params["repeats"] * params["points"])
            run.set_metadata(
                bias_continuous="yes" if continuous else "no",
                standby=standby)
            # Also on params, because each sweep builds its own stored
            # Run and the header has to travel with the data rather
            # than only with the run context.
            params["bias_continuous"] = "yes" if continuous else "no"
            params["standby"] = standby

            sweeps = []
            gaps = []
            try:
                for cycle in range(cycles):
                    run.checkpoint(f"cycle {cycle + 1}")

                    if biased:
                        # On a continuously biased run the output is
                        # still on from the previous cycle, so there is
                        # nothing to configure and nothing to energise -
                        # only the level to re-assert, which every
                        # instrument in the suite applies immediately
                        # while live. Reconfiguring here instead would
                        # break house rule 12 on every cycle after the
                        # first.
                        if continuous and cycle > 0:
                            self._set_bias(smu, standby_mode,
                                           periodic["bias"])
                        else:
                            self._prepare(run, smu, params, standby_mode,
                                          params["compliance"])
                            run.checkpoint(
                                f"before bias on (cycle {cycle + 1})")
                            self._energise(smu)
                            self._set_bias(smu, standby_mode,
                                           periodic["bias"])
                    else:
                        self._de_energise(smu)
                    if cycle == 0:
                        run.start()

                    self._report(f"Cycle {cycle + 1}/{cycles}: "
                                 f"{standby.lower()} for "
                                 f"{periodic['period']:g} s")
                    run.sleep(periodic["period"], stage=f"standby {cycle + 1}")

                    if continuous:
                        # Nothing to reconfigure: the instrument is
                        # already sourcing the swept quantity with this
                        # run's compliance and ranges in place.
                        gap = 0.0
                    else:
                        gap = self._cross_to_sweep(run, smu, params)
                    gaps.append(gap)

                    for index in range(params["repeats"]):
                        if params["repeats"] > 1:
                            label = (f"{params['dataset']} "
                                     f"({cycle + 1}-{index + 1})")
                        else:
                            label = f"{params['dataset']} ({cycle + 1})"
                        sweeps.append(
                            self._one_sweep(run, smu, params, label,
                                            cycle=cycle + 1,
                                            bias_gap_s=gap))

                    if not continuous:
                        self._de_energise(smu)

                    elapsed = time.monotonic() - started
                    remaining = max(0.0, total - elapsed)
                    minutes, seconds = divmod(int(remaining), 60)
                    self.app.ui(self.eta_var.set,
                                f"ETA: {minutes} min {seconds} s")
            finally:
                report = run.confirm_shutdown(smu, log=self.log)
                self.app.ui(self.set_lamp, False)
                self.app.ui(self.eta_var.set, "ETA: -")
                if report.uncertain:
                    self.app.report_uncertain_shutdown("source", report)

            if gaps and not continuous:
                worst = max(gaps)
                self.log(f"Bias interrupted at every cycle boundary; "
                         f"longest gap {worst * 1000:.0f} ms")
            self._commit_sweeps(run, sweeps)

    # ---- the standby/sweep contract ----
    def _prepare(self, run, smu, params, mode, compliance):
        """Put the instrument into the state the next output-on needs.

        House rule 12 (Wave 6, decision W6-7): every configuration
        command precedes the output-on transition, and nothing is
        reconfigured while the sample is energised.

        Before this, `_apply_standby` energised a biased standby with no
        compliance set at all, so the sample was protected by whatever
        the previous sweep left behind - or, on a fresh session, by the
        instrument's reset default. On a B2901A those defaults are
        100 uA and 2 V, which will not damage anything but will quietly
        clamp a bias so the device is never held where the operator
        asked. The run then records the requested bias, not the achieved
        one.
        """
        run.checkpoint("configure")

        # Source function first: on TSP the compliance attribute that
        # matters (limiti vs limitv) depends on what is being sourced,
        # so setting it before the function can land on the wrong one.
        smu.set_source_function(mode)

        # Both compliances belong to whichever function is live, and the
        # other one is not reachable from here. Setting the one that
        # matches `mode` is therefore the whole protection for this
        # output-on.
        # Ranging, all four axes, before the limit (Wave 6d-ii).
        #
        # Range before limit is fault 15 / deviation 21: a compliance is
        # clamped to the range active when it arrives on at least one
        # instrument here, and *RST leaves the smallest range selected.
        # A limit sent first is accepted, silently reduced, and the
        # sweep runs against a compliance far below the one on screen.
        #
        # The source axis is the new part, and it matters more here than
        # anywhere else. Until now this experiment set no source range
        # at all, so a sweep relied on source autoranging - and a sweep
        # is precisely the operation that walks across range boundaries.
        # Each crossing leaves a step in the data where the two segments
        # were sourced with different gain and offset errors, and a
        # straight line fitted across that step absorbs it as slope.
        # Slope is resistance. Fixing the source range to the largest
        # magnitude the sweep will reach removes the crossings.
        # The sourced quantity spans start..stop; the measured one is
        # bounded by the compliance. `for_sourcing` fills in the rest,
        # and in particular refuses to let this set a measurement range
        # for the quantity being sourced.
        span = max(abs(params["start"]), abs(params["stop"]))
        ranges = RangePlan.for_sourcing(mode, source_range=span,
                                        measure_range=compliance)
        params["ranges"] = smu.apply_ranges(ranges, log=self.log)

        if mode == "voltage":
            smu.set_current_limit(compliance)
        else:
            smu.set_voltage_limit(compliance)

        params["sensing"] = apply_remote_sense(
            smu, params["remote_sense"], self.log)
        params["nplc"] = apply_nplc(smu, params.get("nplc"), self.log)
        params["high_z_off"] = apply_high_z(
            smu, params.get("high_z_off"), self.log)

        if params.get("ovp") is not None and smu.supports_ovp():
            smu.set_voltage_protection(params["ovp"])

        # Stamp which mechanism will run the sweeps. Taken from the
        # driver rather than assumed, so a run saved from a 2611A and one
        # saved from a point-by-point instrument are told apart in the
        # file, not just on screen.
        params["sweep_kind"] = smu.sweep_kind()

    def _energise(self, smu):
        """The output-on transition. Configuration is already done."""
        smu.output_on()
        self.app.ui(self.set_lamp, True)

    def _de_energise(self, smu):
        smu.safe_output_off()
        self.app.ui(self.set_lamp, False)

    def _set_bias(self, smu, mode, level):
        """Hold the sample at the standby level."""
        if mode == "voltage":
            smu.set_voltage_level(level)
        else:
            smu.set_current_level(level)

    def _cross_to_sweep(self, run, smu, params):
        """Move from a standby that cannot flow into the sweep.

        Returns the measured length of the interval during which the
        sample was not energised, in seconds. Measured, not estimated:
        on a slow bus the gap is dominated by command turnaround, and a
        number the operator can compare against their device's
        relaxation time is worth more than an assurance that it was
        brief.
        """
        run.checkpoint("bias interrupted for source-function change")
        opened = time.monotonic()
        self._de_energise(smu)
        self._prepare(run, smu, params, params["mode"], params["compliance"])
        run.checkpoint("before output on after function change")
        self._energise(smu)
        return time.monotonic() - opened

    def _commit_sweeps(self, run, sweeps):
        """The single commit gate for the whole run.

        A run commits once or not at all, so every sweep in the sequence
        lands together or none of them does. Stop therefore discards the
        lot, which is the same rule Van der Pauw, Hall and 4PP follow.
        """
        rows = [s for s in sweeps if s is not None]
        if not rows:
            run.record_error("no sweep returned any data")
        run.commit(rows, lambda built: self.app.ui(self._record_sweeps, built))

    def _one_sweep(self, run, smu, params, label, cycle=None,
                   bias_gap_s=None):
        """Sweep, collect, fit. Background thread.

        Configuration and the output-on transition have already
        happened - see `_prepare` and house rule 12. This method never
        reconfigures the instrument, because by the time it is called
        the sample is live.

        Returns the built (row, Run, dataset) triple, or None if the
        sweep returned nothing. Nothing is recorded here: the run
        commits once, at the end, so a cancelled sequence leaves no
        half of itself in the results table.
        """
        mode = params["mode"]
        points = params["points"]

        # The originals slept a flat 2 s here before starting the sweep,
        # to let the source settle at the start level. Kept, but through
        # run.sleep(): it wakes early when cancelled, so Stop during the
        # settle is felt at once instead of after the full two seconds.
        run.sleep(PRE_SWEEP_SETTLE_S, stage=f"settle {label}")

        run.checkpoint(f"before sweep ({label})")
        self._report(f"{label}: sweeping {points} points")
        smu.start_linear_sweep(mode, params["start"], params["stop"],
                               points, params["delay"])
        try:
            collected = self._await_sweep(run, smu, points,
                                          params["delay"], label)
            # The poll loop can exit on its own terms - a complete
            # sweep, a short one, a timeout - so a cancellation that
            # arrived during the last poll would otherwise be noticed
            # only after the buffer had been read out and fitted. §8
            # asks for a checkpoint after every long wait; a sweep is
            # the longest wait this experiment has.
            run.checkpoint(f"before reading {label}")
            sourced, measured = smu.read_sweep(collected)
        finally:
            # Whatever happened - a short sweep, a cancellation, an
            # instrument fault - no worker may be left able to set a
            # source level while the caller tidies up. A False here
            # means one still can, and that is worth saying out loud.
            if not smu.abort_sweep():
                run.record_error(
                    f"{label}: the sweep worker did not stop and may "
                    f"still be driving the source")

        if not measured:
            self.log(f"{label}: no data returned")
            run.record_error(f"{label}: no data returned")
            return None

        # The instrument reports what it actually sourced. If it didn't,
        # fall back to the requested levels so the run isn't lost -
        # this is what the originals always did.        # DEVIATION 4
        if len(sourced) != len(measured):
            step = (params["stop"] - params["start"]) / (points - 1)
            sourced = [params["start"] + step * i for i in range(len(measured))]
            self.log(f"{label}: source values unavailable, "
                     f"x-axis reconstructed from start/stop/points")

        if params["do_fit"]:
            slope, intercept, r_squared, resistance = fit_sweep(
                sourced, measured, mode)
        else:
            # Non-ohmic sample. The raw points are stored exactly as
            # they would be otherwise; only the fitted columns are left
            # empty, so nothing is lost and no meaningless resistance
            # is invented.
            slope = intercept = r_squared = resistance = None

        # A sweep that ran into compliance still yields a tidy straight
        # line with a convincing R-squared - but the instrument was
        # clamping, so the fit describes the limit rather than the
        # sample. Instruments that can't answer return None and say
        # nothing, so this stays silent rather than crying wolf.
        try:
            tripped = smu.compliance_tripped()
        except Exception:
            tripped = None
        if tripped:
            self.log(f"WARNING: {label} hit compliance. The instrument was "
                     f"limiting, so any fitted resistance describes the "
                     f"compliance setting, not the sample.")

        # Readings go onto the run, not into the store. They are
        # provisional until the whole sequence commits.
        run.extend_readings(measured)

        return self._finish_sweep(run, params, label, sourced, measured,
                                  slope, intercept, r_squared, resistance,
                                  cycle, bias_gap_s)

    def _await_sweep(self, run, smu, points, delay_s, label):
        """Wait for the sweep by asking the instrument how many points
        it has, rather than sleeping a guessed duration.

        This is the fix for the original's timing.        # DEVIATION 3

        The originals computed `total_wait = round(points * delay * 1.30)`
        and slept that long. Two problems. `round()` puts the wait on a
        whole-second grid, so a 10-point sweep at 0.1 s delay waited 1 s
        instead of 1.3 s. And `waitcomplete()` was sent with write(),
        never read back, so it never blocked the host - that sleep was
        the *only* thing standing between firing the sweep and reading
        the buffer. Short sweeps could read a partly-filled buffer and
        silently return fewer points than requested.

        Polling the buffer count removes the guess. On a TSP instrument
        the query may not answer until the sweep has finished anyway,
        since commands are processed in order - which is fine, and is
        itself a real completion signal. Either way the loop exits on
        the instrument's own count reaching the requested points.

        The timeout is a backstop against an instrument that stalls, not
        a duration estimate; it is deliberately several times the
        nominal sweep length.
        """
        nominal = points * max(delay_s, 0.0)
        timeout = max(nominal * SWEEP_TIMEOUT_FACTOR, SWEEP_TIMEOUT_FLOOR_S)
        deadline = time.monotonic() + timeout
        interval = min(max(delay_s / 2.0, MIN_POLL_INTERVAL_S),
                       MAX_POLL_INTERVAL_S)

        ready = 0
        while ready < points:
            # Raises RunCancelled, which unwinds to the run's finally
            # block. Breaking out instead would have carried on to read
            # a partial sweep and record it.
            run.checkpoint(f"polling {label}")
            try:
                ready = smu.sweep_points_ready()
            except Exception as e:
                self.log(f"{label}: buffer poll failed ({e})")
                break

            self._report(f"{label}: {ready}/{points} points")

            if ready >= points:
                break
            if time.monotonic() > deadline:
                self.log(f"{label}: timed out with {ready}/{points} points "
                         f"after {timeout:.0f} s")
                run.record_error(f"{label}: sweep timed out with "
                                 f"{ready}/{points} points")
                break
            run.sleep(interval, stage=f"polling {label}")

        return max(ready, 0)

    def _finish_sweep(self, run, params, label, sourced, measured,
                      slope, intercept, r_squared, resistance, cycle,
                      bias_gap_s=None):
        """Build the run row and its plot dataset and return them.

        Returns rather than posting to the UI: what the sequence has
        built so far is provisional until the run commits, and a
        cancelled sequence must leave nothing behind.
        """
        mode = params["mode"]
        timestamp = datetime.datetime.now().isoformat()
        meas_num = self.app.take_meas_number()

        if mode == "voltage":
            source_key, measure_key = "voltage_V", "current_A"
        else:
            source_key, measure_key = "current_A", "voltage_V"

        readings = []
        for index, (source_value, measured_value) in enumerate(
                zip(sourced, measured), start=1):
            readings.append({
                "point": index,
                "timestamp": timestamp,
                source_key: source_value,
                measure_key: measured_value,
            })

        sample = params["sample"]
        record = Run(
            sample=sample.slug,
            metadata={
                "meas_number": meas_num,
                # Identity, added in Wave 7b-i, matching what Van der
                # Pauw, Hall and 4PP already record. `run_id` is the
                # *lifecycle* run: one periodic run produces several of
                # these records and they all share it, which is what
                # lets the event log in 7d join them back together.
                # `record_id` - minted by `Run` itself - is what
                # identifies this row.
                "sample_id": sample.sample_id,
                "sample_label": sample.label,
                "run_id": run.run_id,
                "dataset": label,
                "mode": f"source_{mode}",
                "start": params["start"],
                "stop": params["stop"],
                "points_requested": params["points"],
                "points_returned": len(measured),
                "delay_s": params["delay"],
                "compliance": params["compliance"],
                "sensing": params.get(
                    "sensing",
                    "4-wire" if params["remote_sense"] else "2-wire"),
                # Integration time belongs with the data, not in a
                # note: two sweeps of the same sample at 0.01 and 10
                # NPLC have visibly different scatter, and without this
                # column that difference looks like the sample changed.
                "nplc": params.get("nplc") if params.get("nplc") is not None
                        else "",
                "ovp": params.get("ovp") or "",
                "output_off_mode":
                    ("high-Z" if params.get("high_z_off")
                     else ("normal" if params.get("high_z_off") is not None
                           else "")),
                "sweep_kind": params.get("sweep_kind", ""),
                "fitted": "yes" if params["do_fit"] else "no",
                "cycle": cycle if cycle is not None else "",
                "standby": params.get("standby", ""),
                "bias_continuous": params.get("bias_continuous", ""),
                # Blank on a single run and on a continuously biased
                # cycle; a number of seconds when the bias had to be
                # interrupted so the source function could change. A
                # file where this column is populated describes a device
                # that relaxed before every sweep.
                "bias_gap_s": (f"{bias_gap_s:.3f}"
                               if bias_gap_s else ""),
                "fit_slope": slope if slope is not None else "",
                "fit_intercept": intercept if intercept is not None else "",
                "fit_r_squared": r_squared if r_squared is not None else "",
                "resistance_ohm": resistance if resistance is not None else "",
                "stage_temp_C": self._stage_temperature() or "",
            },
            readings=readings,
        )

        row = (
            label,
            "V→I" if mode == "voltage" else "I→V",
            f"{params['start']:g} → {params['stop']:g}",
            str(len(measured)),
            f"{resistance:.6g}" if resistance is not None else "-",
            f"{r_squared:.5f}" if r_squared is not None else "-",
        )

        dataset = {
            "label": label,
            "x": list(sourced),
            "y": list(measured),
            "fit": (slope, intercept, r_squared)
            if slope is not None else None,
            "resistance": resistance,
        }

        self._calculated = {
            "last_dataset": label,
            "mode": f"source_{mode}",
            "resistance_ohm": f"{resistance:.9g}" if resistance is not None else "",
            "fit_slope": f"{slope:.9g}" if slope is not None else "",
            "fit_intercept": f"{intercept:.9g}" if intercept is not None else "",
            "fit_r_squared": f"{r_squared:.9g}" if r_squared is not None else "",
        }

        if resistance is not None:
            self.log(f"{label}: R = {resistance:.6g} Ω, R² = {r_squared:.5f}, "
                     f"{len(measured)} points")
        else:
            self.log(f"{label}: {len(measured)} points, fit unavailable")

        return (row, record, dataset)

    def _report(self, text):
        """Update the progress line from a background thread."""
        self.app.ui(self.progress_var.set, text)

    def _stage_temperature(self):
        """Current stage temperature, or None. Recorded per run because
        an IV curve depends on it."""
        if not self.temp_ctrl.is_connected():
            return None
        status = self.temp_ctrl.status()
        if status.is_stale or status.fault or status.temp_c is None:
            return None
        return round(status.temp_c, 1)

    # ---- results table and plot ----
    def _record_sweeps(self, built):
        """Add every committed sweep to the table, the store and the
        plot - all keyed on the same Treeview item id, so they can't
        drift.

        Called once per run, from the commit gate, on the UI thread.
        """
        for row, record, dataset in built:
            item = self.tree.insert("", "end", text="☐", values=row)
            self.run_store.add(item, record)
            self._datasets[item] = dataset
        self.refresh_plot()

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
        """Draw the ticked rows. The house 'copy ticked' action, in the
        form that makes sense here."""
        if not self.ticked_items():
            messagebox.showinfo("Nothing ticked",
                                "Tick the sweeps you want on the plot.")
            return
        self.refresh_plot()

    def refresh_plot(self):
        """Redraw the axes from the ticked rows. Main thread only."""
        if not hasattr(self, "plot_ax"):
            return

        # Ticked rows are what gets plotted. With nothing ticked the most
        # recent sweep is shown anyway - a run that finished and left the
        # axes empty looks like a failure, and the original always drew
        # the newest curve. Ticking is therefore a way to *narrow* the
        # plot, not a precondition for seeing anything.
        if hasattr(self, "tree"):
            ticked = [i for i in self.ticked_items() if i in self._datasets]
            if not ticked:
                rows = [i for i in self.tree.get_children()
                        if i in self._datasets]
                ticked = rows[-1:]
            datasets = [self._datasets[i] for i in ticked]
            if not self.plot_overlap_var.get() and datasets:
                datasets = datasets[-1:]
        else:
            datasets = []

        mode = self.mode_var.get()
        if mode == "voltage":
            xlabel, ylabel = "Voltage [V]", "Current [A]"
        else:
            xlabel, ylabel = "Current [A]", "Voltage [V]"

        draw_datasets(self, datasets, xlabel=xlabel, ylabel=ylabel,
                      show_fit=True)

    def delete_ticked(self):
        """Inherited behaviour, plus dropping the curves from the plot."""
        ticked = list(self.ticked_items())
        super().delete_ticked()
        # Only the rows that actually went away are gone from the tree.
        remaining = set(self.tree.get_children())
        for item in ticked:
            if item not in remaining:
                self._datasets.pop(item, None)
        self.refresh_plot()

    def clear_output(self):
        """Inherited behaviour, plus clearing the plot."""
        super().clear_output()
        if not self.tree.get_children():
            self._datasets.clear()
        self.refresh_plot()

    def calculated_fields(self):
        """The most recent fit, for the saved CSV header.

        Per-sweep fits also travel in each run's metadata, so the header
        is a convenience rather than the only copy - a file with twelve
        sweeps in it has twelve resistances in its table columns.
        """
        return dict(self._calculated)

    def set_lamp(self, on):
        """Colour the output indicator."""
        self.lamp_canvas.itemconfig(self.lamp_id, fill="green" if on else "gray")

    # `on_close()` is inherited. It cancelled the run in flight and
    # nothing else, which is now what `Experiment.on_close()` does for
    # every experiment - see the note there about the tab that had no
    # override at all.
