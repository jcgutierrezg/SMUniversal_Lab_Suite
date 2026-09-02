"""
Instrument checkup - what the offline test suite cannot prove.

`tests/` proves every driver has the right *shape* and sends the right
strings to a fake. It cannot prove a real instrument agrees. Every
command spelling in the U2722A and miniSMU drivers was written from a
manual and has never been answered by hardware; the ones in the older
drivers were read off working scripts but have since been reordered,
retimed and re-ranged.

This module is the other half: it drives a connected instrument through
the whole BaseSMU contract and asks, at every step, whether the
instrument understood. `tools/smu_checkup.py` is the front end.

---------------------------------------------------------------------
IT ASSUMES NOTHING IS CONNECTED TO THE OUTPUT
---------------------------------------------------------------------
Every level it sources is chosen to be safe into an open circuit, and
the expected results are the open-circuit ones: source a small voltage,
measure approximately no current. That is not a limitation, it is the
point - an open circuit is a *known* DUT, so the readings can be checked
rather than merely recorded. With a sample connected, "0.1 V produced
2 uA" proves nothing without knowing the sample.

Connect a sample and the measurement checks will report failures that
are not faults. The report says so at the top.

**Sensing is forced to 2-wire wherever the driver allows it.** With
nothing connected, an SMU in 4-wire mode has open sense leads and many
will slew the output to compliance trying to servo a voltage they cannot
see. Two instruments cannot be forced: the U2722A is hardwired 4-wire,
and the miniSMU's 4-wire mode is system-wide. Both are noted in the
report rather than silently skipped.

---------------------------------------------------------------------
Three tiers
---------------------------------------------------------------------
1. Identity and declarations - output off, nothing sourced.
2. Configuration syntax     - output off, every contract method called
                              and the error queue checked after each.
3. Live measurement         - sources at small levels into open circuit.

Tier 3 stops at the first failure in tiers 1-2 severe enough to make
sourcing unwise, and never runs if the output could not be turned off.
"""
import time

from core import readback as readback_states
from core.provenance import as_markdown_lines
from core.ranges import AUTO, NOT_SOURCED, RangeError, RangePlan
from core.transports.base import TransportDesynchronised
import traceback

# ---------------------------------------------------------------------
# Probe levels
# ---------------------------------------------------------------------
#
# These four are the *nominal* request, not the levels. They are small
# enough to be harmless into an open circuit and well clear of the noise
# floor on the instruments they were chosen against, and that is all
# they are: a starting point that `probe_levels_for()` reconciles
# against each driver's own declared envelope before anything is sent.
#
# They used to be the levels, applied unchanged to every instrument in
# the registry, and one instrument proved that cannot work. The U2722A
# has no autorange, so an all-AUTO current axis lands on R120mA where
# one count is 7.32 uA - and a module-wide 1 uA probe is a seventh of a
# count there, which the driver correctly refuses because the sign of
# what comes out is not the sign that was asked for. The checkup was
# therefore **structurally unable to pass** on that instrument: not
# because anything was wrong with it, but because the tool was asking
# for a configuration that instrument does not have.
#
# A commissioning tool that cannot pass on a working instrument is worse
# than no tool, for the same reason a tool that invents failures is: it
# teaches people to read past its output.
PROBE_VOLTAGE = 0.1          # V, nominal
PROBE_CURRENT = 1e-6         # A, nominal
PROBE_COMPLIANCE_I = 1e-4    # A, nominal
PROBE_COMPLIANCE_V = 1.0     # V, nominal


class ProbeLevels:
    """The four levels this checkup will actually source, per driver.

    Each carries the reason it is what it is, because the report has to
    be able to say *why* an instrument was probed at 73 uA when the tool
    nominally asks for 1 uA. A level with no stated provenance in a
    commissioning report is a number somebody will later assume was
    chosen for their instrument.
    """

    __slots__ = ("voltage", "current", "compliance_v", "compliance_i",
                 "notes")

    def __init__(self, voltage, current, compliance_v, compliance_i,
                 notes=()):
        self.voltage = float(voltage)
        self.current = float(current)
        self.compliance_v = float(compliance_v)
        self.compliance_i = float(compliance_i)
        self.notes = tuple(notes)

    def describe(self):
        return (f"source {self.voltage:.6g} V / {self.current:.6g} A, "
                f"compliance {self.compliance_i:.6g} A / "
                f"{self.compliance_v:.6g} V")

    def as_dict(self):
        return {"voltage": self.voltage, "current": self.current,
                "compliance_v": self.compliance_v,
                "compliance_i": self.compliance_i,
                "notes": list(self.notes)}


def probe_levels_for(driver):
    """Reconcile the nominal probe against one instrument's envelope.

    Every level is clamped into what the model declares it can do, in
    the one direction that fails safe: **downward, to the widest range
    the model has**. A probe above that is a request the instrument
    cannot carry out - the compliance would be refused or clamped, and
    every check downstream would then be measuring the clamp rather than
    the instrument.

    Two things this function deliberately does **not** do.

    It does not round a compliance onto a declared range. That was the
    first draft and it is wrong in exactly the case it was written for:
    the U2722A's narrowest voltage range is 2 V, so rounding a 1 V
    nominal onto a range would probe at the range's full scale - where
    the compliance and the range rail are the same number, and where the
    "is the limit in force?" check cannot tell them apart. That is fault
    25, arriving through the probe rather than through the comparison.
    A compliance need only be *settable*, and where an instrument's
    windows make a value unsettable the driver refuses it and the
    checkup reports the refusal, which is a better answer than a probe
    that quietly moved.

    It does not compute a sub-count floor. That depends on the range the
    ranging plan lands on, which is not known until the plan has been
    carried out, and is asked of the instrument at that point instead -
    see `Checkup._resolve_source_level`. A floor guessed from the model
    alone would be right on one range and wrong on five.
    """
    limits = getattr(type(driver), "LIMITS", None)
    notes = []

    if limits is None:
        return ProbeLevels(
            PROBE_VOLTAGE, PROBE_CURRENT, PROBE_COMPLIANCE_V,
            PROBE_COMPLIANCE_I,
            ["this driver declares no LIMITS, so the nominal probe is "
             "used unchanged"])

    resolved = {}
    for key, nominal, ranges, maximum, what, unit in (
            ("compliance_i", PROBE_COMPLIANCE_I, limits.current_ranges,
             limits.max_current, "current compliance", "A"),
            ("compliance_v", PROBE_COMPLIANCE_V, limits.voltage_ranges,
             limits.max_voltage, "voltage compliance", "V"),
            ("current", PROBE_CURRENT, limits.current_ranges,
             limits.max_current, "source current", "A"),
            ("voltage", PROBE_VOLTAGE, limits.voltage_ranges,
             limits.max_voltage, "source voltage", "V")):
        value, note = _clamp_to_ceiling(nominal, ranges, maximum, what, unit)
        resolved[key] = value
        if note:
            notes.append(note)

    if not notes:
        notes.append("every nominal level is inside this model's "
                     "declared envelope and is used unchanged")
    return ProbeLevels(resolved["voltage"], resolved["current"],
                       resolved["compliance_v"], resolved["compliance_i"],
                       notes)


def _clamp_to_ceiling(nominal, ranges, maximum, what, unit):
    """`(value, note)`, where the note is empty when nothing moved."""
    ceiling = max(ranges) if ranges else maximum
    if maximum:
        ceiling = min(ceiling, maximum)
    if nominal <= ceiling:
        return (nominal, "")
    return (ceiling,
            f"the nominal {what} of {nominal:.6g} {unit} is beyond this "
            f"model's {ceiling:.6g} {unit} ceiling and is clamped to it")

# The window in which a reading counts as "the output is at its
# compliance", as a fraction of the requested limit. Both edges are
# decisions rather than tuned numbers, and both were set from measured
# hardware on 2026-08-21:
#
#   floor  - below this the output never got there. A settled reading
#            under it means something is drawing the current away.
#   ceiling- above this the limit is NOT being enforced at the value
#            that was asked for. The U2722A sat at -2.0 V against a 1 V
#            limit, because the limit had been refused and the range
#            rail was bounding the output instead; the check tested only
#            the floor and recorded it as a pass. An output beyond its
#            own compliance is the one reading that proves the
#            compliance is not working, and it must be the loudest
#            result the probe can produce, not the quietest.
#
# The ceiling has to allow overshoot, because a healthy clamp does
# overshoot: the miniSMU settles at 1.023x its limit with the
# compliance working correctly. 1.25 sits clear of that and a factor of
# two below a limit that is simply not in force.
COMPLIANCE_FLOOR = 0.8
COMPLIANCE_CEILING = 1.25

# Two consecutive readings closer together than this are treated as the
# same reading, and the output as settled. Chosen against the ramp it
# has to distinguish: the GSM-20H10 climbs about 0.23 V per poll at the
# probe current, roughly forty times this, while the noise on a settled
# reading is far below it - the U2722A is the coarsest instrument here
# and one count on its 2 V range is 122 uV.
#
# Expressed as a fraction of the compliance in force, because it is a
# fraction of the compliance that it has to mean: an instrument whose
# envelope moved the compliance would otherwise get a settle window
# calibrated for somebody else's limit. `SETTLE_TOLERANCE_V` is the
# nominal value, kept because it is the number the paragraph above was
# measured against; `Checkup._settle_tolerance()` is what the run uses.
SETTLE_TOLERANCE_FRACTION = 0.005
SETTLE_TOLERANCE_V = PROBE_COMPLIANCE_V * SETTLE_TOLERANCE_FRACTION

#: Readings timed for the per-reading figure, after a warm-up read that
#: is taken and discarded. Named because two places have to agree on it:
#: the headline timing and the fast-end point of the aperture fit, which
#: is a difference between them and is only meaningful if both ends were
#: measured the same way.
TIMED_READINGS = 5

