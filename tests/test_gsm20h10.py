import time

"""The GW Instek GSM-20H10 driver: its dialect, and its sweeps.

1. The dialect really is distinct. Sending 2450 or 2401 syntax to this
   instrument would not raise - it would be logged, ignored, and the
   previous compliance kept. So the test asserts the exact spellings
   rather than merely that a sweep came back.

2. Sweeps are stepped from the PC and recover a known resistor end to
   end. The instrument's staircase was retired on 2026-10-15, and
   nothing of it may be sent; the fake below still models it, so that
   any return of it would be seen.

The instrument is faked; the driver under test is the one that runs on
the bench.
"""
from smuniversal_lab_suite.core.transports.base import Transport
from smuniversal_lab_suite.drivers.gwinstek_gsm20h10 import GWInstekGSM20H10
from smuniversal_lab_suite.drivers.keithley_2450 import Keithley2450
from smuniversal_lab_suite.drivers.registry import driver_for_idn

SAMPLE_OHM = 470.0


class GSMTransport(Transport):
    """A fake GSM-20H10 with a plain resistor across its terminals.

    `understands_sweep` flips the instrument between one that accepts
    the staircase commands and one that rejects them via the error
    queue - which is the whole point of the exercise.
    """

    def __init__(self, understands_sweep=True):
        super().__init__()
        self.sent = []
        self.connected = True
        self.understands_sweep = understands_sweep
        self.errors = []
        self.tripped = False
        self.nan_points = set()      # sweep indices to return as NAN
        self.level = 0.0
        self.mode = "voltage"
        #: The flag on the axis that is NOT being sourced - a leftover
        #: from a previous run. A driver that ORs both axes reports this
        #: as a clamp that is not happening.
        self.stale_axis = False
        self.sweep = None          # (start, stop, points) once configured
        self.initiated = False

        # Settings this instrument can be asked about. The values are
        # the factory defaults from the manual's table, which is also
        # what the bench read on 2026-08-20: `SENS:CURR:DC:PROT:LEV?`
        # answered `+1.050000e-04` after `*RST`.
        #
        # Modelled because a fake that answers "0" to a settings query
        # turns a readback check into a guaranteed mismatch, which
        # reports a fault on a driver that did nothing wrong. That is
        # the same non-discriminating shape as a fake that always
        # answers "fine", and it teaches the same lesson in reverse.
        self.current_limit = 1.05e-4
        self.voltage_limit = 21.0
        self.measure_current_range = 1.05e-4
        self.measure_voltage_range = 21.0

    def connect(self, address, **kw):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        self.sent.append(text)
        upper = text.upper()

        if upper.startswith("SOUR:FUNC") and not upper.endswith("?"):
            # Not the query. `SOUR:FUNC?` starts with the same header and
            # contains no CURR, so without this it silently reset the
            # fake to voltage every time the driver asked what mode it
            # was in - and the driver then read back the wrong axis on a
            # current source. A real instrument does not answer a
            # question by changing its own state.
            self.mode = "current" if "CURR" in upper else "voltage"

        if upper.startswith("SOUR:VOLT ") or upper.startswith("SOUR:CURR "):
            try:
                self.level = float(text.split()[-1])
            except ValueError:
                pass

        if not upper.endswith("?"):
            if upper.startswith("SENS:CURR:DC:PROT:LEV"):
                self.current_limit = self._number(text, self.current_limit)
            elif upper.startswith("SENS:VOLT:DC:PROT:LEV"):
                self.voltage_limit = self._number(text, self.voltage_limit)
            elif upper.startswith("SENS:CURR:DC:RANG") and \
                    ":AUTO" not in upper:
                self.measure_current_range = self._full_scale(
                    self._number(text, self.measure_current_range),
                    self.CURRENT_RANGES)
            elif upper.startswith("SENS:VOLT:DC:RANG") and \
                    ":AUTO" not in upper:
                self.measure_voltage_range = self._full_scale(
                    self._number(text, self.measure_voltage_range),
                    self.VOLTAGE_RANGES)

        if upper.startswith("SOUR:SWE") or ":MODE SWE" in upper \
                or upper.startswith("SOUR:VOLT:STAR") \
                or upper.startswith("SOUR:VOLT:STOP") \
                or upper.startswith("SOUR:CURR:STAR") \
                or upper.startswith("SOUR:CURR:STOP"):
            if not self.understands_sweep:
                # What a real SCPI instrument does with a command it
                # doesn't have: queue an error and carry on.
                self.errors.append((-113, "Undefined header"))
                return

        if upper.startswith("SOUR:VOLT:STAR") or upper.startswith("SOUR:CURR:STAR"):
            self._start = float(text.split()[-1])
        if upper.startswith("SOUR:VOLT:STOP") or upper.startswith("SOUR:CURR:STOP"):
            self._stop = float(text.split()[-1])
        if upper.startswith("SOUR:SWE:POIN"):
            self._points = int(float(text.split()[-1]))
        if upper == "INIT":
            self.initiated = True
            self.sweep = (self._start, self._stop, self._points)

    #: Nominal ranges, and the 5% of headroom this family reports above
    #: each one. Measured rather than assumed: the bench read
    #: `1.050000E-05` back from the 10 uA range on 2026-08-20, and
    #: `+1.050000e-04` for the 100 uA compliance default.
    CURRENT_RANGES = (1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0)
    VOLTAGE_RANGES = (0.2, 2.0, 20.0, 200.0)
    FULL_SCALE = 1.05

    @staticmethod
    def _number(text, fallback):
        try:
            return float(text.split()[-1])
        except ValueError:
            return fallback

    @classmethod
    def _full_scale(cls, wanted, table):
        """What this instrument answers after being given a range.

        The smallest nominal range that holds the value, reported at its
        full scale. Both halves matter: a fake that echoed the written
        number could not tell a correct answer from a silently narrowed
        one, and a fake that ignored the 5% would make every correct
        answer look like a 5% discrepancy.
        """
        for nominal in table:
            if abs(wanted) <= nominal * cls.FULL_SCALE:
                return nominal * cls.FULL_SCALE
        return table[-1] * cls.FULL_SCALE

    def _read(self, timeout_s):
        last = self.sent[-1] if self.sent else ""
        upper = last.upper()

        if "IDN" in upper:
            return "GW INSTEK,GSM-20H10,GEW852313,V1.10"

        if upper.startswith("SENS:CURR:DC:PROT:LEV?"):
            return f"{self.current_limit:+.6E}"
        if upper.startswith("SENS:VOLT:DC:PROT:LEV?"):
            return f"{self.voltage_limit:+.6E}"
        if upper.startswith("SENS:CURR:DC:RANG?"):
            return f"{self.measure_current_range:+.6E}"
        if upper.startswith("SENS:VOLT:DC:RANG?"):
            return f"{self.measure_voltage_range:+.6E}"

        if upper.startswith("SYST:ERR:ALL"):
            if self.errors:
                out = ",".join(f'{c},"{m}"' for c, m in self.errors)
                self.errors = []
                return out
            return '0,"No error"'

        if upper.startswith("SYST:ERR"):
            if self.errors:
                code, message = self.errors.pop(0)
                return f'{code},"{message}"'
            return '0,"No error"'

        if upper.startswith("SOUR:FUNC?"):
            return "CURR" if self.mode == "current" else "VOLT"

        # Per axis, because a single flag cannot tell the two candidate
        # rules apart. `self.tripped` sets the flag belonging to the
        # quantity that is NOT being sourced - which is what the manual
        # says these queries report - and `stale_axis` sets the other
        # one, standing in for a flag left over from an earlier run.
        if "CURR:DC:PROT:TRIP" in upper:
            # The V-Source's compliance state.
            live = self.mode == "voltage"
            return "1" if (self.tripped if live else self.stale_axis) else "0"

        if "VOLT:DC:PROT:TRIP" in upper:
            # The I-Source's compliance state.
            live = self.mode == "current"
            return "1" if (self.tripped if live else self.stale_axis) else "0"

        if "PROT:TRIP" in upper:
            return "1" if self.tripped else "0"

        if upper.startswith("TRAC:POIN:ACT"):
            return str(self.sweep[2]) if self.sweep else "0"

        if upper.startswith("TRAC:DATA"):
            start, stop, points = self.sweep
            step = (stop - start) / (points - 1)
            out = []
            for i in range(points):
                level = start + step * i
                if self.mode == "voltage":
                    volts, amps = level, level / SAMPLE_OHM
                else:
                    amps, volts = level, level * SAMPLE_OHM
                if i in self.nan_points:
                    # What the instrument actually sends for "no
                    # reading" - a number, not an error.
                    volts, amps = 9.91e37, 9.91e37
                out.append(f"{volts:.6E}")
                out.append(f"{amps:.6E}")
            return ",".join(out)

        if upper.startswith("READ?"):
            if self.mode == "voltage":
                volts = self.level
                amps = volts / SAMPLE_OHM
            else:
                amps = self.level
                volts = amps * SAMPLE_OHM
            return f"{volts:.6E},{amps:.6E}"

        return "0"


