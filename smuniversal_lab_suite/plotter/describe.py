"""
The details shown beside the plot: what a file is, what a run was, and
what in it deserves a second look.

Each experiment has a short list of the settings that decide how its
data should be read - integration time, sensing, sweep kind, what the
compliance really was - shown first and with units. Every other column
still appears below them under "All settings", so nothing in the file is
hidden by being uncurated.

Checks, not verdicts
--------------------
A check states something the file itself records and a reader could
miss: fewer points returned than requested, a compliance limit applied
that differs from the one asked for, samples that landed late. It never
applies a threshold of its own - "R² looks low" would be this tool's
opinion presented as a property of the data.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from smuniversal_lab_suite.plotter import detect
from smuniversal_lab_suite.plotter.reader import (
    StoredFile,
    StoredRun,
    format_number,
)

PREFIXES = ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""), (1e-3, "m"),
            (1e-6, "µ"), (1e-9, "n"), (1e-12, "p"), (1e-15, "f"))


def eng(value: float | None, unit: str = "", digits: int = 5) -> str:
    """A number with an SI prefix: `0.0001, "A"` -> `100 µA`.

    A unitless number gets more figures, because the unitless numbers
    here are mostly ratios such as R², where `1` would hide `0.9999994`.
    """
    if value is None:
        return ""
    if not math.isfinite(value):
        return f"{value} {unit}".strip()
    if not unit:
        return format_number(value) if value == int(value) \
            else f"{value:.{digits + 3}g}"
    if value == 0:
        return f"0 {unit}"
    magnitude = abs(value)
    for scale, prefix in PREFIXES:
        if magnitude >= scale * 0.9999999:
            return f"{value / scale:.{digits}g} {prefix}{unit}"
    scale, prefix = PREFIXES[-1]
    return f"{value / scale:.{digits}g} {prefix}{unit}"


@dataclass(frozen=True)
class Fact:
    label: str
    value: str
    key: str = ""
    flagged: bool = False


#: (column, label, unit). A unit of `source` or `measure` is resolved
#: from the run's mode, because `start` is volts on one run and amps on
#: the next.
CURATED = {
    detect.IV_SWEEP.key: (
        ("dataset", "Dataset", ""),
        ("mode", "Mode", ""),
        ("start", "Start", "source"),
        ("stop", "Stop", "source"),
        ("points_requested", "Points requested", ""),
        ("points_returned", "Points returned", ""),
        ("delay_s", "Delay per point", "s"),
        ("compliance", "Compliance requested", "measure"),
        ("compliance_applied", "Compliance applied", "measure"),
        ("sensing", "Sensing", ""),
        ("nplc", "Integration (NPLC)", ""),
        ("sweep_kind", "Sweep kind", ""),
        ("output_off_mode", "Output off", ""),
        ("cycle", "Cycle", ""),
        ("standby", "Between cycles", ""),
        ("bias_gap_s", "Bias interrupted for", "s"),
        ("resistance_ohm", "Fitted resistance", "Ω"),
        ("fit_r_squared", "Fit R²", ""),
        ("stage_temp_C", "Stage temperature", "°C"),
        ("compliance_suspected", "Compliance suspected", ""),
    ),
    detect.FIXED_SOURCE.key: (
        ("dataset", "Dataset", ""),
        ("source_mode", "Sourcing", ""),
        ("level", "Level", "source"),
        ("measured_quantity", "Measuring", ""),
        ("compliance", "Compliance requested", "measure"),
        ("compliance_applied", "Compliance applied", "measure"),
        ("duration_requested_s", "Duration requested", "s"),
        ("interval_requested_s", "Interval requested", "s"),
        ("interval_achieved_s", "Interval achieved", "s"),
        ("samples_nominal", "Samples expected", ""),
        ("samples_collected", "Samples collected", ""),
        ("overruns", "Late samples", ""),
        ("worst_overrun_s", "Latest by", "s"),
        ("compliance_watched", "Compliance watched", ""),
        ("compliance_trips", "Compliance trips", ""),
        ("no_reading_n", "Samples with no reading", ""),
        ("ended_by", "Ended by", ""),
        ("ended_detail", "End detail", ""),
        ("sensing", "Sensing", ""),
        ("nplc", "Integration (NPLC)", ""),
        ("ranges", "Ranges", ""),
        ("timebase", "Timebase", ""),
        ("compliance_suspected", "Compliance suspected", ""),
    ),
    detect.OSSILA_4PP.key: (
        ("dataset", "Dataset", ""),
        ("sweep_mode", "Sweep", ""),
        ("points", "Points", ""),
        ("points_fitted", "Points fitted", ""),
        ("reversals", "Reversals", ""),
        ("delay_s", "Delay", "s"),
        ("voltage_limit_V", "Voltage limit", "V"),
        ("probe_spacing_mm", "Probe spacing (mm)", ""),
        ("width_mm", "Width (mm)", ""),
        ("length_mm", "Length (mm)", ""),
        ("thickness_um", "Thickness (µm)", ""),
        ("resistance_ohm", "Fitted resistance", "Ω"),
        ("fit_r_squared", "Fit R²", ""),
        ("thickness_factor", "Thickness factor", ""),
        ("geometry_factor", "Geometry factor", ""),
        ("sheet_resistance_ohm_sq", "Sheet resistance", "Ω/□"),
        ("resistivity_ohm_m", "Resistivity", "Ω·m"),
        ("conductivity_S_per_m", "Conductivity", "S/m"),
        ("notes", "Notes", ""),
        ("compliance_suspected", "Compliance suspected", ""),
    ),
    detect.VAN_DER_PAUW.key: (
        ("dataset", "Dataset", ""),
        ("position", "Position", ""),
        ("level_A", "Current", "A"),
        ("points_requested", "Points per polarity", ""),
        ("delay_s", "Delay", "s"),
        ("compliance_v", "Voltage compliance", "V"),
        ("compliance_applied", "Compliance applied", "V"),
        ("R_pos_ohm", "R at +I", "Ω"),
        ("R_neg_ohm", "R at −I", "Ω"),
        ("R_ave_ohm", "R average", "Ω"),
        ("R_fit_ohm", "R from fit", "Ω"),
        ("fit_intercept", "Fit intercept", "V"),
        ("fit_r_squared", "Fit R²", ""),
        ("thickness_nm", "Thickness (nm)", ""),
        ("nplc", "Integration (NPLC)", ""),
        ("ranges", "Ranges", ""),
        ("stage_temp_C", "Stage temperature", "°C"),
        ("compliance_suspected", "Compliance suspected", ""),
    ),
    detect.HALL.key: (
        ("dataset", "Dataset", ""),
        ("position", "Position", ""),
        ("b_polarity", "Field polarity", ""),
        ("level_A", "Current", "A"),
        ("points_requested", "Points per polarity", ""),
        ("delay_s", "Delay", "s"),
        ("compliance_v", "Voltage compliance", "V"),
        ("compliance_applied", "Compliance applied", "V"),
        ("V_plus_V", "V at +I", "V"),
        ("V_minus_V", "V at −I", "V"),
        ("I_mean_pos_A", "Mean +I", "A"),
        ("I_mean_neg_A", "Mean −I", "A"),
        ("thickness_nm", "Thickness (nm)", ""),
        ("nplc", "Integration (NPLC)", ""),
        ("stage_temp_C", "Stage temperature", "°C"),
        ("compliance_suspected", "Compliance suspected", ""),
    ),
}

#: Identifiers: kept out of "All settings", shown under "Identity".
IDENTITY_KEYS = ("run_timestamp", "meas_number", "sample_label",
                 "sample_id", "run_id", "record_id")


def _mode_units(kind_key: str, run: StoredRun) -> tuple[str, str]:
    """(sourced unit, measured unit) for this run."""
    if kind_key == detect.IV_SWEEP.key:
        mode = run.text("mode")
        if mode == "source_voltage":
            return "V", "A"
        if mode == "source_current":
            return "A", "V"
    if kind_key == detect.FIXED_SOURCE.key:
        mode = run.text("source_mode")
        if mode == "voltage":
            return "V", "A"
        if mode == "current":
            return "A", "V"
    return "", ""


#: Column-name endings and the unit they spell, longest first so
#: `_ohm_per_sq` is not read as `_ohm`. This is the suite's own naming
#: convention (house rule 5), so a column nobody curated still gets a
#: unit - and one that does not follow it gets none rather than a guess.
SUFFIX_UNITS = (
    ("_ohm_per_sq", "Ω/□"), ("_ohm_sq", "Ω/□"),
    ("_ohm_cm", "Ω·cm"), ("_ohm_m", "Ω·m"),
    ("_S_per_m", "S/m"), ("_ohm", "Ω"), ("_V", "V"), ("_A", "A"),
    ("_s", "s"), ("_C", "°C"), ("_T", "T"),
)


def unit_of(kind_key: str, run: StoredRun, key: str) -> str:
    """The unit of a run's setting: curated first, then the name's suffix.

    Curated units of `source` or `measure` resolve from the run's mode,
    so `start` is volts on one IV run and amps on the next.
    """
    for curated_key, _label, unit in CURATED.get(kind_key, ()):
        if curated_key == key:
            source_unit, measure_unit = _mode_units(kind_key, run)
            return {"source": source_unit,
                    "measure": measure_unit}.get(unit, unit)
    return suffix_unit(key)


def suffix_unit(key: str) -> str:
    for suffix, unit in SUFFIX_UNITS:
        if key.endswith(suffix):
            return unit
    return ""


def label_of(kind_key: str, key: str) -> str:
    """The curated label for a column, or the column name itself."""
    for curated_key, label, _unit in CURATED.get(kind_key, ()):
        if curated_key == key:
            return label
    return key


def _value(run: StoredRun, key: str, unit: str) -> str:
    number = run.number(key)
    if number is not None:
        return eng(number, unit)
    return run.text(key)


def file_sections(stored: StoredFile, duplicates: int = 0):
    """[(heading, [Fact])] describing a whole file."""
    about = [
        Fact("Experiment", stored.kind.name),
        Fact("Identified by", stored.detection.method),
        Fact("Sample", stored.sample),
        Fact("Saved", stored.header.get("saved",
                                        stored.header.get("generated", ""))),
    ]
    if not stored.is_summary:
        about.append(Fact("Runs", str(len(stored.runs))))
    if duplicates:
        about.append(Fact("Already open elsewhere",
                          f"{duplicates} run(s), shown once", flagged=True))
    about += [
        Fact("Schema", str(stored.schema)),
        Fact("Build", stored.header.get("build_id", "")),
        Fact("Save id", stored.header.get("save_id", "")),
    ]
    sections = [("File", about)]
    if stored.calculated:
        sections.append(("Calculated", [
            Fact(key, value, key) for key, value in stored.calculated.items()
        ]))
    attention = [Fact("Note", note, flagged=True)
                 for note in stored.detection.notes + tuple(stored.warnings)]
    if attention:
        sections.insert(0, ("Attention", attention))
    return sections


def run_sections(stored: StoredFile, run: StoredRun):
    """[(heading, [Fact])] describing one run."""
    kind = stored.kind.key
    source_unit, measure_unit = _mode_units(kind, run)
    shown = set(IDENTITY_KEYS)
    main = []
    for key, label, unit in CURATED.get(kind, ()):
        if key not in run.settings:
            continue
        shown.add(key)
        unit = {"source": source_unit, "measure": measure_unit}.get(unit,
                                                                     unit)
        value = _value(run, key, unit)
        if value:
            main.append(Fact(label, value, key))

    checks = [Fact("Check", text, flagged=True)
              for text in run_checks(stored, run)]
    identity = [Fact(key, run.text(key), key) for key in IDENTITY_KEYS
                if key != "record_id" and run.text(key)]
    identity.append(Fact("record_id", run.record_id, "record_id"))
    rest = [Fact(key, run.text(key), key) for key in run.settings
            if key not in shown and run.text(key)]

    sections = []
    if checks:
        sections.append(("Checks", checks))
    sections.append((f"Run: {run.label}", main))
    sections.append(("Readings", [
        Fact("Count", str(len(run))),
        Fact("Columns", ", ".join(run.readings)),
    ]))
    sections.append(("Identity", identity))
    if rest:
        sections.append(("All settings", rest))
    return sections


def _differs(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    return not math.isclose(a, b, rel_tol=1e-9, abs_tol=0.0)


def run_checks(stored: StoredFile, run: StoredRun) -> list[str]:
    """Things the file records that a reader could easily miss."""
    kind = stored.kind.key
    out = []

    blank = {key: int((~np.isfinite(values)).sum())
             for key, values in run.readings.items()
             if values.dtype.kind == "f"}
    for key in ("voltage_V", "current_A"):
        if blank.get(key):
            out.append(f"{blank[key]} reading(s) with no {key}.")
    errors = run.readings.get("error")
    if errors is not None:
        failed = sum(1 for e in errors if str(e).strip())
        if failed:
            out.append(f"{failed} reading(s) recorded an error.")

    if _differs(run.number("compliance"), run.number("compliance_applied")):
        out.append(
            f"Compliance applied ({run.text('compliance_applied')}) differs "
            f"from the one requested ({run.text('compliance')}).")

    if kind == detect.IV_SWEEP.key:
        requested = run.number("points_requested")
        returned = run.number("points_returned")
        if requested is not None and returned is not None \
                and returned < requested:
            out.append(f"{format_number(returned)} of "
                       f"{format_number(requested)} points returned.")
        gap = run.number("bias_gap_s")
        if gap:
            out.append(f"Bias was interrupted for {eng(gap, 's')} before "
                       f"this sweep.")
        if run.text("fitted") == "yes" and run.number("fit_slope") is None:
            out.append("A fit was asked for but none was saved.")

    if kind == detect.FIXED_SOURCE.key:
        for key, text in (("overruns", "sample(s) landed late"),
                          ("compliance_trips", "compliance trip(s)"),
                          ("no_reading_n", "sample(s) with no reading")):
            count = run.number(key)
            if count:
                out.append(f"{format_number(count)} {text}.")
        nominal = run.number("samples_nominal")
        collected = run.number("samples_collected")
        if nominal is not None and collected is not None \
                and collected < nominal:
            out.append(f"{format_number(collected)} of "
                       f"{format_number(nominal)} samples collected.")
        ended = run.text("ended_by")
        if ended and ended != "duration":
            detail = run.text("ended_detail")
            out.append(f"Ended by {ended}" + (f": {detail}" if detail
                                               else "."))
    return out


def compare_rows(pairs):
    """Settings side by side for several runs.

    `pairs` is [(StoredFile, StoredRun)]. Returns rows of (key, label,
    [text per run], differs). Curated keys come first, in their
    experiment's order and under their label; a key differs when the
    runs do not all hold the same value, numbers compared with a
    tolerance (house rule 9).
    """
    order: list[str] = []
    labels: dict[str, str] = {}
    for stored, _run in pairs:
        for key, label, _unit in CURATED.get(stored.kind.key, ()):
            if key not in order:
                order.append(key)
                labels[key] = label
    for _stored, run in pairs:
        for key in run.settings:
            if key not in order and key not in IDENTITY_KEYS:
                order.append(key)

    rows = []
    for key in order:
        texts = [run.text(key) for _stored, run in pairs]
        if not any(texts):
            continue
        # Compared among the runs that hold a value. A setting one
        # experiment does not have is a blank cell, not a difference:
        # otherwise every row of an IV-against-4PP comparison is marked
        # and the mark stops meaning anything.
        held = [(text, run.number(key))
                for text, (_stored, run) in zip(texts, pairs) if text]
        numbers = [number for _text, number in held]
        if all(n is not None for n in numbers):
            first = numbers[0]
            differs = any(_differs(first, n) for n in numbers[1:])
        else:
            differs = len({text for text, _n in held}) > 1
        rows.append((key, labels.get(key, key), texts, differs))
    return rows
