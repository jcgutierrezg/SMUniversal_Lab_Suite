"""The readback verifier has to catch a query that is lying.

A tool that only confirms honest instruments is worth nothing: an honest
instrument is the case nobody needed a tool for. So every test here
builds a query with a specific way of being wrong and asserts the tool
refuses it - and one honest query, so that "refuses everything" cannot
pass either.

The dishonest shapes are not invented. Each is a way a real instrument
has behaved or could behave with the driver none the wiser:

* **echo** - the query plays back the last value written to it. This is
  the case the front-panel leg exists for, and the reason the leg cannot
  be automated: over the bus an echo and an honest read are the same
  reply.
* **constant** - the query answers the same thing forever. The
  GSM-20H10's `OUTP?` did exactly this on 2026-08-20, answering `0`
  three times with the output on.
* **latch** - the query reports what the instrument was on until the
  first bus write, and that write forever after. Passes the front-panel
  leg and the first bus leg, which is why there are three.

And two honest shapes the first version refused, both from 2026-09-11:
the Keithley and GW Instek full-scale convention (the 1 A range answers
`1.05`), and a hand-set range that was already the one in force, which
proves nothing whatever the query says.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ranges import RangeError  # noqa: E402
from drivers.dummy_smu import DummySMU  # noqa: E402
from tools import bench_readback  # noqa: E402

#: Where the fake instrument's range sits before anyone touches it.
RESET_RANGE = 1e-3


class NullTransport:
    """Enough of a transport for a driver to be constructed."""

    def write(self, text):
        pass

    def query(self, text):
        return "LAB SUITE,MODEL DUMMY SMU,SIMULATED,1.0"

    def close(self):
        pass


def driver_with(reader):
    """A DummySMU whose measure-current range query behaves as given.

    `physical` is the range the instrument is actually on - where a hand
    on the panel or a bus write puts it. `applied` is the last bus write
    and `first_seen` the first. A reader is a rule over those three.
    """

    class Model(DummySMU):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.physical = RESET_RANGE
            self.applied = None
            self.first_seen = None

        def _apply_measure_current_range(self, amps):
            self.applied = float(amps)
            self.physical = float(amps)
            if self.first_seen is None:
                self.first_seen = float(amps)

        def read_measure_current_range(self):
            return reader(self)

    return Model(NullTransport())


def by_hand(driver, amps):
    """The operator: turns the dial to `amps`, then types it."""
    def operator():
        driver.physical = amps
        return repr(amps)
    return operator


def run(driver, operator, log=None):
    """Put the three legs to one subject and return the row."""
    lines = []
    row = bench_readback.one_subject(
        driver, "measure_current", "read_measure_current_range",
        "_apply_measure_current_range", "current_ranges", "A",
        lines.append, scripted=operator)
    if log is not None:
        log.extend(lines)
    return row


# ---------------------------------------------------------------
# ranges
# ---------------------------------------------------------------
def test_an_echoing_query_is_refused(check):
    """The case the front panel exists to catch.

    The instrument is on a range the operator dialled in by hand. A query
    that echoes the last *written* value cannot know that, so it answers
    with whatever it last stored - here, the range reset left.
    """
    driver = driver_with(
        lambda s: s.applied if s.applied is not None else RESET_RANGE)
    row = run(driver, by_hand(driver, 1e-4))
    check("an echo does not survive the front-panel leg",
          row["verdict"] == "not verified", row)
    check("and it is leg 1 that catches it", row.get("leg1") is False, row)


def test_a_constant_query_is_caught_at_the_front_panel(check):
    """Answers the same thing forever - the GSM-20H10's `OUTP?` shape.

    The first version could only catch this at a bus leg, because leg 1
    passed whenever the operator happened to pick the constant's value.
    Reading the query first, and requiring a different range, means the
    hand-set value is never the constant.
    """
    driver = driver_with(lambda s: RESET_RANGE)
    row = run(driver, by_hand(driver, 1e-4))
    check("the constant is refused", row["verdict"] == "not verified", row)
    check("at leg 1", row.get("leg1") is False, row)


def test_the_range_already_in_force_is_not_accepted_by_hand(check):
    """A hand-set range equal to the one before proves nothing.

    A query that never moves would report it, so the tool asks again
    rather than scoring a leg nobody could fail.
    """
    driver = driver_with(lambda s: RESET_RANGE)
    log = []
    row = run(driver, by_hand(driver, RESET_RANGE), log)
    check("nothing is established", row["verdict"] == "skipped", row)
    check("and the operator was told why",
          any("already on" in line for line in log), log)


def test_a_latching_query_is_refused(check):
    """Honest until the first bus write, which it then reports forever.

    Passes the front-panel leg and the first bus leg. This is the whole
    reason there is a third leg: two agreements in a row are not
    evidence when the second could be the first one repeated.
    """
    driver = driver_with(
        lambda s: s.first_seen if s.first_seen is not None else s.physical)
    row = run(driver, by_hand(driver, 1e-4))
    check("a latch is not verified", row["verdict"] == "not verified", row)
    check("it got past leg 1", row.get("leg1") is True, row)
    check("and past leg 2", row.get("leg2") is True, row)


def test_an_honest_query_is_verified(check):
    """The control.

    Without this the tests above are satisfied by a tool that refuses
    everything, which would be useless in the opposite direction.
    """
    driver = driver_with(lambda s: s.physical)
    row = run(driver, by_hand(driver, 1e-4))
    check("an honest query is verified", row["verdict"] == "verified", row)
    check("through all three legs",
          row.get("leg1") and row.get("leg2") and row.get("leg3"), row)


def test_full_scale_with_overrange_names_the_range(check):
    """The GSM-20H10 and 2401 answer `1.05` for the 1 A range.

    The first version compared digits and stopped both instruments at
    leg 1, on four subjects, on answers that were correct.
    """
    driver = driver_with(lambda s: s.physical * 1.05)
    log = []
    row = run(driver, by_hand(driver, 1e-4), log)
    check("an overranged full scale is verified",
          row["verdict"] == "verified", row)
    check("and the log says which range the reply names",
          any("(the 0.0001 A range)" in line for line in log), log)


def test_a_32_bit_float_names_the_range(check):
    """The TSP instruments answer 1e-4 with float32(1e-4)."""
    driver = driver_with(lambda s: s.physical * (1 - 2.5e-9))
    row = run(driver, by_hand(driver, 1e-4))
    check("verified", row["verdict"] == "verified", row)


def test_a_value_the_model_does_not_have_is_refused(check):
    """On 2026-09-11 a 1 V source range was typed for the 2401.

    It has 0.2, 2 and 20 V. The query named the 2 V range, which is
    probably what was set - but the tool cannot know that, and a leg
    scored against a guess is not a leg.
    """
    driver = driver_with(lambda s: s.physical)
    log = []

    def operator():
        driver.physical = 1e-4
        return "0.0005"
    row = run(driver, operator, log)
    check("nothing is established", row["verdict"] == "skipped", row)
    check("and the operator was told why",
          any("not a range this model declares" in line for line in log),
          log)


def test_a_skipped_subject_establishes_nothing(check):
    """No front panel, no verdict.

    The tempting shortcut is to fall back to the bus legs alone when
    nobody is there to turn a dial. That would report `verified` for an
    echo, which is the one answer this tool must never give.
    """
    driver = driver_with(lambda s: s.physical)
    row = run(driver, "")
    check("skipping is not a pass", row["verdict"] == "skipped", row)


def test_an_unanswered_query_is_unreadable(check):
    driver = driver_with(lambda s: None)
    row = run(driver, by_hand(driver, 1e-4))
    check("unreadable", row["verdict"] == "unreadable", row)


def test_too_few_ranges_is_inconclusive_not_verified(check):
    """A model with one range cannot rule out a constant.

    Two bus legs need two ranges to move between. Where the ladder
    cannot supply them the honest answer is that nothing was
    established, not that everything was fine.
    """
    driver = driver_with(lambda s: s.physical)
    driver.LIMITS = type(driver.LIMITS)(
        **{**driver.LIMITS.__dict__, "current_ranges": [1e-4]})
    row = run(driver, by_hand(driver, 1e-4))
    check("one range gives an inconclusive verdict",
          row["verdict"] == "inconclusive", row)


# ---------------------------------------------------------------
# the refused write
# ---------------------------------------------------------------
class Compliance(DummySMU):
    """A current compliance with a chosen way of handling a bad write.

    `refuse` keeps the old value and queues an error - the U2722A on
    2026-08-24. `clamp` takes the maximum instead. `accept` takes the
    value. `echo` refuses but reports the write anyway.
    """

    def __init__(self, behaviour):
        super().__init__(NullTransport())
        self.behaviour = behaviour
        self.limit = 1.05e-4
        self.echoed = self.limit
        self.queue = []

    def set_current_limit(self, amps):
        amps = float(amps)
        self.echoed = amps
        if amps <= self.LIMITS.max_current:
            self.limit = amps
        elif self.behaviour in ("refuse", "echo"):
            self.queue.append((-222, "Parameter data out of range"))
        elif self.behaviour == "clamp":
            self.limit = self.LIMITS.max_current
        elif self.behaviour == "accept":
            self.limit = amps
        elif self.behaviour == "driver refuses":
            raise RangeError(f"{amps} A is not settable")

    def read_current_limit(self):
        return self.echoed if self.behaviour == "echo" else self.limit

    def read_error(self):
        return self.queue.pop(0) if self.queue else (0, "")


def put_to(driver):
    lines = []
    subjects = bench_readback.setting_subjects(driver)
    rows = [bench_readback.refused_write(driver, *s, lines.append)
            for s in subjects]
    return rows, lines


def test_a_refused_write_that_is_not_reported_verifies(check):
    driver = Compliance("refuse")
    rows, log = put_to(driver)
    check("one subject - the voltage compliance has no reader here",
          [r["axis"] for r in rows] == ["current_compliance"], rows)
    check("verified", rows[0]["verdict"] == "verified", rows[0])
    check("and the limit is put back", driver.limit == 1.05e-4,
          driver.limit)


def test_a_query_that_repeats_a_refused_write_is_refused(check):
    """The discriminating case - an echo over the bus."""
    rows, _ = put_to(Compliance("echo"))
    check("not verified", rows[0]["verdict"] == "not verified", rows[0])


def test_a_clamped_write_verifies(check):
    """The instrument holds a value nobody sent, and the query says so."""
    rows, _ = put_to(Compliance("clamp"))
    check("verified", rows[0]["verdict"] == "verified", rows[0])


def test_an_accepted_write_establishes_nothing(check):
    driver = Compliance("accept")
    rows, _ = put_to(driver)
    check("inconclusive", rows[0]["verdict"] == "inconclusive", rows[0])
    check("and the absurd limit is not left behind",
          driver.limit == 1.05e-4, driver.limit)


def test_a_write_the_driver_refuses_establishes_nothing(check):
    """The U2722A driver refuses out-of-window limits itself.

    Then the instrument never sees the write, and its handling of one
    is exactly what this leg cannot observe.
    """
    rows, _ = put_to(Compliance("driver refuses"))
    check("inconclusive", rows[0]["verdict"] == "inconclusive", rows[0])


class PowerTransport(NullTransport):
    """Holds a TSP `limitp`, refusing anything above 300 W."""

    def __init__(self):
        self.limitp = 0.0
        self.queue = []

    def write(self, text):
        if ".source.limitp" in text:
            watts = float(text.split("=")[1])
            if watts > 300:
                self.queue.append((5007, "Parameter too big"))
                return
            self.limitp = watts


class Keithley2635B(DummySMU):
    """Named for the one writer the tool has; nothing else is 2635B."""

    channel = "smua"
    POWER_LIMIT_SETTING = 0.0

    def __init__(self, reports=None):
        super().__init__(PowerTransport())
        self.reports = reports

    def read_power_limit(self):
        return (self.transport.limitp if self.reports is None
                else self.reports)

    def read_error(self):
        queue = self.transport.queue
        return queue.pop(0) if queue else (0, "")


def test_the_power_limit_is_verified_and_left_disabled(check):
    driver = Keithley2635B()
    rows, _ = put_to(driver)
    power = [r for r in rows if r["axis"] == "power_limit"]
    check("the power limit is put to the refused write", len(power) == 1,
          rows)
    check("verified", power[0]["verdict"] == "verified", power[0])
    check("and disabled afterwards", driver.transport.limitp == 0.0,
          driver.transport.limitp)


def test_the_power_limit_is_disabled_even_when_a_leg_fails(check):
    """A nonzero ceiling left behind overrides every later compliance."""
    driver = Keithley2635B(reports=0.25)
    rows, _ = put_to(driver)
    power = [r for r in rows if r["axis"] == "power_limit"][0]
    check("a query that ignores writes is not verified",
          power["verdict"] == "not verified", power)
    check("and the ceiling still goes back to disabled",
          driver.transport.limitp == 0.0, driver.transport.limitp)
