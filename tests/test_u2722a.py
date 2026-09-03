import pytest

from core.ranges import AUTO, RangeError

pytestmark = [pytest.mark.gui]


"""The Keysight U2722A driver: dialect, command order, and two silent
wrong-answer traps.

Most of this file is not the happy path, because the happy path is the
part that would still look fine if the driver were wrong. Three things
on this instrument produce a tidy, plausible, incorrect dataset:

1. **Compliance clamped by the active range.** `CURRent:LIMit`'s
   accepted maximum depends on the current range that is set at the
   time, and after *RST the range is R1uA with a 100 nA limit. The
   experiment sets the limit before the range. Send them in that order
   without compensating and you source volts into a sample with a
   ~100 nA compliance and record something that reads exactly like an
   open circuit. The fake instrument here models the clamp, so the test
   fails if the driver stops re-sending the limit.

2. **Source range left at R2V.** There is no auto range and the
   experiment does not set the range of the quantity it sweeps, because
   every other SMU in the suite auto-ranges its source. A sweep to 5 V
   would clip at 2 V and return a straight line with an excellent R².
   The fake clamps to the active range, so a driver that forgets to
   range up fails the resistor recovery.

3. **A neighbour's spelling.** SCPI instruments log an unrecognised
   command and carry on with the previous setting. So the tests assert
   the exact strings sent, including the channel list and its
   whitespace, and assert that the 2450, 2401 and GSM spellings are
   absent.

The instrument is faked; the driver under test is the one that will run
on the bench.
"""
import time

from core.gui.widgets import apply_remote_sense
from core.transports.base import Transport
from drivers.gwinstek_gsm20h10 import GWInstekGSM20H10
from drivers.keithley_2450 import Keithley2450
from drivers.keysight_u2722a import KeysightU2722A
from drivers.registry import driver_for_idn

SAMPLE_OHM = 470.0

CURRENT_CEILING = {"R1uA": 1e-6, "R10uA": 1e-5, "R100uA": 1e-4,
                   "R1mA": 1e-3, "R10mA": 1e-2, "R120mA": 0.12}
VOLTAGE_CEILING = {"R2V": 2.0, "R20V": 20.0}


#: A limit is settable only between a tenth of the active range's full
#: scale and full scale. Measured on the bench 2026-08-24; see the
#: instrument note for the twelve observations and the two that do not
#: fit any single rule.
LIMIT_FLOOR_FRACTION = 0.1


def window(token, table):
    ceiling = table[token]
    return (ceiling * LIMIT_FLOOR_FRACTION, ceiling)


class U2722ATransport(Transport):
    """A fake U2722A with a resistor across channel 1.

    Models the three behaviours that make this instrument dangerous,
    all of them measured rather than assumed:

    1. **A limit outside the active range's window is refused**, with
       `-222, "Data out of range"`, and the previous value stays in
       force. It is not clamped. Bench snippet E: three refused writes,
       readbacks either side of each, the value never moved.
    2. **A range change moves the limit into the new range's window**,
       silently. Snippet A watched 100 uA become 12 mA on a move to
       R120mA with a clean error queue - the protection around the
       sample widened 120-fold and nothing said so.
    3. **A source level is clamped to the active range**, silently.

    (1) and (3) are the ones the driver has to survive; (2) is the one
    it exists to detect. The fake deliberately models the *hazardous*
    reading of (2) - clamp into the window in both directions - because
    one bench observation showed a limit surviving above the new
    range's ceiling instead, and a driver that is correct against the
    hazardous reading is correct against both.
    """

    def __init__(self, strict_channel=True):
        super().__init__()
        self.sent = []
        self.connected = True
        self.strict_channel = strict_channel
        self.errors = []

        # instrument state, at *RST defaults
        self.current_range = "R1uA"
        self.voltage_range = "R2V"
        self.current_limit = 1e-7
        self.voltage_limit = 0.2
        self.voltage_level = 0.0
        self.current_level = 0.0
        self.nplc = 0
        self.output = False

    def connect(self, address, **kw):
        self.connected = True

    def close(self):
        self.connected = False

    # -- helpers ----------------------------------------------------
    # IEEE-488.2 common commands and the error query address the whole
    # module, not a channel - the manual's own examples send them bare.
    CHANNEL_FREE = ("*", "SYST:ERR")

    def _needs_channel(self, text):
        head = text.strip().upper()
        return not any(head.startswith(p) for p in self.CHANNEL_FREE)

    def _strip_channel(self, text, complain=False):
        """Pull the channel list off a command, complaining exactly as
        the instrument would if it is missing or malformed."""
        if "(@" not in text:
            if complain and self.strict_channel and self._needs_channel(text):
                self.errors.append((-109, "Missing parameter"))
            return text.strip(), None
        head, _, tail = text.partition("(@")
        channel = tail.rstrip(")").strip()
        # A query needs a space between '?' and the channel list, or the
        # instrument answers -103. The command form uses a comma.
        if complain and "?" in head and not head.endswith("? "):
            self.errors.append((-103, "Invalid separator"))
        return head.rstrip(", ").strip(), channel

    def _write(self, text):
        self.sent.append(text)
        body, _ = self._strip_channel(text, complain=True)
        upper = body.upper()

        # A query is not a setting. Without this, `SOUR:CURR:LIM?`
        # matches the `SOUR:CURR:LIM` write handler and asking the fake
        # what it holds tries to parse "?" as a number - the same fault
        # the GSM-20H10 fake had with `SOUR:FUNC?`, where the query
        # silently reset the mode it was asking about. A fake that
        # changes state when questioned makes every test above it
        # meaningless.
        if upper.endswith("?"):
            return

        if upper.startswith("SOUR:CURR:RANG"):
            self.current_range = body.split()[-1]
            # A range change drags the limit into the new range's
            # window. Silently, in both directions.
            floor, ceiling = window(self.current_range, CURRENT_CEILING)
            self.current_limit = max(floor, min(self.current_limit,
                                                ceiling))
        elif upper.startswith("SOUR:VOLT:RANG"):
            self.voltage_range = body.split()[-1]
            floor, ceiling = window(self.voltage_range, VOLTAGE_CEILING)
            self.voltage_limit = max(floor, min(self.voltage_limit,
                                                ceiling))
        elif upper.startswith("SOUR:CURR:LIM"):
            asked = abs(float(body.split()[-1]))
            floor, ceiling = window(self.current_range, CURRENT_CEILING)
            # Refused, not clamped: the old value stays.
            if floor * 0.999999 <= asked <= ceiling * 1.000001:
                self.current_limit = asked
            else:
                self.errors.append((-222, "Data out of range"))
        elif upper.startswith("SOUR:VOLT:LIM"):
            asked = abs(float(body.split()[-1]))
            floor, ceiling = window(self.voltage_range, VOLTAGE_CEILING)
            if floor * 0.999999 <= asked <= ceiling * 1.000001:
                self.voltage_limit = asked
            else:
                self.errors.append((-222, "Data out of range"))
        elif upper.startswith("SOUR:VOLT "):
            asked = float(body.split()[-1])
            ceiling = VOLTAGE_CEILING[self.voltage_range]
            self.voltage_level = max(-ceiling, min(asked, ceiling))
        elif upper.startswith("SOUR:CURR "):
            asked = float(body.split()[-1])
            ceiling = CURRENT_CEILING[self.current_range]
            self.current_level = max(-ceiling, min(asked, ceiling))
        elif upper.startswith("SENS:CURR:NPLC") or \
                upper.startswith("SENS:VOLT:NPLC"):
            self.nplc = int(float(body.split()[-1]))
        elif upper.startswith("OUTP "):
            self.output = "ON" in upper
        elif upper == "*RST":
            self.current_range = "R1uA"
            self.voltage_range = "R2V"
            self.current_limit = 1e-7
            self.voltage_limit = 0.2

    def _read(self, timeout_s):
        last = self.sent[-1] if self.sent else ""
        body, _ = self._strip_channel(last)
        upper = body.upper()

        if "IDN" in upper:
            return "Keysight Technologies,U2722A,MY62030002,1.06"

        if upper.startswith("SYST:ERR"):
            if self.errors:
                code, message = self.errors.pop(0)
                return f'{code},"{message}"'
            return '+0,"No error"'

        if upper.startswith("SOUR:CURR:LIM"):
            return f"{self.current_limit:.8E}"
        if upper.startswith("SOUR:VOLT:LIM"):
            return f"{self.voltage_limit:.8E}"

        if upper.startswith("SENS:CURR:APER") or \
                upper.startswith("SENS:VOLT:APER"):
            return f"{self.nplc / 50.0:.6E}"

        if upper.startswith("MEAS:VOLT"):
            return f"{self._volts():.6E}"
        if upper.startswith("MEAS:CURR"):
            return f"{self._amps():.6E}"

        return "0"

    def _volts(self):
        volts = self.voltage_level
        amps = volts / SAMPLE_OHM
        if abs(amps) > self.current_limit:
            volts = self.current_limit * SAMPLE_OHM * (1 if volts >= 0 else -1)
        return volts

    def _amps(self):
        amps = self.voltage_level / SAMPLE_OHM
        if abs(amps) > self.current_limit:
            amps = self.current_limit * (1 if amps >= 0 else -1)
        return amps


