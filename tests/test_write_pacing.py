"""Write pacing: declared by the instrument, enforced by the transport.

The GSM-20H10 drops commands that arrive faster than it parses them.
Measured on the bench on 2026-09-16 with the twenty-five writes an IV
sweep sends before its first query: unpaced, 7 runs in 10 never had
that query answered and the 3 that did returned three different error
queues; with 5 ms after each write, 10 in 10 answered with the same
queue. See `WRITE_DELAY_S` on the driver.

None of that can be reproduced offline - a fake transport parses as fast
as it is written to. What these pin is the mechanism the bench result
depends on: that the instrument's declaration reaches the transport,
that it does not leak onto another instrument's, and that the pause is
taken where it actually protects the instrument.
"""
import pytest

from smuniversal_lab_suite.core.transports import base as transport_base
from smuniversal_lab_suite.core.transports.base import Transport
from smuniversal_lab_suite.drivers.gwinstek_gsm20h10 import GWInstekGSM20H10
from smuniversal_lab_suite.drivers.keithley_2401 import Keithley2401


class Wire(Transport):
    """Records what was written, and answers nothing."""

    def __init__(self):
        super().__init__()
        self.sent = []

    def connect(self, address, **kwargs):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        self.sent.append(text)

    def _read(self, timeout_s):
        return "0"


@pytest.fixture
def wire():
    w = Wire()
    w.connect("fake")
    return w


def test_the_gsm_paces_the_link_it_is_given(check, wire):
    GWInstekGSM20H10(wire)
    check("the GSM declares a pause",
          GWInstekGSM20H10.WRITE_DELAY_S > 0,
          f"WRITE_DELAY_S = {GWInstekGSM20H10.WRITE_DELAY_S}")
    check("and it is on the transport, where write() can see it",
          wire.write_delay_s == GWInstekGSM20H10.WRITE_DELAY_S,
          f"transport.write_delay_s = {wire.write_delay_s}")


def test_a_link_another_instrument_paced_does_not_stay_paced(check, wire):
    """The pause is a fact about one instrument, not about a link.

    Without the reset in BaseInstrument, a transport a GSM had used would
    carry its 5 ms into whichever driver took it next - harmless in speed
    and wrong in principle, because it would hide a burst fault in the
    second instrument behind a guard declared for the first.
    """
    GWInstekGSM20H10(wire)
    Keithley2401(wire)
    check("the 2401 declares no pause", Keithley2401.WRITE_DELAY_S == 0)
    check("and the link it took is no longer paced",
          wire.write_delay_s == 0,
          f"transport.write_delay_s = {wire.write_delay_s}")


def test_every_write_is_followed_by_the_declared_pause(check, wire,
                                                       monkeypatch):
    slept = []
    monkeypatch.setattr(transport_base.time, "sleep", slept.append)
    GWInstekGSM20H10(wire)

    wire.write("SOUR:FUNC VOLT")
    wire.write("SOUR:VOLT 0")

    check("both commands went out", wire.sent == ["SOUR:FUNC VOLT",
                                                  "SOUR:VOLT 0"], wire.sent)
    check("each was followed by the pause",
          slept == [GWInstekGSM20H10.WRITE_DELAY_S] * 2, slept)


def test_the_pause_is_held_inside_the_lock(check, wire, monkeypatch):
    """Outside the lock the pause protects nothing.

    Another thread could take the lock the instant the write released it
    and send a query straight behind the command - the unpaced traffic
    the pause exists to prevent, arriving by a different route.
    """
    held = []
    monkeypatch.setattr(transport_base.time, "sleep",
                        lambda s: held.append(wire.lock.locked()))
    GWInstekGSM20H10(wire)

    wire.write("SOUR:FUNC VOLT")

    check("the pause was taken", held, held)
    check("while the lock was held", all(held), held)


def test_an_unpaced_instrument_does_not_sleep_at_all(check, wire,
                                                    monkeypatch):
    slept = []
    monkeypatch.setattr(transport_base.time, "sleep", slept.append)
    Keithley2401(wire)

    wire.write(":SOUR:FUNC VOLT")

    check("no pause for an instrument that declares none", slept == [],
          slept)


# ---------------------------------------------------------------------
# The checkup report says which pacing the run was taken under
# ---------------------------------------------------------------------


def _header_line(driver):
    from smuniversal_lab_suite.core.checkup import build_report
    report = build_report(driver, [], "fake")
    lines = [l for l in report.splitlines() if "Write pacing" in l]
    return lines[0] if lines else ""


def test_the_report_names_a_declared_pause(check, wire):
    line = _header_line(GWInstekGSM20H10(wire))
    check("the header carries the pause", "5 ms" in line, line)
    check("and says whose it is", "as the driver declares" in line, line)


def test_the_report_says_when_there_is_none(check, wire):
    line = _header_line(Keithley2401(wire))
    check("an unpaced run says so rather than saying nothing",
          line.startswith("- **Write pacing:** none"), line)


def test_the_report_flags_a_pause_the_driver_did_not_declare(check, wire):
    """In force and declared disagreeing is the case worth a line.

    Reading the class alone would report the declaration whatever the
    link actually did, which is the silent version of this fault.
    """
    driver = GWInstekGSM20H10(wire)
    wire.write_delay_s = 0.0
    line = _header_line(driver)
    check("the disagreement is named", "NOT what the driver declares" in line,
          line)
    check("with both values", "0 ms" in line and "(5 ms)" in line, line)


def test_the_report_does_not_invent_a_value_it_cannot_read(check, wire):
    driver = Keithley2401(wire)
    driver.transport = object()
    line = _header_line(driver)
    check("a transport with no such setting reads as not recorded",
          "not recorded" in line, line)