def fit_resistance(sourced, measured, mode):
    """Least-squares slope, converted to ohms for the given mode."""
    n = len(sourced)
    mean_x = sum(sourced) / n
    mean_y = sum(measured) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(sourced, measured))
    den = sum((x - mean_x) ** 2 for x in sourced)
    slope = num / den
    return (1.0 / slope) if mode == "voltage" else slope


# ---------------------------------------------------------------
# A. auto-detection
# ---------------------------------------------------------------


def run_software_sweep(smu, mode, start, stop, points, timeout=15.0):
    smu.start_linear_sweep(mode, start, stop, points, 0.0)
    deadline = time.monotonic() + timeout
    while smu.sweep_points_ready() < points and time.monotonic() < deadline:
        time.sleep(0.005)
    return smu.read_sweep(points)


def test_identification(check):
    idn = "GW INSTEK,GSM-20H10,GEW852313,V1.10"
    check("*IDN? resolves to the GSM driver",
          driver_for_idn(idn) is GWInstekGSM20H10,
          f"got {driver_for_idn(idn)}")
    check("a 2450 reply still resolves to the 2450",
          driver_for_idn("KEITHLEY INSTRUMENTS,MODEL 2450,04412345,1.7.12b")
          is Keithley2450)

    # ---------------------------------------------------------------
    # B. the dialect is genuinely its own
    # ---------------------------------------------------------------


