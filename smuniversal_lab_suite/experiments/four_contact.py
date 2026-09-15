"""What Van der Pauw and Hall share: a current-sourced, four-contact run.

Both experiments put a current through two corners of a film and read
the voltage across the other two, from the same setup panel, on the
same stage, with the same thickness box. Review A-08 found the parts of
that which do not depend on what happens to the readings copied into
both, identical but for their comments. They are here once.

What stays in each experiment is what differs between them: how a run
is sequenced, what is done with its two polarities, and the
calculation. Van der Pauw averages the polarities into one resistance;
Hall keeps them apart, because reversing the current is one of the two
reversals its eight-term average depends on.
"""
from tkinter import messagebox

from smuniversal_lab_suite.core.gui.widgets import (
    apply_compliance,
    apply_high_z,
    apply_nplc,
)
from smuniversal_lab_suite.core.limits import parse_si
from smuniversal_lab_suite.core.ranges import AUTO, RangePlan
from smuniversal_lab_suite.experiments.base_experiment import Experiment


class FourContactExperiment(Experiment):
    """Shared behaviour of the Van der Pauw and Hall tabs.

    Expects the widgets their setup and results panels build:
    `volt_range_var`, `vlim_var`, `thickness_entry_var` and `tree`.
    """

    @staticmethod
    def _volt_label(volts):
        """Label a voltage range for the dropdown."""
        return f"{volts*1000:g} mV" if volts < 1 else f"{volts:g} V"

    # ---- input parsing ----
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

    # ---- the run ----
    def _ready_to_run(self):
        """Refuse a second run while the first is still unwinding.

        `run_in_progress()` stays true until instrument ownership has
        been released, which is later than "the worker thread finished".
        An instrument that has not been handed back is not free,
        whatever the thread is doing.
        """
        if self.run_in_progress():
            return False
        # The other tab may hold the SMU. Asked here rather than at the
        # claim, so the refusal lands before the operator is sent to the
        # switch box (and, for Hall, the magnet).
        if self.refuse_if_sibling_busy():
            return False
        if not self.app.is_connected("source"):
            messagebox.showwarning("Not connected", "Connect the SMU first.")
            return False
        if not self._summary_collision_ok():
            return False
        return True

    def _configure(self, run, smu, params):
        """Put the instrument into the state this run needs.

        Applied every run rather than once at connect, for the same
        reason as remote sense: otherwise the instrument keeps whatever
        the last experiment left it in, and the same sample reads
        differently depending on history.
        """
        run.checkpoint("configure")
        smu.set_source_function("current")
        # Ranging, all four axes, stated once before the output goes on.
        # Both experiments source current and measure voltage, so:
        #
        #   source current   the level being driven, +/- level_a
        #   source voltage   AUTO - nothing sources voltage here
        #   measure current  the same current, read back per point
        #   measure voltage  the operator's chosen voltage range
        #
        # The source range is sized to the largest magnitude this run
        # will source and set once, never re-sent while the sample is
        # live - house rule 12, where the electrical reason is: a range
        # change mid-run leaves a step in the data that a fit reads as
        # resistance.
        #
        # Every driver in the suite rounds *up* - the U2722A and miniSMU
        # pick the smallest range that still fits, and the SCPI and TSP
        # range commands select a range that accommodates the value - so
        # sizing to the level itself cannot clamp it.
        #
        # The form uses None for "let it autorange"; the plan spells
        # that AUTO. Converted here, at the boundary, which is where
        # RangePlan insists such conversions happen - a plan accepting
        # None would be treating the shape of an unset variable as a
        # deliberate choice.
        #
        # Note what is NOT here: a measurement range for current. The
        # measured current is read back from the source, so it has no
        # separate measure range - `for_sourcing` is what keeps that
        # axis out of reach.
        ranges = RangePlan.for_sourcing(
            "current",
            source_range=abs(params.level_a),
            measure_range=(AUTO if params.voltage_range_v is None
                           else params.voltage_range_v))
        run.set_metadata(ranges=smu.apply_ranges(ranges, log=self.log))
        smu.set_remote_sense(True)
        run.set_metadata(compliance_applied=apply_compliance(
            smu, "current", params.compliance_v, self.log))
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

    def _stage_temperature(self):
        """Current stage temperature, or None when there's no usable
        reading. Recorded per run because both sheet resistance and the
        Hall quantities depend on it - carrier density and mobility
        strongly."""
        if not self.temp_ctrl.is_connected():
            return None
        status = self.temp_ctrl.status()
        if status.is_stale or status.fault or status.temp_c is None:
            return None
        return round(status.temp_c, 1)

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
