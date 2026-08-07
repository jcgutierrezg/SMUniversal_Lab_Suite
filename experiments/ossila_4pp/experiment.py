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

from core.gui.plot_panel import build_plot_panel, draw_datasets
from core.limits import parse_si
from core.run_store import Run
from experiments.base_experiment import Experiment

from . import fourpp_math as maths
from .panels.geometry_panel import build_geometry_panel
from .panels.sweep_panel import build_sweep_panel, MAX_CURRENTS
from .panels.action_panel import build_action_panel
from .panels.results_panel import build_results_panel
from .panels.calculation_panel import build_calculation_panel


class Ossila4PPExperiment(Experiment):
    NAME = "Ossila 4-point probe - sheet resistance"

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
        self.measuring = False
        self._stop_requested = False
        # Keyed by tree item id, not a flat list, so the plot can be
        # filtered by what is ticked - the same shape the IV sweep uses.
        self._datasets = {}
        self._calculated = {}
        # item id -> full-precision fitted resistance. The tree stores a
        # rounded string for display; this keeps the real number.
        self._run_resistance = {}

    # ---- driver-aware setup ----
    def on_connected(self, role, driver):
        self.log(f"Ranges loaded from {driver.DISPLAY_NAME}")

    def on_sweep_mode_changed(self):
        """Swap which mode-specific block is visible.

        Refused mid-run for the same reason the IV sweep refuses a mode
        change: the shape of what is being sourced must not change while
        the output is live.
        """
        if self.measuring:
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
        """Read and validate the form. Raises ValueError for a dialog."""
        mode = params_mode = self.sweep_mode_var.get()

        if mode == "triangular":
            try:
                start = float(parse_si(self.tri_start_var.get()))
                stop = float(parse_si(self.tri_stop_var.get()))
            except Exception:
                raise ValueError("Start and stop currents must be numbers.")
            try:
                points = int(float(self.tri_points_var.get()))
            except Exception:
                raise ValueError("Points must be a whole number.")
            if points < 2:
                raise ValueError("A sweep needs at least 2 points.")
            if points > MAX_CURRENTS:
                raise ValueError(
                    f"{points} points requested; the maximum is "
                    f"{MAX_CURRENTS}.")
            if start >= 0 or stop <= 0:
                raise ValueError(
                    "A triangular sweep runs from a negative start current "
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
                try:
                    currents.append(float(parse_si(text)))
                except Exception:
                    raise ValueError(
                        f"Current I{index} ({text!r}) is not a number.")
            if len(currents) < 2:
                raise ValueError(
                    "Enter at least two currents to fit a resistance.")
            if len(set(currents)) < 2:
                raise ValueError("The currents must not all be the same.")
            middle_start, middle_len = 0, len(currents)

        # The ceiling applies to what was asked for, not to the expanded
        # list. A triangular sweep of 21 middle points generates about
        # 41 levels once its approach and return legs are added, and
        # rejecting that would make the limit mean something different
        # in each mode.
        #
        # The original's limit guarded the length of the TSP list-sweep
        # string it built. Sourcing point by point, that constraint is
        # gone; what is left is a sanity bound on run length, since each
        # point costs `reversals` readings.
        if params_mode == "list" and len(currents) > MAX_CURRENTS:
            raise ValueError(
                f"{len(currents)} currents entered; the maximum is "
                f"{MAX_CURRENTS}.")

        try:
            delay = float(self.delay_var.get())
        except Exception:
            raise ValueError("Delay must be a number.")
        if delay < 0:
            raise ValueError("Delay cannot be negative.")

        try:
            reversals = int(float(self.reversals_var.get()))
        except Exception:
            raise ValueError("Reversals must be a whole number.")
        if reversals < 1:
            raise ValueError("Reversals must be at least 1.")
        if reversals > 1 and reversals % 2:
            raise ValueError(
                "Reversals must be even, so that each polarity is measured "
                "the same number of times.\n\n"
                "An odd count weights the average towards whichever "
                "polarity came first, which defeats the cancellation.")

        try:
            compliance = float(parse_si(self.compliance_var.get()))
        except Exception:
            raise ValueError("Voltage limit must be a number.")
        if compliance <= 0:
            raise ValueError("Voltage limit must be positive.")

        # Snapshot the geometry here, with the rest of the form, rather
        # than reading it again when the run finishes.
        #
        # _finish_run() used to re-read the entry boxes after the sweep.
        # Anything typed into W, L or t while the measurement ran would
        # be picked up instead - and if a box was mid-edit or empty, the
        # validation raised and the completed run was discarded with it.
        # The numbers that describe the sample must be the ones that
        # were true when it was measured.
        geometry = self._geometry_params()

        return {
            "mode": mode,
            "geometry": geometry,
            "currents": currents,
            "middle_start": middle_start,
            "middle_len": middle_len,
            "delay": delay,
            "reversals": reversals,
            "compliance": compliance,
            "dataset": (self.dataset_var.get() or "run").strip(),
        }

    def _geometry_params(self):
        """Read and validate the sample dimensions. Raises ValueError."""
        try:
            width = float(self.width_var.get())
            length = float(self.length_var.get())
            thickness = float(self.thickness_var.get())
        except Exception:
            raise ValueError("W, L and t must be numbers.")

        if width <= 0 or length <= 0 or thickness <= 0:
            raise ValueError("W, L and t must all be greater than zero.")
        if length < width:
            raise ValueError(
                f"L ({length:g} mm) is shorter than W ({width:g} mm).\n\n"
                f"W is the short side and L the long side - see the "
                f"diagram. The geometry correction is indexed by L/W and "
                f"is wrong if they are swapped.")
        return {"width": width, "length": length, "thickness": thickness}

    def _check_limits(self, params):
        """Check every current in the list against the instrument."""
        for current in params["currents"]:
            self.app.check_source_point(
                "source", current=current, voltage=params["compliance"])

    # ---- run ----
    def run_pressed(self):
        if not self._ready_to_run():
            return
        try:
            params = self._sweep_params()
            self._geometry_params()      # validate now, use after the run
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
            self.app.guard_run(lambda: self._do_run(params)),
            on_error=lambda e: self._end_run())

    def _ready_to_run(self):
        if self.measuring:
            return False
        if self.app.instruments.get("source") is None:
            messagebox.showerror(
                "Not connected", "Connect the source SMU first.")
            return False
        return True

    def _begin_run(self):
        self.measuring = True
        self._stop_requested = False
        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.off_btn.config(state="normal")

    def _end_run(self):
        self.measuring = False
        self._stop_requested = False
        try:
            self.run_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.off_btn.config(state="disabled")
            self.set_lamp(False)
            self.progress_var.set("Idle")
        except Exception:
            pass

    def stop_pressed(self):
        if not self.measuring:
            return
        self._stop_requested = True
        self.progress_var.set("Stopping after this point...")
        self.log("Stop requested")

    def off_pressed(self):
        def task():
            self._stop_requested = True
            driver = self.app.instruments.get("source")
            if driver is not None:
                driver.safe_output_off()
            self.log("Output OFF")
            self.app.ui(self.set_lamp, False)
        self.app.run_in_background(self.app.guard_run(task))

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
        """
        smu = self.instrument("source")
        label = params["dataset"]

        try:
            smu.set_source_function("current")
            smu.set_voltage_limit(params["compliance"])
            smu.set_voltage_range(params["compliance"])
            smu.set_current_range(max(abs(c) for c in params["currents"]))
            smu.set_source_delay(params["delay"])
            smu.set_remote_sense(True)     # a 4PP head is 4-wire by definition

            smu.set_current_level(0.0)
            smu.output_on()
            self.app.ui(self.set_lamp, True)

            currents, voltages, offsets = [], [], []
            total = len(params["currents"])

            for index, current in enumerate(params["currents"], start=1):
                if self._stop_requested:
                    self._report(f"{label}: stopped after {index - 1} points")
                    break

                self.app.ui(self.progress_var.set,
                            f"Point {index}/{total}: {current:.3g} A")
                voltage, offset = self._measure_current(
                    smu, current, params["reversals"], params["delay"])
                if voltage is None:
                    self._report(f"{label}: no reading at {current:.3g} A")
                    continue

                currents.append(current)
                voltages.append(voltage)
                offsets.append(offset)
        finally:
            # Always bring the source down, whatever went wrong.
            try:
                smu.set_current_level(0.0)
                smu.output_off()
            except Exception:
                pass
            self.app.ui(self.set_lamp, False)

        if len(currents) < 2:
            self._report(f"{label}: not enough points to fit")
            self.app.ui(self._end_run)
            return

        # Triangular runs record only the middle leg - the outer legs
        # exist to bring the sample to the start current and back to
        # zero, not to be measured. In list mode this is the whole set.
        if params["mode"] == "triangular":
            start = params["middle_start"]
            stop = start + params["middle_len"]
            fit_currents = currents[start:stop]
            fit_voltages = voltages[start:stop]
            if len(fit_currents) < 2:      # a stop landed inside the first leg
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
                    f"{max(point_r):.4g} Ω) - check for self-heating or "
                    f"non-ohmic contacts before trusting the fit")

        worst_offset = max((abs(o) for o in offsets), default=0.0)
        if params["reversals"] > 1 and worst_offset > 0:
            self._report(
                f"{label}: largest cancelled offset "
                f"{worst_offset:.3g} V")

        self._finish_run(params, label, currents, voltages, offsets,
                         fit_currents, fit_voltages,
                         slope, intercept, r_squared)

    def _measure_current(self, smu, current, reversals, delay):
        """One current, with polarity reversal averaging.

        Returns (voltage, offset). The offset is the common-mode part
        that cancelled out - reported because a large one usually means
        a warm or poorly seated probe, which is worth knowing before
        trusting the sheet resistance.
        """
        readings = []
        for level in maths.reversal_pattern(current, reversals):
            if self._stop_requested:
                break
            smu.set_current_level(level)
            volts, _amps = smu.measure()
            if volts is not None:
                readings.append(volts)

        if not readings:
            return None, 0.0
        if reversals == 1:
            return readings[0], 0.0
        return maths.average_reversals(readings)

    def _finish_run(self, params, label, currents, voltages, offsets,
                    fit_currents, fit_voltages,
                    slope, intercept, r_squared):
        """Build the run record and hand it to the UI thread."""
        timestamp = datetime.datetime.now().isoformat()
        meas_num = self.app.take_meas_number()
        geometry = params["geometry"]

        derived = maths.sheet_resistance(
            slope, geometry["width"], geometry["length"],
            geometry["thickness"])

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

        run = Run(
            sample=self.current_sample_name(),
            metadata={
                "meas_number": meas_num,
                "dataset": label,
                "sweep_mode": params["mode"],
                "points": len(currents),
                "points_fitted": len(fit_currents),
                "reversals": params["reversals"],
                "delay_s": params["delay"],
                "voltage_limit_V": params["compliance"],
                "probe_spacing_mm": maths.PROBE_SPACING_MM,
                "width_mm": geometry["width"],
                "length_mm": geometry["length"],
                "thickness_um": geometry["thickness"],
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

        self.app.ui(self._record_run, run, params, label, slope, r_squared,
                    derived, fit_currents, fit_voltages, intercept)

    def _record_run(self, run, params, label, slope, r_squared, derived,
                    fit_currents, fit_voltages, intercept):
        """Insert the row, store the run, refresh the plot. Main thread."""
        item = self.tree.insert(
            "", "end", text="☐",
            values=(label,
                    "triangular" if params["mode"] == "triangular" else "list",
                    len(run.readings),
                    f"{slope:.6g}",
                    f"{r_squared:.5f}",
                    f"{derived['sheet_resistance_ohm_sq']:.6g}"))
        self.run_store.add(item, run)
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
        self._end_run()

    # ---- calculation ----
    def calculate(self):
        """Recompute the derived quantities from the resistance box.

        Separate from the run so a resistance measured earlier - or one
        typed in by hand from another instrument - can be pushed through
        the same corrections after the geometry is corrected.
        """
        try:
            resistance = float(parse_si(self.calc_r_var.get()))
        except Exception:
            messagebox.showerror(
                "Invalid input", "Measured R must be a number.")
            return

        try:
            geometry = self._geometry_params()
        except ValueError as e:
            messagebox.showerror("Invalid geometry", str(e))
            return

        try:
            derived = maths.sheet_resistance(
                resistance, geometry["width"], geometry["length"],
                geometry["thickness"])
        except ValueError as e:
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
        self.calc_note_var.set(" ".join(derived["notes"]))

        self._calculated = {
            "Measured R (ohm)": resistance,
            "W (mm)": geometry["width"],
            "L (mm)": geometry["length"],
            "t (um)": geometry["thickness"],
            "Probe spacing (mm)": maths.PROBE_SPACING_MM,
            "Thickness factor": derived["thickness_factor"],
            "Geometry factor": derived["geometry_factor"],
            "Sheet resistance (ohm/sq)":
                derived["sheet_resistance_ohm_sq"],
            "Resistivity (ohm.m)": derived["resistivity_ohm_m"],
            "Conductivity (S/m)": derived["conductivity_S_per_m"],
        }
        for note in derived["notes"]:
            self.log(note)

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
        for var in self.result_vars.values():
            var.set("-")
        self.calc_note_var.set("")
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
        """Extra block written into the CSV header by save_runs()."""
        return self._calculated
