"""What Van der Pauw and Hall share: a current-sourced, four-contact run.

Both experiments put a current through two corners of a film and read
the voltage across the other two, from the same setup panel, on the
same stage, with the same thickness box. Review A-08 found the parts of
that which do not depend on what happens to the readings copied into
both, identical but for their comments. They are here once.

Both take a run as a current sweep through zero, from Start to Stop,
like the IV sweep: `_sweep()` here. Its two halves - the readings at
negative current and at positive current - stand where the two polarity
blocks used to, so everything after the run is unchanged.

What stays in each experiment is what differs between them: what is
done with the two halves, and the calculation. Van der Pauw averages the
polarities into one resistance; Hall keeps them apart, because reversing
the current is one of the two reversals its eight-term average depends
on.
"""
import datetime
import math
from tkinter import messagebox

from matplotlib.ticker import EngFormatter, MaxNLocator

from smuniversal_lab_suite.core.calculation import InputValue
from smuniversal_lab_suite.core.gui.plot_panel import draw_datasets
from smuniversal_lab_suite.core.gui.widgets import (
    apply_compliance,
    apply_high_z,
    apply_nplc,
)
from smuniversal_lab_suite.core.limits import parse_si
from smuniversal_lab_suite.core.ranges import AUTO, RangePlan
from smuniversal_lab_suite.core.units import m_to_nm, nm_to_m
from smuniversal_lab_suite.core.validation import (
    ValidationError,
    positive_length,
    si_level,
    whole_number,
)
from smuniversal_lab_suite.experiments.base_experiment import Experiment
from smuniversal_lab_suite.experiments.iv_sweep.iv_math import fit_sweep


