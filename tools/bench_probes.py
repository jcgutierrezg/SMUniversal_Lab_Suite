"""
Bench probes - the specific questions no manual answered.

This is a **throwaway diagnostic**, not a permanent capability. It exists
because bench access is closing and seven questions need instruments in
front of them. Once the answers are recorded in PORTING_NOTES.md this
file has done its job; keeping it afterwards is optional and it should
not grow.

It is deliberately NOT part of `smu_checkup.py`. The checkup is the tool
being relied on at the bench, and changing it days before a session is
the wrong risk. Connection, identification and transport handling are
imported from the same modules the checkup uses, so there is one copy of
that machinery, not two.

What it does not do
-------------------
It does not interpret. Every probe records the command, the raw reply,
the error queue afterwards, and - where it matters - the value *before*
the write as well as after. The interpretation happens later, off the
bench, against the manuals. A probe that decided for itself whether it
had passed would be the third time this project fooled itself with an
assertion that was true either way.

Each probe carries a `control` step wherever the naive version could
succeed for the wrong reason. Those are the important lines in the
report.

SAFETY
------
This sources real levels into whatever is in the fixture. Everything is
small - 1 V or 100 uA, which is 100 uA or 1 V across a 10k - but the
output is real. The output is taken off between every probe and in a
handler that runs on exception and on Ctrl-C. Nothing runs until you
have told it what is connected via --load.

Usage
-----
    uv run python tools/bench_probes.py --dry-run
    uv run python tools/bench_probes.py --address GPIB0::9::INSTR --load 10k
    uv run python tools/bench_probes.py --address GPIB0::27::INSTR --load open

Paste the whole report back rather than summarising it. The useful
results are the ones neither of us predicted.
"""
import sys, os, json, time, argparse, datetime, traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drivers.registry import identify, UnknownInstrumentError
from core.transports.visa_transport import VisaTransport, VisaPyTransport
from core.transports.serial_transport import SerialTransport
from core.transports.minismu_transport import MiniSMUTransport
from core.transports.null_transport import NullTransport

TRANSPORTS = {
    "visa": VisaTransport,
    "visapy": VisaPyTransport,
    "serial": SerialTransport,
    "minismu": MiniSMUTransport,
    "demo": NullTransport,
}

#: Nominal load, only used to say what a reading should look like. The
#: report records what you declared; nothing is inferred from it.
LOADS = {"open": None, "10k": 10_000.0}


class Probes:
    """Runs probe steps and records exactly what happened."""

    def __init__(self, driver, transport, load, log=print):
        self.driver = driver
        self.transport = transport
        self.load = load
        self.log = log
        self.steps = []

    # ---- recording ----
    def step(self, probe, what, sent=None, reply=None, note="",
             elapsed_s=None):
        entry = {"probe": probe, "what": what, "sent": sent,
                 "reply": reply, "note": note, "elapsed_s": elapsed_s,
                 "errors": None}
        self.steps.append(entry)
        shown = "" if reply is None else f" -> {reply!r}"
        self.log(f"    {what}{shown}" + (f"   [{note}]" if note else ""))
        return entry

    def ask(self, probe, what, command, note=""):
        """Send a query, record the raw reply verbatim."""
        started = time.monotonic()
        try:
            reply = self.transport.query(command)
        except Exception as exc:
            reply = f"<EXCEPTION {type(exc).__name__}: {exc}>"
        elapsed = time.monotonic() - started
        entry = self.step(probe, what, sent=command, reply=reply,
                          note=note, elapsed_s=elapsed)
        entry["errors"] = self._drain_errors()
        return reply

    def tell(self, probe, what, command, note=""):
        try:
            self.transport.write(command)
            reply = "<written>"
        except Exception as exc:
            reply = f"<EXCEPTION {type(exc).__name__}: {exc}>"
        entry = self.step(probe, what, sent=command, reply=reply, note=note)
        entry["errors"] = self._drain_errors()
        return reply

    def _drain_errors(self):
        """Empty the error queue and return everything in it.

        Drained after every step rather than at the end: an error left
        in the queue would be attributed to whichever later command
        happened to look at it, which is how a spelling fault gets
        blamed on the wrong line.
        """
        seen = []
        for _ in range(10):
            try:
                code, text = self.driver.read_error()
            except Exception as exc:
                seen.append(f"<read_error failed: {exc}>")
                break
            if not code:
                break
            seen.append(f"{code}: {text}")
        return seen

    def safe(self):
        try:
            self.driver.safe_output_off()
        except Exception as exc:
            self.log(f"    ! could not take the output off: {exc}")