def test_dialect_differs_from_its_neighbours(check):
    gsm_t = GSMTransport()
    gsm = GWInstekGSM20H10(gsm_t)
    gsm.set_source_function("voltage")
    gsm.set_current_limit(1e-3)
    gsm.set_nplc(1)

    sent = " | ".join(gsm_t.sent)
    check("compliance uses SENS:CURR:DC:PROT:LEV",
          "SENS:CURR:DC:PROT:LEV" in sent)
    check("does NOT use the 2450 spelling", "SOUR:VOLT:ILIM" not in sent)
    check("does NOT use the 2401 spelling", "SENS:CURR:PROT " not in sent)
    check("NPLC carries the :DC: infix", "SENS:CURR:DC:NPLC" in sent)

    k_t = GSMTransport()
    k = Keithley2450(k_t)
    k.set_current_limit(1e-3)
    check("the 2450 driver still sends its own spelling",
          any("SOUR:VOLT:ILIM" in s for s in k_t.sent))

    # ---------------------------------------------------------------
    # C. capability declarations
    # ---------------------------------------------------------------


def test_capabilities(check):
    check("declares NPLC support", GWInstekGSM20H10.supports_nplc())
    check("declares OVP support", GWInstekGSM20H10.supports_ovp())
    check("20 V is the default OVP choice, matching the original's MIN",
          GWInstekGSM20H10.OVP_CHOICES[0] == "20")
    check("the 2450 has NPLC but no OVP control",
          Keithley2450.supports_nplc() and not Keithley2450.supports_ovp())
    check("NPLC clamps above the range",
          GWInstekGSM20H10.clamp_nplc(50) == 10.0)
    check("NPLC clamps below the range",
          GWInstekGSM20H10.clamp_nplc(0.0001) == 0.01)

    # ---------------------------------------------------------------
    # D. the power envelope
    # ---------------------------------------------------------------


