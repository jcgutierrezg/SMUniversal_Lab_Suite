"""
Does a readback report the instrument, or repeat the question?

    uv run python tools/bench_readback.py --address GPIB0::9::INSTR
    uv run python tools/bench_readback.py --transport demo --scripted

Run `tools/smu_checkup.py` first. This tool does not repeat it; it
answers the one question the checkup cannot ask itself.

Why this needs a person
-----------------------
`core/readback.py` has five states, and the difference between two of
them is not in the reply. `UNVERIFIED` and `CONFIRMED` both mean the
instrument agreed with what it was asked for. What separates them is
whether anyone has established that the query reports a *physical
state* rather than echoing the last value written to it.

Software cannot settle that alone, and that is not a gap in the
software. If the driver sets a range and then asks what the range is, an
instrument that stores the written value and plays it back is
indistinguishable from one that interrogates its own hardware. Both
answer correctly, every time, for as long as nobody sets the range any
other way. That is the shape of fault 19 - a probe asked where the
answer is already known - and asking it more often does not help.

So the discriminating leg is the front panel. A value dialled in by hand
never passes through the bus, so a query that reports it is reading
hardware.

The GSM-20H10 is why this is not paranoia. On 2026-08-20 `OUTP?` on that
instrument answered `0` three times in a row with the output
demonstrably on. A readback that lies is worse than none, because it
produces confident reassurance about exactly the thing it exists to
check.

The three legs
--------------
1. **Front panel.** The operator sets a value by hand; the query must
   name it. Discriminating: nothing the software did could have told the
   instrument to say this.
2. **Bus tracking.** The driver sets a different value; the query must
   follow. Catches a query that returns a constant, which would pass
   leg 1 by luck if the constant happened to match.
3. **Bus tracking again**, to a third value. Catches a query that
   latches the first thing it is told, which passes legs 1 and 2.

All three must pass before a subject is reported verifiable. One is not
evidence and two are not either.

What to do with the result
--------------------------
A subject that passes all three legs is one whose `*_READBACK_TRUSTED`
flag may be set on that driver, which promotes its `UNVERIFIED` warnings
to `CONFIRMED` passes.

**Nothing here sets that flag.** This tool prints what it established
and a person decides, because the flag is a standing claim about a model
and this is the record of one session with one unit.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import readback as _readback  # noqa: E402
from drivers.registry import driver_for_idn  # noqa: E402
from tools.bench_envelope import TRANSPORTS  # noqa: E402

#: What this tool can put to an instrument: the axis name the checkup
#: uses, how to read it, how to set it over the bus, and which declared
#: ladder the bus legs pick their values from.
SUBJECTS = (
    ("measure_current", "read_measure_current_range",
     "_apply_measure_current_range", "current_ranges", "A"),
    ("measure_voltage", "read_measure_voltage_range",
     "_apply_measure_voltage_range", "voltage_ranges", "V"),
    ("source_current", "read_source_current_range",
     "_apply_source_current_range", "current_ranges", "A"),
    ("source_voltage", "read_source_voltage_range",
     "_apply_source_voltage_range", "voltage_ranges", "V"),
)


def ask(prompt, scripted=None):
    """One line from the operator, or from a script under test."""
    if scripted is not None:
        return scripted
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def readable_subjects(driver):
    """The subjects this driver can be both asked and told about.

    A subject with no reader cannot be verified, and one with no setter
    cannot have legs 2 and 3 put to it - so it cannot reach a verdict
    here either, and saying so is better than reporting a partial pass.
    """
    out = []
    for axis, reader, setter, ladder, unit in SUBJECTS:
        if not driver.supports_range_readback(axis):
            continue
        if not hasattr(driver, setter):
            continue
        out.append((axis, reader, setter, ladder, unit))
    return out


def bus_candidates(driver, ladder, avoid, wanted=2):
    """Two declared ranges, different from each other and from `avoid`.

    Picked from the driver's own ladder rather than invented, so the
    instrument is never asked for a range it does not have - a refusal
    would be a fact about the request, not about the readback.
    """
    limits = getattr(driver, "LIMITS", None)
    values = list(getattr(limits, ladder, None) or []) if limits else []
    out = []
    for value in sorted({abs(float(v)) for v in values if v}, reverse=True):
        if avoid is not None and _readback.agrees(avoid, value):
            continue
        out.append(value)
        if len(out) == wanted:
            break
    return out


def leg(driver, reader, expected, log, label):
    """Ask, compare, and say which it was."""
    reported = getattr(driver, reader)()
    if reported is None:
        log(f"  {label}: the query returned nothing - UNREADABLE")
        return None, reported
    ok = _readback.agrees(expected, reported)
    log(f"  {label}: set {expected:g}, query reports {reported:g}"
        f" - {'follows' if ok else 'DOES NOT FOLLOW'}")
    return bool(ok), reported


def one_subject(driver, axis, reader, setter, ladder, unit, log,
                scripted=None):
    """The three legs, in order, stopping at the first that fails."""
    log("")
    log(f"--- {axis.replace('_', ' ')} range ({unit}) ---")
    log("  Set this range on the instrument's FRONT PANEL, then type the")
    log(f"  value you selected, in {unit}, and press Enter.")
    log("  Press Enter alone to skip.")
    answer = ask("  value set by hand: ", scripted)
    if not answer:
        log("  skipped - without the front-panel leg nothing is established")
        return {"axis": axis, "verdict": "skipped"}
    try:
        by_hand = float(answer)
    except ValueError:
        log(f"  {answer!r} is not a number - skipping")
        return {"axis": axis, "verdict": "skipped"}

    row = {"axis": axis, "front_panel": by_hand}
    ok1, reported = leg(driver, reader, by_hand, log, "leg 1 (front panel)")
    row["leg1"] = ok1
    row["leg1_reported"] = reported
    if not ok1:
        row["verdict"] = "not verified"
        log("  STOP: the query does not report what the instrument is on.")
        return row

    candidates = bus_candidates(driver, ladder, avoid=by_hand)
    if len(candidates) < 2:
        row["verdict"] = "inconclusive"
        log("  this model declares too few ranges for the bus legs, so "
            "a query that returns a constant cannot be ruled out here")
        return row

    for i, value in enumerate(candidates, start=2):
        getattr(driver, setter)(value)
        ok, reported = leg(driver, reader, value, log, f"leg {i} (bus)")
        row[f"leg{i}"] = ok
        if not ok:
            row["verdict"] = "not verified"
            log("  STOP: the query did not follow a range change.")
            return row

    row["verdict"] = "verified"
    log("  VERIFIED on this unit: the query tracked a value it was never "
        "told, and two it was.")
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="demo")
    parser.add_argument("--transport", default="visa", choices=TRANSPORTS)
    parser.add_argument("--scripted", action="store_true",
                        help="answer every prompt with skip, so the tool "
                             "runs without a person or an instrument")
    args = parser.parse_args(argv)

    transport = TRANSPORTS[args.transport]()
    transport.connect(args.address)
    idn = transport.query("*IDN?")
    driver = driver_for_idn(idn)(transport)
    driver.identify()
    driver.reset()

    def log(text):
        print(text, flush=True)

    log(idn)
    log("")
    log("Readback verification. Every subject needs you at the front")
    log("panel: a value that reached the instrument over the bus proves")
    log("nothing about whether the query reads hardware.")
    log("")
    log("The output is off throughout and stays off.")

    rows = []
    try:
        driver.safe_output_off()
        subjects = readable_subjects(driver)
        if not subjects:
            log("")
            log("This driver reads none of these back, so there is nothing")
            log("here to verify. Implementing the query comes first.")
        for axis, reader, setter, ladder, unit in subjects:
            rows.append(one_subject(
                driver, axis, reader, setter, ladder, unit, log,
                scripted="" if args.scripted else None))
    finally:
        driver.safe_output_off()
        transport.close()

    verified = [r["axis"] for r in rows if r.get("verdict") == "verified"]
    log("")
    log(f"Verified on this unit: {', '.join(verified) if verified else 'none'}")
    log("")
    log("--- paste everything above this line ---")
    return {"idn": idn, "subjects": rows, "verified": verified}


if __name__ == "__main__":
    main()
