
"""The Keithley 2401 driver.

The 2401 is the same instrument family as the 2450 but an older
generation, and the SCPI spelling differs in ways that do not announce
themselves: send a 2450 compliance command to a 2401 and the instrument
logs an error, ignores it, and carries on with whatever compliance it
had. Nothing raises. The sweep completes. The numbers are wrong.

So the thing worth testing is not "does it emit SCPI" but "does it emit
the *2400-series* SCPI, and never the 2450's". That is what this file
checks, along with the sweep it inherits from BaseSMU.
"""
import time

from core.ranges import AUTO
from core.transports.base import Transport
from drivers.base_smu import BaseSMU
from drivers.keithley_2401 import Keithley2401
from drivers.keithley_2450 import Keithley2450
from drivers.registry import driver_for_idn

SAMPLE_OHM = 470.0


class Fake2401(Transport):
    """A 2401 holding a plain resistor.

    Tracks the sourced level from the SCPI it receives so the test can
    assert on what was actually asked for, and answers :READ? with the
    five-field group a real 2400 returns.
    """

    #: Settings this instrument holds and can be asked about, mapped
    #: from the command that writes one to the query that reads it.
    #:
    #: Holding them is what makes the readback tests discriminating. A
    #: fake that answered every settings query with a constant would
    #: pass a correct driver and a driver that sent the wrong header
    #: equally well, which is fault 19 - so the value that comes back is
    #: the value that was written, and a driver asking the wrong
    #: question gets nothing.
    SETTINGS = (":SENS:CURR:PROT", ":SENS:VOLT:PROT",
                ":SOUR:CURR:RANG", ":SOUR:VOLT:RANG",
                ":SENS:CURR:RANG", ":SENS:VOLT:RANG")

    def __init__(self):
        super().__init__()
        self.sent = []
        self.connected = True
        self.level = 0.0
        self.mode = "voltage"
        self.settings = {}
        # Which protection is tripped, per sourced quantity. Nothing is
        # clamping by default; a test that wants a trip sets it.
        self.tripped = {"CURR": False, "VOLT": False}

    def connect(self, address, **kw):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        self.sent.append(text)
        upper = text.upper()
        if ":SOUR:FUNC" in upper and "?" not in upper:
            self.mode = "current" if "CURR" in upper else "voltage"
        if ":SOUR:VOLT:LEV" in upper or ":SOUR:CURR:LEV" in upper:
            try:
                self.level = float(text.split()[-1])
            except ValueError:
                pass
        if "?" not in text:
            head = text.split()[0] if text.split() else ""
            if head in self.SETTINGS:
                try:
                    self.settings[head] = float(text.split()[-1])
                except ValueError:
                    pass

    def _read(self, timeout_s):
        last = self.sent[-1] if self.sent else ""
        upper = last.upper()
        if "IDN" in upper:
            return "KEITHLEY INSTRUMENTS INC.,MODEL 2401,4102345,C30"
        if upper.startswith(":SOUR:FUNC?"):
            return "CURR" if self.mode == "current" else "VOLT"
        if ":PROT:TRIP?" in upper:
            axis = "CURR" if ":SENS:CURR" in upper else "VOLT"
            return "1" if self.tripped[axis] else "0"
        if last.endswith("?") and last[:-1] in self.SETTINGS:
            held = self.settings.get(last[:-1])
            # Unset settings answer nothing, so a driver reading a
            # setting nobody wrote gets `unreadable` rather than a
            # plausible number.
            return "" if held is None else f"{held:.6E}"
        if self.mode == "voltage":
            volts, amps = self.level, self.level / SAMPLE_OHM
        else:
            amps, volts = self.level, self.level * SAMPLE_OHM
        # voltage, current, resistance, timestamp, status
        return (f"{volts:.6E},{amps:.6E},{SAMPLE_OHM:.6E},"
                f"{time.time():.3f},0")


# ---------------------------------------------------------------
# A. the registry finds it
# ---------------------------------------------------------------


