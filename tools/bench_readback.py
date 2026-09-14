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

So the discriminating leg for a range is the front panel. A value
dialled in by hand never passes through the bus, so a query that reports
it is reading hardware.

The GSM-20H10 is why this is not paranoia. On 2026-08-20 `OUTP?` on that
instrument answered `0` three times in a row with the output
demonstrably on. A readback that lies is worse than none, because it
produces confident reassurance about exactly the thing it exists to
check.

The three legs, for a range
---------------------------
1. **Front panel.** The tool reads the range first and says what it is;
   the operator sets a *different* one by hand; the query must name it.
   Discriminating: nothing the software did could have told the
   instrument to say this. The first reading is what makes it so - if
   the hand-set range were the one already in force, a query that never
   moves would name it too, and on 2026-09-11 nothing recorded which
   range each instrument had been on.
2. **Bus tracking.** The driver sets a different range; the query must
   follow. Catches a query that returns a constant.
3. **Bus tracking again**, to a third range. Catches a query that
   latches the first thing it is told, which passes legs 1 and 2.

A range is compared by the range it *names*, not by its digits: the
Keithley and GW Instek families report full scale 5% above the nominal
decade, so the 1 A range answers `1.05`. On 2026-09-11 the first version
of this tool compared digits and stopped the GSM-20H10 and the 2401 at
leg 1 on answers that were correct.

The refused write, for a compliance or power limit
--------------------------------------------------
These need no front panel. Two bus writes must be followed, and then the
tool writes a value no instrument here can hold - ten times the model's
maximum. What the query says next is the discriminating answer:

* **the value that survived**, with an error queued: the instrument
  refused the write and the query reports what it is holding - the
  state, not the question. This is how the U2722A's compliance readback
  was verified on 2026-08-24.
* **a value between the two**: the instrument clamped the write, and the
  query reports a value nobody sent.
* **the refused value itself**, with an error queued: the query repeats
  the write. Not verified.
* **the written value, with no error**: the instrument took it, so the
  state and the write are the same number and nothing is told apart.
  Inconclusive.

What to do with the result
--------------------------
A subject that passes is one whose `*_READBACK_TRUSTED` flag may be set
on that driver, which promotes its `UNVERIFIED` warnings to `CONFIRMED`
passes.

**Nothing here sets that flag.** This tool prints what it established
and a person decides, because the flag is a standing claim about a model
and this is the record of one session with one unit.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smuniversal_lab_suite.core import readback as _readback  # noqa: E402
from smuniversal_lab_suite.core.ranges import RangeError  # noqa: E402
from smuniversal_lab_suite.drivers.base_smu import (  # noqa: E402
    _RANGE_FLOOR_SLACK,
    BaseSMU,
)
from smuniversal_lab_suite.drivers.registry import driver_for_idn  # noqa: E402
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

#: The settings the refused-write legs are put to: a name, the quantity
#: sourced while it applies, how to read and write it, the unit, two
#: values every instrument here holds, and the `LIMITS` field ten times
#: which no instrument here can.
COMPLIANCES = (
    ("current_compliance", "voltage", "read_current_limit",
     "set_current_limit", "A", (1e-3, 2e-4), "max_current"),
    ("voltage_compliance", "current", "read_voltage_limit",
     "set_voltage_limit", "V", (5.0, 2.0), "max_voltage"),
)

#: How far outside the model's maximum the refused write goes.
OUTSIDE = 10.0

#: The power ceiling has no setter on any driver: it is written once, to
#: disabled, at reset. The one model that reports it gets a writer here,
#: so the check lives in this tool rather than in a commissioned driver,
#: and the ceiling goes back to the driver's own `POWER_LIMIT_SETTING`
#: however the check ends - a nonzero one left behind would override the
#: compliance of every run after it.
POWER_LIMIT_WRITERS = {
    "Keithley2635B": lambda driver, watts: driver.transport.write(
        f"{driver.channel}.source.limitp = {watts:.6e}"),
}
POWER_LIMIT_VALUES = (1.0, 0.5)


def ask(prompt, scripted=None):
    """One line from the operator, or from a script standing in for one.

    A callable stands in for the whole operator: it may change the fake
    instrument, as a hand on the panel would, and returns what they
    typed.
    """
    if callable(scripted):
        return str(scripted()).strip()
    if scripted is not None:
        return scripted
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def readable_subjects(driver):
    """The range subjects this driver can be both asked and told about.

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


def rungs_of(driver, ladder):
    """The model's declared ranges on one ladder, narrowest first."""
    limits = getattr(driver, "LIMITS", None)
    values = list(getattr(limits, ladder, None) or []) if limits else []
    return sorted({abs(float(v)) for v in values if v})