def test_power_envelope(check):
    from smuniversal_lab_suite.core.limits import LimitError

    limits = GWInstekGSM20H10.LIMITS
    ok = True
    try:
        limits.validate_source_point(voltage=200.0, current=0.1)
    except LimitError:
        ok = False
    check("200 V at 100 mA is allowed", ok)

    refused = False
    try:
        limits.validate_source_point(voltage=200.0, current=1.0)
    except LimitError:
        refused = True
    check("200 V at 1 A is refused (22 W part)", refused)

    refused = False
    try:
        limits.validate_source_point(voltage=250.0)
    except LimitError:
        refused = True
    check("250 V is refused", refused)

    # ---------------------------------------------------------------
    # E. sweeps are stepped from the PC
    # ---------------------------------------------------------------


def test_sweeps_are_stepped_from_the_pc(check):
    """The staircase was retired on 2026-10-15: `TRAC:POIN:ACT?` is not
    answered until it finishes, so Stop and output-off waited behind the
    poll for the whole sweep. Nothing of it may be sent any more."""
    t = GSMTransport(understands_sweep=True)
    smu = GWInstekGSM20H10(t)
    smu.reset()
    check("software, even on an instrument that would take the staircase",
          smu.sweep_kind() == "software"
          and GWInstekGSM20H10.sweep_kind() == "software")
    check("the console says so", "software sweep" in smu.sweep_note())

    smu.set_source_function("voltage")
    smu.set_current_limit(1e-3)
    before = len(t.sent)
    sourced, measured = run_software_sweep(smu, "voltage", -1.0, 1.0, 11)
    sent = t.sent[before:]
    check("11 points returned", len(measured) == 11, f"got {len(measured)}")
    r = fit_resistance(sourced, measured, "voltage")
    check("recovers the resistor", abs(r - SAMPLE_OHM) / SAMPLE_OHM < 5e-4,
          f"{r:.4f} ohm vs {SAMPLE_OHM}")
    check("no staircase, no buffer, no INIT",
          not t.initiated and not any(
              x.upper().startswith(("SOUR:SWE", "TRAC", "INIT", "TRIG:COUN",
                                    "ARM:COUN"))
              or "MODE SWE" in x.upper() for x in sent), f"{sent[:6]}")
    check("one READ? per point", sum(x == "READ?" for x in sent) == 11,
          f"{sum(x == 'READ?' for x in sent)}")

    # ---------------------------------------------------------------
    # G. a current-mode sweep
    # ---------------------------------------------------------------


def test_current_mode_sweep(check):
    t3 = GSMTransport(understands_sweep=True)
    smu3 = GWInstekGSM20H10(t3)
    smu3.set_source_function("current")
    sourced3, measured3 = run_software_sweep(smu3, "current", -1e-3, 1e-3, 9)
    r3 = fit_resistance(sourced3, measured3, "current")
    check("recovers the resistor sourcing current",
          abs(r3 - SAMPLE_OHM) / SAMPLE_OHM < 5e-4,
          f"{r3:.4f} ohm vs {SAMPLE_OHM}")
    check("source values are the currents",
          abs(sourced3[0] - (-1e-3)) < 1e-9,
          f"first source value {sourced3[0]:.3e}")

    # ---------------------------------------------------------------
    # H. OVP
    # ---------------------------------------------------------------