class FourContactExperiment(Experiment):
    """Shared behaviour of the Van der Pauw and Hall tabs.

    Expects the widgets their setup and results panels build:
    `start_var`, `stop_var`, `points_var`, `delay_ms_var`,
    `volt_range_var`, `vlim_var` and `tree`, and the session strip's
    `thickness_entry_var`.
    """

    #: The sweep a new window offers: -1 uA to +1 uA in 80 points, 100 ms
    #: at each. Small enough not to heat a film, and 80 points put 40 in
    #: each half - which is what the averaging of the old blocks did.
    DEFAULT_START = "-1 µA"
    DEFAULT_STOP = "1 µA"
    DEFAULT_POINTS = "80"
    DEFAULT_DELAY_MS = "100"

    # This measurement is defined by sourcing into the sample: Van der
    # Pauw and Hall both push a known current through a passive film and
    # measure the voltage it develops. An instrument that cannot push is
    # refused at connect, by capability rather than by type - see
    # `Experiment.ROLE_REQUIRES`.
    ROLE_REQUIRES = {"source": ("sourcing",)}

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

    def get_sweep_amps(self):
        """Start and stop currents from their boxes, in amps.

        Typed like any other level in the suite - '-1u', '-1 µA',
        '-1e-6' - and refused when either cannot be read, or when the
        sweep does not cross zero. A sweep that stays on one side has
        one polarity, and both calculations are built on having two:
        the reversal is what cancels the contacts' thermoelectric
        offsets.
        """
        start = si_level(self.start_var.get(), "Start current", unit="A")
        stop = si_level(self.stop_var.get(), "Stop current", unit="A")
        if not min(start, stop) < 0 < max(start, stop):
            raise ValidationError(
                "Start current",
                "The sweep has to cross zero - one end below it and one "
                "above - so that both current polarities are measured. "
                f"Got {start:g} A to {stop:g} A.")
        return start, stop

    def get_points(self):
        """Points in the sweep. At least two: one at each end, which is
        the original's single reading at -I and at +I. That is the form
        an instrument that cannot source near zero - the U2722A on its
        widest range - can still take."""
        return whole_number(self.points_var.get(), "Points", minimum=2)

    def nominal_mean_current(self):
        """The mean current magnitude of the sweep the form describes -
        what a run's two halves average to, before anything is measured.
        Raises `ValidationError` while the form cannot be read."""
        start, stop = self.get_sweep_amps()
        n = self.get_points()
        step = (stop - start) / (n - 1)
        levels = [abs(start + step * i) for i in range(n)]
        tiny = max(abs(start), abs(stop)) * 1e-9
        levels = [level for level in levels if level > tiny]
        return sum(levels) / len(levels)

    # ---- thickness ----
    # Typed with a suffix on the session strip, read in nanometres when
    # there is none. Everything below goes through `thickness_nm()`, so
    # the run, the calculation and the staleness trace cannot disagree
    # about what '180' means.
    def thickness_nm(self):
        """The session strip's thickness, in nanometres. Raises
        `ValidationError` when it cannot be read."""
        return positive_length(self.thickness_entry_var.get(), "Thickness",
                               unit="nm")

    def thickness_m(self):
        """The same thickness in metres, for the parameters and maths."""
        return nm_to_m(self.thickness_nm())

    def _thickness_input(self):
        """The thickness as a calculation input.

        The text is the value in nanometres rather than what was typed,
        so '0.18 µm' and '180' are one input and the header reads
        `180 nm (1.8e-07 m)` either way.
        """
        nm = self.thickness_nm()
        return InputValue(nm_to_m(nm), "m", f"{nm:.12g}", "nm")

    def _thickness_signature(self):
        """The thickness as the staleness trace samples it.

        The same text `_thickness_input()` puts in the result, so an
        unedited box is never stale. Raw text while the box does not
        parse yet - a trace fires on every keystroke.
        """
        try:
            return f"{self.thickness_nm():.12g}"
        except ValidationError:
            return self.thickness_entry_var.get().strip()

    @staticmethod
    def _thickness_nm_column(params):
        """A run's thickness for its `thickness_nm` column, without the
        residue a metres-to-nanometres round trip leaves behind."""
        return float(f"{m_to_nm(params.thickness_m):.12g}")

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
        # The wait at each point is the host's, in `_sweep()`: a run.sleep
        # that Stop cuts short. An instrument-side delay as well would
        # double every one of eighty waits.
        smu.set_source_delay(0.0)

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

    def _sweep(self, run, smu, params, polarity_key, extra=None):
        """Step the current from start to stop, reading at each level.
        Background thread, with the output already on.

        Returns `{"pos": [(v, i), ...], "neg": [...]}` - the readings in
        each half of the sweep, which each experiment then treats exactly
        as it treated the two polarity blocks. A level at zero, when the
        points put one there, is read and kept in the file but belongs
        to neither half.

        `polarity_key` is the column each experiment has always named
        the polarity with, and `extra(v, i)` adds the columns of its
        own. Every reading goes onto the run context, so a cancelled
        run's readings are discarded with it.
        """
        levels = params.levels_a
        tiny = params.level_a * 1e-9
        halves = {"pos": [], "neg": []}
        for n, level in enumerate(levels, start=1):
            label = ("pos" if level > tiny else
                     "neg" if level < -tiny else "zero")
            run.checkpoint(f"point {n}")
            if not self.app.is_connected("source"):
                break
            smu.set_current_level(level)
            # `run.sleep` rather than `time.sleep`: it wakes early when
            # cancelled, so Stop during a settle is felt at once.
            if params.delay_s > 0:
                run.sleep(params.delay_s, stage=f"settle point {n}")
            reading = {"point": n, polarity_key: label, "level_A": level,
                       "timestamp": datetime.datetime.now().isoformat()}
            try:
                v, current = smu.measure()
            except Exception as e:
                self.log(f"Point {n}/{len(levels)} error: {e}")
                reading.update({"voltage_V": "", "current_A": "",
                                "error": str(e)})
                if extra is not None:
                    reading.update({k: "" for k in extra(None, None)})
                run.add_reading(reading)
                run.record_error(str(e))
                continue
            self.log(f"Point {n}/{len(levels)} I={current} V={v}")
            reading.update({"voltage_V": v, "current_A": current,
                            "error": ""})
            if extra is not None:
                reading.update(extra(v, current))
            run.add_reading(reading)
            if label in halves and v is not None and current is not None:
                halves[label].append((v, current))
            self.app.ui(self.progress_var.set,
                        f"point {n}/{len(levels)}")
        return halves

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
        """Click in the checkbox column toggles that row's ☑/☐, and
        redraws: ticked rows are what the plot shows."""
        if self.tree.identify("region", event.x, event.y) != "tree":
            return
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        current = self.tree.item(row_id, "text") or ""
        self.tree.item(row_id, text="☐" if current == "☑" else "☑")
        self.refresh_plot()

    def delete_ticked(self):
        """Inherited behaviour, plus dropping the curves from the plot."""
        super().delete_ticked()
        self.refresh_plot()

    def clear_output(self):
        """Inherited behaviour, plus clearing the plot."""
        super().clear_output()
        self.refresh_plot()

    # ---- the V-I plot ----
    #: What labels a run in the plot legend, after its measurement
    #: number: the results-table column holding its position.
    PLOT_LABEL_COLUMNS = (1,)

    def refresh_plot(self):
        """Redraw the V-I plot from the stored runs. Main thread only.

        Ticked rows are plotted; with nothing ticked, the newest run is,
        the same rule as the IV sweep. Each run is its sweep, with the
        straight line through it: the slope is the run's resistance and
        the intercept the offset the two polarities cancel, so a run
        whose points leave the line is visible before its numbers are
        copied. Drawn from the run store rather than from a second copy
        of the data, so a deleted run cannot linger on the axes.
        """
        if not hasattr(self, "plot_ax") or not hasattr(self, "tree"):
            return
        items = [i for i in self.tree.get_children()
                 if self.run_store.get(i) is not None]
        ticked = set(self.ticked_items())
        shown = [i for i in items if i in ticked] or items[-1:]
        if not self.plot_overlap_var.get():
            shown = shown[-1:]

        datasets = []
        for item in shown:
            record = self.run_store.get(item)
            meta = record.metadata
            currents, voltages = vi_points(record.readings)
            slope, intercept, r_squared, resistance = fit_sweep(
                currents, voltages, "current")
            fit = None
            if None not in (slope, intercept, r_squared):
                fit = (slope, intercept, r_squared)
            values = self.tree.item(item, "values")
            label = " ".join(str(values[c]) for c in self.PLOT_LABEL_COLUMNS)
            datasets.append({
                "label": f"#{meta.get('meas_number', '')} {label}",
                "x": currents,
                "y": voltages,
                "fit": fit,
                "resistance": resistance,
            })

        draw_datasets(self, datasets, xlabel="Current",
                      ylabel="Voltage", show_fit=True, fit_each=True)
        # Engineering prefixes on the ticks: a microamp sweep otherwise
        # labels its axis -0.000001 ... and the labels collide.
        self.plot_ax.xaxis.set_major_formatter(EngFormatter(unit="A"))
        self.plot_ax.yaxis.set_major_formatter(EngFormatter(unit="V"))
        # Hall's plot sits in the narrow middle column, where nine
        # engineering labels along the current axis run into each other.
        self.plot_ax.xaxis.set_major_locator(MaxNLocator(5))
        self.plot_canvas.draw_idle()


def vi_points(readings):
    """(currents, voltages) from the readings that have both.

    A reading that errored carries blanks, and is left out of the fit
    and the plot rather than drawn at zero.
    """
    currents, voltages = [], []
    for reading in readings:
        v, i = reading.get("voltage_V"), reading.get("current_A")
        if isinstance(v, (int, float)) and isinstance(i, (int, float)):
            currents.append(i)
            voltages.append(v)
    return currents, voltages


def half_means(half):
    """One half of a sweep as its mean voltage and mean current, or
    (None, None) when it has no readings."""
    if not half:
        return None, None
    return (math.fsum(v for v, _i in half) / len(half),
            math.fsum(i for _v, i in half) / len(half))
