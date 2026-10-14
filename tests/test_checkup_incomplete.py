"""A checkup that did not finish says so in its headline.

On 2026-10-14 two Keithley 487 runs lost a reading inside the software
sweep - in the worker thread, surfacing in the checkup only through
`sweep_points_ready()`. The desync passed a bare re-raise on its way out,
so no row named it, and the reports were headed **PASS WITH WARNINGS**
with 0 failures above a banner saying the run had not finished. The
command-line tool exited 0.

Reproduced here with the 487 and its fake, losing the first reading the
sweep asks for, which is where both bench runs lost theirs.
"""
import threading

from test_keithley487 import Fake487

from smuniversal_lab_suite.core.checkup import Checkup, build_report
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised
from smuniversal_lab_suite.drivers.keithley_487 import Keithley487


class LosesTheSweepsReading(Keithley487):
    """A reading that never comes, asked for from the sweep's thread."""

    def measure(self, timeout_s=3.0):
        if threading.current_thread() is not threading.main_thread():
            self.transport._mark_desynchronised(TimeoutError("no reply"),
                                                "<read>")
            raise TransportDesynchronised(self.transport._desync_message())
        return super().measure(timeout_s)


def run_one():
    checkup = Checkup(LosesTheSweepsReading(Fake487(resistance=None)),
                      open_circuit=True)
    checkup.run()
    return checkup


def test_an_unfinished_run_is_headed_incomplete(check):
    checkup = run_one()
    check("it stopped early", checkup._stopped_early)
    report = build_report(checkup.driver, checkup.results,
                          stopped_early=checkup._stopped_early)
    check("headed INCOMPLETE", "- **Result:** INCOMPLETE" in report,
          report.splitlines()[2])
    check("never PASS", "PASS" not in report.splitlines()[2])


def test_the_stop_is_named_once_as_a_failure(check):
    checkup = run_one()
    stops = [r for r in checkup.results
             if r.severity == "fail" and "out of step" in r.detail]
    check("one row says where the run stopped", len(stops) == 1,
          f"{[(r.name, r.detail[:60]) for r in stops]}")
    if stops:
        check("in tier 3, where the sweep is", stops[0].tier == 3)
        check("and it carries the output-off note",
              "OUTPUT-OFF" in stops[0].detail, stops[0].detail)


def test_a_stop_inside_a_graded_check_is_not_recorded_twice(check):
    """The ordinary path: `attempt()` already recorded it."""
    class LosesTheFirstReading(Keithley487):
        def measure(self, timeout_s=3.0):
            self.transport._mark_desynchronised(TimeoutError("no reply"),
                                                "<read>")
            raise TransportDesynchronised(self.transport._desync_message())

    checkup = Checkup(LosesTheFirstReading(Fake487(resistance=None)),
                      open_circuit=True)
    checkup.run()
    stops = [r for r in checkup.results
             if r.severity == "fail" and "out of step" in r.detail]
    check("one row, from the check itself", len(stops) == 1,
          f"{[r.name for r in stops]}")
    check("named for the check", stops and stops[0].name.startswith(
        "measure()"), f"{[r.name for r in stops]}")


def test_a_finished_run_is_judged_on_its_results(check):
    checkup = Checkup(Keithley487(Fake487(resistance=None)),
                      open_circuit=True)
    checkup.run()
    report = build_report(checkup.driver, checkup.results,
                          stopped_early=checkup._stopped_early)
    check("not incomplete", not checkup._stopped_early)
    check("headed by its results",
          "- **Result:** PASS WITH WARNINGS" in report,
          report.splitlines()[2])