def test_ovp(check):
    t4 = GSMTransport()
    smu4 = GWInstekGSM20H10(t4)
    smu4.set_voltage_protection("20")
    smu4.set_voltage_protection("OFF")
    sent4 = " | ".join(t4.sent)
    check("a numeric level is passed through", "SOUR:VOLT:PROT 20" in sent4)
    # NONE turns out to be valid after all - the manual lists it
    # alongside the numeric range. See section K.
    check("OFF becomes NONE", "SOUR:VOLT:PROT NONE" in sent4)

    # ---------------------------------------------------------------
    # I. READ? not MEAS? - the same fault the 2401 original had
    # ---------------------------------------------------------------


def test_read_not_meas(check):
    t5 = GSMTransport()
    smu5 = GWInstekGSM20H10(t5)
    smu5.reset()
    smu5.set_source_function("voltage")
    smu5.set_current_limit(1e-3)
    t5.level = 0.5
    volts, amps = smu5.measure()
    sent5 = " | ".join(t5.sent)
    check("uses READ?", "READ?" in sent5)
    check("never sends MEAS?, which would reset compliance per point",
          "MEAS?" not in sent5)
    check("FORM:ELEM fixes the reply to volts,amps",
          "FORM:ELEM VOLT,CURR" in sent5)
    check("the reading parses", volts is not None and amps is not None,
          f"{volts}, {amps}")
    check("and obeys Ohm's law",
          abs(amps - 0.5 / SAMPLE_OHM) < 1e-9, f"{amps:.6e}")

    # ---------------------------------------------------------------
    # J. corrections forced by the official command list
    # ---------------------------------------------------------------


def test_matches_the_published_command_list(check):
    t6 = GSMTransport()
    smu6 = GWInstekGSM20H10(t6)
    smu6.reset()
    smu6.set_source_function("voltage")
    smu6.set_voltage_protection("OFF")
    sent6 = " | ".join(t6.sent)

    check("OFF maps to NONE", "SOUR:VOLT:PROT NONE" in sent6)
    check("concurrent measurement is on", "SENS:FUNC:CONC ON" in sent6)
    check("both sense functions are enabled",
          'SENS:FUNC:ON "VOLT","CURR"' in sent6)
    check("line frequency is auto-detected", "SYST:LFR:AUTO 1" in sent6)
    # Not pinned at reset: the manual warns against HIMPedance for tests
    # that cycle the output often, and iv_sweep's periodic mode does.
    check("output-off mode is NOT pinned at reset", "OUTP:SMOD" not in sent6,
          "it is a per-run panel choice, defaulting to NORMal")
    check("reset disarms buffer storage by name, not by assuming *RST did",
          "TRAC:FEED:CONT NEV" in sent6)


def test_output_off_mode(check):
    t_oz = GSMTransport()
    smu_oz = GWInstekGSM20H10(t_oz)
    check("the model declares the capability",
          GWInstekGSM20H10.supports_high_z_off())
    smu_oz.set_output_off_mode(False)
    check("unchecked gives NORMal",
          any(x == "OUTP:SMOD NORM" for x in t_oz.sent))
    smu_oz.set_output_off_mode(True)
    check("checked gives HIMPedance",
          any(x == "OUTP:SMOD HIMP" for x in t_oz.sent))


def test_compliance_trip(check):
    t7 = GSMTransport()
    smu7 = GWInstekGSM20H10(t7)
    check("reports False when nothing tripped",
          smu7.compliance_tripped() is False)
    t7.tripped = True
    check("reports True when compliance was hit",
          smu7.compliance_tripped() is True)
    check("a driver with no such query says None, not False",
          Keithley2450(GSMTransport()).compliance_tripped() is None)