#: How many commands an error names as its possible cause. A group in
#: this tool is a handful of writes; a cap this size only bites on a
#: driver method that sends a great many, where a full list would be
#: unreadable anyway.
COMMANDS_LISTED_WITH_AN_ERROR = 12

# Sourcing 0.1 V into an open circuit should draw essentially nothing.
# The threshold is loose because the 2611A's low ranges and the
# miniSMU's autoranging both have offsets at this level; what it is
# really catching is a reading that came back in the wrong units, from
# the wrong quantity, or as a compliance-clamped value.
OPEN_CIRCUIT_MAX_A = 1e-5

SWEEP_POINTS = 5


class Result:
    """One check: what was tried, what happened, and how bad it is.

    `severity` is one of "pass", "warn", "fail", "skip". A warn is
    something worth a human's attention that does not mean the driver
    is wrong - an unverifiable capability, a slow reading, an instrument
    that cannot be asked about errors.
    """

    def __init__(self, tier, name, severity, detail="", elapsed_s=None):
        self.tier = tier
        self.name = name
        self.severity = severity
        self.detail = detail
        self.elapsed_s = elapsed_s

    def as_dict(self):
        return {"tier": self.tier, "name": self.name,
                "severity": self.severity, "detail": self.detail,
                "elapsed_s": self.elapsed_s}


