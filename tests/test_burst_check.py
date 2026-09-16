"""The checkup's burst check: does an instrument drop commands sent in a burst?

The GSM-20H10 does. On the bench on 2026-09-16 the query after the
twenty-five writes of an IV sweep's configuration was never answered in 7
runs of 10, and with 5 ms after each write it was answered in 10 of 10.
Nothing had shown it for a month because nothing but the suite ever sent
a burst - see `WRITE_DELAY_S` on the driver.

A fake parses as fast as it is written to, so the instrument's fault is
modelled here directly: once armed, a query that follows more than a few
writes is never answered. Armed only when the burst check starts, so the
tiers before it run on an ordinary link and the check is graded on its
own finding.
"""
import contextlib
import io

from test_2401_driver import Fake2401
from test_gsm20h10 import GSMTransport
from test_load_checkup import build as build_load

from smuniversal_lab_suite.core.checkup import Checkup, LoadCheckup
from smuniversal_lab_suite.drivers.gwinstek_gsm20h10 import GWInstekGSM20H10
from smuniversal_lab_suite.drivers.keithley_2401 import Keithley2401

#: More consecutive writes than this and an armed fake loses the query.
#: Both instruments' bursts are longer, so the first burst trips it.
DROPS_AFTER = 8


def dropping(base):
    """`base`, losing the query after a burst once armed."""

    class Dropping(base):
        armed = False
        delay_seen = None

        def _write(self, text):
            super()._write(text)
            self._burst = getattr(self, "_burst", 0) + 1

        def _read(self, timeout_s):
            burst, self._burst = getattr(self, "_burst", 0), 0
            if self.armed and burst > DROPS_AFTER:
                # What the link was paced at when the query went missing,
                # so a check that forgot to go unpaced can be caught.
                self.delay_seen = self.write_delay_s
                raise TimeoutError("the query after a burst was never "
                                   "answered")
            return super()._read(timeout_s)

    return Dropping


class AnswersSomeoneElse(Fake2401):
    """Once armed, answers *IDN? with a reply to another question."""

    armed = False

    def _read(self, timeout_s):
        if self.armed and "IDN" in (self.sent[-1] if self.sent else "").upper():
            return "+1.000000E-04"
        return super()._read(timeout_s)


def run_checkup(driver, transport, checkup_cls=Checkup, **run_kwargs):
    checkup = checkup_cls(driver, open_circuit=False)
    inner = checkup.burst_configuration

    def configure():
        transport.armed = True
        return inner()

    checkup.burst_configuration = configure
    with contextlib.redirect_stdout(io.StringIO()):
        checkup.run(**run_kwargs)
    return checkup


def burst_row(checkup):
    rows = [r for r in checkup.results if r.name == Checkup.BURST_NAME]
    return rows[0] if rows else None


def test_a_drop_with_no_pause_declared_fails(check):
    transport = dropping(Fake2401)()
    checkup = run_checkup(Keithley2401(transport), transport)
    row = burst_row(checkup)

    check("the check ran", row is not None)
    if row is None:
        return
    check("a lost query on an unpaced driver is a failure",
          row.severity == "fail", f"{row.severity}: {row.detail}")
    check("and it names the fix", "WRITE_DELAY_S" in row.detail, row.detail)
    check("the run is not reported as cut short - it reached the end",
          checkup._stopped_early is False)
    check("the link's pacing is put back", transport.write_delay_s == 0.0,
          transport.write_delay_s)
    check("and its methods are unwrapped",
          "write" not in vars(transport) and "query" not in vars(transport),
          sorted(k for k in vars(transport) if k in ("write", "query")))


