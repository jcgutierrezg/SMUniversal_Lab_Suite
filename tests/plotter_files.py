"""
Saved files for the plotter tests, built by the real file builder.

Shared by bare-name import, the way `vdp_harness.py` is. The metadata
keys follow what each experiment writes; `test_plotter_real_files.py`
is what proves those keys are still current.
"""
import datetime

from smuniversal_lab_suite.core.run_store import Run, build_sample_csv
from smuniversal_lab_suite.plotter.reader import parse

IV_TITLE = "IV sweep"
FIXED_TITLE = "Fixed sourcing vs time"

_counter = [0]


def _stamp(run, minutes):
    run.timestamp = (datetime.datetime(2026, 9, 16, 12, 0)
                     + datetime.timedelta(minutes=minutes)).isoformat()
    return run


def iv_run(dataset="fwd", resistance=1000.0, points=11, mode="voltage",
           minutes=0, cycle="", run_id="iv-1", **extra):
    _counter[0] += 1
    readings = []
    for i in range(points):
        v = -0.5 + i * (1.0 / max(points - 1, 1))
        readings.append({"point": i + 1, "voltage_V": v,
                         "current_A": v / resistance})
    slope, intercept = ((1 / resistance, 0.0) if mode == "voltage"
                        else (resistance, 0.0))
    metadata = {
        "meas_number": _counter[0], "sample_label": "filmA",
        "run_id": run_id, "dataset": dataset, "mode": f"source_{mode}",
        "start": -0.5, "stop": 0.5, "points_requested": points,
        "points_returned": points, "delay_s": 0.01, "compliance": 0.01,
        "compliance_applied": 0.01, "sensing": "4-wire", "nplc": 1.0,
        "sweep_kind": "hardware", "fitted": "yes", "cycle": cycle,
        "bias_gap_s": "", "fit_slope": slope, "fit_intercept": intercept,
        "fit_r_squared": 0.9999, "resistance_ohm": resistance,
    }
    metadata.update(extra)
    return _stamp(Run("filmA", metadata, readings), minutes)


def fixed_run(dataset="hold", samples=6, measured="current", tripped=(),
              temperature=None, minutes=0, **extra):
    _counter[0] += 1
    readings = []
    for i in range(samples):
        reading = {"sample_index": i + 1, "reading_id": f"fs#{i}",
                   "time_s": 0.1 * i, "read_s": 0.01,
                   "voltage_V": 0.1, "current_A": 1e-4 + 1e-7 * i,
                   "compliance": "yes" if i in tripped else "no"}
        if temperature is not None:
            reading["stage_temp_C"] = temperature + 0.1 * i
        readings.append(reading)
    metadata = {
        "meas_number": _counter[0], "sample_label": "filmA",
        "run_id": f"fs-{_counter[0]}", "dataset": dataset,
        "source_mode": "voltage" if measured == "current" else "current",
        "measured_quantity": measured, "level": 0.1, "compliance": 0.01,
        "duration_requested_s": 0.5, "interval_requested_s": 0.1,
        "interval_achieved_s": 0.1, "samples_nominal": samples,
        "samples_collected": samples, "overruns": 0,
        "compliance_trips": len(tripped), "no_reading_n": 0,
        "ended_by": "duration",
    }
    metadata.update(extra)
    return _stamp(Run("filmA", metadata, readings), minutes)


def stored(runs, title=IV_TITLE, path="filmA_iv_sweep.csv"):
    return parse(build_sample_csv("filmA", runs, title), path)


def write(tmp_path, name, runs, title=IV_TITLE):
    path = tmp_path / name
    path.write_text(build_sample_csv("filmA", runs, title),
                    encoding="utf-8", newline="")
    return str(path)