def rung_of(driver, ladder, value):
    """The declared range a reported value names, or None.

    The checkup's own rule, from `BaseSMU.verify_range`: a range answers
    with its full scale, anywhere from its nominal value - less the
    slack a 32-bit float needs - up to `RANGE_READBACK_HEADROOM` above
    it. The headroom sits clear of the 5% overrange convention and well
    below the next rung, so at most one rung matches.
    """
    if not _is_number(value):
        return None
    headroom = getattr(type(driver), "RANGE_READBACK_HEADROOM",
                       BaseSMU.RANGE_READBACK_HEADROOM)
    magnitude = abs(float(value))
    for rung in rungs_of(driver, ladder):
        if rung * (1.0 - _RANGE_FLOOR_SLACK) <= magnitude <= rung * headroom:
            return rung
    return None


def _names(rung, unit):
    if rung is None:
        return " (not a range this model declares)"
    return f" (the {rung:g} {unit} range)"


def bus_candidates(driver, ladder, avoid, wanted=2):
    """Two declared ranges, different from each other and from `avoid`.

    Picked from the driver's own ladder rather than invented, so the
    instrument is never asked for a range it does not have - a refusal
    would be a fact about the request, not about the readback.
    """
    out = []
    for value in sorted(rungs_of(driver, ladder), reverse=True):
        if avoid is not None and _readback.agrees(avoid, value):
            continue
        out.append(value)
        if len(out) == wanted:
            break
    return out


def leg(driver, reader, expected, ladder, unit, log, label):
    """Ask, compare by the range named, and say which it was."""
    reported = getattr(driver, reader)()
    if reported is None:
        log(f"  {label}: the query returned nothing - UNREADABLE")
        return None, reported
    named = rung_of(driver, ladder, reported)
    ok = named is not None and _readback.agrees(expected, named)
    log(f"  {label}: set {expected:g}, query reports {reported:g}"
        f"{_names(named, unit)} - {'follows' if ok else 'DOES NOT FOLLOW'}")
    return bool(ok), reported


#: How many times an operator's answer is asked for again before the
#: subject is skipped.
ATTEMPTS = 3


def _hand_set_range(driver, ladder, unit, before_rung, log, scripted):
    """The range the operator set by hand, or (None, reason).

    Refused, and asked again, when it is not a range this model has or
    when it is the range the instrument was already on - the second
    because then a query that never moves would name it too.
    """
    for _ in range(ATTEMPTS):
        answer = ask("  value set by hand: ", scripted)
        if not answer:
            return None, ("skipped - without the front-panel leg nothing "
                          "is established")
        try:
            typed = float(answer)
        except ValueError:
            log(f"  {answer!r} is not a number.")
            continue
        rung = rung_of(driver, ladder, typed)
        if rung is None:
            log(f"  {typed:g} {unit} is not a range this model declares.")
            continue
        if before_rung is not None and _readback.agrees(rung, before_rung):
            log("  that is the range it was already on, so a query that "
                "never moves would report it too. Choose another.")
            continue
        return rung, None
    return None, "skipped - no usable front-panel range was given"


def one_subject(driver, axis, reader, setter, ladder, unit, log,
                scripted=None):
    """The three legs, in order, stopping at the first that fails."""
    log("")
    log(f"--- {axis.replace('_', ' ')} range ({unit}) ---")
    before = getattr(driver, reader)()
    if before is None:
        log("  the query returned nothing - UNREADABLE")
        return {"axis": axis, "verdict": "unreadable"}
    before_rung = rung_of(driver, ladder, before)
    log(f"  It reports {before:g} {unit} now{_names(before_rung, unit)}.")
    log(f"  This model's ranges: "
        f"{', '.join(f'{r:g}' for r in rungs_of(driver, ladder))} {unit}.")
    log("  Set a DIFFERENT one on the instrument's FRONT PANEL, then type")
    log(f"  the value you selected, in {unit}, and press Enter.")
    log("  Press Enter alone to skip.")
    by_hand, reason = _hand_set_range(driver, ladder, unit, before_rung,
                                      log, scripted)
    if by_hand is None:
        log(f"  {reason}")
        return {"axis": axis, "verdict": "skipped", "before": before}

    row = {"axis": axis, "before": before, "front_panel": by_hand}
    ok1, reported = leg(driver, reader, by_hand, ladder, unit, log,
                        "leg 1 (front panel)")
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
        ok, reported = leg(driver, reader, value, ladder, unit, log,
                           f"leg {i} (bus)")
        row[f"leg{i}"] = ok
        if not ok:
            row["verdict"] = "not verified"
            log("  STOP: the query did not follow a range change.")
            return row

    row["verdict"] = "verified"
    log("  VERIFIED on this unit: the query tracked a range it was never "
        "told, and two it was.")
    return row


# ---------------------------------------------------------------------
# the refused write
# ---------------------------------------------------------------------
def drain_errors(driver, limit=10):
    """Everything in the error queue, emptying it."""
    found = []
    for _ in range(limit):
        code, message = driver.read_error()
        if not code:
            break
        found.append((code, message))
    return found