def fit_resistance(sourced, measured, mode):
    n = len(sourced)
    mean_x = sum(sourced) / n
    mean_y = sum(measured) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(sourced, measured))
    den = sum((x - mean_x) ** 2 for x in sourced)
    slope = num / den
    return (1.0 / slope) if mode == "voltage" else slope


def run_software_sweep(smu, mode, start, stop, points, timeout=15.0):
    smu.start_linear_sweep(mode, start, stop, points, 0.0)
    deadline = time.monotonic() + timeout
    while smu.sweep_points_ready() < points and time.monotonic() < deadline:
        time.sleep(0.005)
    return smu.read_sweep(points)


# ---------------------------------------------------------------
# A. auto-detection
# ---------------------------------------------------------------


def test_identification(check):
    idn = "Keysight Technologies,U2722A,MY62030002,1.06"
    check("*IDN? resolves to the U2722A driver",
          driver_for_idn(idn) is KeysightU2722A, f"got {driver_for_idn(idn)}")
    check("a 2450 reply still resolves to the 2450",
          driver_for_idn("KEITHLEY INSTRUMENTS,MODEL 2450,04412345,1.7.12b")
          is Keithley2450)
    check("a GSM reply still resolves to the GSM",
          driver_for_idn("GW INSTEK,GSM-20H10,GEW852313,V1.10")
          is GWInstekGSM20H10)
    # The U2723A is the same dialect with different current ranges, so
    # resolving it here would hand it the wrong LIMITS.
    check("a U2723A reply is NOT claimed by this driver",
          driver_for_idn("Keysight Technologies,U2723A,MY1234,1.06")
          is not KeysightU2722A,
          "it needs its own LIMITS before it is registered")

    # ---------------------------------------------------------------
    # B. the channel list, on everything
    # ---------------------------------------------------------------


def test_the_fake_does_not_change_state_when_questioned(check):
    """A fake that answers by mutating proves nothing above it.

    This is the second time in this project: the GSM-20H10's fake had
    `SOUR:FUNC?` matching its `SOUR:FUNC` write handler, so asking it
    which mode it was in silently set the mode to voltage. Here the
    same shape would have `SOUR:CURR:LIM?` parsed as a limit write.
    Cheap to check, and it fails loudly instead of turning a readback
    test into a tautology.
    """
    t = U2722ATransport()
    t.current_range = "R120mA"
    t.current_limit = 1.2e-2
    t.voltage_range = "R20V"
    t.voltage_limit = 5.0
    before = (t.current_range, t.current_limit,
              t.voltage_range, t.voltage_limit, list(t.errors))

    for q in ["SOUR:CURR:LIM? (@1)", "SOUR:VOLT:LIM? (@1)",
              "SOUR:CURR:RANG? (@1)", "SOUR:VOLT:RANG? (@1)"]:
        t.query(q, timeout_s=1.0)

    after = (t.current_range, t.current_limit,
             t.voltage_range, t.voltage_limit, list(t.errors))
    check("querying the fake leaves its state alone", before == after,
          f"{before} became {after}")
    check("and the limit query reports what is held",
          abs(float(t.query("SOUR:CURR:LIM? (@1)", timeout_s=1.0))
              - 1.2e-2) < 1e-12)


def test_channel_list(check):
    global t
    t = U2722ATransport()
    smu = KeysightU2722A(t)
    smu.reset()
    smu.set_source_function("voltage")
    smu.set_current_limit(1e-3)
    smu._apply_source_current_range(1e-3)
    smu.set_voltage_level(1.0)
    smu.set_nplc(1)
    smu.output_on()
    smu.measure()

    # *CLS and *RST are IEEE-488.2 common commands and take no channel.
    addressed = [s for s in t.sent
                 if not s.startswith("*") and not s.startswith("SYST:ERR")]
    missing = [s for s in addressed if "(@" not in s]
    check("every instrument-specific command carries a channel list",
          not missing, f"missing on: {missing[:3]}")
    check("commands use the comma form", any(s.endswith(", (@1)")
                                             for s in addressed))
    check("queries put a space before the channel list, not a comma",
          all("? (@1)" in s for s in addressed if "?" in s),
          "otherwise the instrument answers -103, Invalid separator")
    check("the fake instrument logged no separator errors", not t.errors,
          f"{t.errors}")

    # ---------------------------------------------------------------
    # C. the dialect is its own
    # ---------------------------------------------------------------