class Checkup:
    """Runs the checks and collects Results.

    Takes a live driver. Does not open or close the transport - the
    caller owns the connection, same rule the experiments follow.
    """

    def __init__(self, driver, log=None, open_circuit=True, nplc=None,
                 command_log=None):
        self.driver = driver
        #: The levels this run will source, reconciled against this
        #: driver's declared envelope. Resolved once here so every check
        #: and every message quotes the same numbers, and re-derived on
        #: one axis in tier 3 where the active range turns out to
        #: demand it.
        self.probe = probe_levels_for(driver)
        #: The trace sink, when one is installed - a list of
        #: `(elapsed, sent, reply)`. Read-only here: the checkup uses it
        #: to say which commands an error could have come from, and does
        #: not care whether anyone is collecting it. None when tracing
        #: is off, in which case errors are reported without candidates
        #: exactly as before.
        self._command_log = command_log
        self._command_mark = 0
        self.results = []
        self._log = log or (lambda text: None)
        self._output_is_off = False
        self._sensing_note = None
        self._nplc = None
        self._seconds_per_reading = None
        # The one-off cost of the first reading after the output comes
        # up, kept separate from the steady-state figure because a run
        # pays it once and a sweep does not pay it per point.
        self._first_reading_s = None
        self._timing_error = None
        self._timeouts = 0
        self._comms_suspect = False
        # Set when run() ended on a desynchronised link rather than by
        # reaching the end of the requested tiers. build_report() turns
        # it into the banner that says the report is incomplete.
        self._stopped_early = False
        self._ramping = False
        # False when something IS attached - the simulated instrument
        # models a resistor, and a bench operator may be checking a rig
        # they cannot easily unplug. The measurement checks then record
        # what they saw without judging it, because the expected answer
        # is unknown. Everything else runs unchanged.
        self.open_circuit = bool(open_circuit)
        # Integration time to measure at. None means the fast end of
        # the declared range, which is what a commissioning run wants.
        # Setting it deliberately turns Tier 3's timing figure into an
        # experiment: read at two NPLCs and the difference is the
        # instrument's actual per-reading cost, which is how many
        # apertures a "reading" really costs.
        self.requested_nplc = nplc

    # ---- bookkeeping ----
    def record(self, tier, name, severity, detail="", elapsed_s=None):
        result = Result(tier, name, severity, detail, elapsed_s)
        self.results.append(result)
        mark = {"pass": "ok  ", "warn": "warn", "fail": "FAIL",
                "skip": "skip"}[severity]
        self._log(f"  [{mark}] {name}" + (f"  -- {detail}" if detail else ""))
        return result

    def attempt(self, tier, name, action, expect=None, allow_unsupported=True):
        """Call `action`, time it, and record what happened.

        `expect`, if given, is called with the return value and returns
        either True or a string explaining the problem. A
        NotImplementedError is recorded as a skip rather than a failure
        when `allow_unsupported` - declining a capability the driver
        never claimed is correct behaviour, not a fault.
        """
        started = time.perf_counter()
        try:
            value = action()
        except NotImplementedError as exc:
            elapsed = time.perf_counter() - started
            if allow_unsupported:
                return self.record(tier, name, "skip", str(exc) or
                                   "not supported by this model", elapsed)
            return self.record(tier, name, "fail",
                               f"unexpectedly unsupported: {exc}", elapsed)
        except TransportDesynchronised as exc:
            elapsed = time.perf_counter() - started
            self._on_desynchronised(tier, name, exc, elapsed)
            raise
        except Exception as exc:
            elapsed = time.perf_counter() - started
            detail = f"{type(exc).__name__}: {exc}"
            return self.record(tier, name, "fail", detail, elapsed)

        elapsed = time.perf_counter() - started
        if expect is not None:
            verdict = expect(value)
            if verdict is not True:
                return self.record(tier, name, "fail", str(verdict), elapsed)
        return self.record(tier, name, "pass",
                           "" if value is None else str(value)[:120], elapsed)

    def setup(self, tier, what, steps):
        """Run a sequence of configuration calls, grading each one.

        Returns True when every step succeeded. On the first failure it
        records that step and stops, because the ones after it were
        written assuming it worked - running them would produce a page
        of consequential failures with the real one buried at the top.

        This exists because configuration used to be called bare while
        every *check* went through `attempt()`. A driver that refuses a
        configuration - which is correct behaviour, and which deviation
        54 on the U2722A made real - crashed the tool instead of being
        reported by it.
        """
        for name, action in steps:
            result = self.attempt(tier, f"{what}: {name}", action,
                                  allow_unsupported=False)
            if result.severity != "pass":
                return False
        return True

    def check_queue(self, tier, after):
        """Ask the instrument whether it understood the last command.

        This is the check that makes the whole tool worth running: it is
        the difference between "the method did not raise" - which the
        offline tests already prove against a fake - and "the instrument
        confirmed it parsed that".

        The queue is drained once per group of commands, not after every
        write, because a drain is a round trip and doing it per write
        would roughly double the length of a run. The cost is
        attribution: on the U2722A on 2026-08-21 a `-222` arrived after
        a group of three writes and nothing in the report could say
        which of the three the instrument had refused.

        So when there ARE errors, the commands written since the last
        drain are named. That is free - they are already being recorded
        for the trace - and it narrows "somewhere in this check" to a
        list you can read. It deliberately does not guess which one:
        SCPI queues are not required to preserve order against writes,
        and naming a single command would be a confident answer to a
        question the instrument was never asked.
        """
        try:
            errors = []
            for _ in range(21):
                code, message = self.driver.read_error()
                if code == 0:
                    break
                errors.append(f"{code}: {message}")
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self._mark_commands()
            return self.record(tier, f"error queue after {after}", "warn",
                               f"could not read the queue: {exc}")
        detail = "; ".join(errors)
        candidates = self._commands_since_mark()
        self._mark_commands()
        if errors:
            if candidates:
                listed = " | ".join(candidates)
                detail += f"  [after: {listed}]"
            return self.record(tier, f"error queue after {after}", "fail",
                               detail)
        return self.record(tier, f"error queue after {after}", "pass")

    def _commands_since_mark(self):
        """Writes recorded since the previous drain, oldest first.

        Queries are excluded: a query that the instrument refused fails
        loudly at the read instead, so including them would pad the list
        with commands already known to have worked.
        """
        log = self._command_log
        if log is None:
            return []
        out = []
        for entry in log[self._command_mark:]:
            try:
                sent = entry[1]
            except (IndexError, TypeError):
                continue
            text = str(sent)
            if text.endswith("[?]"):
                continue
            out.append(text.strip())
        return out[:COMMANDS_LISTED_WITH_AN_ERROR]

    def _mark_commands(self):
        if self._command_log is not None:
            self._command_mark = len(self._command_log)

    def _on_desynchronised(self, tier, name, exc, elapsed):
        """De-energise, record why the run ended, and let it end.

        This replaces a resync-and-continue path. That path warned
        correctly that everything below it might be a consequence rather
        than a fault, and then ran 1386 further checks anyway on
        2026-08-25 - so the warning was true and useless. A report whose
        every line after some point may be fiction is not a report.

        Output-off first, because a checkup can be left running and the
        link may have gone while the output was on. It is a write, so it
        still reaches a desynchronised instrument; what it cannot be is
        *confirmed*, since confirming means querying. The wording below
        says commanded, not confirmed, and that distinction is the
        difference between a note and a false reassurance.
        """
        self._timeouts += 1
        self._comms_suspect = True
        commanded = False
        driver = self.driver
        if driver is not None:
            try:
                driver.safe_output_off()
                commanded = True
            except Exception:
                # Deliberately NOT re-raising a desync here, unlike
                # everywhere else in this file. This handler IS the
                # de-energise; letting the exception past it would
                # abandon the shutdown in order to report the fault
                # that made the shutdown necessary.
                # Bounded by the transport's own write timeout; never
                # retried, because there is nothing to wait for and a
                # loop here would hang the caller on a dead cable.
                commanded = False
        self._output_is_off = False
        note = (" [OUTPUT-OFF WAS COMMANDED BUT COULD NOT BE CONFIRMED - "
                "check the front panel before touching the fixture]"
                if commanded else
                " [OUTPUT-OFF COULD NOT EVEN BE SENT - de-energise the "
                "instrument at the front panel before touching the "
                "fixture]")
        self.record(tier, name, "fail",
                    f"{type(exc).__name__}: {exc}"
                    " [the link went out of step here; the checkup stopped "
                    "rather than report readings that would answer the "
                    "previous command. Reconnect the instrument and run it "
                    "again]" + note,
                    elapsed)

    def _drain_quietly(self):
        """Empty the error queue without recording anything.

        Used after a deliberate mode change, so that a complaint about
        the *previous* mode's configuration is not attributed to the
        first command of the next one.
        """
        try:
            for _ in range(21):
                code, _ = self.driver.read_error()
                if code == 0:
                    return
        except TransportDesynchronised:
            raise
        except Exception:
            return

    def counts(self):
        out = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
        for result in self.results:
            out[result.severity] += 1
        return out

    # ---- tier 1 ----
    def tier1_identity(self):
        driver = self.driver
        self._log("\nTier 1 - identity and declarations")

        self.attempt(1, "identify()", driver.identify,
                     expect=lambda v: True if v and str(v).strip()
                     else "empty identity reply")

        # The registry is what picks the driver at connect. If the
        # identity no longer resolves to the class in use, auto-detection
        # is broken even though everything else may work.
        from drivers.registry import driver_for_idn
        try:
            idn = driver.identify()
            resolved = driver_for_idn(idn)
            if resolved is type(driver):
                self.record(1, "identity resolves to this driver", "pass",
                            type(driver).__name__)
            elif resolved is None:
                self.record(1, "identity resolves to this driver", "fail",
                            f"MODEL_IDS {type(driver).MODEL_IDS} does not "
                            f"match {idn!r} - auto-detect would fail")
            else:
                self.record(1, "identity resolves to this driver", "fail",
                            f"resolves to {resolved.__name__}, not "
                            f"{type(driver).__name__} - auto-detect would "
                            f"pick the wrong driver for this instrument")
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(1, "identity resolves to this driver", "fail", str(exc))

        for label, value in (
                ("firmware", getattr(driver, "firmware", None)),
                ("sweep kind", getattr(driver, "sweep_kind", None))):
            if callable(value):
                self.attempt(1, label, value)

        self.attempt(1, "reset()", driver.reset)
        self.check_queue(1, "reset()")

        note = getattr(driver, "sweep_note", None)
        if callable(note):
            self.attempt(1, "sweep_note()", note)

        limits = driver.LIMITS
        self.record(1, "declared limits", "pass",
                    f"{limits.max_voltage} V, {limits.max_current} A, "
                    f"{len(limits.current_ranges)} current range(s)")

        # The levels this run will source, and why they are what they
        # are. Recorded in tier 1 rather than left implicit, because a
        # commissioning report is read against other instruments' and a
        # probe that differs between them has to say so on its own line
        # - otherwise the first person to compare two reports finds a
        # different current in tier 3 and has nowhere to look.
        self.record(1, "probe levels", "pass",
                    f"{self.probe.describe()} - "
                    + "; ".join(self.probe.notes))

        # What is known about a source level below one count of whatever
        # range is active. Three answers, and none of them is a pass:
        # this is a property of the instrument that a checkup can report
        # and cannot establish.
        for quantity in ("current", "voltage"):
            self._record_sub_count_state(quantity)

    def _record_sub_count_state(self, quantity):
        """Say, per axis, what is known about sub-count source levels.

        A `warn` for `unmeasured`, deliberately, and on six of the eight
        drivers in the registry. It is not noise: below one count of the
        active range a commanded level is offset residue, and on the one
        instrument where that has been measured the residue's sign was
        not the sign anybody asked for - it walked the output to the
        range rail during a commissioning run. Whether the same is true
        of the Keithleys, the B2901A and the GSM-20H10 is unknown, and
        an unknown that changes which way current flows through somebody
        's sample does not render as a skip.

        Each warn is closed by one bench measurement on one instrument,
        not by a change here.
        """
        cls = type(self.driver)
        state = cls.sub_count_state(quantity)
        name = f"sub-count {quantity} levels"
        if state == cls.SUB_COUNT_REFUSED:
            self.record(1, name, "pass",
                        "measured on this model, and this driver refuses a "
                        "level below its declared floor before the output "
                        "is energised")
        elif state == cls.SUB_COUNT_NOT_APPLICABLE:
            self.record(1, name, "skip",
                        f"this model has no source {quantity} range for a "
                        f"level to fall below, so the question does not "
                        f"arise in this form. What a sub-count source "
                        f"{quantity} would mean here is itself unmeasured")
        else:
            self.record(
                1, name, "warn",
                f"UNMEASURED on this model. Every fixed-range converter "
                f"has a bottom count; below it a commanded level is offset "
                f"residue whose sign is not commanded, which on the one "
                f"instrument where this was measured drove the output to "
                f"the range rail. Nothing in this suite puts a floor under "
                f"a source {quantity} here, and nothing has measured where "
                f"the floor is. Closed by one bench measurement: command "
                f"plus and minus a small fraction of a count on a wide "
                f"range and see whether the output follows the sign")

    # ---- tier 2 ----
    def tier2_configuration(self):
        driver = self.driver
        self._log("\nTier 2 - configuration syntax (output off)")

        # Off first and off throughout. Everything below is configuration
        # only; nothing should reach the terminals.
        result = self.attempt(2, "output_off()", driver.output_off)
        self._output_is_off = result.severity == "pass"
        self.check_queue(2, "output_off()")

        self._force_two_wire()

        for mode in ("voltage", "current"):
            self.attempt(2, f"set_source_function({mode!r})",
                         lambda m=mode: driver.set_source_function(m))
            self.check_queue(2, f"set_source_function({mode!r})")

        # Each setter is exercised in the source mode the experiments
        # actually use it in, and NOT in the other one.
        #
        # This is not fussiness. A real instrument rejects the wrong
        # combination and is right to: setting a current *level* while
        # sourcing voltage is a settings conflict, and on the GSM-20H10
        # setting the source range while source read-back is on is
        # error 823. An earlier version of this checkup called every
        # setter in one mode and reported both as driver faults, which
        # they are not - IVSweepExperiment._one_sweep never makes either
        # call. A commissioning tool that invents failures the
        # application cannot produce is worse than useless, because it
        # trains people to ignore it.
        #
        # So the shape below mirrors _one_sweep: sourcing voltage means
        # limiting and ranging the *current*, and vice versa.
        # Ranges before limits, which is fault 15 and which this tool had
        # backwards until 2026-08-20.
        #
        # On the GSM-20H10 the wrong order cost three of six checkup
        # failures and took tier 3 with them: the instrument would not
        # energise afterwards, so `measure()` returned `(None, None)`
        # and every reading, the sweep and the timing figure went with
        # it. Reordering took that instrument from six failures to
        # three, with tier 3 green.
        #
        # Every experiment already orders it correctly - that is what
        # `tests/test_range_before_limit.py` holds - so this tool was
        # producing a failure the application cannot produce, and then a
        # cascade of failures behind it. A commissioning tool that
        # invents faults teaches people to ignore it, which is the one
        # thing it cannot afford.
        by_mode = {
            "voltage": [
                ("apply_ranges", lambda: driver.apply_ranges(
                    RangePlan.for_sourcing(
                        "voltage", source_range=self.probe.voltage,
                        measure_range=self.probe.compliance_i))),
                ("set_current_limit", lambda: driver.set_current_limit(
                    self.probe.compliance_i)),
                ("set_voltage_level(0)",
                 lambda: driver.set_voltage_level(0.0)),
            ],
            "current": [
                ("apply_ranges", lambda: driver.apply_ranges(
                    RangePlan.for_sourcing(
                        "current", source_range=self.probe.current,
                        measure_range=self.probe.compliance_v))),
                ("set_voltage_limit", lambda: driver.set_voltage_limit(
                    self.probe.compliance_v)),
                ("set_current_level(0)",
                 lambda: driver.set_current_level(0.0)),
            ],
        }
        for mode, checks in by_mode.items():
            driver.set_source_function(mode)
            self._drain_quietly()
            for name, action in checks:
                label = f"{name}()" if "(" not in name else name
                self.attempt(2, f"{label}  [sourcing {mode}]", action)
                self.check_queue(2, f"{name} while sourcing {mode}")

        driver.set_source_function("voltage")
        self._drain_quietly()
        self.attempt(2, "set_source_delay()",
                     lambda: driver.set_source_delay(0.01))
        self.check_queue(2, "set_source_delay")

        # Autoranging is a real capability on some models and absent on
        # others; a refusal here is information, not a fault. The
        # U2722A has no autorange at all and says so - which is why the
        # plan carries AUTO on every axis rather than a value that
        # would quietly succeed.
        self.attempt(2, "apply_ranges(all AUTO)",
                     lambda: driver.apply_ranges(RangePlan(
                         source_current=AUTO, source_voltage=AUTO,
                         measure_current=AUTO, measure_voltage=AUTO)))
        self.check_queue(2, "apply_ranges(all AUTO)")

        self._tier2_compliance_survives_ranging()
        self._tier2_range_readback()
        self._tier2_power_limit()
        self._tier2_sub_count_refusal()
        self._tier2_capabilities()

    def _tier2_range_readback(self):
        """Is the instrument on the ranges it was just told to be on?

        `apply_ranges()` reports what it *sent*. That is the half of the
        problem the compliance readback did not cover, and it is not the
        lesser half: on the GSM-20H10, asking for a 100 uA measurement
        range with a 10 uA compliance in force gives `+824` and leaves
        `SENS:CURR:DC:RANG?` reading `1.050000E-05`. No exception, a
        range the operator did not choose, and every reading afterwards
        taken on it - overranging into a sentinel rather than reading.

        Runs immediately after `_tier2_compliance_survives_ranging()`
        restored the correct order, so the ranges in force are known
        exactly: this is the voltage-sourcing plan, with the source
        current axis carrying nothing and the measured voltage read back
        from the source.

        Every axis is reported, including the ones with nothing to
        compare against and the ones this driver cannot query. An axis
        that is silently absent from a report reads as an axis that was
        checked.
        """
        driver = self.driver
        requested = {
            "source_voltage": self.probe.voltage,
            "source_current": NOT_SOURCED,
            "measure_current": self.probe.compliance_i,
            "measure_voltage": AUTO,
        }
        for axis in type(driver).RANGE_AXES:
            self._record_readback(
                2, f"range readback: {axis.replace('_', ' ')}",
                lambda a=axis: driver.verify_range(a, requested[a]))

    def _tier2_power_limit(self):
        """The ceiling nothing watched.

        Power compliance applies whichever of the three limits is lower,
        so a nonzero one silently overrides the compliance the
        experiment set - and reading the voltage or current limit back
        reports the *programmed* value rather than the effective one, so
        the readback that already exists cannot see it. It resets to
        disabled on every model that has it, which is exactly why
        nothing looked: `Recall setup` can carry a nonzero one into a
        session and no other check in this tool would notice.

        One query answers it, and this is that query.
        """
        self._record_readback(2, "power limit is where the driver put it",
                              self.driver.verify_power_limit)

    def _tier2_sub_count_refusal(self):
        """Where a floor is declared, prove it actually refuses.

        Asked with the output off, and asked in the direction where the
        interesting answer is the correct one: the level offered is a
        tenth of the driver's own declared floor, so a driver whose
        guard works must decline it. A guard that has stopped guarding
        passes every other check in this file - the level is written,
        the instrument accepts it, the error queue is clean - which is
        exactly the shape of fault 19.

        Skipped where no floor is declared. That is not silence: the
        tier 1 entry has already said, per axis, whether the floor is
        unmeasured or does not apply.

        Each axis is exercised in the source mode that axis belongs to,
        for the same reason the rest of tier 2 is: setting a current
        level while sourcing voltage is a settings conflict, and a
        commissioning tool that produces failures the application cannot
        produce trains people to ignore it.
        """
        driver = self.driver
        probed = False
        for quantity, unit in (("current", "A"), ("voltage", "V")):
            name = f"a sub-count {quantity} level is refused"
            try:
                floor = driver.source_level_floor(quantity)
            except TransportDesynchronised:
                raise
            except Exception as exc:
                self.record(2, name, "warn",
                            f"the driver could not say what its floor is: "
                            f"{type(exc).__name__}: {exc}")
                continue
            if floor is None:
                self.record(2, name, "skip",
                            f"this model declares no source {quantity} floor "
                            f"- see the tier 1 entry for what that means "
                            f"here")
                continue

            # Only now, and only for an axis that is actually going to
            # be written. A mode change is real traffic on most models,
            # and sending it to prove nothing would put commands in
            # every instrument's trace for the sake of the one that has
            # a floor.
            driver.set_source_function(quantity)
            self._drain_quietly()
            probed = True

            setter = (driver.set_current_level if quantity == "current"
                      else driver.set_voltage_level)
            offered = floor / 10.0
            try:
                setter(offered)
            except TransportDesynchronised:
                raise
            except RangeError as exc:
                self.record(2, name, "pass",
                            f"{offered:.6g} {unit} against a {floor:.6g} "
                            f"{unit} floor: {exc}")
                self._drain_quietly()
                continue
            except Exception as exc:
                self.record(2, name, "fail",
                            f"refused with {type(exc).__name__} rather than "
                            f"RangeError, so callers cannot tell an "
                            f"unreachable level from a broken link: {exc}")
                self._drain_quietly()
                continue
            self.record(
                2, name, "fail",
                f"{offered:.6g} {unit} is a tenth of this model's own "
                f"{floor:.6g} {unit} floor and it was accepted. Below the "
                f"floor the output is offset residue whose sign is not "
                f"commanded, so the guard is what stops an operator "
                f"getting a bias at the opposite polarity from the one "
                f"their sample is wired for")
            self._drain_quietly()
            # Put the axis back where the rest of tier 2 expects it.
            setter(0.0)

        if probed:
            driver.set_source_function("voltage")
            self._drain_quietly()

    def _record_readback(self, tier, name, ask):
        """Run one readback and record it, loudly where it disagrees.

        The whole reason `core.readback` has five states rather than two
        is that four of them are not a pass, and this is the one place
        that decides how each renders. A mismatch is a fail with the
        word SAFETY in it, because a range or a compliance that is not
        the one the software asked for is the bound on what reaches the
        sample, and the operator reading a wall of green needs it to
        stop being a wall.
        """
        try:
            answer = ask()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(tier, name, "fail",
                        f"the readback itself raised "
                        f"{type(exc).__name__}: {exc}")
            return None
        detail = answer.detail
        if answer.is_safety_event:
            detail = ("SAFETY: the instrument is not in the state it was "
                      "asked for. " + detail)
        self.record(tier, name, answer.severity, detail)
        return answer

    def _tier2_compliance_survives_ranging(self):
        """Does the compliance still hold after the ranges are applied?

        The check that would have caught the GSM-20H10 in one run
        instead of a week. On that instrument
        `SOUR:CURR:RANG:AUTO ON` - a command sent only to express
        indifference about an axis carrying nothing - silently reset the
        current compliance from 105 uA to 1 nA, with a clean error queue
        and nothing raised. It surfaced only because a later, innocent
        command tripped over the collapsed value and complained about
        something else entirely.

        Nothing in this suite read a compliance back, so on an
        instrument where nothing downstream trips, that collapse is
        invisible. Five of the seven checkups on 2026-08-18 came back
        clean, and "clean" there means *none observed*, not *none*.

        **Deliberately sends the limit before the ranges**, which is the
        order fault 15 exists to prevent and which this tool was fixed
        to stop using. That is the point: the question is what ranging
        does to a compliance already in force, and asking it the safe
        way round - where the experiment's own limit arrives afterwards
        and papers over any damage - is a probe whose interesting answer
        is not the correct one. The correct order is restored
        immediately afterwards, and the output is off throughout tier 2.
        """
        driver = self.driver
        mode = "voltage"
        limit = self.probe.compliance_i

        before = driver.verify_compliance(mode, limit)
        if before.state == readback_states.UNSUPPORTED:
            self.record(2, "compliance survives ranging", "skip",
                        f"{before.detail} - a collapse here would be "
                        f"invisible")
            return

        # limit first, on purpose; see the docstring
        try:
            driver.set_current_limit(limit)
            driver.apply_ranges(RangePlan.for_sourcing(
                mode, source_range=self.probe.voltage, measure_range=limit),
                log=self._log)
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(2, "compliance survives ranging", "fail",
                        f"{type(exc).__name__}: {exc}")
            return

        after = driver.verify_compliance(mode, limit)
        detail = after.detail
        if after.is_safety_event:
            detail += (" - a ranging command moved the compliance. "
                       "See docs/faults/23-autorange-resets-compliance.md")
        self.record(2, "compliance survives ranging", after.severity, detail)

        # Put the correct order back before anything else runs.
        driver.apply_ranges(RangePlan.for_sourcing(
            mode, source_range=self.probe.voltage, measure_range=limit),
            log=self._log)
        driver.set_current_limit(limit)
        self.check_queue(2, "compliance survives ranging")

    def _force_two_wire(self):
        """2-wire for the checkup, where the driver allows it.

        With nothing connected, 4-wire leaves the sense leads open and
        many SMUs will slew to compliance trying to servo a voltage they
        cannot measure. Where sensing cannot be changed, that is recorded
        rather than worked around - the operator needs to know the
        readings below were taken 4-wire into an open circuit.
        """
        driver = self.driver
        supports = driver.supports_remote_sense_control()
        if not supports:
            self._sensing_note = (
                f"sensing is fixed at {driver.fixed_sense() or 'unknown'} on "
                f"this model, so the measurement checks below run 4-wire "
                f"into an open circuit and may read at compliance")
            self.record(2, "set_remote_sense(False)", "skip",
                        self._sensing_note)
            return
        result = self.attempt(2, "set_remote_sense(False)  [2-wire]",
                              lambda: driver.set_remote_sense(False))
        if result.severity != "pass":
            self._sensing_note = ("2-wire could not be selected; readings "
                                  "below may be affected")
        self.check_queue(2, "set_remote_sense(False)")

    def _tier2_capabilities(self):
        """Every declared optional capability, exercised once.

        A declaration that the instrument rejects is the most valuable
        thing this tool can find: the ledger says the model has the
        feature, the hardware disagrees, and until now nothing checked.
        """
        driver = self.driver
        cls = type(driver)

        if cls.supports_nplc():
            low, high = cls.NPLC_RANGE
            for value in (low, high):
                self.attempt(2, f"set_nplc({value:g})  [declared limit]",
                             lambda v=value: driver.set_nplc(v),
                             allow_unsupported=False)
                self.check_queue(2, f"set_nplc({value:g})")
            # And put it somewhere sensible before anything is
            # measured. Leaving it at the declared ceiling is a real
            # trap: the U2722A's ceiling is 255 PLC, which at 50 Hz is a
            # 5.1 s aperture, and with no combined read that is 10.5 s
            # per point. A 5-point sweep then takes nearly a minute and
            # times out, which reads as a broken sweep on an instrument
            # that was working exactly as configured.
            wanted = low if self.requested_nplc is None \
                else driver.clamp_nplc(self.requested_nplc)
            label = "restored for measuring" if self.requested_nplc is None \
                else "requested"
            self.attempt(2, f"set_nplc({wanted:g})  [{label}]",
                         lambda: driver.set_nplc(wanted),
                         allow_unsupported=False)
            self._nplc = driver.clamp_nplc(wanted)
        else:
            self.record(2, "NPLC", "skip", "not declared for this model")

        if cls.supports_ovp():
            choice = cls.OVP_CHOICES[0]
            self.attempt(2, f"set_voltage_protection({choice!r})",
                         lambda: driver.set_voltage_protection(choice),
                         allow_unsupported=False)
            self.check_queue(2, "set_voltage_protection()")
        else:
            self.record(2, "OVP", "skip", "not declared for this model")

        if cls.supports_high_z_off():
            self.attempt(2, "set_output_off_mode(high_z=True)",
                         lambda: driver.set_output_off_mode(True),
                         allow_unsupported=False)
            self.check_queue(2, "set_output_off_mode()")
            self.attempt(2, "set_output_off_mode(high_z=False)",
                         lambda: driver.set_output_off_mode(False),
                         allow_unsupported=False)
        else:
            self.record(2, "high-Z output off", "skip",
                        "not declared for this model")

        # Not through `attempt()`. With no expectation attached, a
        # driver returning None passed indistinguishably from one
        # returning a real answer, and the detail column came out empty
        # - which reads as "checked, fine" rather than "asked, and it
        # cannot say". That is the same non-discriminating shape the
        # tier 3 version's docstring warns about, one tier up.
        #
        # This one cannot be a verdict on correctness: the output is off
        # here, so False is the honest answer and True would be the
        # suspicious one. What it can do is say which of the three
        # things happened.
        try:
            state = driver.compliance_tripped()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(2, "compliance_tripped()", "fail",
                        f"raised {type(exc).__name__}: {exc} with the "
                        f"output off")
        else:
            if state is None:
                self.record(2, "compliance_tripped()", "skip",
                            "not implemented by this driver")
            elif state:
                self.record(2, "compliance_tripped()", "warn",
                            "reported True with the output off, which "
                            "should not be possible - the flag may be "
                            "latched from an earlier run, or read from "
                            "an axis that is not the active one")
            else:
                self.record(2, "compliance_tripped()", "pass",
                            "False with the output off")

    # ---- choosing a level the instrument can actually express ----
    def _resolve_source_level(self, quantity, unit):
        """Raise the probe level to this instrument's floor, if it has one.

        Called **after** the ranging plan has been carried out and
        **before** anything is sourced, because the floor is a property
        of the range that is now active and of nothing else. On the
        U2722A the checkup's current-mode plan puts the shared knob on
        R120mA, where one count is 7.32 uA; the nominal 1 uA probe is a
        seventh of a count there and comes out as offset residue whose
        sign is not the one that was asked for. On the same instrument's
        R1uA range the same 1 uA is eleven counts and perfectly good.
        There is no single number that is right on both.

        The resolved level is written back into `self.probe`, so every
        message after this quotes what was actually sourced rather than
        what was nominally asked for. A report that says "sourcing 1e-06
        A" while the instrument was handed 73 uA is a report that will
        be quoted later.

        Returns the level to use. Never lowers one: a floor says what is
        too small, and nothing here knows what would be too large beyond
        the envelope clamp that has already been applied.
        """
        wanted = (self.probe.current if quantity == "current"
                  else self.probe.voltage)
        name = f"{quantity} probe level is expressible on the active range"
        state = type(self.driver).sub_count_state(quantity)

        try:
            floor = self.driver.source_level_floor(quantity)
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(3, name, "warn",
                        f"the driver could not say what its floor is: "
                        f"{type(exc).__name__}: {exc}. Probing at "
                        f"{wanted:.6g} {unit} anyway")
            return wanted

        if floor is None:
            # No declared floor. Whether that is safe depends entirely
            # on which of the three sub-count states this model is in,
            # and the difference is the whole point: "there is no
            # converter to fall below" and "nobody has measured this
            # converter" must not read the same in a report.
            if state == type(self.driver).SUB_COUNT_NOT_APPLICABLE:
                self.record(3, name, "skip",
                            f"{wanted:.6g} {unit}; this model has no source "
                            f"{quantity} range for a level to fall below, so "
                            f"the question does not arise in this form")
            else:
                self.record(3, name, "warn",
                            f"probing at {wanted:.6g} {unit}, and this model "
                            f"declares no floor: what a source level below "
                            f"one count of the active range does here is "
                            f"UNMEASURED. On the one instrument where it has "
                            f"been measured the output was offset residue "
                            f"whose sign was not the one commanded. Nothing "
                            f"here says this level is in that regime - it "
                            f"says nobody can tell")
            return wanted

        if abs(wanted) >= floor:
            self.record(3, name, "pass",
                        f"{wanted:.6g} {unit} is at or above the "
                        f"{floor:.6g} {unit} this instrument can express on "
                        f"the range the plan landed on")
            return wanted

        raised = floor
        if quantity == "current":
            self.probe.current = raised
        else:
            self.probe.voltage = raised
        self.record(
            3, name, "pass",
            f"the nominal {wanted:.6g} {unit} is below the {floor:.6g} "
            f"{unit} this instrument can express on the range the plan "
            f"landed on, so it is probed at {raised:.6g} {unit} instead. "
            f"Below the floor the output is offset residue whose sign is "
            f"not commanded, so a smaller probe would be testing the "
            f"instrument's offset rather than its source")
        return raised

    def _settle_tolerance(self):
        """Two readings closer than this count as the same reading.

        Derived from the compliance this run is actually using rather
        than from a module constant, for the same reason the probe is:
        the number has to mean the same fraction of the limit on every
        instrument. See SETTLE_TOLERANCE_V for what it has to
        distinguish.
        """
        return self.probe.compliance_v * SETTLE_TOLERANCE_FRACTION

    # ---- tier 3 ----
    def tier3_measurement(self):
        driver = self.driver
        self._log("\nTier 3 - live measurement (open circuit expected)")

        if not self._output_is_off:
            self.record(3, "live measurement", "skip",
                        "output_off() did not succeed, so enabling the "
                        "output is not safe")
            return

        driver.set_source_function("voltage")
        # Ranges before the limit, all four axes: sourcing volts and
        # measuring the current that flows.
        driver.apply_ranges(RangePlan.for_sourcing(
            "voltage", source_range=self.probe.voltage,
            measure_range=self.probe.compliance_i))
        driver.set_current_limit(self.probe.compliance_i)
        # Asked here, with the output still off and the ranges just
        # applied, so that a level the instrument cannot express is
        # found before anything is energised rather than after.
        self._resolve_source_level("voltage", "V")
        driver.set_voltage_level(0.0)

        self.attempt(3, "output_on()", driver.output_on)
        self.check_queue(3, "output_on()")

        try:
            self._tier3_body()
        finally:
            # Whatever happened above, the output comes off. A checkup
            # that aborts with the terminals live is worse than no
            # checkup.
            self.attempt(3, "output_off()  [cleanup]", driver.output_off)

    def _tier3_body(self):
        driver = self.driver

        # Generous, and derived from the integration time rather than
        # left at measure()'s 3 s default. At NPLC 10 a 2401 that has
        # to autorange on the way takes longer than that, and the
        # timeout it produces looks like a broken instrument rather
        # than a slow one.
        self.attempt(3, "measure() at 0 V",
                     lambda: driver.measure(timeout_s=self._read_timeout()),
                     expect=self._expect_reading)

        driver.set_voltage_level(self.probe.voltage)
        time.sleep(0.05)
        result = self.attempt(
            3, f"measure() at {self.probe.voltage} V",
            lambda: driver.measure(timeout_s=self._read_timeout()),
            expect=self._expect_reading)
        if result.severity == "pass":
            self._check_open_circuit(result)

        self.check_queue(3, "measure()")
        driver.set_voltage_level(0.0)

        # Sourcing current into an open circuit is the one place a
        # compliance limit is genuinely exercised: the instrument cannot
        # push the current anywhere, so it must ride into the voltage
        # limit. An instrument that reports something else here has a
        # compliance setting that is not doing what it says.
        # House rule 12 (Wave 6): the output comes down before the
        # source function changes, and everything is configured before
        # it goes back up.
        #
        # This block used to change function with the output still on
        # and rely on the instrument dropping it - which the 2400 family
        # does, and which no manual in the suite states for the 2450,
        # the B2901A or the 2611A. Doing it explicitly makes the
        # sequence identical on every model instead of depending on an
        # answer nobody has, and it turns the gap into something that
        # can be measured rather than assumed.
        gap_start = time.monotonic()
        driver.safe_output_off()

        # Every one of these is graded rather than called bare, because
        # a driver is allowed to REFUSE a configuration and that is not
        # a crash.
        #
        # The U2722A did exactly that until the probe became
        # instrument-aware: the tool asked for a module-wide 1 uA, the
        # shared-knob reconciliation put the current axis on R120mA
        # where one count is 7.32 uA, and the driver declined rather
        # than emitting offset residue of a sign nobody commanded.
        # Called bare, that RangeError escaped and took tier 3 with it -
        # the tool reporting nothing at all about an instrument that had
        # answered the question correctly.
        #
        # The refusal path stays, and stays graded. Choosing the level
        # from the instrument's own floor removes the case where the
        # *tool* provoked it; a driver may still decline for a reason
        # nobody has thought of, and that belongs in the report next to
        # everything else the instrument said, with the driver's own
        # message, while the run continues to whatever can still be
        # checked.
        #
        # The level is settled in two stages for the same reason the
        # floor is an instance method on the driver: it depends on the
        # range `apply_ranges()` just landed on, so it cannot be known
        # until those three steps have run.
        configured = self.setup(3, "configure for current sourcing", [
            ("set_source_function('current')",
             lambda: driver.set_source_function("current")),
            ("apply_ranges()  [current mode]",
             lambda: driver.apply_ranges(RangePlan.for_sourcing(
                 "current", source_range=self.probe.current,
                 measure_range=self.probe.compliance_v))),
            (f"set_voltage_limit({self.probe.compliance_v:g})",
             lambda: driver.set_voltage_limit(self.probe.compliance_v)),
        ])
        if configured:
            level = self._resolve_source_level("current", "A")
            configured = self.setup(3, "configure for current sourcing", [
                (f"set_current_level({level:g})",
                 lambda: driver.set_current_level(level)),
            ])
        if not configured:
            # The gap entry is recorded even here, as a skip, so every
            # driver's report has the same shape and a missing entry
            # always means a tool fault rather than an instrument that
            # declined. There is no duration to give: the output never
            # came back up, because there was nothing to bring it up
            # for.
            self.record(3, "output gap across a source-function change",
                        "skip",
                        "not measured - the instrument could not be "
                        "configured for current sourcing, so the output "
                        "was left off rather than restored",
                        elapsed_s=time.monotonic() - gap_start)
            self.record(3, "current-sourcing checks", "skip",
                        "the instrument could not be configured for "
                        "current sourcing - see the failure above; the "
                        "checks that depend on it were not attempted")
            driver.safe_output_off()
            return
        # The output has to be turned on AGAIN after a source-function
        # change. Changing function drops the output on the 2400 family,
        # and with auto output-off disabled - which this driver sets, so
        # that a sweep holds its level between points - the 2401's own
        # documentation is explicit that "the output must be turned on
        # before you can perform a :READ?".
        #
        # Miss it and `:READ?` simply never answers: the trigger model
        # is waiting for source-measure operations that cannot happen,
        # so the query blocks until the VISA timeout and reports a
        # comms failure for what is actually a configuration mistake.
        # Every experiment already calls output_on() after
        # set_source_function(); this checkup did not, and spent two
        # rounds looking like a driver fault.
        self.attempt(3, "output_on()  [after the mode change]",
                     driver.output_on)

        # How long the sample was not energised across a source-function
        # change, on this instrument, over this bus. Recorded because
        # the IV periodic run has to interrupt a bias to change function
        # (decision W6-3) and the operator needs a number to compare
        # against their device's relaxation time - not an assurance that
        # it was brief. On a slow GPIB link this is dominated by command
        # turnaround, not by the instrument.
        #
        # Informational: there is no threshold to pass or fail against,
        # because what counts as too long depends on the sample.
        gap_s = time.monotonic() - gap_start
        self.record(3, "output gap across a source-function change",
                    "pass", f"{gap_s * 1000:.0f} ms de-energised",
                    elapsed_s=gap_s)
        result = self.attempt(
            3,
            f"measure() sourcing {self.probe.current:g} A into open circuit",
            lambda: self._settle_to_compliance(),
            expect=self._expect_reading)
        if result.severity == "pass":
            volts, _ = self._last_reading
            ramping = getattr(self, "_ramping", False)
            if not self.open_circuit:
                self.record(3, "compliance on a sourced current", "skip",
                            f"{volts:.4g} V - not checked, something is "
                            f"connected")
            elif abs(volts) > self.probe.compliance_v * COMPLIANCE_CEILING:
                # The compliance is not being enforced at the value that
                # was requested. Checked BEFORE settling, because an
                # output above its own limit is a fault whether it has
                # come to rest there or is still on its way past.
                #
                # This is what the U2722A did on 2026-08-21: -2.0 V
                # against a 1 V limit, the limit having been refused as
                # below that range's floor, so the range rail bounded
                # the output instead. The check tested only the lower
                # edge and called it a pass.
                #
                # Loud, because of what a compliance is for. It is the
                # bound on what reaches the sample and the person at the
                # fixture, and an instrument holding a wider one than
                # the software asked for is exactly the case that must
                # not be discovered from the data afterwards.
                self.record(
                    3, "compliance reached on open circuit", "fail",
                    f"{volts:.4g} V against a "
                    f"{self.probe.compliance_v} V limit"
                    f" - beyond it by more than "
                    f"{(COMPLIANCE_CEILING - 1) * 100:.0f}%, so the limit "
                    f"that is holding the output is not the one that was "
                    f"set. Check whether the instrument accepted it: a "
                    f"limit can be refused for being small relative to "
                    f"the active range, and the range rail bounds the "
                    f"output instead")
            elif ramping:
                # Still climbing when the budget ran out. That is the
                # output capacitance charging at the probe current, not
                # a load - so it says so rather than sending someone to
                # check the terminals.
                self.record(
                    3, "compliance reached on open circuit", "skip",
                    f"reached {volts:.4g} V of a {self.probe.compliance_v} V "
                    f"limit and was still rising - the output is charging "
                    f"its own capacitance at {self.probe.current:g} A, "
                    f"which is open-circuit behaviour, just slow. "
                    f"Not a load")
            elif abs(volts) >= self.probe.compliance_v * COMPLIANCE_FLOOR:
                # Settled, and within the window. Only now is the
                # instrument known to be clamping, which is the one
                # moment `compliance_tripped()` can be asked where True
                # is the correct answer.
                #
                # Magnitude only. The SIGN carries no information here
                # and an earlier version of this check wrongly warned
                # about it.
                #
                # An instrument in compliance is not regulating: the
                # miniSMU reported -1.02 V while measuring -1.2e-10 A
                # against a requested +1 uA, so it was not delivering
                # the current at all. Which rail the loop saturates to
                # with nothing to push against is implementation-
                # defined, and a 10 kohm resistor later confirmed that
                # model's polarity is entirely conventional - positive
                # current, positive voltage, R = +9.95 kohm.
                #
                # Polarity can only be judged where the instrument is
                # actually delivering what was asked, which an open
                # circuit never is. The known-resistor test settles it;
                # this one cannot.
                self.record(
                    3, "compliance reached on open circuit", "pass",
                    f"{volts:.4g} V against a "
                    f"{self.probe.compliance_v} V limit,"
                    f" settled (sign not checked - a railed output saturates "
                    f"whichever way the loop happens to go)")
                self._check_compliance_reported()
            else:
                self.record(
                    3, "compliance reached on open circuit", "warn",
                    f"settled at {volts:.4g} V against a "
                    f"{self.probe.compliance_v} V limit and stopped rising - "
                    f"with nothing connected the output should ride up to "
                    f"compliance. Is something attached?")

        # Back to sourcing voltage for the timing and sweep checks.
        # Same house rule 12 sequence as the change on the way in: down,
        # reconfigure, up. This one also relied on the instrument
        # dropping its own output at the function change.
        driver.set_current_level(0.0)
        driver.safe_output_off()
        driver.set_source_function("voltage")
        driver.set_current_limit(self.probe.compliance_i)
        driver.output_on()
        # Timed before the sweep, because the sweep's deadline depends
        # on the answer.
        self._tier3_timing()
        self._tier3_sweep()

    def _tier3_sweep(self):
        """A short sweep through whichever path this driver uses.

        Deliberately runs the same three-method sequence the experiments
        use rather than a shortcut, because on the miniSMU and the GSM
        that sequence is where the hardware path lives, and a hardware
        sweep that never starts is invisible from a single measure().
        """
        driver = self.driver
        kind = driver.sweep_kind()
        try:
            driver.start_linear_sweep("voltage", 0.0, self.probe.voltage,
                                      SWEEP_POINTS, 0.01)
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(3, f"start_linear_sweep()  [{kind}]", "fail",
                        f"{type(exc).__name__}: {exc}")
            return
        self.record(3, f"start_linear_sweep()  [{kind}]", "pass")

        # The deadline is derived from what a reading has already been
        # observed to cost on THIS instrument, not from a fixed number.
        # Readings here span four orders of magnitude - sub-millisecond
        # on the simulated driver, over ten seconds on a U2722A at a
        # long aperture - so any constant is either uselessly long for
        # one instrument or a false failure on another.
        per_reading = self._seconds_per_reading or 1.0
        # The first-read cost is added rather than folded into
        # `per_reading`, because a sweep pays it once and not per point.
        # It used to be inside the average, which made the deadline
        # accidentally generous - and would have made it accidentally
        # tight on any instrument whose first read is quicker than its
        # steady state, arriving as "sweep completes: fail" with nothing
        # to say why.
        first_read = getattr(self, "_first_reading_s", None) or 0.0
        budget = max(30.0,
                     per_reading * SWEEP_POINTS * 3.0 + first_read + 10.0)
        started = time.perf_counter()
        deadline = started + budget
        ready = 0
        while ready < SWEEP_POINTS and time.perf_counter() < deadline:
            try:
                ready = driver.sweep_points_ready()
            except TransportDesynchronised:
                raise
            except Exception as exc:
                self.record(3, "sweep_points_ready()", "fail", str(exc))
                driver.abort_sweep()
                return
            time.sleep(0.02)
        elapsed = time.perf_counter() - started

        if ready < SWEEP_POINTS:
            self.record(3, "sweep completes", "fail",
                        f"only {ready} of {SWEEP_POINTS} points after "
                        f"{elapsed:.1f} s (allowed {budget:.0f} s for "
                        f"{SWEEP_POINTS} points at {per_reading:.3g} s per "
                        f"reading); aborting")
            driver.abort_sweep()
            return
        self.record(3, "sweep completes", "pass",
                    f"{SWEEP_POINTS} points in {elapsed:.2f} s", elapsed)

        try:
            sourced, measured = driver.read_sweep(SWEEP_POINTS)
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(3, "read_sweep()", "fail",
                        f"{type(exc).__name__}: {exc}")
            return

        if len(sourced) != SWEEP_POINTS or len(measured) != SWEEP_POINTS:
            self.record(3, "read_sweep() returns the right shape", "fail",
                        f"{len(sourced)} sourced, {len(measured)} measured, "
                        f"expected {SWEEP_POINTS} of each")
        else:
            self.record(3, "read_sweep() returns the right shape", "pass",
                        f"{SWEEP_POINTS} pairs")
            span = max(sourced) - min(sourced)
            # A short span has two very different causes, and calling
            # them both a fault would make this check cry wolf on every
            # low-resistance sample. Either the source never moved -
            # clamped by its range, or not stepping - or it moved
            # exactly as asked and the *compliance* limited it, which is
            # the instrument working correctly.
            peak = max((abs(i) for i in measured if i is not None),
                       default=0.0)
            clamped_by_compliance = peak >= self.probe.compliance_i * 0.9

            if span >= self.probe.voltage * 0.5:
                self.record(3, "the sweep actually moved", "pass",
                            f"{min(sourced):.4g} to {max(sourced):.4g} V")
            elif clamped_by_compliance and not self.open_circuit:
                self.record(
                    3, "the sweep actually moved", "skip",
                    f"span was only {span:.4g} V, but the current reached "
                    f"{peak:.3g} A against a {self.probe.compliance_i:g} A "
                    f"compliance - the limit stopped it, not the source. "
                    f"Expected with a low-resistance sample connected")
            elif clamped_by_compliance:
                self.record(
                    3, "the sweep actually moved", "warn",
                    f"span was only {span:.4g} V and the current reached "
                    f"{peak:.3g} A against a {self.probe.compliance_i:g} A "
                    f"compliance. The source is working, but an open "
                    f"circuit should not draw compliance current - "
                    f"something is probably connected")
            else:
                self.record(
                    3, "the sweep actually moved", "fail",
                    f"sourced values span only {span:.4g} V of a requested "
                    f"{self.probe.voltage} V, and the current stayed well "
                    f"below compliance at {peak:.3g} A - so the source is not "
                    f"stepping. It may be clamped, or clipped by its range")
        self.check_queue(3, "the sweep")

        # Drivers set their sweep note during read_sweep() when
        # something needed saying - the GSM records how many points came
        # back as NAN or over-range and were dropped. Tier 1 reads this
        # note too, but that is before any sweep has run, so the
        # interesting version only exists now. Without this, a short
        # sweep looks like an unexplained shortfall when the driver
        # already knows exactly why.
        note = getattr(driver, "sweep_note", None)
        if callable(note):
            try:
                text = note()
            except TransportDesynchronised:
                raise
            except Exception:
                text = None
            if text:
                self.record(3, "driver note after the sweep", "pass", text)

    def _check_compliance_reported(self):
        """Ask `compliance_tripped()` at the one moment the answer is
        known, and known to be True.

        Tier 2 already calls it, but with the output off - where the
        honest answer is False, and where a method that always returns
        False, or always returns None, passes just as well. That is the
        same shape as the B2901A's first sense-function probe, which
        counted enabled measurement functions after a reset that had
        already enabled them all: an observation that would have been
        identical whether or not the command worked.

        Here the instrument is demonstrably clamping - it is sourcing a
        current into an open circuit and the measured voltage has just
        been confirmed at the limit - so True is the only correct
        answer, and every wrong implementation is distinguishable:

          * `None`  - the driver does not implement it. Recorded as a
                      skip, because "cannot say" is a legitimate answer
                      and several drivers here give it.
          * `False` - implemented and wrong. This is the failure worth
                      catching: a sweep that clamps still draws a
                      convincing straight line with a high R-squared,
                      and the fit describes the limit rather than the
                      sample.
          * raises  - implemented and broken.

        Only meaningful on an open circuit; with something connected the
        instrument may legitimately not be in compliance at all, and the
        caller has already established that before getting here.
        """
        driver = self.driver
        try:
            state = driver.compliance_tripped()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(
                3, "compliance_tripped() while clamping", "fail",
                f"raised {type(exc).__name__}: {exc}")
            return

        if state is None:
            self.record(
                3, "compliance_tripped() while clamping", "skip",
                "this driver does not report compliance - a flat top on "
                "a curve may be the only warning you get")
        elif state:
            self.record(
                3, "compliance_tripped() while clamping", "pass",
                "reported True while riding the voltage limit")
        else:
            self.record(
                3, "compliance_tripped() while clamping", "fail",
                "reported False while the output was demonstrably at "
                "compliance. A clamped sweep still produces a neat "
                "straight line, so this is the check that would have "
                "told you the fit describes the limit and not the "
                "sample")

    def _time_readings(self, count=TIMED_READINGS):
        """Time `count` readings, discarding a warm-up read first.

        Returns `(steady_s, first_s)`, or `(None, None)` if a read
        raised.

        The warm-up is the whole point. **Every instrument in the
        registry pays a large one-off on the first reading after
        `output_on()`**, and averaging it in was distorting the headline
        figure on all of them - measured 2026-08-21:

            B2901A      173.2 ms then 4.8 ms      reported 38.6 (8x)
            2635B      1098.4 ms then 17.1 ms     reported 233.6 (14x)
            GSM-20H10   318.9 ms then 14.3 ms     reported 75.3 (5.2x)
            2611A        70.8 ms then 15.9 ms     reported 26.9 (1.7x)
            2401         91.7 ms then 37.0 ms     reported 48.0 (1.3x)

        That number is not cosmetic. It is published as the "Per
        reading" column in `bench/choosing-an-smu.md`, where somebody
        plans a run from it; it sets the sweep deadline; and it is the
        input to `_aperture_cost()`, whose slope answers whether an
        instrument's NPLC integrates at all. A first-read offset that
        differs between the two NPLC points corrupts both the slope and
        the intercept.

        It was not autoranging, which was the first hypothesis. The
        B2901A's ranges were fixed before its 173 ms read and it still
        paid 36x its steady state.

        Both numbers are real and the caller reports both. A user pays
        the first-read cost once per run, and on the 2635B that is over
        a second of dead time nobody had written down.
        """
        driver = self.driver
        try:
            first_started = time.perf_counter()
            driver.measure(timeout_s=self._read_timeout())
            first = time.perf_counter() - first_started

            started = time.perf_counter()
            for _ in range(count):
                driver.measure(timeout_s=self._read_timeout())
            steady = (time.perf_counter() - started) / float(count)
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self._timing_error = str(exc)
            return None, None
        return steady, first

    def _tier3_timing(self):
        """How long a reading takes, as information rather than a verdict.

        Worth recording because it is the number that decides whether a
        200-point sweep takes a minute or half an hour, it varies by two
        orders of magnitude across these instruments, and it is invisible
        until someone waits for it.
        """
        per_reading, first = self._time_readings()
        if per_reading is None:
            self.record(3, "reading timing", "warn",
                        getattr(self, "_timing_error", "read failed"))
            return
        self._seconds_per_reading = per_reading
        self._first_reading_s = first
        # Stated with the NPLC it was measured at. The number is
        # meaningless without it - the same instrument spans two orders
        # of magnitude across its own NPLC range - and an unqualified
        # figure in a report is one somebody will quote later.
        at = f" at NPLC {self._nplc:g}" if self._nplc else ""
        self.record(3, f"time per reading{at}", "pass",
                    f"{per_reading * 1000:.1f} ms "
                    f"({per_reading * 200:.1f} s for a 200-point sweep), "
                    f"steady state - the first reading is reported "
                    f"separately below",
                    per_reading)
        # Its own line rather than a parenthesis, because it is a cost
        # somebody plans around: it is paid once per run, it is not
        # predictable from the steady-state figure, and it spans a
        # factor of two hundred across this bench.
        ratio = (f", {first / per_reading:.0f}x the steady state"
                 if per_reading > 0 else "")
        self.record(3, "first reading after the output comes up", "pass",
                    f"{first * 1000:.1f} ms{ratio}", first)
        # After the headline figure, not before it: the aperture
        # calculation is a follow-up that only makes sense once the
        # reader has seen the number it is derived from.
        self._aperture_cost(per_reading)

    # ---- helpers ----
    def _aperture_cost(self, slow_reading_s):
        """How many apertures a single reading really costs.

        Only runs when --nplc asked for a specific integration time,
        because it needs two points on the same instrument: time a
        reading at the requested NPLC and again at the fast end, and the
        slope between them is the number of apertures per reading. The
        intercept is the fixed bus overhead.

        Worth automating rather than leaving as two manual runs. It
        answers a question that keeps coming up and that a single
        timing figure cannot: whether a driver's `measure()` costs one
        integration or two. The U2722A measured 2.04 apertures and
        34 ms of overhead, confirming that its separate `MEAS:VOLT?` and
        `MEAS:CURR?` each pay in full - which is why the driver says a
        point costs twice the aperture.

        Comparing across two separate runs is unreliable: per-reading
        overhead varies by machine and by port, by a factor of eight on
        one instrument here.
        """
        driver = self.driver
        cls = type(driver)
        if self.requested_nplc is None or not cls.supports_nplc():
            return
        fast = cls.NPLC_RANGE[0]
        slow = self._nplc
        if slow is None or abs(slow - fast) < 1e-9:
            return

        try:
            driver.set_nplc(fast)
            fast_clamped = cls.clamp_nplc(fast)
            # Through the same helper as the slow figure, so both points
            # on the fit are steady-state. They were not: each end
            # averaged in its own first read, and changing NPLC provokes
            # a fresh one. The two offsets do not cancel - on the 2635B
            # the first read is 65x the steady state at one end - so
            # they corrupted the slope and the intercept, which is the
            # whole output of this calculation.
            fast_reading, _ = self._time_readings()
            if fast_reading is None:
                raise RuntimeError(getattr(self, "_timing_error",
                                           "read failed"))
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(3, "apertures per reading", "warn", str(exc))
            return
        finally:
            try:
                driver.set_nplc(slow)     # leave it as asked
            except TransportDesynchronised:
                raise
            except Exception:
                pass

        span = (slow - fast_clamped) / 50.0
        if span <= 0:
            return
        apertures = (slow_reading_s - fast_reading) / span
        overhead = slow_reading_s - apertures * (slow / 50.0)
        detail = (f"{apertures:.2f} (fixed overhead {overhead * 1000:.0f} "
                  f"ms) - {fast_reading * 1000:.1f} ms at NPLC "
                  f"{fast_clamped:g} vs {slow_reading_s * 1000:.1f} ms at "
                  f"NPLC {slow:g}")

        # Well under one aperture is not a fast instrument - it is a
        # driver whose idea of an aperture is too big. The reading
        # cannot take less time than the integration it claims to be
        # doing, so a figure of 0.05 means the declared window is about
        # twenty times the real one, and the NPLC going into every CSV
        # is wrong by that factor. The miniSMU was out by eighteen.
        #
        # A slope of zero or below is a different thing again: it means
        # the two readings were not distinguishable, so there is no
        # measurement to report. It happens when the clock is too coarse
        # for the interval - time.monotonic() ticks every 15.6 ms on
        # Windows, which is why this code now uses perf_counter - or
        # when the instrument is quick enough that jitter swamps the
        # difference. Reporting "0.00 apertures" as if it were measured
        # would be worse than saying nothing, and dividing by it used to
        # raise ZeroDivisionError from inside a diagnostic tool.
        if apertures <= 0.0:
            self.record(
                3, "apertures per reading", "warn",
                f"{detail}. NOT MEASURABLE: the readings at NPLC "
                f"{fast_clamped:g} and {slow:g} were indistinguishable, so "
                f"the slope is zero or negative. Either the interval is "
                f"below the clock resolution or the difference is lost in "
                f"jitter; re-run with a larger NPLC separation",
                apertures)
            return

        if apertures < 0.5:
            self.record(
                3, "apertures per reading", "warn",
                f"{detail}. UNDER ONE APERTURE, which is impossible: a "
                f"reading cannot be quicker than the integration it "
                f"claims. The driver's declared aperture is about "
                f"{1 / apertures:.0f}x too long, so the NPLC it records "
                f"in the CSV is overstated by roughly that much",
                apertures)
            return

        # How much of the slow reading was actually integration. The
        # slope is only as good as this ratio: if the reading is mostly
        # overhead then the fit is measuring the link rather than the
        # instrument, and a few milliseconds of drift moves the answer
        # a long way.
        #
        # This is the difference between the two cross-session estimates
        # made by hand here. The U2722A's slow point was 500 ms of
        # integration against ~35 ms of overhead, so 3 ms of session
        # drift shifted it by 0.6% and the answer survived. The
        # miniSMU's was 5 ms of integration against overhead that varied
        # from 6 ms to 29 ms between sessions - the drift was four times
        # the signal, and the estimate was wrong by a factor of five.
        integration = apertures * (slow / 50.0)
        share = integration / slow_reading_s if slow_reading_s else 0.0
        if share < 0.5:
            detail += (f". Only {share * 100:.0f}% of that reading was "
                       f"integration, the rest overhead - so this slope is "
                       f"weakly determined. Use a slower NPLC for a firmer "
                       f"number")
        else:
            detail += (". About 1 means one integration per reading; about "
                       "2 means voltage and current are integrated "
                       "separately")

        self.record(3, "apertures per reading", "pass", detail, apertures)

    _last_reading = (None, None)

    def _read_timeout(self):
        """A read timeout that allows for the integration time in use,
        plus room for the instrument to autorange on the way."""
        aperture = (self._nplc or 1.0) / 50.0
        return max(10.0, aperture * 4.0 + 5.0)

    def _expect_reading(self, value):
        try:
            volts, amps = value
        except (TypeError, ValueError):
            return f"measure() returned {value!r}, expected a (volts, amps) pair"
        if volts is None or amps is None:
            return f"measure() returned {value!r} - a None means the reply " \
                   f"could not be parsed"
        try:
            float(volts), float(amps)
        except (TypeError, ValueError):
            return f"measure() returned non-numeric {value!r}"
        self._last_reading = (float(volts), float(amps))
        return True

    def _settle_to_compliance(self, budget_s=6.0):
        """Read while the output rides up, and stop when it stops rising.

        A fixed short wait is wrong here. Sourcing a small current into
        an open circuit charges the instrument's own output capacitance
        and nothing else, so the voltage *ramps* rather than jumping -
        and the ramp can be slow. A U2722A read 41 mV after 50 ms, which
        works out at about 1.2 uF being charged at 1 uA: a slew of
        roughly 1 V/s, needing well over a second to reach a 1 V limit.

        That produced a warning saying "expected the output to ride up
        to compliance - is something attached?", when nothing was
        attached and the output was simply still on its way. The
        earlier run passed the same check only because NPLC was left at
        255, making each reading take 10 s and hiding the ramp inside
        the measurement.

        **This loop used to exit the moment a reading passed 80% of the
        limit, without asking whether it was still climbing**, which is
        a different fault with the same cause. On the GSM-20H10 on
        2026-08-21 it stopped at 0.9151 V of a 1 V limit while still
        rising 0.23 V per poll, having spent 1.294 s of a 6 s budget -
        then asked `compliance_tripped()`, got the correct answer
        `False`, and recorded it as a failure. Invisible on a fast
        instrument: the 2401 and the 2611A reach the rail inside a
        single reading, so an 80% exit lands on an output that really
        is clamping and the check passes for the right reason. The
        threshold is a *verdict*, not a reason to stop looking.

        So the exit condition is now settling alone: two consecutive
        readings within `SETTLE_TOLERANCE_V` of each other, or the
        budget. `self._ramping` says which, and the caller decides what
        the settled value means.
        """
        deadline = time.perf_counter() + budget_s
        previous = None
        tolerance = self._settle_tolerance()
        reading = self.driver.measure(timeout_s=self._read_timeout())
        self._ramping = False

        while time.perf_counter() < deadline:
            volts = reading[0] if reading else None
            if volts is None:
                break
            if previous is not None and abs(volts - previous) < tolerance:
                break                      # stopped moving, wherever it is
            previous = volts
            time.sleep(0.25)
            reading = self.driver.measure(timeout_s=self._read_timeout())

        volts = reading[0] if reading else None
        # Still moving when the loop ended. Note this is decided by the
        # last pair of readings and not by where they landed: an output
        # sitting above the limit and still climbing is a fault, not a
        # settled clamp, and the old form could not express that.
        self._ramping = (volts is not None and previous is not None
                         and abs(volts - previous) >= tolerance)
        return reading

    def _check_open_circuit(self, result):
        volts, amps = self._last_reading
        if not self.open_circuit:
            self.record(3, "current at the probe voltage", "skip",
                        f"{amps:.3g} A at {volts:.4g} V - not checked, "
                        f"something is connected so the expected value is "
                        f"unknown")
            return
        if abs(amps) <= OPEN_CIRCUIT_MAX_A:
            self.record(3, "open-circuit current is near zero", "pass",
                        f"{amps:.3g} A at {volts:.4g} V")
        else:
            self.record(
                3, "open-circuit current is near zero", "warn",
                f"{amps:.3g} A at {volts:.4g} V, above the "
                f"{OPEN_CIRCUIT_MAX_A:g} A threshold. Either something is "
                f"connected to the output, or the reading is not in amps")

    def run(self, tiers=(1, 2, 3)):
        """Run the requested tiers, stopping dead on a desynchronised
        link.

        The stop is here rather than inside each tier so that it is one
        decision in one place: a tier that catches it locally would have
        to remember to stop the *next* tier too, and that is the kind of
        thing a later edit forgets.

        The results gathered before the break are kept and reported. They
        were taken on a synchronised link, so they are the one part of
        the run that is still worth reading.
        """
        self._stopped_early = False
        try:
            if 1 in tiers:
                self.tier1_identity()
            if 2 in tiers:
                self.tier2_configuration()
            if 3 in tiers:
                self.tier3_measurement()
        except TransportDesynchronised:
            # Already recorded by _on_desynchronised(), with the
            # output-off note attached. Swallowed here and nowhere else:
            # this is the layer that owns "the run is over".
            self._stopped_early = True
        return self.results


