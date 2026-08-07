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
import datetime
import os
import time
import tkinter as tk
from tkinter import messagebox, filedialog

from experiments.base_experiment import Experiment
from core.limits import format_amps, parse_si
from core.gui.corner_diagram import paint_corner_roles
from core.gui.temp_panel import build_temp_panel
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

    ROLES = {"source": "SMU"}

    CSV_SLUG = "hall"
    CSV_TITLE = "Hall effect - carrier density and mobility"

    PANELS = [
        build_diagram_panel,
        build_positions_panel,
        build_setup_panel,
        build_temp_panel,
        build_action_panel,
        build_results_panel,
        build_calc_panel,
    ]

    def __init__(self, app):
        super().__init__(app)
        self.thickness_um = 1.0
        self.measuring = False
        # Where the sheet resistance came from, if it was loaded rather
        # than typed. Recorded in saved files so a Hall result can be
        # traced back to the Van der Pauw run behind it.
        self.rs_source_path = None
        # Last successful calculation, embedded in the CSV header on save.
        self._calculated = {}

    def on_panels_built(self):
        """Paint the corner diagram for the starting position, once the
        canvas exists."""
        self.on_pos_changed()

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
    def run_pressed(self):
        """Run button: confirm the bench setup, validate, then measure
        both current polarities on a background thread."""
        if not self.app.is_connected("source"):
            messagebox.showwarning("Not connected", "Connect the SMU first.")
            return

        pos = int(self.pos_var.get())
        b_pol = self.field_sign_var.get()
        if not messagebox.askokcancel(
                "Confirm setup",
                f"Set the switch box to position {pos} "
                f"and the magnet to B polarity {b_pol}.\n\nClick OK to start."):
            self.log("User cancelled run")
            return

        try:
            points = int(self.points_var.get())
            if points <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid points", "Points must be a positive integer.")
            return

        delay_s = self.parse_delay()
        level = self.get_level_amps()
        vlim = self.get_vlim_volts()

        # The hard gate: refuse before anything is sourced. This matters
        # more here than in Van der Pauw, because the level box is
        # free-form - it is the only check on a mistyped level.
        try:
            self.app.check_source_point("source", current=level, voltage=vlim)
        except Exception as e:
            self.log("Refused:", e)
            messagebox.showerror("Outside instrument limits", str(e))
            return

        self.app.run_in_background(
            self.app.guard_run(
                lambda: self._do_run(pos, b_pol, points, level, vlim, delay_s))
        )

    def _do_run(self, pos, b_pol, points, level, vlim, delay_s):
        """The measurement proper. Runs off the main thread."""
        smu = self.instrument("source")
        self.measuring = True
        try:
            smu.set_source_function("current")
            smu.set_current_range(None)             # auto
            smu.set_voltage_range(self.get_voltage_range())
            smu.set_remote_sense(True)
            smu.set_voltage_limit(vlim)
            smu.set_source_delay(delay_s)
            # Applied every run rather than once at connect, for the
            # same reason as remote sense: otherwise the instrument
            # keeps whatever the last experiment left it in, and the
            # same sample reads differently depending on history.
            nplc = apply_nplc(smu, parse_nplc(self.nplc_var), self.log)
            self._applied_nplc = nplc
            high_z = apply_high_z(smu, self.high_z_var.get(), self.log)
            self._applied_high_z = high_z

            smu.output_on()
            self.log("Output ON")
            self.app.ui(self.set_lamp, True)
            self.app.ui(self.off_btn.config, state="normal")

            v_plus, i_plus, pos_raw = self._measure_polarity(
                smu, +1, points, level, delay_s)
            v_minus, i_minus, neg_raw = self._measure_polarity(
                smu, -1, points, level, delay_s)

            sample = (self.sample_name_var.get() or "sample").strip().replace(" ", "_")
            current_shown = abs(i_plus) if i_plus is not None else abs(level)

            meas_num = self.app.take_meas_number()
            row = (
                sample,
                f"Pos{pos}",
                b_pol,
                f"{current_shown:.6g}",
                f"{v_plus:.{VOLTAGE_FIGURES}g}" if v_plus is not None else "-",
                f"{v_minus:.{VOLTAGE_FIGURES}g}" if v_minus is not None else "-",
            )

            run = Run(
                sample=sample,
                metadata={
                    "meas_number": meas_num,
                    "position": pos,
                    "b_polarity": b_pol,
                    "level_A": level,
                    "points_requested": points,
                    "delay_s": delay_s,
                    "thickness_um": self.thickness_um,
                    "V_plus_V": v_plus if v_plus is not None else "",
                    "V_minus_V": v_minus if v_minus is not None else "",
                    "I_mean_pos_A": i_plus if i_plus is not None else "",
                    "I_mean_neg_A": i_minus if i_minus is not None else "",
                    "nplc": getattr(self, "_applied_nplc", None)
                            if getattr(self, "_applied_nplc", None)
                            is not None else "",
                    "output_off_mode":
                        ("high-Z" if getattr(self, "_applied_high_z", None)
                         else ("normal" if getattr(self, "_applied_high_z", None)
                               is not None else "")),
                    "stage_temp_C": self._stage_temperature() or "",
                },
                readings=pos_raw + neg_raw,
            )
            self.app.ui(self._record_run, row, run)
        finally:
            self.measuring = False
            smu.safe_output_off()
            self.log("Output OFF")
            self.app.ui(self.set_lamp, False)

    def _measure_polarity(self, smu, polarity, points, level, delay_s):
        """Source `level * polarity`, let it settle, take `points`
        readings, and return (mean V, mean I, raw rows).

        Averaging is unchanged from the original: V and I are averaged
        *independently* across the block. Note this differs from Van der
        Pauw, which averages the per-reading ratio V/I instead. Both are
        faithful to their own original script, and the difference is
        deliberate - Hall wants the voltage itself, not a resistance.

        One deviation from the original: it issued no host-side wait
        between successive readings, and issued :SOUR:DEL in microseconds
        (the 2450 family takes seconds - the same unit bug already found
        in the Van der Pauw script). The delay is now sent correctly in
        seconds via the driver, and the host-side settle after switching
        polarity is kept, which is what actually dominated.
        """
        signed = level * polarity
        label = "pos" if polarity > 0 else "neg"

        smu.set_source_delay(delay_s)
        smu.set_current_range(None)
        smu.set_current_level(signed)

        if delay_s > 0:
            self.log(f"Settling {delay_s:.3f} s at {label} polarity")
            time.sleep(delay_s)

        readings = []
        v_values = []
        i_values = []
        for n in range(points):
            if not self.app.is_connected("source"):
                break
            try:
                v, current = smu.measure()
            except Exception as e:
                self.log(f"Point {n+1}/{points} [{label}] error: {e}")
                readings.append({"point": n + 1, "current_polarity": label,
                                 "timestamp": datetime.datetime.now().isoformat(),
                                 "voltage_V": "", "current_A": "",
                                 "error": str(e)})
                continue
            ts = datetime.datetime.now().isoformat()
            self.log(f"Point {n+1}/{points} [{label}] V={v} I={current}")
            readings.append({"point": n + 1, "current_polarity": label,
                             "timestamp": ts, "voltage_V": v,
                             "current_A": current, "error": ""})
            if v is not None:
                v_values.append(v)
            if current is not None:
                i_values.append(current)

        v_avg = sum(v_values) / len(v_values) if v_values else None
        i_avg = sum(i_values) / len(i_values) if i_values else None
        return v_avg, i_avg, readings

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
        fields = dict(self._calculated)
        if self.rs_source_path:
            fields["Rs_source"] = self.rs_source_path
        return fields

    def off_pressed(self):
        """OFF button: kill the output now."""
        def task():
            self.measuring = False
            self.instrument("source").safe_output_off()
            self.log("Output OFF")
            self.app.ui(self.set_lamp, False)
            self.app.ui(self.off_btn.config, state="disabled")
        self.app.run_in_background(self.app.guard_run(task))

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

        Requires exactly the set {Pos1+, Pos1-, Pos2+, Pos2-} - one run
        per position-and-field combination. Anything else is refused
        rather than half-filled, because a partly-populated calculation
        panel that still holds values from a previous sample is the kind
        of mistake that produces a plausible wrong answer.

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
            by_combo[(pos_num, str(values[2]).strip())] = values

        if set(by_combo) != set(COPY_MAP):
            messagebox.showerror(
                "Copy error",
                "Ticked rows must be exactly one each of "
                "Pos1+, Pos1-, Pos2+, Pos2-.")
            return

        # parse everything before writing anything, so a bad row can't
        # leave the panel half-updated
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

        for attr, value in parsed.items():
            getattr(self, attr).set(f"{value:.{VOLTAGE_FIGURES}g}")

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

    def calculate_hall(self):
        """V_H from the eight voltages, then n_s, mobility and
        resistivity. Arithmetic unchanged from the original."""
        voltages = {}
        missing = []
        for attr in ("v13p_var", "v31p_var", "v24p_var", "v42p_var",
                     "v13n_var", "v31n_var", "v24n_var", "v42n_var"):
            value = _float_or_none(getattr(self, attr).get())
            if value is None:
                missing.append(attr.replace("_var", "").upper())
            voltages[attr] = value

        if missing:
            messagebox.showerror("Invalid inputs",
                                 "Enter numeric values for: " + ", ".join(missing))
            return

        vh = hall_math.hall_voltage(
            voltages["v13p_var"], voltages["v31p_var"],
            voltages["v24p_var"], voltages["v42p_var"],
            voltages["v13n_var"], voltages["v31n_var"],
            voltages["v24n_var"], voltages["v42n_var"])
        self.vh_var.set(f"{vh:.6g}")
        self.log(f"V_H = {vh:.6g} V")
        self.update_differences()

        field = _float_or_none(self.calc_B_var.get())
        sheet_r = _float_or_none(self.calc_Rs_var.get())
        if field is None or sheet_r is None:
            messagebox.showerror(
                "Invalid inputs",
                "Enter numeric B (T) and sheet resistance Rs (Ω/□) "
                "to compute carrier density and mobility.")
            self._calculated = {}
            for var in (self.ns_var, self.mu_var, self.rho_var,
                        self.carrier_type_var):
                var.set("-")
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

        try:
            ns_cm2 = hall_math.sheet_carrier_density(current, field, vh)
            mobility = hall_math.hall_mobility(ns_cm2, sheet_r)
            thickness_cm = hall_math.um_to_cm(self.thickness_um)
            rho = hall_math.resistivity(sheet_r, thickness_cm)
        except ZeroDivisionError as e:
            self.carrier_type_var.set(hall_math.INDETERMINATE)
            for var in (self.ns_var, self.mu_var, self.rho_var):
                var.set("ERR")
            self.log("Calculation error:", e)
            messagebox.showerror("Calculation error", str(e))
            return
        except ValueError as e:
            for var in (self.ns_var, self.mu_var, self.rho_var):
                var.set("ERR")
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
        if is_bulk:
            density = hall_math.bulk_carrier_density(ns_cm2, thickness_cm)
            self.ns_var.set(f"{abs(density):.6g} cm^-3")
            self.mu_var.set(f"{abs(mobility):.6g} cm^2/Vs (bulk)")
            self.rho_var.set(f"{rho:.6g} Ω·cm (bulk)")
        else:
            self.ns_var.set(f"{abs(ns_cm2):.6g} cm^-2")
            self.mu_var.set(f"{abs(mobility):.6g} cm^2/Vs")
            self.rho_var.set(f"{rho:.6g} Ω·cm")

        # The signed values still go to the console, so nothing is hidden
        # and an old result can be compared against the original script.
        self._calculated = {
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
            "thickness_um": f"{self.thickness_um:.6g}",
        }

        self.log(f"{carrier}: n={self.ns_var.get()}, mu={self.mu_var.get()}, "
                 f"rho={self.rho_var.get()}")
        self.log(f"  (signed: n_s={ns_cm2:.6g}, mu={mobility:.6g})")

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
        """Stop measuring before the app tears connections down. The
        stage is handled by Experiment.shutdown_devices()."""
        self.measuring = False


def _float_or_none(text):
    """float() that returns None instead of raising, for optional or
    possibly-blank entry boxes."""
    try:
        return float(str(text).strip())
    except (ValueError, TypeError):
        return None
