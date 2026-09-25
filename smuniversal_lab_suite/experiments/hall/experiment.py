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
from tkinter import messagebox

from smuniversal_lab_suite.core.calculation import (
    CalculationInput,
    CalculationRefused,
    InputValue,
    SourceRow,
    derive,
    require_set,
    signature,
    tag,
    upstream_signature_items,
    validate,
)
from smuniversal_lab_suite.core.gui import theme
from smuniversal_lab_suite.core.gui.corner_diagram import paint_corner_roles
from smuniversal_lab_suite.core.gui.equations import number
from smuniversal_lab_suite.core.gui.run_controls import build_run_controls
from smuniversal_lab_suite.core.gui.widgets import (
    parse_nplc,
    refresh_high_z,
    refresh_nplc,
)
from smuniversal_lab_suite.core.identity import reading_id
from smuniversal_lab_suite.core.limits import parse_si
from smuniversal_lab_suite.core.parameters import HallParameters
from smuniversal_lab_suite.core.progress import seconds_per_reading
from smuniversal_lab_suite.core.run_store import Run
from smuniversal_lab_suite.core.validation import (
    ValidationError,
    one_of,
)
from smuniversal_lab_suite.experiments.four_contact import (
    FourContactExperiment,
    half_means,
)

from . import hall_math
from .hall_math import EQUATIONS
from .panels.calc_panel import build_calc_panel
from .panels.diagram_panel import build_diagram_panel
from .panels.plot_panel import build_hall_plot_panel
from .panels.positions_panel import build_positions_panel
from .panels.results_panel import build_results_panel
from .panels.setup_panel import build_setup_panel

# Which corner plays which role, per switch-box position, as the box
# itself is drawn: corners numbered clockwise from top left, and each
# role the SMU terminal wired there - Hi and Lo carry the current, Sense
# Hi and Sense Lo read the voltage. The two positions put the current
# on the two diagonals. Drives the diagram.
CORNER_ROLES = {
    "C": {1: "V,L", 2: "I,H", 3: "V,H", 4: "I,L"},
    "D": {1: "I,H", 2: "V,H", 3: "I,L", 4: "V,L"},
}
POSITIONS = tuple(CORNER_ROLES)

# How a (position, B polarity) run maps onto the calculation boxes.
# V+ is the voltage in the positive-current half of the sweep, V- in the
# negative half; swapping the digits in the name is what "current
# reversed" means. C is the box's Hall 1 and D its Hall 2, in the slots
# the original's positions 1 and 2 filled.
COPY_MAP = {
    ("C", "+"): ("v13p_var", "v31p_var"),
    ("C", "-"): ("v13n_var", "v31n_var"),
    ("D", "+"): ("v24p_var", "v42p_var"),
    ("D", "-"): ("v24n_var", "v42n_var"),
}

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


