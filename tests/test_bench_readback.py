"""The readback verifier has to catch a query that is lying.

A tool that only confirms honest instruments is worth nothing: an honest
instrument is the case nobody needed a tool for. So every test here
builds a query with a specific way of being wrong and asserts the tool
refuses it - and one honest query, so that "refuses everything" cannot
pass either.

The three dishonest shapes are not invented. Each is a way a real
instrument has behaved or could behave with the driver none the wiser:

* **echo** - the query plays back the last value written to it. This is
  the case the front-panel leg exists for, and the reason the leg cannot
  be automated: over the bus an echo and an honest read are the same
  reply.
* **constant** - the query answers the same thing forever. The
  GSM-20H10's `OUTP?` did exactly this on 2026-08-20, answering `0`
  three times with the output on.
* **latch** - the query reports the first value it ever saw. Passes the
  front-panel leg and the first bus leg, which is why there are three.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drivers.dummy_smu import DummySMU  # noqa: E402
from tools import bench_readback  # noqa: E402


class NullTransport:
    """Enough of a transport for a driver to be constructed."""

    def write(self, text):
        pass

    def query(self, text):
        return "LAB SUITE,MODEL DUMMY SMU,SIMULATED,1.0"

    def close(self):
        pass


def driver_with(reader):
    """A DummySMU whose measure-current range query behaves as given."""

    class Model(DummySMU):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.applied = None
            self.first_seen = None

        def _apply_measure_current_range(self, amps):
            self.applied = float(amps)
            if self.first_seen is None:
                self.first_seen = float(amps)

        def read_measure_current_range(self):
            return reader(self)

    return Model(NullTransport())


def run(driver, by_hand, log=None):
    """Put the three legs to one subject and return the row."""
    lines = []
    row = bench_readback.one_subject(
        driver, "measure_current", "read_measure_current_range",
        "_apply_measure_current_range", "current_ranges", "A",
        lines.append, scripted=str(by_hand))
    if log is not None:
        log.extend(lines)
    return row


def test_an_echoing_query_is_refused(check):
    """The case the front panel exists to catch.

    The instrument is on a range the operator dialled in by hand. A query
    that echoes the last *written* value cannot know that, so it answers
    with whatever the driver last set - which is nothing yet.
    """
    driver = driver_with(lambda self: self.applied)
    row = run(driver, by_hand=1e-4)
    check("an echo does not survive the front-panel leg",
          row["verdict"] == "not verified", row)
    check("and it is leg 1 that catches it", row.get("leg1") is not True,
          row)


def test_a_constant_query_is_refused(check):
    """Answers the same thing forever - the GSM-20H10's `OUTP?` shape.

    Set up so the constant *matches* what the operator dialled in, which
    is the awkward case: leg 1 passes on a coincidence, and only a range
    change exposes it.
    """
    driver = driver_with(lambda self: 1e-4)
    log = []
    row = run(driver, by_hand=1e-4, log=log)
    check("leg 1 passes, because the constant happens to match",
          row.get("leg1") is True, row)
    check("but the tool still refuses it",
          row["verdict"] == "not verified", row)
    check("and says a range change was not followed",
          any("DOES NOT FOLLOW" in line for line in log), log)


def test_a_latching_query_is_refused(check):
    """Reports the first value it ever saw.

    Passes the front-panel leg and the first bus leg. This is the whole
    reason there is a third leg: two agreements in a row are not
    evidence when the second could be the first one repeated.
    """
    driver = driver_with(lambda self: self.first_seen or 1e-4)
    row = run(driver, by_hand=1e-4)
    check("a latch is not verified", row["verdict"] == "not verified", row)
    check("it got past leg 1", row.get("leg1") is True, row)


def test_an_honest_query_is_verified(check):
    """The control.

    Without this the three tests above are satisfied by a tool that
    refuses everything, which would be useless in the opposite
    direction.
    """
    driver = driver_with(lambda self: self.applied)

    # An honest instrument knows the range it is physically on, whether
    # or not the bus put it there. The front-panel leg is modelled by
    # seeding that state directly - which is exactly what a hand on the
    # dial does.
    driver.applied = 1e-4
    row = run(driver, by_hand=1e-4)
    check("an honest query is verified", row["verdict"] == "verified", row)
    check("through all three legs",
          row.get("leg1") and row.get("leg2") and row.get("leg3"), row)


def test_a_skipped_subject_establishes_nothing(check):
    """No front panel, no verdict.

    The tempting shortcut is to fall back to the bus legs alone when
    nobody is there to turn a dial. That would report `verified` for an
    echo, which is the one answer this tool must never give.
    """
    driver = driver_with(lambda self: self.applied)
    row = bench_readback.one_subject(
        driver, "measure_current", "read_measure_current_range",
        "_apply_measure_current_range", "current_ranges", "A",
        lambda _line: None, scripted="")
    check("skipping is not a pass", row["verdict"] == "skipped", row)


def test_too_few_ranges_is_inconclusive_not_verified(check):
    """A model with one range cannot rule out a constant.

    Two bus legs need two ranges to move between. Where the ladder
    cannot supply them the honest answer is that nothing was
    established, not that everything was fine.
    """
    driver = driver_with(lambda self: self.applied)
    # Seeded, as in the honest case: the instrument is physically on the
    # range the operator dialled in, so leg 1 passes and the verdict
    # turns on the ladder rather than on the query.
    driver.applied = 1e-4
    driver.LIMITS = type(driver.LIMITS)(
        **{**driver.LIMITS.__dict__, "current_ranges": [1e-4]})
    row = run(driver, by_hand=1e-4)
    check("one range gives an inconclusive verdict",
          row["verdict"] == "inconclusive", row)