# ------------------------------------------------------------------
# SCPI probes - B2901A and the 2400 family
# ------------------------------------------------------------------
def probe_compliance_range_coupling(p):
    """Is compliance clamped by the present measurement range?

    The B2901A reference says effective compliance values run between
    the channel's minimum and maximum measurement value. "Of the
    channel" reads like the instrument's full capability rather than
    the range currently selected - but the U2722A does clamp (deviation
    15/21), and the experiments disagree about whether the range or the
    limit is set first, so the reading matters.

    The control leg is what makes this discriminating. Asking for 10 mA
    on the 100 uA range and reading back 100 uA could equally mean the
    compliance write failed outright. So the same write is repeated on
    a range that comfortably contains it: if *that* one takes, the
    write works and the first reading was a clamp.
    """
    name = "compliance vs measurement range"
    p.tell(name, "reset", "*RST")

    # Reset state, recorded before anything is changed. Also answers
    # the separate question of what the compliances reset to - the
    # manual gives these as the DEFault parameter, not as the *RST
    # value, and it is the number protecting a biased sample.
    p.ask(name, "current compliance at reset", ":SENS:CURR:PROT?",
          "manual says DEFault is 1E-4")
    p.ask(name, "voltage compliance at reset", ":SENS:VOLT:PROT?",
          "manual says DEFault is 2")
    p.ask(name, "current measure autorange at reset", ":SENS:CURR:RANG:AUTO?",
          "manual table says ON")
    p.ask(name, "current measure range at reset", ":SENS:CURR:RANG?",
          "manual table says 1.00E-04")

    # --- the question ---
    p.tell(name, "autorange off", ":SENS:CURR:RANG:AUTO OFF")
    p.tell(name, "measure range to 100 uA", ":SENS:CURR:RANG 1E-4")
    p.ask(name, "measure range took", ":SENS:CURR:RANG?")
    p.tell(name, "ask for 10 mA compliance on the 100 uA range",
           ":SENS:CURR:PROT 1E-2")
    p.ask(name, "compliance now reads", ":SENS:CURR:PROT?",
          "1E-2 = no coupling; 1E-4 = clamped by the range")

    # --- the control ---
    p.tell(name, "measure range up to 100 mA", ":SENS:CURR:RANG 1E-1")
    p.tell(name, "ask for the same 10 mA compliance again",
           ":SENS:CURR:PROT 1E-2")
    p.ask(name, "compliance now reads", ":SENS:CURR:PROT?",
          "CONTROL - if this is not 1E-2 the write itself is failing "
          "and the result above says nothing about clamping")

    # --- and the reverse order, which is what the experiments disagree on ---
    p.tell(name, "reset", "*RST")
    p.tell(name, "autorange off", ":SENS:CURR:RANG:AUTO OFF")
    p.tell(name, "compliance first, then range",
           ":SENS:CURR:PROT 1E-2")
    p.tell(name, "then the small range", ":SENS:CURR:RANG 1E-4")
    p.ask(name, "compliance after the range was narrowed",
          ":SENS:CURR:PROT?",
          "does narrowing the range retroactively clamp an existing "
          "compliance?")
    p.safe()


def probe_acquisition_delay_path(p):
    """Does :TRIG:ACQ:DEL apply to :MEAS? or only :INIT/:FETCh?

    If it does not apply to the :MEAS? path, `set_source_delay()`
    silently does nothing on this instrument and the readings look like
    ordinary noisy data. Timed rather than queried because there is no
    query that answers it.

    Two seconds is chosen to be far larger than any bus latency, so the
    comparison does not depend on a quiet bus.
    """
    name = "acquisition delay path"
    p.tell(name, "reset", "*RST")
    p.tell(name, "source 0 V", ":SOUR:FUNC:MODE VOLT")
    p.tell(name, "level 0", ":SOUR:VOLT 0")
    p.tell(name, "output on", ":OUTP ON")

    p.tell(name, "acquisition delay 0", ":TRIG:ACQ:DEL 0")
    p.ask(name, "MEAS? with no delay", ":MEAS:CURR?")

    p.tell(name, "acquisition delay 2 s", ":TRIG:ACQ:DEL 2")
    p.ask(name, "MEAS? with a 2 s delay", ":MEAS:CURR?",
          "compare elapsed_s with the line above - a ~2 s difference "
          "means the delay applies to this path")

    # Control: the path the delay is documented for. If this one does
    # not slow down either, the delay was never set and neither result
    # means anything.
    p.tell(name, "arm", ":INIT")
    p.ask(name, "FETCh? with the same 2 s delay", ":FETC:CURR?",
          "CONTROL - the delay is documented for this path")

    p.tell(name, "delay back to 0", ":TRIG:ACQ:DEL 0")
    p.safe()