def test_identification(check):
    resolved = driver_for_idn("KEITHLEY INSTRUMENTS INC.,MODEL 2401,4102345,C30")
    check("2401 IDN resolves to the 2401 driver", resolved is Keithley2401,
          resolved.DISPLAY_NAME if resolved else "None")

    # A serial number containing '2401' must not hijack another model. The
    # registry prefers the longest matching ID, which is what protects this.
    hijack = driver_for_idn("KEITHLEY INSTRUMENTS INC.,MODEL 2611A,124019,3.2.1")
    check("a serial containing 2401 doesn't hijack a 2611A",
          hijack is not Keithley2401,
          hijack.DISPLAY_NAME if hijack else "None")

    # ---------------------------------------------------------------
    # B. the dialect is the 2400 one, not the 2450 one
    # ---------------------------------------------------------------


def test_dialect_is_2400_series(check):
    t = Fake2401()
    smu = Keithley2401(t)

    smu.set_source_function("voltage")
    smu.set_current_limit(1e-3)
    smu._apply_measure_current_range(1e-3)
    smu.set_remote_sense(True)
    sent = " | ".join(t.sent)

    check("compliance uses :SENS:CURR:PROT", ":SENS:CURR:PROT" in sent)
    check("compliance does NOT use the 2450's :SOUR:VOLT:ILIM",
          "ILIM" not in sent.upper())
    check("sense function is set alongside source", ':SENS:FUNC "CURR"' in sent)
    check("auto-clear is disabled", ":SOUR:CLE:AUTO 0" in sent)
    check("remote sense uses numeric 1", ":SYST:RSEN 1" in sent)

    # The distinctness claim, stated directly: drive both models through the
    # same call and confirm the bytes differ.
    t2450 = Fake2401()
    Keithley2450(t2450).set_voltage_limit(2.0)
    t2401 = Fake2401()
    Keithley2401(t2401).set_voltage_limit(2.0)
    check("2450 and 2401 emit different compliance commands",
          t2450.sent != t2401.sent,
          f"{t2450.sent[0].split()[0]} vs {t2401.sent[0].split()[0]}")

    # ---------------------------------------------------------------
    # C. configure() puts it in a safe known state
    # ---------------------------------------------------------------


def test_reset(check):
    t = Fake2401()
    Keithley2401(t).reset()
    sent = " | ".join(t.sent)
    check("resets", "*RST" in sent)
    # configure() used to pin :OUTP:SMOD HIMP. It is now a per-run choice
    # from the panel, defaulting to NORMal - the relay has a finite number
    # of operations in it and a periodic run cycles the output hundreds of
    # times. Asserting its ABSENCE here so the old behaviour can't creep
    # back in unnoticed.
    check("output-off mode is NOT pinned at configure",
          ":OUTP:SMOD" not in sent,
          "it is a per-run panel choice now")
    check("but the control exists and both ways work",
          Keithley2401.supports_high_z_off())
    t_off = Fake2401()
    d_off = Keithley2401(t_off)
    d_off.set_output_off_mode(False)
    d_off.set_output_off_mode(True)
    check("NORMal and HIMPedance both reachable",
          any(":OUTP:SMOD NORM" in x for x in t_off.sent)
          and any(":OUTP:SMOD HIMP" in x for x in t_off.sent))
    check("4-wire by default", ":SYST:RSEN 1" in sent)

    # ---------------------------------------------------------------
    # D. it sweeps, via the inherited software fallback
    # ---------------------------------------------------------------


def test_inherited_software_sweep(check):
    check("declares software sweep", Keithley2401.sweep_kind() == "software")
    check("does not define its own sweep",
          Keithley2401.start_linear_sweep is BaseSMU.start_linear_sweep,
          "inherits BaseSMU's")

    t = Fake2401()
    smu = Keithley2401(t)
    smu.set_source_function("voltage")
    smu.start_linear_sweep("voltage", -1.0, 1.0, 21, 0.0)

    deadline = time.monotonic() + 20
    while smu.sweep_points_ready() < 21 and time.monotonic() < deadline:
        time.sleep(0.01)
    sourced, measured = smu.read_sweep(21)

    check("all points returned", len(measured) == 21, f"{len(measured)}/21")
    if len(measured) == 21:
        recovered = (sourced[-1] - sourced[0]) / (measured[-1] - measured[0])
        error = abs(recovered - SAMPLE_OHM) / SAMPLE_OHM
        check("recovers the sample resistance", error < 1e-5,
              f"{recovered:.4f} Ω vs {SAMPLE_OHM:g} Ω")

    # ---------------------------------------------------------------
    # E. the rounding bug is not reproduced
    # ---------------------------------------------------------------