def test_a_drop_on_a_driver_that_declares_its_pause_passes(check):
    transport = dropping(GSMTransport)()
    transport.connect("fake")
    checkup = run_checkup(GWInstekGSM20H10(transport), transport)
    row = burst_row(checkup)

    check("the check ran", row is not None)
    if row is None:
        return
    check("the declaration matches the instrument, so it passes",
          row.severity == "pass", f"{row.severity}: {row.detail}")
    check("the burst that lost the query was sent unpaced",
          transport.delay_seen == 0.0,
          f"write_delay_s was {transport.delay_seen} when it went missing")
    check("and the driver's own pause is back in force afterwards",
          transport.write_delay_s == GWInstekGSM20H10.WRITE_DELAY_S,
          transport.write_delay_s)


def test_a_declared_pause_not_reproduced_warns(check):
    transport = GSMTransport()
    transport.connect("fake")
    checkup = run_checkup(GWInstekGSM20H10(transport), transport)
    row = burst_row(checkup)

    check("the check ran", row is not None)
    if row is not None:
        check("a pause the instrument did not need here is a warning, "
              "not a pass", row.severity == "warn",
              f"{row.severity}: {row.detail}")
        check("and it says not to remove it on one round",
              "not grounds to remove it" in row.detail, row.detail)


def test_an_instrument_that_answers_every_burst_passes(check):
    transport = Fake2401()
    checkup = run_checkup(Keithley2401(transport), transport)
    row = burst_row(checkup)

    check("the check ran", row is not None)
    if row is not None:
        check("it passes", row.severity == "pass",
              f"{row.severity}: {row.detail}")
        check("having sent every burst",
              row.detail.startswith(f"{Checkup.BURST_REPEATS} of "
                                    f"{Checkup.BURST_REPEATS} answered"),
              row.detail)


def test_a_reply_to_another_question_fails(check):
    """The other way a burst fault shows: the stream, not the silence."""
    transport = AnswersSomeoneElse()
    checkup = run_checkup(Keithley2401(transport), transport)
    row = burst_row(checkup)

    check("the check ran", row is not None)
    if row is not None:
        check("a wrong identity is a failure", row.severity == "fail",
              f"{row.severity}: {row.detail}")
        check("described as out of step", "out of step" in row.detail,
              row.detail)


def test_the_burst_runs_after_everything_else(check):
    """A drop ends the session, so nothing may be queued behind it."""
    transport = Fake2401()
    checkup = run_checkup(Keithley2401(transport), transport)
    names = [r.name for r in checkup.results]

    check("tier 3 ran", any(r.tier == 3 for r in checkup.results))
    check("the burst check is the last result",
          names and names[-1] == Checkup.BURST_NAME,
          names[-3:])


def test_it_can_be_skipped_and_says_so(check):
    transport = Fake2401()
    checkup = Checkup(Keithley2401(transport), open_circuit=False)
    sent = []
    checkup.burst_configuration = lambda: sent.append("burst")
    with contextlib.redirect_stdout(io.StringIO()):
        checkup.run(burst=False)
    row = burst_row(checkup)

    check("no burst was sent", sent == [], sent)
    check("and the report says it was skipped, and why",
          row is not None and row.severity == "skip"
          and "--skip-burst" in row.detail,
          None if row is None else f"{row.severity}: {row.detail}")


def test_the_load_checkup_runs_it_too(check):
    load, transport = build_load()
    with contextlib.redirect_stdout(io.StringIO()):
        checkup = LoadCheckup(load)
        checkup.run(tiers=(1, 2))
    check("the load checkup records a burst result",
          burst_row(checkup) is not None,
          [r.name for r in checkup.results][-3:])


def test_the_gsm_burst_is_as_long_as_the_one_that_failed_on_the_bench(check):
    """A shorter burst than the real one can pass an instrument for free.

    The bench's failing burst was 25 writes: `reset()` at connect, then
    `_prepare()`. Without the reset the checkup's was 12.
    """
    import re

    transport = GSMTransport()
    transport.connect("fake")
    row = burst_row(run_checkup(GWInstekGSM20H10(transport), transport))
    found = re.search(r"bursts of up to (\d+) writes", row.detail if row else "")
    longest = int(found.group(1)) if found else 0
    check("the burst includes the connect-time reset", longest >= 20,
          row.detail if row else "no row")