def probe_function_change_drops_output_scpi(p):
    """Does a source-function change drop the output?

    Three manuals are silent on this. Wave 6 removed the dependency on
    the answer, but the answer is still worth having: it decides whether
    the deliberate down-up sequence is belt-and-braces or load-bearing.
    """
    name = "output across a source-function change"
    p.tell(name, "reset", "*RST")
    p.tell(name, "source voltage", ":SOUR:FUNC:MODE VOLT")
    p.tell(name, "level 0", ":SOUR:VOLT 0")
    p.tell(name, "output on", ":OUTP ON")
    p.ask(name, "output before the change", ":OUTP?",
          "CONTROL - must read 1, or the probe below proves nothing")
    p.tell(name, "change source function to current",
           ":SOUR:FUNC:MODE CURR")
    p.ask(name, "output after the change", ":OUTP?",
          "1 = survives; 0 = the instrument dropped it")
    p.safe()


# ------------------------------------------------------------------
# TSP probes - 2611A and 2635B
# ------------------------------------------------------------------
def probe_ascii_precision(p):
    """print() vs printnumber(), and what asciiprecision resets to.

    The claim under test is that `format.asciiprecision` resets to 6
    significant figures and governs `print()`. If so, every 2611A
    reading this suite has ever taken was truncated to six figures -
    and Hall pins nine, because V_H is recovered by subtracting
    nearly-equal numbers.

    1/3 is the probe value on purpose: the digit count in the reply is
    unambiguous, and it depends on no instrument state, no range and no
    sample. The measured reading afterwards is what turns "the
    formatter truncates" into "our data was truncated".
    """
    name = "ascii precision"
    p.tell(name, "reset", "*RST")
    p.ask(name, "asciiprecision at reset", "print(format.asciiprecision)",
          "the claim is 6")

    p.ask(name, "print(1/3) at reset precision", "print(1/3)",
          "count the significant figures")
    p.ask(name, "printnumber(1/3) at reset precision", "printnumber(1/3)",
          "does it differ from print()?")

    p.tell(name, "raise precision to 16", "format.asciiprecision = 16")
    p.ask(name, "asciiprecision now", "print(format.asciiprecision)",
          "CONTROL - if this is not 16 the write failed and the "
          "readings below say nothing")
    p.ask(name, "print(1/3) at 16", "print(1/3)")
    p.ask(name, "printnumber(1/3) at 16", "printnumber(1/3)")


def probe_ascii_precision_on_a_real_reading(p):
    """The same question, on an actual measurement.

    Needs a load. Into an open circuit the current is noise and the
    digit count is not meaningful.
    """
    name = "ascii precision on a reading"
    if p.load is None:
        p.step(name, "skipped - needs a known load", note="run with --load 10k")
        return

    p.tell(name, "reset", "*RST")
    p.tell(name, "source voltage", "smua.source.func = smua.OUTPUT_DCVOLTS")
    p.tell(name, "compliance 10 mA", "smua.source.limiti = 1e-2")
    p.tell(name, "level 1 V", "smua.source.levelv = 1")
    p.tell(name, "output on", "smua.source.output = smua.OUTPUT_ON")
    p.ask(name, "reading at reset precision", "print(smua.measure.i())",
          f"expect about {1.0 / p.load:.6g} A")
    p.tell(name, "raise precision to 16", "format.asciiprecision = 16")
    p.ask(name, "the same reading at 16", "print(smua.measure.i())",
          "more digits here means the stored data was truncated")
    p.safe()