def test_low_bias_sweep_not_quantised(check):
    # The original sent round(Vo + i*step, 4), quantising the source to
    # 100 µV. Over ±1 V that is invisible. Over ±100 µV it collapses 21
    # requested levels into 3 duplicates, while the saved x-axis still
    # claims 21 evenly spaced points - so the damage is undetectable after
    # the fact. This is the regression guard for that.
    t = Fake2401()
    smu = Keithley2401(t)
    smu.set_source_function("voltage")
    smu.start_linear_sweep("voltage", -1e-4, 1e-4, 21, 0.0)

    deadline = time.monotonic() + 20
    while smu.sweep_points_ready() < 21 and time.monotonic() < deadline:
        time.sleep(0.01)
    sourced, _ = smu.read_sweep(21)

    distinct = len({round(v, 12) for v in sourced})
    check("21 distinct levels at ±100 µV", distinct == 21, f"{distinct}/21")

    quantised = len({round(round(-1e-4 + i * (2e-4 / 20), 4), 12)
                     for i in range(21)})
    check("the original's rounding would have given far fewer",
          quantised < 21, f"round(...,4) yields {quantised}/21")

    # ---------------------------------------------------------------
    # F. reading format
    # ---------------------------------------------------------------


def test_reading_parse(check):
    volts, amps = Keithley2401._parse_reading(
        "1.234000E-01,1.000000E-04,1.234000E+03,1234.5,0")
    check("takes voltage and current from a 5-field group",
          volts == 0.1234 and amps == 1e-4, f"V={volts} I={amps}")
    check("empty reply is handled",
          Keithley2401._parse_reading("") == (None, None))

    # ---------------------------------------------------------------
    # G. reading state back (2026-09-04)
    # ---------------------------------------------------------------
    #
    # Until this round the checkup said "Keithley 2401 does not report
    # its compliance - a collapse here would be invisible" and "has no
    # confirmed query for this range". Both were statements about the
    # driver rather than about the instrument: every header below is the
    # query form of a header this driver already writes.


def test_compliance_and_ranges_read_back(check):
    t = Fake2401()
    smu = Keithley2401(t)

    smu.set_current_limit(1e-3)
    smu.set_voltage_limit(2.0)
    smu._apply_source_current_range(1e-4)
    smu._apply_source_voltage_range(0.2)
    smu._apply_measure_current_range(1e-3)
    smu._apply_measure_voltage_range(2.0)

    # The values come back, and they come back as what was written -
    # which a fake answering a constant could not demonstrate.
    check("current compliance reads back", smu.read_current_limit() == 1e-3,
          f"{smu.read_current_limit()}")
    check("voltage compliance reads back", smu.read_voltage_limit() == 2.0,
          f"{smu.read_voltage_limit()}")
    check("source current range reads back",
          smu.read_source_current_range() == 1e-4,
          f"{smu.read_source_current_range()}")
    check("source voltage range reads back",
          smu.read_source_voltage_range() == 0.2,
          f"{smu.read_source_voltage_range()}")
    check("measure current range reads back",
          smu.read_measure_current_range() == 1e-3,
          f"{smu.read_measure_current_range()}")
    check("measure voltage range reads back",
          smu.read_measure_voltage_range() == 2.0,
          f"{smu.read_measure_voltage_range()}")

    asked = [s for s in t.sent if s.endswith("?")]
    check("the queries are 2400-series spellings, not the 2450's",
          all("VLIM" not in s.upper() and "ILIM" not in s.upper()
              for s in asked), f"{asked}")

    # The control leg. A driver answering from a local copy instead of
    # asking would pass everything above; this is what tells them apart.
    # The instrument's held value is changed behind the driver's back,
    # exactly as a front-panel turn or a silent range collapse would,
    # and the readback has to follow the instrument.
    t.settings[":SENS:CURR:PROT"] = 1e-9
    check("the readback follows the instrument, not a remembered value",
          smu.read_current_limit() == 1e-9,
          f"{smu.read_current_limit()} - a local copy would say 0.001")

    # And a setting nobody wrote is not a number. `None` renders as
    # `unreadable`, a warn; a 0.0 here would be compared against as
    # though it had been reported.
    check("an unanswered settings query is None, not a plausible number",
          Keithley2401(Fake2401()).read_current_limit() is None)