def test_dialect_differs_from_its_neighbours(check):
    sent = " | ".join(t.sent)
    check("compliance uses SOUR:CURR:LIM", "SOUR:CURR:LIM" in sent)
    check("does NOT use the 2450 spelling", "SOUR:VOLT:ILIM" not in sent)
    check("does NOT use the 2401 spelling", "SENS:CURR:PROT" not in sent)
    check("does NOT use the GSM spelling", "SENS:CURR:DC:PROT:LEV" not in sent)
    check("NPLC has no :DC: infix", "SENS:CURR:NPLC" in sent
          and "SENS:CURR:DC:NPLC" not in sent)
    check("ranges are tokens, not numbers", "SOUR:CURR:RANG R1mA" in sent)
    # There is no SOUR:FUNC on this instrument; the mode is implied by
    # which quantity gets driven. Sending one would be logged and ignored,
    # and would look like it had worked.
    check("never sends SOUR:FUNC, which does not exist here",
          "SOUR:FUNC" not in sent)
    check("line frequency is pinned, since there is no auto-detect",
          "SYST:LFREQ F50HZ" in sent)

    # ---------------------------------------------------------------
    # D. TRAP 1 - compliance clamped by the active range
    # ---------------------------------------------------------------


def test_the_fake_reproduces_the_bench(check):
    """The instrument model is a claim about hardware. Check it.

    Everything below rests on the fake behaving as the U2722A did on
    2026-08-24. Two behaviours, both measured, and a test that asserts
    them directly rather than through the driver - because a driver
    test cannot tell a correct driver from a fake that never posed the
    problem.
    """
    # Snippet E: a limit outside the active range's window is REFUSED,
    # not clamped, and the previous value stays in force.
    t = U2722ATransport()
    t.current_range = "R100uA"
    t.current_limit = 5e-5
    t.write("SOUR:CURR:LIM 1.000000e-09, (@1)")
    check("an out-of-window limit is refused",
          (-222, "Data out of range") in t.errors, f"{t.errors}")
    check("and the previous limit is untouched",
          abs(t.current_limit - 5e-5) < 1e-15,
          f"clamped to {t.current_limit:.3e} instead of being refused")

    # Snippet A: a range change moves the limit into the new range's
    # window, silently. 100 uA on R100uA became 12 mA on R120mA with a
    # clean error queue - the fault this whole wave exists for.
    t2 = U2722ATransport()
    t2.current_range = "R100uA"
    t2.current_limit = 1e-4
    t2.errors.clear()
    t2.write("SOUR:CURR:RANG R120mA, (@1)")
    check("a range change moves the compliance",
          abs(t2.current_limit - 1.2e-2) < 1e-9,
          f"holds {t2.current_limit:.3e} A - snippet A saw 1.2e-02")
    check("and says nothing about it", not t2.errors, f"{t2.errors}")


def test_compliance_survives_a_range_change(check):
    """The bench fault, in the driver's own terms.

    Snippet A, 2026-08-24: on R100uA holding a 100 uA limit, a move to
    R120mA left the instrument reporting 12 mA - a 120-fold widening of
    the protection around the sample, with `SYST:ERR?` clean. Nothing
    downstream would ever have noticed.
    """
    t2 = U2722ATransport()
    smu2 = KeysightU2722A(t2)
    smu2.reset()
    smu2.set_source_function("voltage")
    smu2.set_current_limit(1e-2)
    check("the limit picked its own range",
          t2.current_range == "R10mA",
          f"{t2.current_range} - 10 mA is settable on R10mA and, "
          f"because the floor is a tenth of full scale, nowhere else")
    check("and the compliance is the value that was requested",
          abs(t2.current_limit - 1e-2) < 1e-12,
          f"instrument holds {t2.current_limit:.3e} A")
    check("no error was logged getting there", not t2.errors, f"{t2.errors}")

    # A later range change that would strand the compliance is refused.
    # This is the assertion that separates the new contract from the
    # old one: before, the range moved and the limit was re-sent into a
    # window that could not hold it.
    t2d = U2722ATransport()
    smu2d = KeysightU2722A(t2d)
    smu2d.reset()
    smu2d.set_source_function("voltage")
    smu2d.set_current_limit(1e-3)
    smu2d._apply_source_current_range(0.12)
    check("a range change that would strand the compliance is refused",
          t2d.current_range == "R1mA",
          f"range moved to {t2d.current_range}, whose limit floor is "
          f"12 mA - the 1 mA compliance cannot exist there")
    check("so the compliance is still the one that was asked for",
          abs(t2d.current_limit - 1e-3) < 1e-12,
          f"{t2d.current_limit:.3e}")
    check("and the instrument never had to refuse anything",
          not t2d.errors, f"{t2d.errors}")

    # and the same for the voltage side, sourcing current
    t3 = U2722ATransport()
    smu3 = KeysightU2722A(t3)
    smu3.reset()
    smu3.set_source_function("current")
    smu3.set_voltage_limit(10.0)
    check("voltage compliance picks R20V and lands there",
          t3.voltage_range == "R20V" and abs(t3.voltage_limit - 10.0) < 1e-9,
          f"{t3.voltage_range} / {t3.voltage_limit}")


def test_a_limit_is_read_back_and_a_refusal_stops_the_run(check):
    """The readback is the guarantee; without it nothing else holds.

    A limit outside the active range's window is refused with `-222`
    and the *previous* value stays in force - the instrument does not
    clamp, and it does not stop. Bench snippet E confirmed that with
    readbacks either side of three refused writes. So the only thing
    standing between a refused compliance and a run that proceeds
    against the wrong one is asking the instrument what it holds.
    """
    t = U2722ATransport()
    smu = KeysightU2722A(t)
    smu.reset()
    smu.set_source_function("voltage")
    smu.set_current_limit(1e-4)

    read = [x for x in t.sent if x.startswith("SOUR:CURR:LIM?")]
    check("the limit is read back after it is written", read, f"{t.sent[-4:]}")

    # Now the instrument's range moves without the driver knowing -
    # a front-panel turn, or a reset from another window. The next
    # restore writes 100 uA into a range whose floor is 12 mA, the
    # instrument refuses it, and the 12 mA it is already holding is
    # what the sample would have been protected by.
    t.current_range = "R120mA"
    t.current_limit = 1.2e-2
    raised = None
    try:
        smu._restore_current_limit()
    except RangeError as exc:
        raised = exc
    check("a refused compliance raises instead of measuring",
          raised is not None,
          f"instrument holds {t.current_limit:.3e} A and nothing objected")
    if raised is not None:
        check("and the message reports both values",
              "0.0001" in str(raised) and "0.012" in str(raised),
              str(raised)[:160])