def probe_measure_range_disables_autorange(p):
    """Confirm the manual: assigning measure.rangeY prevents autoranging.

    The reference says a fixed range prevents autoranging and that an
    overrange returns 9.91e+37 - the sentinel - rather than an error.
    Both halves are worth confirming, the second especially: it makes a
    too-small range a documented route to a sentinel rather than a
    hypothetical one.
    """
    name = "measure range vs autorange"
    p.tell(name, "reset", "*RST")
    p.ask(name, "autorange at reset", "print(smua.measure.autorangei)",
          "the claim is ON (1)")
    p.tell(name, "assign a fixed measure range",
           "smua.measure.rangei = 1e-6")
    p.ask(name, "autorange after assigning a range",
          "print(smua.measure.autorangei)",
          "0 means the assignment disabled it by itself - no explicit "
          "AUTORANGE_OFF needed, unlike the B2901A")
    p.ask(name, "the range that took", "print(smua.measure.rangei)")

    if p.load is not None:
        # Deliberate overrange: 1 V across 10k is 100 uA, on a 1 uA
        # range. The claim is that this returns the sentinel rather
        # than erroring.
        p.tell(name, "source voltage", "smua.source.func = smua.OUTPUT_DCVOLTS")
        p.tell(name, "compliance 10 mA", "smua.source.limiti = 1e-2")
        p.tell(name, "level 1 V", "smua.source.levelv = 1")
        p.tell(name, "output on", "smua.source.output = smua.OUTPUT_ON")
        p.ask(name, "reading on a deliberately too-small range",
              "print(smua.measure.i())",
              "9.91e+37 would confirm the overrange sentinel")
        p.safe()

    p.tell(name, "output off", "smua.source.output = smua.OUTPUT_OFF")


def probe_function_change_drops_output_tsp(p):
    name = "output across a source-function change"
    p.tell(name, "reset", "*RST")
    p.tell(name, "source voltage", "smua.source.func = smua.OUTPUT_DCVOLTS")
    p.tell(name, "level 0", "smua.source.levelv = 0")
    p.tell(name, "output on", "smua.source.output = smua.OUTPUT_ON")
    p.ask(name, "output before the change", "print(smua.source.output)",
          "CONTROL - must read 1")
    p.tell(name, "change source function",
           "smua.source.func = smua.OUTPUT_DCAMPS")
    p.ask(name, "output after the change", "print(smua.source.output)",
          "1 = survives; 0 = the instrument dropped it")
    p.safe()


# ------------------------------------------------------------------
# GSM-20H10
# ------------------------------------------------------------------
def probe_abort_is_accepted(p):
    """Is :ABORt accepted over the bus?

    It is absent from the command list but mentioned in the :MEASure?
    prose as something performed internally. The driver stops sweeps
    with :TRIG:CLE, which is documented outright, so this is about
    whether a simpler path exists rather than about a fault.

    The control comes first: a deliberately bogus header, to prove the
    error queue is actually reporting. An empty queue after :ABOR means
    nothing if the queue would have been empty regardless.
    """
    name = "is :ABORt accepted"
    p.tell(name, "reset", "*RST")
    p.tell(name, "a deliberately undefined header", ":NOSUCHCOMMAND",
           "CONTROL - the error queue must report this one")
    p.tell(name, "abort", ":ABOR",
           "an empty error queue here means it was accepted")
    p.tell(name, "documented alternative", ":TRIG:CLE",
           "CONTROL - the command the driver actually uses")
    p.safe()


def probe_source_range_while_sourcing(p):
    """Is a source-range change rejected with error 823?

    Deviation 41: both the 2401 and the GSM-20H10 rejected a *source*
    range change with "invalid with source read-back on". It never
    mattered, because nothing in the application set a source range -
    every experiment ranged only the quantity it measured.

    Wave 6d-ii changed that. Each experiment now fixes the range of the
    quantity it sources, because a sweep that autoranges its source
    crosses range boundaries and leaves a step in the data that a
    straight-line fit absorbs as slope. So this call is now on a live
    code path, and whether it errors matters.

    The control comes first, as always: a known-bad header, to prove the
    error queue is reporting before an empty queue is read as success.
    """
    name = "source range while sourcing"
    p.tell(name, "reset", "*RST")
    p.tell(name, "a deliberately undefined header", ":NOSUCHCOMMAND",
           "CONTROL - the error queue must report this one")

    p.tell(name, "source voltage", ":SOUR:FUNC:MODE VOLT")
    p.tell(name, "set the SOURCE voltage range while sourcing voltage",
           ":SOUR:VOLT:RANG 2",
           "an empty error queue here means 823 does not apply; "
           "-823 or similar means the new ranging path is rejected "
           "on this model")
    p.ask(name, "what the source range reads back", ":SOUR:VOLT:RANG?")

    p.tell(name, "source current", ":SOUR:FUNC:MODE CURR")
    p.tell(name, "set the SOURCE current range while sourcing current",
           ":SOUR:CURR:RANG 1E-3")
    p.ask(name, "what the source range reads back", ":SOUR:CURR:RANG?")
    p.safe()