def test_the_readback_is_not_claimed_to_be_verified(check):
    """Implemented, and deliberately still `unverified`.

    Moving an axis from `unsupported` to `unverified` is the whole
    change: the first is "nobody can ask", the second is "it answered
    and agreed, and nothing has checked the answer against a state this
    instrument was known to be in". Only a bench session promotes it,
    and setting the flag without one is precisely the failure the
    five-state contract exists to prevent.
    """
    check("compliance readback is not trusted",
          Keithley2401.COMPLIANCE_READBACK_TRUSTED is False)
    check("range readback is not trusted",
          Keithley2401.RANGE_READBACK_TRUSTED is False)

    smu = Keithley2401(Fake2401())
    smu.set_current_limit(1e-3)
    answer = smu.verify_compliance("voltage", 1e-3)
    check("an agreeing readback reports unverified, not confirmed",
          answer.state == "unverified", f"{answer.state}: {answer.detail}")
    check("and renders as a warn, never a pass", answer.severity == "warn",
          answer.severity)

    # Disagreement is not downgraded by doubt - see core/readback.py.
    t = Fake2401()
    loud = Keithley2401(t)
    loud.set_current_limit(1e-3)
    t.settings[":SENS:CURR:PROT"] = 1.2e-2
    answer = loud.verify_compliance("voltage", 1e-3)
    check("a disagreeing readback is a mismatch even though untrusted",
          answer.state == "mismatched", f"{answer.state}: {answer.detail}")


def test_compliance_trip_is_asked_of_the_right_axis(check):
    """The limit is always on the quantity NOT being sourced.

    Asking the other one gets an honest answer to the wrong question -
    which is how the B2901A returned False on a 1 V limit riding into an
    open circuit, on every experiment that sources current.
    """
    t = Fake2401()
    smu = Keithley2401(t)

    smu.set_source_function("voltage")
    t.tripped["CURR"] = True
    check("sourcing voltage, the CURRENT protection is the one asked",
          smu.compliance_tripped() is True)
    check("and that is the query that went out",
          any(":SENS:CURR:PROT:TRIP?" in s for s in t.sent), f"{t.sent}")

    # The control leg: same driver, same instrument, the other flag set.
    # A method that ORed both axes, or asked one unconditionally, would
    # not tell these two apart.
    t2 = Fake2401()
    smu2 = Keithley2401(t2)
    smu2.set_source_function("voltage")
    t2.tripped["VOLT"] = True
    check("the I-Source flag does not report a V-Source clamp",
          smu2.compliance_tripped() is False,
          "sourcing voltage, SENS:VOLT:PROT:TRIP? is about the source "
          "that is not running")

    t3 = Fake2401()
    smu3 = Keithley2401(t3)
    smu3.set_source_function("current")
    t3.tripped["VOLT"] = True
    check("sourcing current, the VOLTAGE protection is the one asked",
          smu3.compliance_tripped() is True)


