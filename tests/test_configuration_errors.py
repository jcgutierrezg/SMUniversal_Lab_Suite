"""A rejected configuration command is reported where it happened.

Reported from the bench, 2026-09-15, on a GSM-20H10: an IV sweep at
default settings beeped several times immediately after Run, and then
ended with a dialog saying *"the output could not be confirmed off -
instrument reported 803"*.

Two separate faults, and the second is the one that misleads.

**Nothing asked.** The instrument beeps for each rejected command, so a
misconfigured run announces itself audibly and then says nothing. There
was no point at which anything asked it what it had just complained
about, even though the answer was sitting in its error queue.

**And then the wrong event was blamed.** `confirm_output_off()` drains
the queue after the output-off and reports whatever it finds as
evidence the shutdown failed. Configuration errors were still in there,
so a run misconfigured at the start ended with a safety warning about
de-energisation - sending somebody to the front panel of an instrument
that had switched off perfectly well. Fault 45: one message standing
for two different gaps.
"""
import pytest

from smuniversal_lab_suite.core.run_control import (
    ShutdownStatus,
    confirm_output_off,
    drain_error_queue,
)
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised


class Instrument:
    """Holds a queue of errors and lets them be read once each."""

    DISPLAY_NAME = "Fake instrument"

    def __init__(self, queued=()):
        self.queue = list(queued)
        self.off_calls = 0

    def read_error(self):
        return self.queue.pop(0) if self.queue else (0, "No error")

    def output_off(self):
        self.off_calls += 1


def say(sink):
    return lambda *parts: sink.append(" ".join(str(p) for p in parts))


def test_the_queue_is_reported_where_the_errors_happened(check):
    log = []
    smu = Instrument([(803, "Not permitted with OUTPUT off"),
                      (803, "Not permitted with OUTPUT off")])
    found = drain_error_queue(smu, say(log))

    check("both are returned", len(found) == 2, f"{found}")
    check("the console names them",
          any("803" in line for line in log), log)
    check("and says the beeping was the only other signal",
          any("beeping" in line for line in log), log)
    check("and that a rejected setting is not applied",
          any("stays in force" in line for line in log), log)


def test_an_ordinary_run_says_nothing(check):
    """The queue is empty on almost every run, and silence is correct.

    A line per run reading "no errors" is the reassurance this project
    refuses elsewhere; it would also bury the run that has one.
    """
    log = []
    found = drain_error_queue(Instrument(), say(log))
    check("nothing found", found == [], f"{found}")
    check("nothing logged", log == [], log)


def test_the_shutdown_is_no_longer_blamed_for_them(check):
    """The whole point. Drain first, and what the shutdown finds is
    attributable to the shutdown."""
    smu = Instrument([(803, "Not permitted with OUTPUT off")])

    # Without the drain - the run the operator actually had.
    untouched = Instrument([(803, "Not permitted with OUTPUT off")])
    before = confirm_output_off(untouched, say([]))
    check("it used to report UNCERTAIN",
          before.status is ShutdownStatus.UNCERTAIN, f"{before.status}")

    # With it.
    drain_error_queue(smu, say([]))
    after = confirm_output_off(smu, say([]))
    check("now the shutdown is confirmed",
          after.status is ShutdownStatus.CONFIRMED,
          f"{after.status}: {after.detail}")
    check("and the output was still commanded off", smu.off_calls == 1)


def test_an_error_the_shutdown_really_caused_is_still_caught(check):
    """The drain must not turn the shutdown check into a no-op.

    An error that appears *after* the output-off is exactly what that
    check exists for, and it still has to be reported.
    """
    class FailsOnOff(Instrument):
        def output_off(self):
            super().output_off()
            self.queue.append((801, "Output blocked"))

    smu = FailsOnOff()
    drain_error_queue(smu, say([]))
    report = confirm_output_off(smu, say([]))
    check("still uncertain", report.status is ShutdownStatus.UNCERTAIN,
          f"{report.status}")
    check("and names the real one", "801" in report.detail, report.detail)


def test_an_unreadable_queue_is_not_a_fault(check):
    """`read_error()` is contracted to report code 0 when it cannot
    ask, and being unable to ask is not evidence that anything failed."""
    class Mute(Instrument):
        def read_error(self):
            raise RuntimeError("no reply")

    log = []
    found = drain_error_queue(Mute(), say(log))
    check("nothing claimed", found == [], f"{found}")
    check("but it is noted", any("unreadable" in line for line in log), log)


def test_a_desynchronised_link_still_propagates(check):
    """The exception everywhere else, and here too: a link that has
    stopped answering is not a queue that happens to be empty."""
    class Lost(Instrument):
        def read_error(self):
            raise TransportDesynchronised("stream out of step")

    with pytest.raises(TransportDesynchronised):
        drain_error_queue(Lost(), say([]))