def test_an_unsettable_compliance_is_refused_up_front(check):
    """Refuse before output-on, naming what would work.

    Each range takes a limit only between a tenth of full scale and
    full scale, so there are compliances this instrument simply cannot
    express - including one in the middle of its span, because the
    current ranges are decades until the last one and R10mA's ceiling
    (10 mA) does not meet R120mA's floor (12 mA).
    """
    t = U2722ATransport()
    smu = KeysightU2722A(t)
    smu.reset()
    smu.set_source_function("voltage")
    before = len(t.sent)

    for value, why in [(1e-9, "below the 100 nA floor of R1uA"),
                       (1.1e-2, "in the gap between R10mA and R120mA"),
                       (1.0, "above the instrument")]:
        raised = None
        try:
            smu.set_current_limit(value)
        except RangeError as exc:
            raised = exc
        check(f"{value:g} A is refused ({why})", raised is not None,
              f"accepted; instrument holds {t.current_limit:.3e} A")
        if raised is not None:
            check(f"the message for {value:g} A names a range that works",
                  "R10mA takes" in str(raised), str(raised)[:140])

    check("nothing was written to the instrument on a refusal",
          not any("LIM" in x for x in t.sent[before:]), f"{t.sent[before:]}")
    check("and no output was turned on", not t.output)

    # Boundary values are legal at both ends, or the windows have holes
    # the operator will fall into.
    for value, token in [(1e-5, "R10uA"), (1e-4, "R100uA"),
                         (1e-2, "R10mA"), (1.2e-2, "R120mA")]:
        t2 = U2722ATransport()
        smu2 = KeysightU2722A(t2)
        smu2.reset()
        smu2.set_source_function("voltage")
        smu2.set_current_limit(value)
        check(f"{value:g} A is accepted on {token}",
              t2.current_range == token and not t2.errors,
              f"{t2.current_range}, errors {t2.errors}")


def test_auto_cannot_strand_a_compliance(check):
    """The reconciliation that lost this instrument its compliance.

    `RangePlan.for_sourcing` forces `measure_current=AUTO`, and AUTO
    beats a fixed value in the shared-knob reconciliation, so a 1 uA
    sweep asked for R120mA - the one range on which a 100 uA compliance
    cannot be set at all.

    AUTO on this model still means "the widest range". What stops it
    here is that the range change is declined, because R120mA cannot
    hold the compliance already in force.
    """
    from core.ranges import RangePlan

    t = U2722ATransport()
    smu = KeysightU2722A(t)
    smu.reset()
    smu.set_source_function("voltage")
    smu.set_current_limit(1e-4)
    smu.apply_ranges(RangePlan(source_current=AUTO, source_voltage=0.1,
                               measure_current=AUTO, measure_voltage=AUTO))
    check("AUTO does not drag the range off the compliance",
          t.current_range == "R100uA",
          f"{t.current_range} - R120mA cannot hold a 100 uA limit")
    check("and the compliance is intact",
          abs(t.current_limit - 1e-4) < 1e-12, f"{t.current_limit:.3e}")
    check("with a clean error queue", not t.errors, f"{t.errors}")

    # With no compliance to defer to, AUTO still means the widest.
    t2 = U2722ATransport()
    smu2 = KeysightU2722A(t2)
    smu2.reset()
    smu2._apply_source_current_range(AUTO)
    check("AUTO with nothing to protect still takes the widest range",
          t2.current_range == "R120mA", t2.current_range)


def test_the_checkup_sequence_runs_clean(check):
    """The four red lines of the 2026-08-24 commissioning round.

    Replayed exactly as `core.checkup` issues them: configure for
    voltage sourcing, then for current sourcing, with the same probe
    values. Every one of the four failures was `-222, "Data out of
    range"`, from two distinct causes.
    """
    from core.ranges import RangePlan

    t = U2722ATransport()
    smu = KeysightU2722A(t)
    smu.reset()

    smu.set_source_function("voltage")
    smu.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=0.1, measure_range=1e-4))
    smu.set_current_limit(1e-4)
    smu.set_voltage_level(0.0)
    check("voltage-sourcing setup logs no error", not t.errors, f"{t.errors}")

    smu.set_source_function("current")
    smu.apply_ranges(RangePlan.for_sourcing(
        "current", source_range=1e-6, measure_range=1.0))
    smu.set_voltage_limit(1.0)
    smu.set_current_level(0.0)
    check("current-sourcing setup logs no error", not t.errors, f"{t.errors}")
    check("the voltage compliance is the one that was asked for",
          abs(t.voltage_limit - 1.0) < 1e-9, f"{t.voltage_limit}")


def test_the_sourced_quantity_cannot_cap_its_own_level(check):
    """A compliance from the previous run must not throttle this one.

    `SOUR:CURR:LIM` is the compliance while sourcing voltage. While
    sourcing *current* it applies to the quantity the operator is
    commanding, so a 100 uA value carried over from a voltage-sourcing
    run is at best meaningless and at worst a cap on the sweep - a
    smooth, plausible curve at a fraction of the requested current.

    The replacement is not full scale. It is the narrowest limit the
    range can hold that still clears every level commanded, so the axis
    keeps a real fallback instead of being opened to 120 mA.
    """
    t = U2722ATransport()
    smu = KeysightU2722A(t)
    smu.reset()
    smu.set_source_function("voltage")
    smu.set_current_limit(1e-4)
    check("the compliance is set while sourcing voltage",
          abs(t.current_limit - 1e-4) < 1e-12, f"{t.current_limit:.3e}")

    smu.set_source_function("current")
    floor = CURRENT_CEILING[t.current_range] * LIMIT_FLOOR_FRACTION
    check("switching to current sourcing drops the stale compliance",
          abs(t.current_limit - floor) < floor * 1e-9,
          f"holds {t.current_limit:.3e} A on {t.current_range}; expected "
          f"the range floor {floor:.3e} A, not the old 1e-04")
    check("and not full scale either - the fallback is kept",
          t.current_limit < CURRENT_CEILING[t.current_range],
          f"opened all the way to {t.current_limit:.3e} A")

    # A level larger than the headroom raises the limit, and does so
    # BEFORE the level is written - if the limit caps the level, the
    # other order comes out clipped with nothing to show for it.
    smu.set_current_level(5e-2)
    lim = t.sent.index("SOUR:CURR:LIM 1.000000e-01, (@1)")
    lvl = t.sent.index("SOUR:CURR 5.000000e-02, (@1)")
    check("headroom is raised before the level is commanded", lim < lvl,
          f"limit at {lim}, level at {lvl}")
    check("the level was not clamped", abs(t.current_level - 5e-2) < 1e-12,
          f"{t.current_level:.3e}")
    check("and the limit clears it without opening to full scale",
          5e-2 < t.current_limit < CURRENT_CEILING[t.current_range],
          f"{t.current_limit:.3e} on {t.current_range}")
    check("with no error logged", not t.errors, f"{t.errors}")