# ------------------------------------------------------------------
# what runs on what
# ------------------------------------------------------------------
PLANS = {
    "KeysightB2901A": [probe_compliance_range_coupling,
                       probe_acquisition_delay_path,
                       probe_function_change_drops_output_scpi],
    "Keithley2611A": [probe_ascii_precision,
                      probe_ascii_precision_on_a_real_reading,
                      probe_function_change_drops_output_tsp],
    "Keithley2635B": [probe_ascii_precision,
                      probe_ascii_precision_on_a_real_reading,
                      probe_measure_range_disables_autorange,
                      probe_function_change_drops_output_tsp],
    "GWInstekGSM20H10": [probe_source_range_while_sourcing,
                      probe_abort_is_accepted],
    "Keithley2450": [probe_function_change_drops_output_scpi],
    "Keithley2401": [probe_source_range_while_sourcing,
                      probe_function_change_drops_output_scpi],
    "DummySMU": [],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="")
    parser.add_argument("--transport", default="visa", choices=TRANSPORTS)
    parser.add_argument("--load", choices=sorted(LOADS), default=None,
                        help="what is in the fixture - recorded in the "
                             "report, and some probes need a load")
    parser.add_argument("--out", default="probes")
    parser.add_argument("--dry-run", action="store_true",
                        help="run against the null transport, no hardware")
    parser.add_argument("--as-driver", default=None, choices=sorted(PLANS),
                        help="with --dry-run, walk this instrument's plan "
                             "against the null transport. A dry run that "
                             "exercises nothing is not a rehearsal.")
    args = parser.parse_args()

    if args.dry_run:
        args.transport = "demo"
        args.address = "demo"
        if args.load is None:
            args.load = "open"
    if not args.address:
        parser.error("--address is required (or use --dry-run)")
    if args.load is None:
        parser.error("--load is required: say what is in the fixture. "
                     "The readings cannot be interpreted without it.")

    transport = TRANSPORTS[args.transport]()
    print(f"Connecting to {args.address} over {args.transport}...")
    try:
        transport.connect(args.address)
    except Exception as exc:
        print(f"Could not connect: {exc}")
        return 1

    driver = None
    try:
        try:
            driver, idn = identify(transport)
        except (TypeError, UnknownInstrumentError) as exc:
            print(f"Connected, but could not identify: {exc}")
            return 1

        name = type(driver).__name__
        print(f"Detected: {type(driver).DISPLAY_NAME}")
        print(f"Identity: {idn}")
        if args.as_driver:
            if not args.dry_run:
                print("--as-driver is only for --dry-run.")
                return 1
            print(f"Dry run: walking the {args.as_driver} plan against the "
                  f"null transport. Replies are meaningless; what is being "
                  f"checked is that every step runs and records.")
            name = args.as_driver
        plan = PLANS.get(name)
        if plan is None:
            print(f"No probes defined for {name}.")
            return 1
        if not plan:
            print(f"No outstanding questions for {name}. Nothing to do.")
            return 0

        p = Probes(driver, transport, LOADS[args.load])
        print(f"Fixture: {args.load}\n")

        for fn in plan:
            print(f"  {fn.__name__}")
            try:
                fn(p)
            except Exception:
                p.step(fn.__name__, "probe raised",
                       note=traceback.format_exc(limit=3))
                print("    ! this probe raised; continuing with the rest")
            finally:
                p.safe()

        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(args.out, exist_ok=True)
        path = os.path.join(args.out, f"probes_{name}_{stamp}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"driver": name, "identity": idn,
                       "address": args.address, "load": args.load,
                       "when": stamp, "steps": p.steps}, fh, indent=2)
        print(f"\nWrote {path}")
        print("Paste the whole file back - do not summarise it.")
        return 0
    finally:
        # Runs on exception and on Ctrl-C. The last thing that happens
        # is the output coming off.
        if driver is not None:
            try:
                driver.safe_output_off()
            except Exception:
                pass
        try:
            transport.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