def setting_subjects(driver):
    """The compliance and power-limit subjects this driver can be put to.

    Each is (name, sourced quantity or None, read, write, unit, the two
    values to track, the value to refuse, the value to leave behind).
    """
    cls = type(driver)
    limits = getattr(driver, "LIMITS", None)
    out = []
    for name, mode, reader, setter, unit, goods, maximum in COMPLIANCES:
        if getattr(cls, reader) is getattr(BaseSMU, reader):
            continue
        if limits is None or not hasattr(driver, setter):
            continue
        out.append((name, mode, getattr(driver, reader),
                    getattr(driver, setter), unit, goods,
                    OUTSIDE * getattr(limits, maximum), None))
    writer = POWER_LIMIT_WRITERS.get(cls.__name__)
    if (writer is not None and limits is not None
            and driver.supports_power_limit_readback()):
        out.append(("power_limit", None, driver.read_power_limit,
                    lambda watts: writer(driver, watts), "W",
                    POWER_LIMIT_VALUES,
                    OUTSIDE * limits.max_voltage * limits.max_current,
                    cls.POWER_LIMIT_SETTING))
    return out


def _refused_write_verdict(reported, outside, survivor, errors):
    """What the query said after a write nothing here can hold."""
    if reported is None:
        return "unreadable", "the query returned nothing"
    said = ", ".join(f"{code} {message!r}" for code, message in errors)
    if _readback.agrees(outside, reported):
        if errors:
            return ("not verified",
                    f"the instrument refused it ({said}) and the query "
                    f"reports it anyway - it repeats the write")
        return ("inconclusive",
                "the instrument took it, so the state and the write are "
                "the same number and nothing is told apart")
    if _readback.agrees(survivor, reported):
        if errors:
            return ("verified",
                    f"the instrument refused it ({said}) and the query "
                    f"kept reporting {survivor:g} - the state, not the "
                    f"last write")
        return ("inconclusive",
                "the value from before, with no error queued - the write "
                "may never have arrived")
    if min(survivor, outside) < reported < max(survivor, outside):
        return ("verified",
                f"{reported:g} is a value nobody sent: the instrument "
                f"clamped the write, and the query reports what it did")
    return ("not verified",
            f"{reported:g} is neither the write, the value before it, nor "
            f"between them")


def refused_write(driver, name, mode, read, write, unit, goods, outside,
                  restore_to, log):
    """Two tracked writes, then one no instrument here can hold."""
    log("")
    log(f"--- {name.replace('_', ' ')} ({unit}) - no front panel needed ---")
    if mode is not None:
        driver.set_source_function(mode)
    before = read()
    if before is None:
        log("  the query returned nothing - UNREADABLE")
        return {"axis": name, "verdict": "unreadable"}
    row = {"axis": name, "before": before}
    restore = before if restore_to is None else restore_to
    try:
        for i, value in enumerate(goods, start=1):
            try:
                write(value)
            except (RangeError, ValueError) as exc:
                row["verdict"] = "inconclusive"
                log(f"  leg {i} (bus): the driver refuses {value:g} {unit}, "
                    f"so the tracking legs cannot be run - {exc}")
                return row
            reported = read()
            ok = reported is not None and _readback.agrees(value, reported)
            log(f"  leg {i} (bus): set {value:g}, query reports "
                f"{'nothing' if reported is None else f'{reported:g}'} - "
                f"{'follows' if ok else 'DOES NOT FOLLOW'}")
            row[f"leg{i}"] = ok
            if not ok:
                row["verdict"] = "not verified"
                log("  STOP: the query did not follow a write.")
                return row

        # Anything queued so far belongs to the writes above, not to the
        # one this leg is about.
        drain_errors(driver)
        survivor = goods[-1]
        try:
            write(outside)
        except (RangeError, ValueError) as exc:
            row["verdict"] = "inconclusive"
            log(f"  leg 3 (refused write): the driver refuses {outside:g} "
                f"{unit} before sending it, so the instrument's own "
                f"handling of it cannot be seen here - {exc}")
            return row
        errors = drain_errors(driver)
        reported = read()
        verdict, why = _refused_write_verdict(reported, outside, survivor,
                                              errors)
        row["leg3_reported"] = reported
        row["leg3_errors"] = errors
        row["verdict"] = verdict
        log(f"  leg 3 (refused write): wrote {outside:g}, query reports "
            f"{'nothing' if reported is None else f'{reported:g}'} - {why}")
        if verdict == "verified":
            log("  VERIFIED on this unit.")
        return row
    finally:
        write(restore)
        drain_errors(driver)
        log(f"  put back to {restore:g} {unit}")


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
    log("Readback verification. Every range needs you at the front")
    log("panel: a value that reached the instrument over the bus proves")
    log("nothing about whether the query reads hardware. The compliance")
    log("and power-limit checks at the end run on their own.")
    log("")
    log("The output is off throughout and stays off.")

    rows = []
    try:
        driver.safe_output_off()
        subjects = readable_subjects(driver)
        if not subjects:
            log("")
            log("This driver reads no range back, so there is no range")
            log("here to verify. Implementing the query comes first.")
        for axis, reader, setter, ladder, unit in subjects:
            rows.append(one_subject(
                driver, axis, reader, setter, ladder, unit, log,
                scripted="" if args.scripted else None))
        for subject in setting_subjects(driver):
            rows.append(refused_write(driver, *subject, log))
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