def test_the_resolution_the_compliance_bought_is_reported(check, capsys):
    """The coupling deviation 52 creates is invisible without this.

    On every other instrument here the compliance and the measurement
    range are separate decisions. On this one the compliance *is* the
    range, so a field the operator reads as protection is also a
    resolution control - and typing 90 uA instead of 9 uA costs a
    decade of it with nothing on the panel to say so.
    """
    t = U2722ATransport()
    smu = KeysightU2722A(t)
    smu.reset()
    smu.set_source_function("voltage")
    capsys.readouterr()

    smu.set_current_limit(9e-6)
    fine = capsys.readouterr().out
    check("the range chosen is named", "R10uA" in fine, fine)
    # 10 uA / 16384 = 610.4 pA
    check("and the resolution it buys is reported",
          "6.104e-10" in fine, fine)

    smu2 = KeysightU2722A(U2722ATransport())
    smu2.reset()
    smu2.set_source_function("voltage")
    capsys.readouterr()
    smu2.set_current_limit(9e-5)
    coarse = capsys.readouterr().out
    check("a decade looser compliance reports a decade coarser reading",
          "R100uA" in coarse and "6.104e-09" in coarse, coarse)


def test_an_unreset_driver_writes_nothing(check):
    """No reset, no known range, so no limit invented for it.

    Found by `test_transition_traces.py`, which builds a driver and asks
    it not to energise on its own. Before `reset()` the driver does not
    know which range the instrument is on, and the sourced axis's limit
    is defined relative to that range - so there is no honest value to
    write, and writing one would be a command to the instrument based on
    a guess about its state. The first range change establishes it
    instead.
    """
    t = U2722ATransport()
    smu = KeysightU2722A(t)
    smu.set_source_function("current")       # deliberately no reset()
    check("nothing was written to the instrument",
          not any("LIM" in x for x in t.sent), f"{t.sent}")
    check("and certainly no output", not t.output)

    # Once a range is known, the limit appears without further prompting.
    smu.reset()
    smu.set_source_function("current")
    smu._apply_source_current_range(1e-3)
    floor = CURRENT_CEILING[t.current_range] * LIMIT_FLOOR_FRACTION
    check("a range change establishes the sourced axis's limit",
          abs(t.current_limit - floor) < floor * 1e-9,
          f"{t.current_limit:.3e} on {t.current_range}")


def test_a_level_below_one_count_is_refused(check):
    """Bench, 2026-08-25: below a count the sign is not commanded.

    On R120mA one count is 7.32 uA. Commanding `-1 uA` and `+1 uA`
    produced *the same output* - the minus sign was simply ignored,
    because 1 uA is a seventh of a count. What comes out is offset
    residue, and its polarity is not under anyone's control: positive
    through every probe that day, negative during the commissioning run
    where it walked the output to the -2 V range rail against a working
    1 V compliance.

    So this refuses rather than warns. An operator asking for a 1 uA
    bias getting an output at the opposite polarity is not something a
    log line covers.
    """
    t = U2722ATransport()
    smu = KeysightU2722A(t)
    smu.reset()
    smu.set_source_function("current")
    smu._apply_source_current_range(AUTO)          # -> R120mA, as the plan does
    check("the plan put us on the widest range",
          t.current_range == "R120mA", t.current_range)

    before = len(t.sent)
    raised = None
    try:
        smu.set_current_level(1e-6)                # a seventh of one count
    except RangeError as exc:
        raised = exc
    check("a sub-count level is refused", raised is not None,
          f"accepted; instrument holds {t.current_level:.3e} A")
    if raised is not None:
        check("the message names the range that would carry it",
              "R1uA would carry it" in str(raised), str(raised)[:200])
        check("and says why, not just that it refused",
              "sign is not commanded" in str(raised), str(raised)[:200])
    check("nothing was commanded on the refusal",
          not any(x.startswith("SOUR:CURR ") for x in t.sent[before:]),
          f"{t.sent[before:]}")
    check("and no output was energised", not t.output)

    # The boundary is exactly MIN_LEVEL_COUNTS, both sides of it.
    count = 0.12 / KeysightU2722A.COUNTS_PER_RANGE
    floor = count * KeysightU2722A.MIN_LEVEL_COUNTS
    for value, ok in [(floor * 0.99, False), (floor, True),
                      (floor * 1.01, True)]:
        t2 = U2722ATransport()
        smu2 = KeysightU2722A(t2)
        smu2.reset()
        smu2.set_source_function("current")
        smu2._apply_source_current_range(AUTO)
        accepted = True
        try:
            smu2.set_current_level(value)
        except RangeError:
            accepted = False
        check(f"{value:.4g} A is {'accepted' if ok else 'refused'}",
              accepted is ok,
              f"{'accepted' if accepted else 'refused'} instead")

    # Zero is always representable, and every stop path writes it.
    t3 = U2722ATransport()
    smu3 = KeysightU2722A(t3)
    smu3.reset()
    smu3.set_source_function("current")
    smu3._apply_source_current_range(AUTO)
    smu3.set_current_level(0.0)
    check("zero is never refused - stop depends on it",
          abs(t3.current_level) < 1e-15, f"{t3.current_level}")

    # Negative levels are judged on magnitude, or the refusal protects
    # one polarity and not the other.
    t4 = U2722ATransport()
    smu4 = KeysightU2722A(t4)
    smu4.reset()
    smu4.set_source_function("current")
    smu4._apply_source_current_range(AUTO)
    negative_refused = False
    try:
        smu4.set_current_level(-1e-6)
    except RangeError:
        negative_refused = True
    check("a negative sub-count level is refused too", negative_refused,
          f"accepted {t4.current_level:.3e} A")