def test_the_trip_query_follows_the_sourced_function(check):
    """Ask the axis that is NOT being sourced, and only that one.

    The manual, twice, in both TRIPped? entries: `:CURRent:PROTection:
    TRIPped?` reports the compliance state of the **V-Source**, and
    `:VOLTage:PROTection:TRIPped?` reports the **I-Source**. The limit
    is on the quantity you are not setting.

    This driver used to query both and OR them. The assertion that
    matters is therefore not "does it get the right answer" - the OR
    gets the right answer whenever the inactive flag happens to be
    clear - but "does it ask the right question".
    """
    for mode, expected, forbidden in (
            ("voltage", "SENS:CURR:DC:PROT:TRIP?", "SENS:VOLT:DC:PROT:TRIP?"),
            ("current", "SENS:VOLT:DC:PROT:TRIP?", "SENS:CURR:DC:PROT:TRIP?")):
        transport = GSMTransport()
        smu = GWInstekGSM20H10(transport)
        smu.set_source_function(mode)
        transport.sent.clear()
        smu.compliance_tripped()

        check(f"sourcing {mode}: asks the instrument what it is sourcing",
              "SOUR:FUNC?" in transport.sent,
              f"{transport.sent} - a remembered copy of the mode is one "
              f"reset() or one front-panel change from being wrong")
        check(f"sourcing {mode}: queries {expected}",
              expected in transport.sent, transport.sent)
        check(f"sourcing {mode}: does not query {forbidden}",
              forbidden not in transport.sent,
              f"{transport.sent} - that axis describes the source that is "
              f"not running")


def test_a_flag_left_on_the_inactive_axis_is_not_reported_as_a_clamp(check):
    """The failure the OR could produce, and the reason it was replaced.

    On a voltage source, the voltage trip flag describes an I-Source
    that is not running. If it holds a value from the last time it was,
    an OR across both axes returns True for a clamp that is not
    happening - and the checkup's clamping check would pass on it while
    the mechanism the experiments depend on was broken.

    Whether these flags really latch on this model is unmeasured. It
    does not need to be: a rule that gives the right answer only when
    they do not is the wrong rule.
    """
    transport = GSMTransport()
    smu = GWInstekGSM20H10(transport)
    smu.set_source_function("voltage")
    transport.tripped = False        # the live axis: not clamping
    transport.stale_axis = True      # the other one: left set

    check("a stale flag on the axis that is not sourcing reports False",
          smu.compliance_tripped() is False,
          "OR-ing both axes reports True here, for a clamp that is not "
          "happening")


def test_an_unreadable_source_mode_says_nothing_rather_than_guessing(check):
    """`MEMory` is a third source mode on this model.

    In it the instrument steps through saved setups, and neither trip
    query describes what it is doing. None renders as "cannot say";
    False would be a reassurance nobody measured.
    """
    class InMemoryMode(GSMTransport):
        def _read(self, timeout_s):
            if self.sent and self.sent[-1].upper().startswith("SOUR:FUNC?"):
                return "MEM"
            return super()._read(timeout_s)

    transport = InMemoryMode()
    smu = GWInstekGSM20H10(transport)
    transport.tripped = True
    check("memory source mode gives None, not a verdict",
          smu.compliance_tripped() is None)
    check("and no trip query is sent at all",
          not any("PROT:TRIP" in s.upper() for s in transport.sent),
          transport.sent)

    # ---------------------------------------------------------------
    # K. corrections forced by the detailed command reference
    # ---------------------------------------------------------------


