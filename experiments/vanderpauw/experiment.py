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
import time
import tkinter as tk
from tkinter import messagebox

from experiments.base_experiment import Experiment
from core.limits import format_amps, parse_si
from core.gui.widgets import (refresh_nplc, parse_nplc, apply_nplc,
                              refresh_high_z, apply_high_z)
from core.run_store import Run, build_sample_csv

from core.gui.corner_diagram import paint_corner_roles

from .vdp_math import solve_vdp_sheet_resistance
from .panels.diagram_panel import build_diagram_panel
from .panels.positions_panel import build_positions_panel
from .panels.setup_panel import build_setup_panel
from core.gui.temp_panel import build_temp_panel
from .panels.action_panel import build_action_panel
from .panels.results_panel import build_results_panel
from .panels.calc_panel import build_calc_panel

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

    ROLES = {"source": "SMU"}

    CSV_SLUG = "vanderpauw"
    CSV_TITLE = "Van der Pauw - sheet resistance"

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
        self.polling = False
        # Last successful calculation, embedded in the CSV header on save.
        self._calculated = {}

    def on_panels_built(self):
        """Paint the corner diagram for the starting position, once the
        canvas exists."""
        self.on_pos_changed()

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
    def run_pressed(self):
        """Run button: confirm position, validate, then measure both
        polarities on a background thread."""
        if not self.app.is_connected("source"):
            messagebox.showwarning("Not connected", "Connect the SMU first.")
            return

        pos = int(self.pos_var.get())
        if not messagebox.askokcancel(
                "Confirm position",
                f"Set the switch box to position {pos}.\n\nClick OK to start."):
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

        # the hard gate: refuse before anything is sourced
        try:
            self.app.check_source_point("source", current=level, voltage=vlim)
        except Exception as e:
            self.log("Refused:", e)
            messagebox.showerror("Outside instrument limits", str(e))
            return

        self.app.run_in_background(
            self.app.guard_run(lambda: self._do_run(pos, points, level, vlim, delay_s))
        )

    def _do_run(self, pos, points, level, vlim, delay_s):
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

            r_pos = self._polarity_block(smu, +1, points, level, delay_s, pos)
            pos_readings = self._block_readings
            r_neg = self._polarity_block(smu, -1, points, level, delay_s, pos)
            neg_readings = self._block_readings

            rave = None
            if r_pos is not None and r_neg is not None:
                rave = (r_pos + r_neg) / 2.0

            sample = (self.sample_name_var.get() or "sample").strip().replace(" ", "_")
            meas_num = self.app.take_meas_number()
            row = (
                sample,
                f"Pos{pos}",
                f"{r_pos:.6g}" if r_pos is not None else "-",
                f"{r_neg:.6g}" if r_neg is not None else "-",
                f"{rave:.6g}" if rave is not None else "",
            )

            run = Run(
                sample=sample,
                metadata={
                    "meas_number": meas_num,
                    "position": pos,
                    "level_A": level,
                    "points_requested": points,
                    "delay_s": delay_s,
                    "thickness_um": self.thickness_um,
                    "R_pos_ohm": r_pos if r_pos is not None else "",
                    "R_neg_ohm": r_neg if r_neg is not None else "",
                    "R_ave_ohm": rave if rave is not None else "",
                    "nplc": getattr(self, "_applied_nplc", None)
                            if getattr(self, "_applied_nplc", None)
                            is not None else "",
                    "output_off_mode":
                        ("high-Z" if getattr(self, "_applied_high_z", None)
                         else ("normal" if getattr(self, "_applied_high_z", None)
                               is not None else "")),
                    "stage_temp_C": self._stage_temperature() or "",
                },
                readings=pos_readings + neg_readings,
            )
            self.app.ui(self._record_run, row, run)
        finally:
            self.measuring = False
            smu.safe_output_off()
            self.log("Output OFF")
            self.app.ui(self.set_lamp, False)

    def _polarity_block(self, smu, polarity, points, level, delay_s, pos):
        """Source `level * polarity`, let it settle, take `points`
        readings, and return their averaged resistance.

        Arithmetic is unchanged from the original: R for each reading is
        V/I from that reading, and the block result is the plain mean of
        the valid R values.

        The readings are kept on self._block_readings for the caller to
        collect. They used to be written straight to a .txt from here;
        they now travel back so the run can be held in memory until the
        operator decides it is worth saving.
        """
        signed = level * polarity
        label = "pos" if polarity > 0 else "neg"

        smu.set_source_delay(delay_s)
        smu.set_current_range(None)
        smu.set_current_level(signed)

        # host-side settle as well as instrument-side - the original did
        # both, and the host wait is what actually dominated
        if delay_s > 0:
            self.log(f"Settling {delay_s:.3f} s at {label} polarity")
            time.sleep(delay_s)

        readings = []
        r_values = []
        for i in range(points):
            if not self.app.is_connected("source"):
                break
            try:
                v, current = smu.measure()
            except Exception as e:
                self.log(f"Point {i+1}/{points} [{label}] error: {e}")
                readings.append({"point": i + 1, "polarity": label,
                                 "timestamp": datetime.datetime.now().isoformat(),
                                 "voltage_V": "", "current_A": "",
                                 "resistance_ohm": "", "error": str(e)})
                continue
            ts = datetime.datetime.now().isoformat()
            self.log(f"Point {i+1}/{points} [{label}] V={v} I={current}")
            resistance = v / current if (v is not None and current) else ""
            readings.append({"point": i + 1, "polarity": label, "timestamp": ts,
                             "voltage_V": v, "current_A": current,
                             "resistance_ohm": resistance, "error": ""})
            if resistance != "":
                r_values.append(resistance)
            time.sleep(0.04)

        avg_r = sum(r_values) / len(r_values) if r_values else None
        self._block_readings = readings
        return avg_r

    def calculated_fields(self):
        """Sheet resistance and friends, for the saved CSV header."""
        return dict(self._calculated)

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
        """Copy the four ticked rows' R(ave) into the Pos1-4 calc boxes.
        Requires exactly one row per position."""
        ticked = [i for i in self.tree.get_children()
                  if (self.tree.item(i, "text") or "") == "☑"]
        if len(ticked) != 4:
            messagebox.showerror("Copy error",
                                 "Tick exactly 4 rows - one per position.")
            return

        by_pos = {}
        for item in ticked:
            vals = self.tree.item(item, "values")
            by_pos[str(vals[1]).strip()] = str(vals[4]).strip()

        if set(by_pos) != {"Pos1", "Pos2", "Pos3", "Pos4"}:
            messagebox.showerror("Copy error",
                                 "Ticked rows must be one each of Pos1-Pos4.")
            return

        try:
            values = [float(by_pos[f"Pos{n}"]) for n in (1, 2, 3, 4)]
        except ValueError:
            messagebox.showerror("Copy error",
                                 "R(ave) must be numeric for all 4 rows.")
            return

        for var, val in zip(self.pos_vars, values):
            var.set(f"{val:.6g}")
        self.log("Copied R(ave) into calculation boxes")

    def calculate_vdp(self):
        """Rh/Rv from the four positions, solve for Rs, convert to rho.

        Arithmetic unchanged: Rh is the mean of Pos1 and Pos2, Rv the
        mean of Pos3 and Pos4, and rho = Rs * thickness in cm.
        """
        try:
            p = [float(v.get().strip()) for v in self.pos_vars]
        except ValueError:
            messagebox.showerror("Invalid inputs",
                                 "Enter numeric values for all four positions.")
            return

        rh = 0.5 * (p[0] + p[1])
        rv = 0.5 * (p[2] + p[3])
        self.rh_var.set(f"{rh:.6g}")
        self.rv_var.set(f"{rv:.6g}")
        self.log(f"Rh={rh:.6g} Ω, Rv={rv:.6g} Ω")

        try:
            rs = solve_vdp_sheet_resistance(rh, rv)
            rho = rs * (self.thickness_um * 1e-4)   # µm -> cm
            self.rs_var.set(f"{rs:.6g}")
            self.rho_var.set(f"{rho:.6g}")
            # Key names matter: core/vdp_result.py looks for
            # Rs_ohm_per_sq when Hall loads a sheet resistance back.
            self._calculated = {
                "Rh_ohm": f"{rh:.9g}",
                "Rv_ohm": f"{rv:.9g}",
                "Rs_ohm_per_sq": f"{rs:.9g}",
                "rho_ohm_cm": f"{rho:.9g}",
                "thickness_um": f"{self.thickness_um:.6g}",
            }
            self.log(f"Rs={rs:.6g} Ω/□, ρ={rho:.6g} Ω·cm")
        except Exception as e:
            self._calculated = {}
            self.rs_var.set("ERR")
            self.rho_var.set("-")
            self.log("Solver error:", e)
            messagebox.showerror("Solver error", str(e))

    def on_close(self):
        """Stop measuring before the app tears connections down. The
        stage is handled by Experiment.shutdown_devices()."""
        self.measuring = False


def _parse_si(text):
    """Kept as a module-level name because the unit tests import it.
    The implementation now lives in core/limits.py, shared with Hall."""
    return parse_si(text)