def test_a_sub_count_voltage_level_is_refused(check):
    """The same fault exists on the voltage axis.

    R20V has a 1.22 mV count, so at ten counts nothing under 12.2 mV is
    settable there. Nothing about the mechanism is specific to current,
    and a driver that guarded only the axis where the bench happened to
    find it would be guarding the anecdote.

    Note what the threshold costs on this axis: with R2V's count at
    122 uV, ten counts puts the instrument's absolute voltage floor at
    **1.22 mV**. A 1 mV level is refused outright, on every range.
    """
    t = U2722ATransport()
    smu = KeysightU2722A(t)
    smu.reset()
    smu.set_source_function("voltage")
    smu._apply_source_voltage_range(AUTO)          # -> R20V
    check("the plan put us on the widest voltage range",
          t.voltage_range == "R20V", t.voltage_range)

    raised = None
    try:
        smu.set_voltage_level(5e-3)
    except RangeError as exc:
        raised = exc
    check("5 mV on the 20 V range is refused", raised is not None,
          f"accepted; instrument holds {t.voltage_level:.3e} V")
    if raised is not None:
        check("and R2V is named as the range that would carry it",
              "R2V would carry it" in str(raised), str(raised)[:200])

    # On R2V the same 5 mV is fine: ten counts there is 1.22 mV.
    t2 = U2722ATransport()
    smu2 = KeysightU2722A(t2)
    smu2.reset()
    smu2.set_source_function("voltage")
    smu2._apply_source_voltage_range(1.0)          # -> R2V
    smu2.set_voltage_level(5e-3)
    check("the same level is accepted on R2V",
          abs(t2.voltage_level - 5e-3) < 1e-12, f"{t2.voltage_level:.3e}")

    # And the floor the threshold creates is stated, not implied: below
    # 1.22 mV there is no range at all, and the message must say so
    # rather than naming one that cannot help.
    t3 = U2722ATransport()
    smu3 = KeysightU2722A(t3)
    smu3.reset()
    smu3.set_source_function("voltage")
    smu3._apply_source_voltage_range(1.0)
    floor_raised = None
    try:
        smu3.set_voltage_level(1e-3)
    except RangeError as exc:
        floor_raised = exc
    check("1 mV is refused on every range", floor_raised is not None,
          f"accepted {t3.voltage_level:.3e} V")
    if floor_raised is not None:
        check("and the message does not name a range that cannot help",
              "no range on this instrument can carry it"
              in str(floor_raised), str(floor_raised)[:200])


def test_headroom_is_not_rewritten_every_point(check):
    """The per-point cost of the sourced axis, counted not timed.

    `set_current_level()` is the inner loop of a software sweep, and a
    limit write plus its readback is two round trips at roughly 13 ms.
    Doing that per point would cost more than the measurement. The
    largest level only grows and the range only widens, so a monotonic
    sweep should touch the limit a handful of times, not once a point.
    """
    t = U2722ATransport()
    smu = KeysightU2722A(t)
    smu.reset()
    smu.set_source_function("current")
    for n in range(40):
        smu.set_current_level(1e-4 + n * 1e-5)

    writes = [x for x in t.sent if x.startswith("SOUR:CURR:LIM ")]
    check("the limit is written far fewer times than there are points",
          len(writes) <= 8, f"{len(writes)} writes for 40 points")
    check("but it is written at least once", writes, "never set at all")
    check("and every level arrived intact",
          abs(t.current_level - (1e-4 + 39e-5)) < 1e-12,
          f"last level {t.current_level:.3e}")


def test_source_range_covers_the_sweep(check):
    t4 = U2722ATransport()
    smu4 = KeysightU2722A(t4)
    smu4.reset()
    smu4.set_source_function("voltage")
    # Compliance chosen to sit clear of the sweep: 5 V across 470 ohm draws
    # 10.6 mA, so a 10 mA limit would put the instrument into compliance and
    # clip the endpoints for a reason that has nothing to do with ranging.
    smu4.set_current_limit(0.1)
    smu4._apply_source_current_range(0.1)
    # The experiment never sets the swept quantity's range - it relies on
    # the source auto-ranging, which this model cannot do.
    check("the instrument is still on R2V before the sweep starts",
          t4.voltage_range == "R2V")

    # A sweep that STARTS inside the 2 V range and ends outside it. This is
    # the case that separates "the range was chosen for the whole sweep" from
    # "the range happened to get bumped when a level didn't fit": both end on
    # R20V, but only the first has one resolution throughout. A range change
    # partway through a dataset is the kind of discontinuity that gets blamed
    # on the sample.
    mark = len(t4.sent)
    run_software_sweep(smu4, "voltage", 0.0, 5.0, 11)
    during = t4.sent[mark:]
    first_range = next((i for i, x in enumerate(during)
                        if "SOUR:VOLT:RANG" in x), None)
    first_level = next((i for i, x in enumerate(during)
                        if x.startswith("SOUR:VOLT ")), None)
    check("the range is chosen before the first point, not mid-sweep",
          first_range is not None and first_level is not None
          and first_range < first_level,
          f"range at {first_range}, first level at {first_level}")
    check("and only once", sum(1 for x in during if "SOUR:VOLT:RANG" in x) == 1)

    sourced, measured = run_software_sweep(smu4, "voltage", -5.0, 5.0, 11)
    check("the driver ranged up to cover +/-5 V", t4.voltage_range == "R20V",
          f"left on {t4.voltage_range} - a sweep to 5 V would clip at 2 V")
    check("11 points returned", len(measured) == 11, f"got {len(measured)}")
    r = fit_resistance(sourced, measured, "voltage")
    check("recovers the resistor", abs(r - SAMPLE_OHM) / SAMPLE_OHM < 5e-4,
          f"{r:.4f} ohm vs {SAMPLE_OHM}")
    # The give-away that clipping happened: the endpoints pin at the range.
    check("the endpoints reached the requested levels",
          abs(abs(sourced[0]) - 5.0) < 1e-6 and abs(abs(sourced[-1]) - 5.0) < 1e-6,
          f"{sourced[0]:.3f} .. {sourced[-1]:.3f}")

    # a sweep that fits inside R2V should stay there rather than range up
    t5 = U2722ATransport()
    smu5 = KeysightU2722A(t5)
    smu5.reset()
    smu5.set_source_function("voltage")
    smu5.set_current_limit(1e-2)
    smu5._apply_source_current_range(1e-2)
    run_software_sweep(smu5, "voltage", -1.0, 1.0, 5)
    check("a +/-1 V sweep stays on the 2 V range for the resolution",
          t5.voltage_range == "R2V", t5.voltage_range)

    # ---------------------------------------------------------------
    # F. sourcing current
    # ---------------------------------------------------------------


def test_current_mode(check):
    t6 = U2722ATransport()
    smu6 = KeysightU2722A(t6)
    smu6.reset()
    smu6.set_source_function("current")
    smu6.set_voltage_limit(10.0)
    smu6._apply_source_voltage_range(10.0)
    smu6.set_current_level(5e-3)
    check("the driver ranged up to reach 5 mA", t6.current_range == "R10mA",
          f"left on {t6.current_range}, which would clip at its ceiling")
    check("the level was not clipped", abs(t6.current_level - 5e-3) < 1e-9,
          f"{t6.current_level:.3e}")

    # ---------------------------------------------------------------
    # G. no auto range, and it says so
    # ---------------------------------------------------------------


