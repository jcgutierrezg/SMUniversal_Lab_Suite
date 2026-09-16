"""A range wider than the compliance in force, on the GSM-20H10.

Every experiment ranges first and limits second (fault 15). On this
instrument a range wider than the compliance *already* there is refused
with `+824 Cannot exceed compliance range`, and the narrower range
stays. After `*RST` the current compliance is 105 uA, so an IV sweep
asking for 100 mA measured on 105 uA. Named against
`SENS:CURR:DC:RANG 1.000000e-01` on the bench on 2026-09-16, three runs
out of three.

The fake below refuses the same way. The shared GSMTransport does not,
which is why every earlier test passed with the bug in place.
"""
import contextlib
import io

import pytest
from test_gsm20h10 import GSMTransport

from smuniversal_lab_suite.core.checkup import Checkup
from smuniversal_lab_suite.core.ranges import AUTO, RangePlan
from smuniversal_lab_suite.drivers.gwinstek_gsm20h10 import GWInstekGSM20H10


class RefusesAWiderRange(GSMTransport):
    """Refuses a fixed measurement range wider than the compliance."""

    AXES = (("SENS:CURR:DC:RANG", "current_limit"),
            ("SENS:VOLT:DC:RANG", "voltage_limit"))

    def _write(self, text):
        upper = text.strip().upper()
        for header, limit in self.AXES:
            if (upper.startswith(header) and ":AUTO" not in upper
                    and not upper.endswith("?")):
                wanted = self._number(text, None)
                if wanted is not None and \
                        wanted > getattr(self, limit) * (1 + 1e-9):
                    self.sent.append(text)
                    self.errors.append((824, "Cannot exceed compliance range"))
                    return
        super()._write(text)


@pytest.fixture
def gsm():
    transport = RefusesAWiderRange()
    transport.connect("fake")
    smu = GWInstekGSM20H10(transport)
    smu.reset()
    return smu, transport


def _ranges_sent_since(transport, mark, header):
    return [c for c in transport.sent[mark:]
            if c.upper().startswith(header) and ":AUTO" not in c.upper()]


def test_a_range_refused_against_the_reset_compliance_is_taken_once_the_limit_arrives(
        check, gsm):
    """The IV sweep's own sequence, first run after a connect."""
    smu, t = gsm
    smu.set_source_function("voltage")
    smu.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=0.8, measure_range=0.1))

    # The control. Without it this passes on a fake that never refuses,
    # which is the fake every earlier test used.
    check("the fake refused the range, as the instrument does",
          any(code == 824 for code, _ in t.errors), t.errors)
    check("and left the reset range in force",
          t.measure_current_range == pytest.approx(1.05e-4),
          t.measure_current_range)

    smu.set_current_limit(0.1)

    check("once the limit arrives, the range asked for is in force",
          t.measure_current_range == pytest.approx(0.105),
          t.measure_current_range)


def test_the_voltage_axis_is_the_mirror(check, gsm):
    """Unmeasured on the bench; the 2026-09-11 200 V question."""
    smu, t = gsm
    smu.set_source_function("current")
    smu.apply_ranges(RangePlan.for_sourcing(
        "current", source_range=1e-3, measure_range=200.0))
    check("refused against the 21 V reset compliance",
          t.measure_voltage_range == pytest.approx(21.0),
          t.measure_voltage_range)

    smu.set_voltage_limit(200.0)

    check("taken once the limit arrives",
          t.measure_voltage_range == pytest.approx(210.0),
          t.measure_voltage_range)


def test_a_compliance_narrower_than_the_range_still_wins(check, gsm):
    """The re-send is refused too, and nothing widens behind the limit."""
    smu, t = gsm
    smu.set_source_function("voltage")
    smu.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=0.8, measure_range=0.1))

    smu.set_current_limit(1e-3)

    check("the range was not widened past the compliance",
          t.measure_current_range <= 1e-3 * 1.05,
          t.measure_current_range)


def test_a_reset_forgets_the_range(check, gsm):
    """*RST discarded it; re-sending it afterwards is inherited state."""
    smu, t = gsm
    smu.set_source_function("voltage")
    smu.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=0.8, measure_range=0.1))
    smu.reset()
    mark = len(t.sent)

    smu.set_current_limit(0.1)

    sent = _ranges_sent_since(t, mark, "SENS:CURR:DC:RANG")
    check("no range follows the limit after a reset", sent == [], sent)


def test_a_source_function_change_forgets_the_range(check, gsm):
    """Setting the measure range of the sourced quantity is +823."""
    smu, t = gsm
    smu.set_source_function("voltage")
    smu.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=0.8, measure_range=0.1))
    smu.set_source_function("current")
    mark = len(t.sent)

    smu.set_current_limit(0.1)

    sent = _ranges_sent_since(t, mark, "SENS:CURR:DC:RANG")
    check("no range follows a limit into the other function", sent == [],
          sent)


def test_autoranging_is_not_resent(check, gsm):
    """AUTO replaces a remembered fixed range, it does not sit beside it.

    The fixed plan first is the point. On a fresh reset nothing is
    remembered, so AUTO alone passes whether or not it forgets anything.
    """
    smu, t = gsm
    smu.set_source_function("voltage")
    smu.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=0.8, measure_range=0.1))
    smu.apply_ranges(RangePlan(source_current=AUTO, source_voltage=AUTO,
                               measure_current=AUTO, measure_voltage=AUTO))
    mark = len(t.sent)

    smu.set_current_limit(0.1)
    smu.set_voltage_limit(20.0)

    sent = (_ranges_sent_since(t, mark, "SENS:CURR:DC:RANG")
            + _ranges_sent_since(t, mark, "SENS:VOLT:DC:RANG"))
    check("nothing is re-sent after an AUTO plan", sent == [], sent)


# ---------------------------------------------------------------------
# The checkup has to be able to see it
# ---------------------------------------------------------------------


def _wider_range_rows(smu):
    c = Checkup(smu, open_circuit=False)
    with contextlib.redirect_stdout(io.StringIO()):
        c.run(tiers=(1, 2))
    return {r.name.split(" range")[0][2:]: r for r in c.results
            if "wider than the old compliance" in r.name}


def test_the_checkup_passes_an_instrument_whose_driver_resends(check, gsm):
    smu, _ = gsm
    rows = _wider_range_rows(smu)
    for quantity in ("current", "voltage"):
        row = rows.get(quantity)
        check(f"{quantity}: the step ran", row is not None, sorted(rows))
        if row is not None:
            check(f"{quantity}: and did not fail", row.severity != "fail",
                  f"{row.severity}: {row.detail}")


def test_the_checkup_fails_an_instrument_whose_driver_does_not(
        check, gsm, monkeypatch):
    """The other half. A step that cannot fail is fault 19."""
    smu, _ = gsm
    monkeypatch.setattr(GWInstekGSM20H10, "_resend_measure_range",
                        lambda self, quantity: None)
    rows = _wider_range_rows(smu)
    for quantity in ("current", "voltage"):
        row = rows.get(quantity)
        check(f"{quantity}: the step ran", row is not None, sorted(rows))
        if row is not None:
            check(f"{quantity}: a refused range is a failure",
                  row.severity == "fail", f"{row.severity}: {row.detail}")
            check(f"{quantity}: marked SAFETY", "SAFETY" in row.detail,
                  row.detail)