class HallExperiment(FourContactExperiment):
    NAME = "Hall effect - carrier density and mobility"
    TAB_NAME = "Hall effect"
    THEME_KEY = "hall"

    ROLES = {"source": "SMU"}

    CSV_SLUG = "hall"
    CSV_TITLE = "Hall effect - carrier density and mobility"

    # The headline numbers this experiment puts in a sample
    # summary. Keys match `calculated_fields()`. Carrier type is the
    # unitless one; the app leaves its unit column blank.
    SUMMARY_QUANTITIES = (
        ("carrier_type", "Carrier type", ""),
        ("carrier_density_cm-2", "Sheet carrier density", "cm\u207b\u00b2"),
        ("mobility_cm2_Vs", "Hall mobility", "cm\u00b2/Vs"),
    )

    # Shared with Van der Pauw in the combined window. The
    # thickness in particular - a carrier density computed from one
    # thickness while the sheet resistance came from another is wrong in
    # a way that looks entirely reasonable on screen.
    USES_TEMP_STAGE = True
    SESSION_FIELDS = ("sample", "thickness")

    EQUATIONS = EQUATIONS

    PANELS = [
        build_diagram_panel,
        build_positions_panel,
        build_setup_panel,
        build_run_controls,
        # Under Run and Stop, in the height the middle column had spare.
        build_hall_plot_panel,
        build_results_panel,
        build_calc_panel,
    ]

    #: The legend names a run by its position and field sign.
    PLOT_LABEL_COLUMNS = (1, 2)

    def __init__(self, app):
        super().__init__(app)
        # `measuring` is gone. It was a flag shared by
        # every consecutive run - a worker that outlived its run and
        # woke during the next one read the new run's cleared flag as
        # permission to continue. State lives on the run now.
        #
        # Where the sheet resistance came from, when it was carried over
        # from the Van der Pauw tab rather than typed. The
        # `UpstreamResult` names that calculation and the runs behind
        # it; the value is the box contents at the moment of transfer,
        # so an edit can be told from a carry-over exactly rather than
        # approximately. Both are read through `rs_upstream()`, never
        # directly - see the all-or-nothing rule there.
        self._rs_upstream = None
        self._rs_upstream_value = None
        # Last successful calculation, embedded in the CSV header on save.
        self._calculated = {}

        # ---- the calculation layer ----
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
        self.refresh_plot()
        # No Van der Pauw tab in this window means nothing to take an Rs
        # from. Disabled rather than absent: a greyed control says the
        # feature exists and is unavailable here, where a missing one
        # says nothing at all and sends the operator looking for it.
        if hasattr(self, "rs_take_btn") \
                and self.app.provider_of("sheet_resistance", exclude=self) is None:
            self.rs_take_btn.configure(state="disabled")
        self._refresh_rs_source()
        watched = [getattr(self, name) for name in (
            "v13p_var", "v31p_var", "v24p_var", "v42p_var",
            "v13n_var", "v31n_var", "v24n_var", "v42n_var",
            "calc_B_var", "calc_Rs_var", "calc_I_var",
            "sample_type_var", "thickness_entry_var", "sample_name_var")]
        for var in watched:
            var.trace_add("write", self._on_calc_input_changed)

    # ---- driver-aware setup ----
    def on_connected(self, role, driver):
        """Repopulate the voltage-range dropdown from the instrument that
        just connected.

        The sweep's currents are typed, as on Van der Pauw, so there is
        no level list to fill. The limit gate, not the widget, is what
        keeps the request legal.
        """
        # Ahead of the early return below: NPLC support is declared
        # separately from LIMITS, so a driver with no declared ranges
        # can still have an integration-time control.
        refresh_nplc(self.nplc_combo, self.nplc_var, driver, self.log)
        refresh_high_z(self.high_z_check, self.high_z_var, driver, self.log)

        limits = driver.LIMITS
        if limits is None:
            return

        v_labels = ["AUTO"] + [self._volt_label(v) for v in sorted(limits.voltage_ranges)]
        self.volt_range_combo["values"] = v_labels
        if self.volt_range_var.get() not in v_labels:
            self.volt_range_var.set("AUTO")

        self.log(f"Ranges loaded from {driver.DISPLAY_NAME}")

    def estimate_run_seconds(self, parameters):
        """One sweep: a settle and a reading at every point."""
        per_point = parameters.delay_s + seconds_per_reading(parameters.nplc)
        return parameters.points_n * per_point

    # ---- input parsing ----
    # `get_sweep_amps()` is inherited from `FourContactExperiment`, and
    # refuses a box it cannot read rather than running at a level nobody
    # typed, as Van der Pauw does.
    def parse_delay(self):
        """Settle delay at each point in seconds, from the ms entry box.
        Falls back to the original's 50 ms default on bad input."""
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
        paint_corner_roles(self, CORNER_ROLES.get(self.pos_var.get(), {}))
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
        position = one_of(self.pos_var.get(), "Position", POSITIONS)
        start, stop = self.get_sweep_amps()
        return HallParameters(
            sample=self.current_sample_ref(),
            dataset=f"Pos{position}{self.field_sign_var.get()}",
            position=position,
            field_sign=one_of(self.field_sign_var.get(), "B polarity",
                              ("+", "-")),
            start_a=start,
            stop_a=stop,
            points_n=self.get_points(),
            delay_s=self.parse_delay(),
            compliance_v=self.get_vlim_volts(),
            voltage_range_v=self.get_voltage_range(),
            nplc=parse_nplc(self.nplc_var),
            high_z=bool(self.high_z_var.get()),
            thickness_m=self.thickness_m(),
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

        # The hard gate: refuse before anything is sourced. The sweep's
        # ends are free-form - this is the only check on a mistyped one.
        try:
            self.app.check_source_point("source", current=params.level_a,
                                        voltage=params.compliance_v,
                                        sourcing="current")
        except Exception as e:
            self.log("Refused:", e)
            messagebox.showerror("Outside instrument limits", str(e))
            return

        self.app.run_in_background(
            self.app.guard_run(lambda: self._do_run(params)))

    def _do_run(self, params):
        """Sweep one (position, B sign) through both current polarities.

        Background thread. The lifecycle is the shared one: the
        sequence sits inside `begin_run()`,
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
                halves = self._sweep(run, smu, params, "current_polarity")
            finally:
                # Always bring the source down, whatever went wrong,
                # including a cancellation. On the thread that owns the
                # session, and the only place the output is turned off.
                report = run.confirm_shutdown(smu, log=self.log)
                self.app.ui(self.set_lamp, False)
                if report.uncertain:
                    self.app.report_uncertain_shutdown("source", report)

            # Averaging unchanged from the original: V and I averaged
            # *independently* across each half, where Van der Pauw
            # averages the ratio. Hall wants the voltage itself.
            v_plus, i_plus = half_means(halves["pos"])
            v_minus, i_minus = half_means(halves["neg"])
            self._finish_run(run, params, v_plus, i_plus, v_minus, i_minus)

    def _finish_run(self, run, params, v_plus, i_plus, v_minus, i_minus):
        """Build the record and put it through the commit gate.

        No averaging across polarities here, unlike Van der Pauw. The
        two voltages are kept separate and both reach the table, because
        the calculation downstream needs them apart - averaging them
        would destroy exactly the quantity being measured.
        """
        run.checkpoint("commit")
        # The current each half ran at, on average - what the Hall
        # voltages in this row belong to.
        currents = [abs(i) for i in (i_plus, i_minus) if i is not None]
        current_shown = (math.fsum(currents) / len(currents) if currents
                         else params.level_a)
        clamped, clamp_message = self.check_clamping(
            f"{params.sample_label} {params.combination}",
            [r.get("level_A") for r in run.readings],
            [r.get("voltage_V") for r in run.readings],
            run.metadata.get("compliance_applied"), "V")

        run.set_metadata(
            position=params.position,
            b_polarity=params.field_sign,
            start_A=params.start_a,
            stop_A=params.stop_a,
            points_requested=params.points_n,
            delay_s=params.delay_s,
            thickness_nm=self._thickness_nm_column(params),
            V_plus_V=v_plus if v_plus is not None else "",
            V_minus_V=v_minus if v_minus is not None else "",
            I_mean_pos_A=i_plus if i_plus is not None else "",
            I_mean_neg_A=i_minus if i_minus is not None else "",
            compliance_suspected=clamped,
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
            self._record_run, row, committed, clamp_message))

    def _record_run(self, row, run, clamp_message=""):
        """Add a finished run to the table and the store together, keyed
        on the Treeview item id so the two can't drift apart."""
        item = self.tree.insert("", "end", text="☐", values=row)
        self.run_store.add(item, run)
        self.refresh_plot()
        self.warn_clamped([clamp_message])

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
        # No `Rs_source` line any more. Where the sheet resistance came
        # from is now part of the `DerivedResult` itself and reaches the
        # header through `to_metadata()` as `input_sheet_resistance_from`,
        # naming the Van der Pauw result and its runs rather than a file
        # path that may since have been renamed, moved or overwritten.
        return dict(self._calculated)

    def equation_values(self):
        """This tab's formulas with the last result's numbers in them.

        Withheld while the result is stale - see the note on the Van der
        Pauw version. The bulk density appears only when the sample type
        was Bulk, because that is the only time it was computed.
        """
        result = self._calc_result
        if result is None:
            return {}, ("No result yet. Copy the four ticked runs in, fill "
                        "in B, Rs and I, and press Calculate to see these "
                        "formulas with your numbers in them.")
        if result.is_stale(self._calc_signature()):
            return {}, ("The calculation is out of date - its inputs have "
                        "changed since it ran - so its numbers are not "
                        "shown. Press Calculate.")

        out, inputs = result.outputs, result.inputs
        vh = out["V_H_V"]
        deltas = [
            inputs[p].value - inputs[n].value
            for p, n in (("v13p_var", "v13n_var"), ("v31p_var", "v31n_var"),
                         ("v24p_var", "v24n_var"), ("v42p_var", "v42n_var"))
        ]
        thickness_cm = inputs["thickness_m"].value * 1e2
        values = {
            "hall_voltage": (
                rf"V_H = \frac{{({number(deltas[0])}) - ({number(deltas[1])})"
                rf" + ({number(deltas[2])}) - ({number(deltas[3])})}}{{8}}"
                rf" = {number(vh)}\,\mathrm{{V}}"),
            "hall_sheet_carrier_density": (
                rf"n_s = \frac{{{number(inputs['current_a'].value)} \times "
                rf"{number(inputs['field_t'].value)}}}{{q \times "
                rf"{number(vh)}}}\times 10^{{-4}} = "
                rf"{number(out['sheet_density_cm2'])}\,\mathrm{{cm^{{-2}}}}"),
            "hall_mobility": (
                rf"\mu = \frac{{1}}{{q \times "
                rf"{number(out['sheet_density_cm2'])} \times "
                rf"{number(inputs['sheet_resistance'].value)}}} = "
                rf"{number(out['mobility_cm2_Vs'])}"
                rf"\,\mathrm{{cm^2/(V\,s)}}"),
            "hall_resistivity": (
                rf"\rho = {number(inputs['sheet_resistance'].value)} \times "
                rf"{number(thickness_cm)} = "
                rf"{number(out['resistivity_ohm_cm'])}"
                rf"\,\Omega\,\mathrm{{cm}}"),
        }
        if "bulk_density_cm3" in out:
            values["hall_bulk_carrier_density"] = (
                rf"n = \frac{{{number(out['sheet_density_cm2'])}}}"
                rf"{{{number(thickness_cm)}}} = "
                rf"{number(out['bulk_density_cm3'])}\,\mathrm{{cm^{{-3}}}}")
        return values, (
            f"Values from {result.result_id}, calculated for "
            f"{result.sample_label_at_calculation}. The signs are the "
            f"measured ones: a negative n_s is the carrier type, not an "
            f"error.")

    def calculated_sample_id(self):
        """Which sample the calculation belongs to.

        With this override the last `current_sample_name()` comparison
        in `save_runs()` is gone from the three ported experiments: all
        of them now file a derived result against the sample identity
        that produced it rather than against the text box.
        """
        return None if self._calc_result is None else self._calc_result.sample_id

    # ---- results table ----
    def copy_over(self):
        """Copy the four ticked rows' V+/V- into the calculation boxes.

        Requires exactly {PosC+, PosC-, PosD+, PosD-} - one run per
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
                "Tick exactly 4 rows - PosC+, PosC-, PosD+, PosD-.")
            return

        by_combo = {}
        sources = {}
        for item in ticked:
            values = self.tree.item(item, "values")
            if len(values) < 6:
                messagebox.showerror("Copy error", "Unexpected table row format.")
                return
            pos_num = str(values[1]).strip().replace("Pos", "")
            if pos_num not in POSITIONS:
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
                "PosC+, PosC-, PosD+, PosD-.")
            return

        # The shared complete-set check, over the *runs* rather than
        # the table rows.
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

    # ---- calculation state ----
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
            "thickness_m": self._thickness_signature(),
            "_sample": self.sample_name_var.get().strip(),
        })
        # The carried-over sheet resistance contributes its
        # *result id*, not just the number it put in the box, so
        # recalculating Van der Pauw invalidates a Hall result that
        # quotes it even when the new Rs comes out identical.
        #
        # Built by the same function the calculation uses, not by a
        # second hand-written copy of the same keys. That is the whole
        # point of `upstream_signature_items()`: two spellings of one
        # field name once shipped a result that read as permanently
        # stale and silently stopped reaching the CSV.
        upstream = self.rs_upstream()
        items.update(upstream_signature_items((upstream,) if upstream else ()))
        return signature(items)

    def _on_calc_input_changed(self, *_args):
        """Tk trace: mark the result stale if it no longer follows from
        what is on screen."""
        # Before the staleness test, not after: typing over the Rs box
        # drops its citation, which changes the signature. Doing it the
        # other way round would compare against a signature built from
        # provenance the panel had already stopped claiming.
        self._refresh_rs_source()
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
        for widget in getattr(self, "calc_result_labels", {}).values():
            base = getattr(widget, "base_style", "TLabel")
            widget.configure(style=theme.stale(base, stale))
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
            self.calc_status_label.configure(style="Warn.TLabel")
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
        self.calc_status_label.configure(style="Hint.TLabel")

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
            thickness = self._thickness_input()
            sample = self.current_sample_ref()
        except (ValidationError, ValueError) as e:
            messagebox.showerror("Invalid setup", str(e))
            return

        # Current from the calc box if given, otherwise the sweep's -
        # the mean current magnitude its two halves ran at, which is what
        # the averaged voltages belong to. The original's fallback, to
        # the level the setup panel asked for; kept because the two
        # legitimately differ when compliance clamps the source.
        current_typed = _float_or_none(self.calc_I_var.get())
        if current_typed is None:
            try:
                current = self.nominal_mean_current()
            except ValidationError as e:
                messagebox.showerror("Invalid setup", str(e))
                return
            self.log(f"Using the sweep's mean current for calculation: "
                     f"{current:g} A")
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
            "thickness_m": thickness,
        })

        # The sheet resistance, when it was carried over rather than
        # typed, enters as an *upstream result* and not as four more
        # source runs. See `UpstreamResult` for why the distinction is
        # load-bearing: folded into `sources`, Van der Pauw's Pos1-4
        # would be refused by `require_set()` as unexpected combinations
        # and the header would claim twelve runs behind eight voltages.
        upstream = self.rs_upstream()

        calc = CalculationInput(
            method="hall_sheet_carrier_density",
            sample_id=sample.sample_id,
            sample_label=sample.label,
            values=values,
            sources=sources,
            required=(*self.VOLTAGE_ATTRS, "field_t", "sheet_resistance",
                      "current_a", "thickness_m"),
            upstream=(upstream,) if upstream else (),
        )

        # The mixed-sample gate. Refused before any arithmetic, with
        # both sample names in
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
            thickness_cm = thickness.value * 1e2
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
            style = {hall_math.N_TYPE: "NType.Bold.TLabel",
                     hall_math.P_TYPE: "PType.Bold.TLabel"}.get(
                         carrier, "Hint.Bold.TLabel")
            self.carrier_type_label.base_style = style
            self.carrier_type_label.configure(style=style)

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
        # to every formula behind it - which is what method versions
        # are for.
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
            "thickness_nm": thickness.text,
        })

        self._set_calc_stale(False)
        self.log(f"{carrier}: n={self.ns_var.get()}, mu={self.mu_var.get()}, "
                 f"rho={self.rho_var.get()}")
        self.log(f"  (signed: n_s={ns_cm2:.6g}, mu={mobility:.6g})")
        self.log(f"{self._calc_result.method_tag} -> "
                 f"{self._calc_result.result_id}")

    def take_rs_from_vdp(self):
        """Fill the Rs box from the Van der Pauw tab's result.

        Hall needs a sheet resistance it cannot measure itself, so a Van
        der Pauw run on the same mounted sample comes first - always,
        which is why the two share a window at all. What crosses is the
        `DerivedResult`, not a number: the value goes into the box and
        the result's identity is remembered alongside it, so a Hall
        carrier density can name the Van der Pauw runs four steps back
        that produced its Rs.

        This replaces reading a saved CSV back off disk. The file was
        the interface while these were two separately launched windows;
        it is not one any more, and keeping it as a fallback would have
        left two paths to the same number that could disagree.
        """
        provider = self.app.provider_of("sheet_resistance", exclude=self)
        if provider is None:
            messagebox.showerror(
                "No sheet resistance available",
                "This window has no Van der Pauw tab to take a sheet "
                "resistance from.\n\nOpen the combined Van der Pauw + "
                "Hall window, or type the value into the Rs box.")
            return

        try:
            supplied = provider.provide("sheet_resistance")
        except CalculationRefused as e:
            self.log("Rs not taken:", e.reason)
            messagebox.showerror("Cannot take Rs", str(e))
            return

        # The box is what the calculation reads, so the box is the value
        # of record. Nine significant figures, matching the voltages and
        # the saved header - see VOLTAGE_FIGURES for why the precision
        # is not cosmetic. The rounded value is kept so that "has this
        # been typed over?" is an exact comparison later.
        text = f"{supplied.value:.9g}"
        self.calc_Rs_var.set(text)
        self._rs_upstream = supplied.as_upstream()
        self._rs_upstream_value = float(text)

        self.log(f"Rs = {supplied.value:.6g} {supplied.unit} from "
                 f"{provider.tab_label} "
                 f"({self._rs_upstream.result_id})")
        self._refresh_rs_source()
        self._warn_on_upstream_mismatch(supplied)

    def _warn_on_upstream_mismatch(self, supplied):
        """Flag a carried-over Rs that looks like it belongs elsewhere.

        Nothing here blocks the transfer: loading a value into a box is
        not a calculation, and the refusal belongs
        where the number is *used*, which is `validate()`.

        **Only one of the original three checks survives, and the other
        two were removed for different reasons.**

        Thickness went because it is a single shared variable on the
        session strip: a Hall panel set to a different thickness
        from the Van der Pauw run it is quoting is no longer a state the
        software can be in.

        The sample name went because it turned out to be *unreachable*,
        which is worse than unnecessary. Van der Pauw's own staleness
        signature includes the sample name, so renaming the strip makes
        its result stale, and `provide()` refuses a stale result before
        this is ever called. The mismatch is therefore already handled -
        and handled more strictly than a warning. Written and then found
        by the test that was supposed to prove it fired; a check that
        cannot fire teaches you the case is covered by *it*, and the day
        the staleness rule changes, nobody looks here.

        The stage temperature stays, and is the one worth keeping. It is
        not a transcription error but physical drift: carrier density
        and mobility are strongly temperature-dependent, and an Rs
        measured at 25 °C applied to a Hall run at 80 °C describes two
        different samples as far as the physics is concerned. It is also
        the one thing here that no signature watches, because the stage
        is not a calculation input.
        """
        if not (supplied.stage_temps_c and self.temp_ctrl.is_connected()):
            return
        status = self.temp_ctrl.status()
        if status.temp_c is None:
            return
        worst = max(supplied.stage_temps_c,
                    key=lambda t: abs(t - status.temp_c))
        if abs(worst - status.temp_c) <= 1.0:
            return

        line = (f"Stage temperature differs: the Van der Pauw runs were at "
                f"{worst:.1f} °C, the stage now reads {status.temp_c:.1f} °C.")
        self.log("Note:", line)
        messagebox.showwarning(
            "Check this is the right sheet resistance",
            "Rs was filled in, but it doesn't match the current "
            f"set-up:\n\n- {line}\n\nThe value has been carried over anyway.")

    # ---- where the Rs in the box came from ----
    def rs_upstream(self):
        """The Van der Pauw result behind the Rs box, or None.

        None as soon as the box no longer holds the number that was
        carried over. Same all-or-nothing rule the measured voltages
        follow: a provenance chain that is half true reads exactly like
        one that is whole, so typing over the box drops the citation
        rather than keeping a source that no longer describes the value.
        """
        if self._rs_upstream is None:
            return None
        typed = _float_or_none(self.calc_Rs_var.get())
        if typed is None or typed != self._rs_upstream_value:
            return None
        return self._rs_upstream

    def _refresh_rs_source(self):
        """One line under the Rs box saying where the number came from."""
        if not hasattr(self, "rs_source_var"):
            return
        upstream = self.rs_upstream()
        if upstream is None:
            self.rs_source_var.set(
                "Rs typed by hand" if self.calc_Rs_var.get().strip() else "")
        else:
            self.rs_source_var.set(
                f"Rs from {upstream.method_tag} \u00b7 "
                f"{upstream.sample_label} \u00b7 "
                f"{len(upstream.run_ids)} run(s)")

    # `on_close()` is inherited. It cancelled the run in flight and
    # nothing else, which is now what `Experiment.on_close()` does for
    # every experiment - see the note there about the tab that had no
    # override at all.


def _float_or_none(text):
    """float() that returns None instead of raising, for optional or
    possibly-blank entry boxes."""
    try:
        return float(str(text).strip())
    except (ValueError, TypeError):
        return None