def test_matches_the_detailed_reference(check):
    t8 = GSMTransport()
    smu8 = GWInstekGSM20H10(t8)
    smu8.set_source_function("voltage")
    check("concurrent is enabled BEFORE both functions are turned on",
          t8.sent.index("SENS:FUNC:CONC ON")
          < t8.sent.index('SENS:FUNC:ON "VOLT","CURR"'))

    smu8.set_source_delay(5000)
    check("source delay clamps to the 999.9999 s maximum",
          any("SOUR:DEL 999.99990" in x for x in t8.sent),
          [x for x in t8.sent if x.startswith("SOUR:DEL ")][-1])


def test_nan_sentinels_are_not_data(check):
    # +9.91e37 parses as a perfectly ordinary float. Left in, one of these
    # drags a least-squares fit entirely to itself.
    t10 = GSMTransport()
    smu10 = GWInstekGSM20H10(t10)
    t10.level = 9.91e37
    volts10, amps10 = smu10.measure()
    check("a single NAN reading becomes None, not 1e37",
          volts10 is None or abs(volts10) < 9e37, f"{volts10}")


def test_a_sub_count_current_level_is_refused(check):
    """MEASURED 2026-09-01, on the instrument that vindicated the probe.

    `tools/bench_envelope.py` pinned the source current range to 1e-4 A
    and halved down; the sign stopped being followed below 3.052e-09 A,
    and 1e-4 / 32768 is 3.0518e-09 - one count of the range the sweep
    was on.

    This instrument is also why the procedure behind that number can be
    believed. On 2026-08-28 an earlier version of the sweep reported
    "sign follows" for twenty-one halvings down to 95 pA, on readings
    that never left +140 uA and +20 uA: a fixed offset kept sitting
    inside a window that shrank with the level. The bound that fixed it
    - both legs on opposite sides of zero, separated by about 2L rather
    than merely more than L - is what the 09-01 figures were taken
    under.

    Both sides of the boundary, because a guard tested only from below
    passes against a driver that refuses everything.
    """
    from smuniversal_lab_suite.core.ranges import RangeError, RangePlan

    counts = GWInstekGSM20H10.SOURCE_COUNTS_PER_RANGE["current"]
    check("the declared count reproduces the measured floor",
          abs(1e-4 / counts - 3.0518e-9) < 1e-13, f"{1e-4 / counts}")

    t = GSMTransport()
    smu = GWInstekGSM20H10(t)
    smu.apply_ranges(RangePlan.for_sourcing(
        "current", source_range=1e-4, measure_range=2.0))

    floor = smu.source_level_floor("current")
    check("the floor is ten counts of the range in force",
          abs(floor - 1e-4 / counts * 10) < 1e-18, f"{floor}")

    before = len(t.sent)
    try:
        smu.set_current_level(floor / 10.0)
        check("a sub-count level is refused", False, "it was written")
    except RangeError:
        check("a sub-count level is refused", True)
        check("and nothing reached the instrument first",
              len(t.sent) == before, f"{t.sent[before:]}")

    smu.set_current_level(floor)
    check("the floor itself goes out",
          any(x.startswith("SOUR:CURR ") for x in t.sent[before:]),
          f"{t.sent[before:]}")

    # This driver sends NOTHING on a source axis carrying nothing -
    # `SOUR:CURR:RANG:AUTO ON` while sourcing voltage silently resets
    # the current compliance to 1 nA (fault 23). So an unsourced axis
    # also leaves the floor unknown, and it falls back to the bound that
    # holds on every range rather than to a range nobody selected.
    unsourced = GWInstekGSM20H10(GSMTransport())
    unsourced.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=1.0, measure_range=1e-4))
    check("an unsourced current axis records no active range",
          unsourced.active_source_range("current") is None)
    check("and falls back to the narrowest range's floor",
          abs(unsourced.source_level_floor("current") - 1e-6 / counts * 10)
          < 1e-20, f"{unsourced.source_level_floor('current')}")

    check("the voltage axis is still unmeasured",
          GWInstekGSM20H10.sub_count_state("voltage") == "unmeasured")
    check("so no voltage floor is offered",
          smu.source_level_floor("voltage") is None)