def test_auto_widens_instead_of_refusing(check):
    """This model has no autorange, so AUTO takes the widest range.

    Wave 6d-ii. The first version of the ranging contract refused AUTO
    here. That broke callers which are model-agnostic by design - the
    checkup asks every instrument for an all-AUTO plan - and it
    contradicted decision W6d-2's own reasoning: the widest range never
    clamps a level and never overranges a reading, so it is the one
    reading of "let the instrument choose" that cannot produce a wrong
    number. It costs resolution, which is a worse measurement rather
    than a false one.

    Accepting AUTO and doing *nothing* would still be wrong - that
    leaves the range wherever it was, most likely R1uA, and clamps
    almost everything. Hence the check that a range command is actually
    sent, and that it is the widest one.
    """
    t7 = U2722ATransport()
    smu7 = KeysightU2722A(t7)

    for name, call, tokens in (
            ("current", smu7._apply_source_current_range,
             KeysightU2722A.CURRENT_RANGE_TOKENS),
            ("voltage", smu7._apply_source_voltage_range,
             KeysightU2722A.VOLTAGE_RANGE_TOKENS)):
        before_len = len(t7.sent)
        call(AUTO)
        new_writes = t7.sent[before_len:]
        widest = max(tokens)[1]
        check(f"AUTO sends a {name} range rather than doing nothing",
              bool(new_writes), "nothing was sent")
        check(f"and it is the widest {name} range ({widest})",
              any(widest in w for w in new_writes), f"{new_writes}")

    # ---------------------------------------------------------------
    # H. NPLC is a whole number of cycles
    # ---------------------------------------------------------------


def test_nplc(check):
    check("declares NPLC support", KeysightU2722A.supports_nplc())
    check("the floor is 1, not 0", KeysightU2722A.NPLC_RANGE[0] == 1,
          "0 would let the menu offer 0.01 and 0.1, which round to no "
          "integration at all")
    check("the ceiling is 255", KeysightU2722A.NPLC_RANGE[1] == 255)
    check("2.6 rounds to a whole number", KeysightU2722A.clamp_nplc(2.6) == 3)
    check("clamps above the range", KeysightU2722A.clamp_nplc(1000) == 255)
    check("clamps below the range", KeysightU2722A.clamp_nplc(0.01) == 1)
    check("and returns an int, not a float",
          isinstance(KeysightU2722A.clamp_nplc(2.6), int))

    t8 = U2722ATransport()
    smu8 = KeysightU2722A(t8)
    smu8.set_nplc(10)
    sent8 = " | ".join(t8.sent)
    check("sets NPLC on both functions",
          "SENS:CURR:NPLC 10" in sent8 and "SENS:VOLT:NPLC 10" in sent8)
    check("sends a bare integer, no decimal point",
          "SENS:CURR:NPLC 10.0" not in sent8)
    # 10 PLC at 50 Hz is a 0.2 s window, and there are two readings per
    # point because there is no combined read.
    check("the aperture is tracked without asking the instrument",
          abs(smu8._aperture_s - 0.2) < 1e-9, f"{smu8._aperture_s}")
    check("no APER? query was needed",
          not any("APER" in s for s in t8.sent))

    # ---------------------------------------------------------------
    # I. sensing is a wiring decision
    # ---------------------------------------------------------------


def test_sensing_is_wiring(check):
    check("declares that software cannot select sensing",
          not KeysightU2722A.supports_remote_sense_control())
    check("and says what the wiring is",
          KeysightU2722A.fixed_sense() == "4-wire (hardwired)")
    check("the other drivers still declare a real control",
          Keithley2450.supports_remote_sense_control()
          and GWInstekGSM20H10.supports_remote_sense_control())

    t9 = U2722ATransport()
    smu9 = KeysightU2722A(t9)
    smu9.set_remote_sense(True)       # matches the wiring: accepted
    check("asking for 4-wire is accepted", True)
    check("and sends nothing, because no such command exists",
          not any("RSEN" in s.upper() for s in t9.sent))

    raised = False
    try:
        smu9.set_remote_sense(False)
    except NotImplementedError:
        raised = True
    check("asking for 2-wire is refused rather than silently ignored", raised,
          "a no-op would write '2-wire' into a CSV describing a 4-wire "
          "measurement")

    check("the CSV records the wiring, not the checkbox",
          apply_remote_sense(smu9, True) == "4-wire (hardwired)")
    # On an instrument that can switch, the same helper reports the choice.
    check("and reports the real choice on an instrument that can switch",
          apply_remote_sense(Keithley2450(U2722ATransport()), False) == "2-wire")

    # ---------------------------------------------------------------
    # J. a rejected setup stops the run instead of producing data
    # ---------------------------------------------------------------


def test_rejected_setup_raises(check):
    t10 = U2722ATransport()
    smu10 = KeysightU2722A(t10)
    smu10.reset()
    smu10.set_source_function("voltage")
    smu10.set_current_limit(1e-3)
    smu10._apply_source_current_range(1e-3)
    # Something the instrument did not like, queued between configure and
    # sweep - a clamped compliance looks exactly like this.
    t10.errors.append((-222, "Data out of range"))
    raised = False
    try:
        smu10.start_linear_sweep("voltage", -1.0, 1.0, 5, 0.0)
    except RuntimeError as exc:
        raised = "out of range" in str(exc).lower()
    check("the sweep refuses to start on a queued error", raised,
          "silently sweeping on would produce a plausible wrong dataset")

    # a clean queue sweeps normally
    t11 = U2722ATransport()
    smu11 = KeysightU2722A(t11)
    smu11.reset()
    smu11.set_source_function("voltage")
    smu11.set_current_limit(1e-3)
    smu11._apply_source_current_range(1e-3)
    _, measured11 = run_software_sweep(smu11, "voltage", -1.0, 1.0, 5)
    check("and a clean setup sweeps normally", len(measured11) == 5,
          f"got {len(measured11)}")

    # ---------------------------------------------------------------
    # K. measurement
    # ---------------------------------------------------------------