def test_a_sub_count_current_level_is_refused(check):
    """MEASURED 2026-09-01, and declared as counts rather than amps.

    `tools/bench_envelope.py` pinned the source current range to 1e-4 A
    and halved the commanded level until the two legs of a +/- pair
    stopped landing on opposite sides of zero. That happened below
    3.052e-09 A, and 1e-4 / 32768 is 3.0518e-09 - one count of the range
    the sweep was on.

    Both sides of the boundary are exercised. A guard tested only from
    below would pass against a driver that refuses everything.
    """
    from core.ranges import RangeError, RangePlan

    check("the declared count reproduces the measured floor",
          abs(1e-4 / Keithley2401.SOURCE_COUNTS_PER_RANGE["current"]
              - 3.0518e-9) < 1e-13)

    t = Fake2401()
    smu = Keithley2401(t)
    smu.apply_ranges(RangePlan.for_sourcing(
        "current", source_range=1e-4, measure_range=2.0))
    smu.set_source_function("current")

    floor = smu.source_level_floor("current")
    expected = 1e-4 / 32768 * Keithley2401.MIN_LEVEL_COUNTS
    check("the floor is MIN_LEVEL_COUNTS counts of the ACTIVE range",
          floor is not None and abs(floor - expected) < 1e-15,
          f"{floor} vs {expected}")

    before = len(t.sent)
    try:
        smu.set_current_level(floor / 10.0)
        check("a tenth of the floor is refused", False,
              "it was accepted and written")
    except RangeError as exc:
        check("a tenth of the floor is refused", True)
        check("and nothing was written before the refusal",
              len(t.sent) == before, f"{t.sent[before:]}")
        check("the message names the range, not just the level",
              "0.0001" in str(exc), str(exc))

    # The other side. At the floor the level goes out, so this is a
    # floor and not a blanket refusal.
    smu.set_current_level(floor)
    check("the floor itself is accepted",
          any(":SOUR:CURR:LEV" in s for s in t.sent[before:]),
          f"{t.sent[before:]}")

    # Zero is always allowed: "off" is exactly representable and is what
    # every settle-to-zero path writes.
    smu.set_current_level(0.0)
    check("zero is never refused",
          any(s.startswith(":SOUR:CURR:LEV 0") for s in t.sent))


def test_the_floor_moves_with_the_range(check):
    """The whole reason the declaration is counts and not amps.

    This model's neighbour on the bench, the B2901A, had its floor
    measured on two different ranges a week apart and the two figures
    are four orders of magnitude apart. A driver holding one absolute
    number would be wrong on every range but the one it was measured on.
    """
    from core.ranges import RangePlan

    floors = {}
    for source_range in (1e-6, 1e-4, 1e-2):
        smu = Keithley2401(Fake2401())
        smu.apply_ranges(RangePlan.for_sourcing(
            "current", source_range=source_range, measure_range=2.0))
        floors[source_range] = smu.source_level_floor("current")

    check("a wider range has a higher floor",
          floors[1e-6] < floors[1e-4] < floors[1e-2], f"{floors}")
    check("and it scales with the range exactly",
          abs(floors[1e-2] / floors[1e-6] - 1e4) < 1e-6, f"{floors}")

    # Under autoranging the driver does not know which range is in
    # force, so it falls back to the bound that holds on every range:
    # counts of the narrowest source range this model has.
    auto = Keithley2401(Fake2401())
    auto.apply_ranges(RangePlan.for_sourcing(
        "current", source_range=AUTO, measure_range=2.0))
    check("autorange falls back to the narrowest range's floor",
          auto.source_level_floor("current") == floors[1e-6],
          f"{auto.source_level_floor('current')} vs {floors[1e-6]}")


def test_the_voltage_axis_is_still_unmeasured(check):
    """The bench sourced current. It did not source voltage.

    `sub_count()` in tools/bench_envelope.py calls
    `set_source_function("current")` and sweeps current levels, so
    nothing in the 2026-09-01 round says anything about this
    instrument's voltage converter. Carrying the current-axis count
    across would be an inference wearing a measurement's clothes, and
    `SUB_COUNT_LEVELS` exists to stop exactly that.
    """
    check("the current axis is declared refused",
          Keithley2401.sub_count_state("current")
          == BaseSMU.SUB_COUNT_REFUSED)
    check("the voltage axis is still unmeasured",
          Keithley2401.sub_count_state("voltage")
          == BaseSMU.SUB_COUNT_UNMEASURED)
    check("and no voltage count is declared",
          Keithley2401.SOURCE_COUNTS_PER_RANGE["voltage"] is None)

    smu = Keithley2401(Fake2401())
    check("so no voltage floor is offered",
          smu.source_level_floor("voltage") is None)

    # And nothing is refused on that axis, however small.
    t = Fake2401()
    quiet = Keithley2401(t)
    quiet.set_voltage_level(1e-15)
    check("an absurdly small voltage is still written, unguarded",
          any(":SOUR:VOLT:LEV" in s for s in t.sent),
          "a floor here would be a claim nobody has measured")
