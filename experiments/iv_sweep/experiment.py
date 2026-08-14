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
HANDOFF.md. The significant one is step 4.
"""
import datetime
import time
from tkinter import messagebox

from experiments.base_experiment import Experiment
from core.limits import parse_si
from core.gui.widgets import (refresh_nplc, parse_nplc, apply_nplc,
                              refresh_high_z, apply_high_z,
                              refresh_remote_sense, apply_remote_sense)
from core.run_store import Run
from core.gui.plot_panel import build_plot_panel, draw_datasets

from .iv_math import fit_sweep
from .panels.mode_panel import build_mode_panel
from .panels.setup_panel import build_setup_panel
from .panels.periodic_panel import build_periodic_panel
from .panels.action_panel import build_action_panel
from .panels.results_panel import build_results_panel

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
        self.measuring = False
        self._stop_requested = False
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
        if self.measuring:
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
            raise ValueError("Start and stop must be numbers.")

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
            raise ValueError("Points must be a whole number.")
        if points < 2:
            raise ValueError("A sweep needs at least 2 points.")

        try:
            delay = float(self.delay_var.get())
        except Exception:
            raise ValueError("Delay must be a number.")
        if delay < 0:
            raise ValueError("Delay cannot be negative.")

        try:
            repeats = int(float(self.runs_var.get()))
        except Exception:
            raise ValueError("Repeats must be a whole number.")
        if repeats < 1:
            raise ValueError("Repeats must be at least 1.")

        try:
            compliance = float(parse_si(self.compliance_var.get()))
        except Exception:
            raise ValueError("Compliance must be a number.")
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
            raise ValueError("Cycles must be a whole number.")
        if cycles < 1:
            raise ValueError("Cycles must be at least 1.")

        try:
            period = float(self.period_var.get())
        except Exception:
            raise ValueError("Cycle period must be a number.")
        if period < 0:
            raise ValueError("Cycle period cannot be negative.")

        standby = self.standby_var.get()
        bias = 0.0
        if standby in ("Bias voltage", "Bias current"):
            try:
                bias = float(parse_si(self.bias_var.get()))
            except Exception:
                raise ValueError("Bias level must be a number.")

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

        self._begin_run()
        self.app.run_in_background(
            self.app.guard_run(lambda: self._do_single(params)),
            on_error=lambda e: self._end_run())

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

        self._begin_run()
        self.app.run_in_background(
            self.app.guard_run(lambda: self._do_periodic(params, periodic)),
            on_error=lambda e: self._end_run())

    def _ready_to_run(self):
        """Common pre-flight checks shared by both Run buttons."""
        if self.measuring:
            messagebox.showinfo("Already running",
                                "A measurement is already in progress.")
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

    def _begin_run(self):
        """Flip the UI into measuring state. Main thread."""
        self.measuring = True
        self._stop_requested = False
        self.run_btn.config(state="disabled")
        self.periodic_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.off_btn.config(state="normal")

    def _end_run(self):
        """Flip the UI back. Safe to call twice."""
        self.measuring = False
        self._stop_requested = False
        try:
            self.run_btn.config(state="normal")
            self.periodic_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.off_btn.config(state="disabled")
            self.set_lamp(False)
            self.progress_var.set("Idle")
        except Exception:
            pass

    def stop_pressed(self):
        """Ask the running sequence to stop at the next safe point.

        A flag rather than a thread kill: the sweep in flight is allowed
        to finish and be recorded, and the output is brought down in the
        normal finally-block path. Killing the thread mid-sweep would
        leave the SMU sourcing.
        """
        if not self.measuring:
            return
        self._stop_requested = True
        self.progress_var.set("Stopping after this sweep...")
        self.log("Stop requested")

    def off_pressed(self):
        """OFF button: drop the output now."""
        def task():
            self._stop_requested = True
            driver = self.app.instruments.get("source")
            if driver is not None:
                driver.abort_sweep()
                driver.safe_output_off()
            self.log("Output OFF")
            self.app.ui(self.set_lamp, False)
        self.app.run_in_background(self.app.guard_run(task))

    # ---- the measurement ----
    def _do_single(self, params):
        """One batch of repeats, output down between each. Background
        thread."""
        smu = self.instrument("source")
        try:
            for index in range(params["repeats"]):
                if self._stop_requested:
                    self.log("Stopped before sweep "
                             f"{index + 1}/{params['repeats']}")
                    break
                label = params["dataset"]
                if params["repeats"] > 1:
                    label = f"{label} ({index + 1})"
                self._one_sweep(smu, params, label, hold_output=False)
        finally:
            smu.safe_output_off()
            self.log("Output OFF")
            self.app.ui(self._end_run)

    def _do_periodic(self, params, periodic):
        """Bias, sweep, repeat. Background thread.

        The output stays on across the standby-to-sweep boundary in the
        two biased modes. That is what `alreadyOn` did in the original:
        dropping the output between holding a device under bias and
        measuring the result would discharge what is being measured.
        """
        smu = self.instrument("source")
        cycles = periodic["cycles"]
        started = time.monotonic()
        total = self._estimate_total(params, periodic)

        try:
            for cycle in range(cycles):
                if self._stop_requested:
                    self.log(f"Stopped before cycle {cycle + 1}/{cycles}")
                    break

                self._apply_standby(smu, periodic)
                self._report(f"Cycle {cycle + 1}/{cycles}: "
                             f"{periodic['standby'].lower()} for "
                             f"{periodic['period']:g} s")
                if not self._interruptible_sleep(periodic["period"]):
                    break

                # In the two biased modes the output is already on and
                # must stay on across the boundary - that is exactly what
                # `alreadyOn` did in the original. After 'Remain idle' it
                # is off, and _one_sweep turns it on itself.
                hold = periodic["standby"] in ("Bias voltage", "Bias current")

                for index in range(params["repeats"]):
                    if self._stop_requested:
                        break
                    if params["repeats"] > 1:
                        label = f"{params['dataset']} ({cycle + 1}-{index + 1})"
                    else:
                        label = f"{params['dataset']} ({cycle + 1})"
                    self._one_sweep(smu, params, label, hold_output=hold,
                                    cycle=cycle + 1)

                elapsed = time.monotonic() - started
                remaining = max(0.0, total - elapsed)
                minutes, seconds = divmod(int(remaining), 60)
                self.app.ui(self.eta_var.set,
                            f"ETA: {minutes} min {seconds} s")
        finally:
            smu.safe_output_off()
            self.log("Output OFF")
            self.app.ui(self.eta_var.set, "ETA: -")
            self.app.ui(self._end_run)

    def _apply_standby(self, smu, periodic):
        """Put the instrument into its between-sweeps state."""
        standby = periodic["standby"]
        if standby == "Bias voltage":
            smu.set_source_function("voltage")
            smu.set_voltage_level(periodic["bias"])
            smu.output_on()
            self.app.ui(self.set_lamp, True)
        elif standby == "Bias current":
            smu.set_source_function("current")
            smu.set_current_level(periodic["bias"])
            smu.output_on()
            self.app.ui(self.set_lamp, True)
        else:
            smu.safe_output_off()
            self.app.ui(self.set_lamp, False)

    def _one_sweep(self, smu, params, label, hold_output, cycle=None):
        """Configure, sweep, collect, fit, record. Background thread."""
        mode = params["mode"]
        points = params["points"]

        # --- configure ---
        # Source function first: on TSP the compliance attribute that
        # matters (limiti vs limitv) depends on what is being sourced,
        # so setting it before the function can land on the wrong one.
        smu.set_source_function(mode)
        if mode == "voltage":
            smu.set_current_limit(params["compliance"])
            smu.set_current_range(params["compliance"])
        else:
            smu.set_voltage_limit(params["compliance"])
            smu.set_voltage_range(params["compliance"])

        # Set every sweep, not once at connect: the originals left this
        # to whatever ran last, so the same sample could read differently
        # depending on history. See mode_panel.py, deviation 5.
        # Returns the description that belongs in the file: "4-wire",
        # "2-wire", or the fixed wiring on an instrument where software
        # cannot choose. The checkbox is not the measurement.
        params["sensing"] = apply_remote_sense(
            smu, params["remote_sense"], self.log)

        # Optional controls, applied on the same every-sweep principle
        # and for the same reason. Guarded by the driver's own
        # capability declaration rather than by model, so an instrument
        # added later that has one and not the other still works.
        params["nplc"] = apply_nplc(smu, params.get("nplc"), self.log)
        params["high_z_off"] = apply_high_z(
            smu, params.get("high_z_off"), self.log)

        if params.get("ovp") is not None and smu.supports_ovp():
            smu.set_voltage_protection(params["ovp"])

        if not hold_output:
            smu.output_on()
            self.app.ui(self.set_lamp, True)

        # The originals slept a flat 2 s here before starting the sweep,
        # to let the source settle at the start level. Kept.
        time.sleep(PRE_SWEEP_SETTLE_S)

        # Stamp which mechanism actually ran this sweep. Taken from the
        # driver rather than assumed, so a run saved from a 2611A and
        # one saved from a point-by-point instrument are told apart in
        # the file, not just on screen.
        params["sweep_kind"] = smu.sweep_kind()

        self._report(f"{label}: sweeping {points} points")
        smu.start_linear_sweep(mode, params["start"], params["stop"],
                               points, params["delay"])

        collected = self._await_sweep(smu, points, params["delay"], label)
        sourced, measured = smu.read_sweep(collected)

        if not hold_output:
            smu.output_off()
            self.app.ui(self.set_lamp, False)

        if not measured:
            self.log(f"{label}: no data returned")
            return

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

        self._finish_sweep(params, label, sourced, measured,
                           slope, intercept, r_squared, resistance, cycle)

    def _await_sweep(self, smu, points, delay_s, label):
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
            if self._stop_requested:
                self.log(f"{label}: stop requested during sweep")
                break
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
                break
            time.sleep(interval)

        return max(ready, 0)

    def _finish_sweep(self, params, label, sourced, measured,
                      slope, intercept, r_squared, resistance, cycle):
        """Build the run and its plot dataset, then hand both to the UI
        thread."""
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

        run = Run(
            sample=self.current_sample_name(),
            metadata={
                "meas_number": meas_num,
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

        self.app.ui(self._record_run, row, run, dataset)

    def _interruptible_sleep(self, seconds):
        """Sleep in short slices so Stop is responsive during a long
        standby period. Returns False if a stop was requested."""
        deadline = time.monotonic() + max(seconds, 0.0)
        while time.monotonic() < deadline:
            if self._stop_requested:
                return False
            time.sleep(min(0.2, max(deadline - time.monotonic(), 0.0)))
        return not self._stop_requested

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
    def _record_run(self, row, run, dataset):
        """Add a finished sweep to the table, the store and the plot -
        all keyed on the same Treeview item id, so they can't drift."""
        item = self.tree.insert("", "end", text="☐", values=row)
        self.run_store.add(item, run)
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

    def on_close(self):
        """Stop measuring before the app tears connections down."""
        self._stop_requested = True
        self.measuring = False
