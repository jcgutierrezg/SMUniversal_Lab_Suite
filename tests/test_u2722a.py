import pytest

from core.ranges import AUTO

pytestmark = [pytest.mark.gui]

import sys, os

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

from core.transports.base import Transport
from drivers.registry import driver_for_idn
from core.gui.widgets import apply_remote_sense
from drivers.keysight_u2722a import KeysightU2722A
from drivers.keithley_2450 import Keithley2450
from drivers.gwinstek_gsm20h10 import GWInstekGSM20H10

SAMPLE_OHM = 470.0

CURRENT_CEILING = {"R1uA": 1e-6, "R10uA": 1e-5, "R100uA": 1e-4,
                   "R1mA": 1e-3, "R10mA": 1e-2, "R120mA": 0.12}
VOLTAGE_CEILING = {"R2V": 2.0, "R20V": 20.0}


class U2722ATransport(Transport):
    """A fake U2722A with a resistor across channel 1.

    Models the two behaviours that make this instrument dangerous:
    a current limit clamped to the active current range, and a source
    voltage clamped to the active voltage range. Both are silent, as
    they are on the real thing.
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

        if upper.startswith("SOUR:CURR:RANG"):
            self.current_range = body.split()[-1]
            # Changing range re-clamps the limit that is already set.
            self.current_limit = min(self.current_limit,
                                     CURRENT_CEILING[self.current_range])
        elif upper.startswith("SOUR:VOLT:RANG"):
            self.voltage_range = body.split()[-1]
            self.voltage_limit = min(self.voltage_limit,
                                     VOLTAGE_CEILING[self.voltage_range])
        elif upper.startswith("SOUR:CURR:LIM"):
            asked = float(body.split()[-1])
            self.current_limit = min(abs(asked),
                                     CURRENT_CEILING[self.current_range])
        elif upper.startswith("SOUR:VOLT:LIM"):
            asked = float(body.split()[-1])
            self.voltage_limit = min(abs(asked),
                                     VOLTAGE_CEILING[self.voltage_range])
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


def test_compliance_survives_a_range_change(check):
    # This is the experiment's own order: limit first, then range. On this
    # instrument that clamps the limit to the range in force at the time,
    # which after *RST is R1uA.
    t2 = U2722ATransport()
    smu2 = KeysightU2722A(t2)
    smu2.reset()
    smu2.set_source_function("voltage")
    smu2.set_current_limit(1e-2)      # asked for 10 mA while still on R1uA
    smu2._apply_source_current_range(1e-2)      # now range up
    check("the range ended up where it was asked",
          t2.current_range == "R10mA", t2.current_range)
    check("and the compliance is the value that was requested",
          abs(t2.current_limit - 1e-2) < 1e-12,
          f"instrument holds {t2.current_limit:.3e} A - a driver that does "
          f"not re-send the limit leaves it clamped at 1e-06")
    # The limit no longer needs sending twice in this order - the range is
    # widened before the first send - but the re-send after a range change
    # still has to exist for the case where the range moves afterwards.
    check("no error was logged getting there", not t2.errors, f"{t2.errors}")

    t2d = U2722ATransport()
    smu2d = KeysightU2722A(t2d)
    smu2d.reset()
    smu2d.set_source_function("voltage")
    smu2d._apply_source_current_range(1e-2)     # range first this time
    smu2d.set_current_limit(1e-3)     # a limit that fits it
    smu2d._apply_source_current_range(0.12)     # then widen the range again
    check("a limit survives a range change made after it was set",
          abs(t2d.current_limit - 1e-3) < 1e-12,
          f"{t2d.current_limit:.3e} - the re-send after a range change is "
          f"still load-bearing")

    # and the same for the voltage side, sourcing current
    t3 = U2722ATransport()
    smu3 = KeysightU2722A(t3)
    smu3.reset()
    smu3.set_source_function("current")
    smu3.set_voltage_limit(10.0)      # asked for 10 V while still on R2V
    smu3._apply_source_voltage_range(10.0)
    check("voltage compliance survives its range change too",
          abs(t3.voltage_limit - 10.0) < 1e-9, f"{t3.voltage_limit}")

    # ---------------------------------------------------------------
    # D2. the limit must be accepted FIRST TIME, not just eventually
    # ---------------------------------------------------------------


def test_limit_is_accepted_without_an_error(check):
    # Found on the bench. Re-sending the limit after a range change leaves
    # the end state right but logs -222, "Data out of range", on the way -
    # and start_linear_sweep() reads that queue and refuses to sweep. So
    # every sweep aborted with a message about a rejected setup, having
    # been configured perfectly correctly.
    t2b = U2722ATransport()
    smu2b = KeysightU2722A(t2b)
    smu2b.reset()
    smu2b.set_source_function("voltage")
    smu2b.set_current_limit(1e-2)      # asked for 10 mA while still on R1uA
    check("the range is widened before the limit is sent",
          t2b.sent.index("SOUR:CURR:RANG R10mA, (@1)")
          < t2b.sent.index("SOUR:CURR:LIM 1.000000e-02, (@1)"),
          f"{[x for x in t2b.sent if 'CURR' in x]}")
    check("so the instrument logs no error at all", not t2b.errors,
          f"{t2b.errors}")
    check("and the compliance is what was asked for",
          abs(t2b.current_limit - 1e-2) < 1e-12, f"{t2b.current_limit:.3e}")

    # The sweep guard must therefore find a clean queue and run.
    smu2b._apply_source_current_range(1e-2)
    sourced2b, measured2b = run_software_sweep(smu2b, "voltage", -1.0, 1.0, 5)
    check("the sweep starts instead of aborting on a queued error",
          len(measured2b) == 5, f"got {len(measured2b)}")

    # same on the voltage side
    t2c = U2722ATransport()
    smu2c = KeysightU2722A(t2c)
    smu2c.reset()
    smu2c.set_source_function("current")
    smu2c.set_voltage_limit(10.0)      # 10 V while still on R2V
    check("the voltage range is widened before its limit too",
          t2c.sent.index("SOUR:VOLT:RANG R20V, (@1)")
          < t2c.sent.index("SOUR:VOLT:LIM 1.000000e+01, (@1)"))
    check("with no error logged", not t2c.errors, f"{t2c.errors}")
    check("and the limit intact", abs(t2c.voltage_limit - 10.0) < 1e-9)

    # ---------------------------------------------------------------
    # E. TRAP 2 - the source range has to cover the sweep
    # ---------------------------------------------------------------


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

    from core.base_app import LabApp
    from experiments.iv_sweep.experiment import IVSweepExperiment
    import experiments.iv_sweep.experiment as iv_experiment
    import experiments.base_experiment as base_experiment
    import core.base_app as base_app


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
