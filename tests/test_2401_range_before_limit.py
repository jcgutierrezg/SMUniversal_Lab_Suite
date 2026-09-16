"""A range wider than the compliance in force, on the Keithley 2401.

Seen on the bench on 2026-09-16: the 2401 refuses a measurement range
wider than the compliance already in force with `824 Cannot exceed
compliance range`, and the narrower range stays - 1 mA asked against
100 uA read back 105 uA, and 20 V against 1 V read back 2.1 V. The same
refusal as the GSM-20H10 (see test_gsm_range_before_limit.py), fixed the
same way in this driver.

The fake below refuses the way the instrument does. Fake2401 does not,
which is why nothing failed with the bug in place.
"""
import contextlib
import io

import pytest

from test_2401_driver import Fake2401

from smuniversal_lab_suite.core.checkup import Checkup
from smuniversal_lab_suite.core.ranges import AUTO, RangePlan
from smuniversal_lab_suite.drivers.keithley_2401 import Keithley2401

RESET = {":SENS:CURR:PROT": 1.05e-4, ":SENS:VOLT:PROT": 21.0,
         ":SENS:CURR:RANG": 1.05e-4, ":SENS:VOLT:RANG": 21.0}


class RefusesAWiderRange(Fake2401):
    """Refuses a fixed measurement range wider than the compliance."""

    LIMIT_FOR = {":SENS:CURR:RANG": ":SENS:CURR:PROT",
                 ":SENS:VOLT:RANG": ":SENS:VOLT:PROT"}

    def __init__(self):
        super().__init__()
        self.settings.update(RESET)
        self.refusals = 0

    def _write(self, text):
        parts = text.split()
        head = parts[0] if parts else ""
        if head in self.LIMIT_FOR and "?" not in text and len(parts) > 1:
            try:
                wanted = float(parts[-1])
            except ValueError:
                wanted = None
            limit = self.settings.get(self.LIMIT_FOR[head])
            if wanted is not None and limit is not None \
                    and wanted > limit * (1 + 1e-9):
                self.sent.append(text)
                self.refusals += 1
                return
        if text.strip().upper() == "*RST":
            self.settings.update(RESET)
        super()._write(text)


@pytest.fixture
def k2401():
    transport = RefusesAWiderRange()
    smu = Keithley2401(transport)
    smu.reset()
    return smu, transport


def _ranges_sent_since(transport, mark, head):
    return [c for c in transport.sent[mark:] if c.startswith(head + " ")]


def test_a_refused_current_range_is_taken_once_the_limit_arrives(check,
                                                                 k2401):
    """The IV sweep's order, first run after a connect."""
    smu, t = k2401
    smu.set_source_function("voltage")
    smu.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=0.8, measure_range=0.1))

    check("the fake refused, as the instrument does", t.refusals == 1,
          t.refusals)
    check("and kept the reset range",
          t.settings[":SENS:CURR:RANG"] == pytest.approx(1.05e-4),
          t.settings[":SENS:CURR:RANG"])

    smu.set_current_limit(0.1)

    check("once the limit arrives, the range asked for is in force",
          t.settings[":SENS:CURR:RANG"] == pytest.approx(0.1),
          t.settings[":SENS:CURR:RANG"])


def test_the_voltage_axis_too(check, k2401):
    smu, t = k2401
    smu.set_source_function("current")
    smu.set_voltage_limit(1.0)
    smu.apply_ranges(RangePlan.for_sourcing(
        "current", source_range=1e-3, measure_range=20.0))
    check("refused against the 1 V compliance",
          t.settings[":SENS:VOLT:RANG"] == pytest.approx(21.0),
          t.settings[":SENS:VOLT:RANG"])

    smu.set_voltage_limit(20.0)

    check("taken once the limit arrives",
          t.settings[":SENS:VOLT:RANG"] == pytest.approx(20.0),
          t.settings[":SENS:VOLT:RANG"])


def test_a_narrower_compliance_still_wins(check, k2401):
    smu, t = k2401
    smu.set_source_function("voltage")
    smu.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=0.8, measure_range=0.1))
    smu.set_current_limit(1e-3)
    check("the range was not widened past the compliance",
          t.settings[":SENS:CURR:RANG"] <= 1e-3,
          t.settings[":SENS:CURR:RANG"])


def test_a_reset_forgets_the_range(check, k2401):
    smu, t = k2401
    smu.set_source_function("voltage")
    smu.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=0.8, measure_range=0.1))
    smu.reset()
    mark = len(t.sent)
    smu.set_current_limit(0.1)
    sent = _ranges_sent_since(t, mark, ":SENS:CURR:RANG")
    check("no range follows the limit after a reset", sent == [], sent)


def test_a_source_function_change_forgets_the_range(check, k2401):
    smu, t = k2401
    smu.set_source_function("voltage")
    smu.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=0.8, measure_range=0.1))
    smu.set_source_function("current")
    mark = len(t.sent)
    smu.set_current_limit(0.1)
    sent = _ranges_sent_since(t, mark, ":SENS:CURR:RANG")
    check("no range follows a limit into the other function", sent == [],
          sent)


def test_autoranging_replaces_a_remembered_range(check, k2401):
    """The fixed plan first: on a fresh reset nothing is remembered."""
    smu, t = k2401
    smu.set_source_function("voltage")
    smu.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=0.8, measure_range=0.1))
    smu.apply_ranges(RangePlan(source_current=AUTO, source_voltage=AUTO,
                               measure_current=AUTO, measure_voltage=AUTO))
    mark = len(t.sent)
    smu.set_current_limit(0.1)
    sent = _ranges_sent_since(t, mark, ":SENS:CURR:RANG")
    check("nothing is re-sent after an AUTO plan", sent == [], sent)


# ---------------------------------------------------------------------
# The checkup step that found it
# ---------------------------------------------------------------------


def _wider_range_rows(smu):
    c = Checkup(smu, open_circuit=False)
    with contextlib.redirect_stdout(io.StringIO()):
        c.run(tiers=(1, 2), burst=False)
    return {r.name.split(" range")[0][2:]: r for r in c.results
            if "wider than the old compliance" in r.name}


def test_the_checkup_passes_the_2401_now(check, k2401):
    smu, _ = k2401
    rows = _wider_range_rows(smu)
    for quantity in ("current", "voltage"):
        row = rows.get(quantity)
        check(f"{quantity}: the step ran", row is not None, sorted(rows))
        if row is not None:
            check(f"{quantity}: and passed", row.severity == "pass",
                  f"{row.severity}: {row.detail}")


def test_the_checkup_still_fails_it_without_the_resend(check, k2401,
                                                       monkeypatch):
    smu, _ = k2401
    monkeypatch.setattr(Keithley2401, "_resend_measure_range",
                        lambda self, quantity: None)
    rows = _wider_range_rows(smu)
    for quantity in ("current", "voltage"):
        row = rows.get(quantity)
        check(f"{quantity}: the step ran", row is not None, sorted(rows))
        if row is not None:
            check(f"{quantity}: a refused range is a SAFETY failure",
                  row.severity == "fail" and "SAFETY" in row.detail,
                  f"{row.severity}: {row.detail}")
