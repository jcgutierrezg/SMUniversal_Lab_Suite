"""The checkup's machinery: recording results, reading the error queue,
and stopping when the link does.

Everything here is shared by the three tiers, which live in their own
modules as mixins on `Checkup`.
"""
import time

from smuniversal_lab_suite.core.checkup.probes import (
    COMMANDS_LISTED_WITH_AN_ERROR,
    probe_levels_for,
)
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised


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


class CheckupBase:
    """State and bookkeeping shared by every tier. See `Checkup`."""

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
        # The tier 1 "probe levels" row, held so the end of the run can
        # rewrite it with the levels that were actually sourced. None
        # until tier 1 runs, and it may never run - `run()` takes tiers.
        self._probe_result = None
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
    def _probe_summary(self):
        """The "probe levels" detail, from the probe's current state."""
        return f"{self.probe.describe()} - " + "; ".join(self.probe.notes)

    def _refresh_probe_summary(self):
        """Rewrite the tier 1 probe row with what was actually sourced.

        Called once, at the end of the run, including a run that stopped
        on a desynchronised link - a probe that moved before the link
        went is still the probe those readings were taken at.

        Editing a recorded row is done here and nowhere else. The rule
        it bends is worth stating: a checkup result is an observation
        and observations are not revised. This one is not a revision but
        a completion - the row states the four levels of a run, and one
        of them is not known until tier 3 has asked the instrument. The
        alternative was a second row, which puts two different answers
        to "what was this probed at?" in one report and leaves the
        reader to work out which is current.
        """
        if self._probe_result is not None:
            self._probe_result.detail = self._probe_summary()

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
        # After the tiers, and outside the try: the probe row has to say
        # what was sourced whether or not the run reached the end.
        self._refresh_probe_summary()
        return self.results