def test_measurement(check):
    t12 = U2722ATransport()
    smu12 = KeysightU2722A(t12)
    smu12.reset()
    smu12.set_source_function("voltage")
    smu12.set_current_limit(1e-2)
    smu12._apply_source_current_range(1e-2)
    smu12.set_voltage_level(1.0)
    volts, amps = smu12.measure()
    sent12 = " | ".join(t12.sent)
    check("reads voltage and current separately",
          "MEAS:VOLT? (@1)" in sent12 and "MEAS:CURR? (@1)" in sent12,
          "there is no combined read on this model")
    check("the reading parses", volts is not None and amps is not None,
          f"{volts}, {amps}")
    check("and obeys Ohm's law", abs(amps - 1.0 / SAMPLE_OHM) < 1e-9,
          f"{amps:.6e}")

    # ---------------------------------------------------------------
    # L. capability declarations match the hardware
    # ---------------------------------------------------------------


def test_capabilities(check):
    check("no overvoltage protection", not KeysightU2722A.supports_ovp())
    check("no high-Z output off", not KeysightU2722A.supports_high_z_off())
    check("software sweep", KeysightU2722A.sweep_kind() == "software")
    check("cannot report compliance trips",
          KeysightU2722A(U2722ATransport()).compliance_tripped() is None,
          "the Questionable register's only bit is over-temperature")

    limits = KeysightU2722A.LIMITS
    from core.limits import LimitError
    refused = False
    try:
        limits.validate_source_point(voltage=25.0)
    except LimitError:
        refused = True
    check("25 V is refused", refused)
    refused = False
    try:
        limits.validate_source_point(current=0.2)
    except LimitError:
        refused = True
    check("200 mA is refused", refused)
    ok = True
    try:
        limits.validate_source_point(voltage=20.0, current=0.12)
    except LimitError:
        ok = False
    check("20 V at 120 mA is allowed - flat maxima, no power corner", ok)

    # ---------------------------------------------------------------
    # M. the connect-time note
    # ---------------------------------------------------------------


def test_sweep_note(check):
    t13 = U2722ATransport()
    smu13 = KeysightU2722A(t13)
    smu13.set_nplc(10)
    note = smu13.sweep_note().lower()
    check("mentions the point-by-point sweep", "point by point" in note)
    check("warns about the auto delay that cannot be disabled",
          "auto delay" in note and "cannot be disabled" in note)
    check("and about the cost of two readings per point", "two readings" in note)

    # ---------------------------------------------------------------
    # N. end to end through the real experiment
    # ---------------------------------------------------------------
    #
    # Everything above tests the driver in isolation. This section drives
    # IVSweepExperiment itself over the fake instrument, because the
    # sensing capability is the one part of this port that touches shared
    # code - the panel, the refresh, and the CSV column - and a unit test on
    # the driver cannot see any of that.


def test_end_to_end_through_the_experiment(check):
    import tkinter as tk

    import core.base_app as base_app
    import experiments.base_experiment as base_experiment
    import experiments.iv_sweep.experiment as iv_experiment
    from core.base_app import LabApp
    from experiments.iv_sweep.experiment import IVSweepExperiment


    class DialogStub:
        """Modal dialogs block a headless test forever. Three modules import
    messagebox independently and all three have to be stubbed - see the
    note in test_iv_demo.py."""

        def __init__(self):
            self.seen = []

        def _record(self, *args, **kw):
            self.seen.append(args)
            return True

        showinfo = showwarning = showerror = _record

        def askokcancel(self, *a, **kw):
            self.seen.append(a)
            return True

        def askyesno(self, *a, **kw):
            self.seen.append(a)
            return False

        def askyesnocancel(self, *a, **kw):
            # Wave 5c-ii save-collision pre-flight: True lets the run go.
            self.seen.append(a)
            return True


    dialogs = DialogStub()
    iv_experiment.messagebox = dialogs
    base_experiment.messagebox = dialogs
    base_app.messagebox = dialogs
    iv_experiment.PRE_SWEEP_SETTLE_S = 0.01

    root = tk.Tk()
    app = LabApp(root, IVSweepExperiment)
    exp = app.experiment
    # The real connect path: transport, *IDN?, registry, reset(), and
    # on_connected() - so the panel refresh under test is the live one.
    app.connect_role("source", U2722ATransport(), "USB0::fake")
    # app.log() posts through root.after(), so console lines only appear
    # once the event queue is drained - update_idletasks() alone is not
    # enough and the console assertions below would read an empty widget.
    for _ in range(20):
        root.update()

    check("auto-detected as the U2722A",
          isinstance(app.instruments["source"], KeysightU2722A))
    check("the sensing checkbox is greyed out",
          str(exp.remote_sense_check.cget("state")) == "disabled",
          f"state is {exp.remote_sense_check.cget('state')}")
    check("and pinned to the wiring, not left at a default",
          exp.remote_sense_var.get() is True)
    check("the console says why",
          "wiring" in app.console.get("1.0", "end").lower())
    check("the NPLC control is offered, since this model has one",
          str(exp.nplc_combo.cget("state")) != "disabled")
    check("the 0.01 and 0.1 presets are gone - they round to no integration",
          all(float(v) >= 1 for v in exp.nplc_combo["values"]),
          f"{list(exp.nplc_combo['values'])}")
    check("the high-Z checkbox is greyed out",
          str(exp.high_z_check.cget("state")) == "disabled")
    check("the OVP dropdown is greyed out",
          str(exp.ovp_combo.cget("state")) == "disabled")

    exp.mode_var.set("voltage")
    exp.on_mode_changed()
    exp.start_var.set("-1")
    exp.stop_var.set("1")
    exp.points_var.set("11")
    exp.delay_var.set("0")
    exp.compliance_var.set("0.01")
    exp.dataset_var.set("u2722a")
    exp.nplc_var.set("2.6")

    params = exp._sweep_params()
    exp._check_limits(params)
    try:
        exp._do_single(params)
    finally:
        for _ in range(60):
            root.update()

    rows = exp.tree.get_children()
    check("the sweep produced a row", len(rows) == 1, f"{len(rows)} rows")
    if rows:
        # Keyed on the Treeview item id, which is the whole point of the
        # store - the row and its raw data cannot drift apart.
        run = exp.run_store._runs[rows[0]]
        check("the CSV records the wiring, not the checkbox",
              run.metadata["sensing"] == "4-wire (hardwired)",
              f"recorded {run.metadata['sensing']!r}")
        check("NPLC was rounded to a whole number in the file",
              run.metadata["nplc"] == 3, f"recorded {run.metadata['nplc']!r}")
        check("the run is marked as a software sweep",
              run.metadata["sweep_kind"] == "software")
        resistance = run.metadata["resistance_ohm"]
        check("and the fit recovers the resistor",
              abs(resistance - SAMPLE_OHM) / SAMPLE_OHM < 5e-4,
              f"{resistance:.4f} ohm vs {SAMPLE_OHM}")

    for _ in range(20):
        root.update()
    app.on_close()
    try:
        root.destroy()
    except Exception:
        pass