def build_report(driver, results, address="", sensing_note=None,
                 open_circuit=True, provenance=None, stopped_early=False):
    """Render the results as Markdown."""
    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for result in results:
        counts[result.severity] += 1

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    verdict = "FAIL" if counts["fail"] else (
        "PASS WITH WARNINGS" if counts["warn"] else "PASS")

    lines = [
        f"# Instrument checkup - {type(driver).DISPLAY_NAME}",
        "",
        f"- **Result:** {verdict}",
        f"- **When:** {stamp}",
        f"- **Address:** {address or 'not recorded'}",
        f"- **Driver:** `{type(driver).__name__}`",
        *as_markdown_lines(provenance or {}),
        f"- **Checks:** {counts['pass']} passed, {counts['warn']} warned, "
        f"{counts['fail']} failed, {counts['skip']} skipped",
        "",
        "> This checkup assumes **nothing is connected to the output**. "
        "The measurement checks expect open-circuit behaviour, so a "
        "connected sample will produce warnings that are not faults."
        if open_circuit else
        "> This checkup was told **something is connected** to the "
        "output. The open-circuit measurement checks were skipped, "
        "because the expected reading is unknown. Everything else ran "
        "normally.",
        "",
    ]
    if sensing_note:
        lines += [f"> {sensing_note}", ""]
    # Deliberately the built-in sum, not math.fsum: this counts
    # results, and fsum would return a float where an integer count is
    # meant. The 3.12 float-summation change that moved the maths
    # modules does not touch integer summation.
    if stopped_early:
        lines += [
            "> **This checkup did not finish.** The link to the instrument "
            "went out of step, so the run stopped there rather than record "
            "readings that would answer the previous command. Everything "
            "listed below was taken before that point and is sound; "
            "everything the instrument was never asked is simply absent. "
            "Reconnect the instrument and run it again.", ""]

    if counts["fail"]:
        lines += ["## Failures", ""]
        for result in results:
            if result.severity == "fail":
                lines.append(f"- **{result.name}** - {result.detail}")
        lines.append("")
    if counts["warn"]:
        lines += ["## Warnings", ""]
        for result in results:
            if result.severity == "warn":
                lines.append(f"- **{result.name}** - {result.detail}")
        lines.append("")

    titles = {1: "Tier 1 - identity and declarations",
              2: "Tier 2 - configuration syntax (output off)",
              3: "Tier 3 - live measurement"}
    for tier in (1, 2, 3):
        rows = [r for r in results if r.tier == tier]
        if not rows:
            continue
        lines += [f"## {titles[tier]}", "",
                  "| Check | Result | Detail |", "|---|---|---|"]
        for result in rows:
            detail = (result.detail or "").replace("|", "\\|")
            lines.append(f"| {result.name} | {result.severity} | {detail} |")
        lines.append("")

    return "\n".join(lines)
