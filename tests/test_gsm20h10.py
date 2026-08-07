import time
import sys, os

"""The GW Instek GSM-20H10 driver: dialect, hardware sweep, and the
fallback that catches a wrong guess.

Three things are worth testing here and only one of them is the happy
path.

1. The dialect really is distinct. Sending 2450 or 2401 syntax to this
   instrument would not raise - it would be logged, ignored, and the
   previous compliance kept. So the test asserts the exact spellings
   rather than merely that a sweep came back.

2. The hardware staircase sweep recovers a known resistor end to end.

3. **The probe catches an instrument that doesn't understand the
   staircase commands and falls back to the software sweep.** The
   staircase spellings are inferred from the 2400-family command set,
   not confirmed on a bench, so the interesting case is the one where
   the inference is wrong. A fake instrument that answers SYST:ERR? with
   a complaint stands in for that, and the run still has to complete.

The instrument is faked; the driver under test is the one that runs on
the bench.
"""
from core.transports.base import Transport
from drivers.registry import driver_for_idn
from drivers.gwinstek_gsm20h10 import GWInstekGSM20H10
from drivers.keithley_2450 import Keithley2450

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
        self.sweep = None          # (start, stop, points) once configured
        self.initiated = False

    def connect(self, address, **kw):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        self.sent.append(text)
        upper = text.upper()

        if upper.startswith("SOUR:FUNC"):
            self.mode = "current" if "CURR" in upper else "voltage"

        if upper.startswith("SOUR:VOLT ") or upper.startswith("SOUR:CURR "):
            try:
                self.level = float(text.split()[-1])
            except ValueError:
                pass

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

    def _read(self, timeout_s):
        last = self.sent[-1] if self.sent else ""
        upper = last.upper()

        if "IDN" in upper:
            return "GW INSTEK,GSM-20H10,GEW852313,V1.10"

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
    from core.limits import LimitError

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
    # E. hardware staircase sweep, end to end
    # ---------------------------------------------------------------


def test_hardware_sweep(check):
    t = GSMTransport(understands_sweep=True)
    smu = GWInstekGSM20H10(t)
    check("probe reports hardware", smu.sweep_kind() == "hardware",
          smu.sweep_note())

    smu.set_source_function("voltage")
    smu.start_linear_sweep("voltage", -1.0, 1.0, 11, 0.01)
    check("INIT was sent", t.initiated)
    check("buffer reports all points", smu.sweep_points_ready() == 11)

    sourced, measured = smu.read_sweep(11)
    check("11 points returned", len(measured) == 11, f"got {len(measured)}")
    r = fit_resistance(sourced, measured, "voltage")
    check("recovers the resistor", abs(r - SAMPLE_OHM) / SAMPLE_OHM < 5e-4,
          f"{r:.4f} ohm vs {SAMPLE_OHM}")
    check("source mode restored to FIX",
          any(s.upper() == "SOUR:VOLT:MODE FIX" for s in t.sent))

    # ---------------------------------------------------------------
    # F. the wrong guess - and the fallback that saves it
    # ---------------------------------------------------------------


def test_falls_back_when_staircase_is_rejected(check):
    t2 = GSMTransport(understands_sweep=False)
    smu2 = GWInstekGSM20H10(t2)
    check("probe reports software", smu2.sweep_kind() == "software",
          smu2.sweep_note())
    check("the reason is recorded", "reject" in smu2.sweep_note().lower())
    check("INIT was never sent", not t2.initiated)

    smu2.set_source_function("voltage")
    smu2.start_linear_sweep("voltage", -1.0, 1.0, 11, 0.0)
    import time
    deadline = time.monotonic() + 10
    while smu2.sweep_points_ready() < 11 and time.monotonic() < deadline:
        time.sleep(0.01)
    sourced2, measured2 = smu2.read_sweep(11)
    check("the run still completes", len(measured2) == 11,
          f"got {len(measured2)}")
    r2 = fit_resistance(sourced2, measured2, "voltage")
    check("and still recovers the resistor",
          abs(r2 - SAMPLE_OHM) / SAMPLE_OHM < 5e-4,
          f"{r2:.4f} ohm vs {SAMPLE_OHM}")

    # ---------------------------------------------------------------
    # G. current-mode sweep unpacks the buffer the other way round
    # ---------------------------------------------------------------


def test_current_mode_sweep(check):
    t3 = GSMTransport(understands_sweep=True)
    smu3 = GWInstekGSM20H10(t3)
    smu3.set_source_function("current")
    smu3.start_linear_sweep("current", -1e-3, 1e-3, 9, 0.0)
    sourced3, measured3 = smu3.read_sweep(9)
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
    smu6.start_linear_sweep("voltage", 0.0, 1.0, 5, 0.0)
    smu6.abort_sweep()
    sent6 = " | ".join(t6.sent)

    check("aborts with TRIG:CLE", "TRIG:CLE" in sent6)
    # :ABORt is absent from the command list but does get mentioned in
    # the :MEASure? prose, so its status is genuinely unclear. :TRIGger:CLEar
    # is documented outright, so that is what gets sent.
    check("stops the sweep with the documented command, not the ambiguous one",
          not any(s.strip().upper() == "ABOR" for s in t6.sent))
    check("OFF maps to NONE", "SOUR:VOLT:PROT NONE" in sent6)
    check("concurrent measurement is on", "SENS:FUNC:CONC ON" in sent6)
    check("both sense functions are enabled",
          'SENS:FUNC:ON "VOLT","CURR"' in sent6)
    check("line frequency is auto-detected", "SYST:LFR:AUTO 1" in sent6)
    # Not pinned at reset: the manual warns against HIMPedance for tests
    # that cycle the output often, and iv_sweep's periodic mode does.
    check("output-off mode is NOT pinned at reset", "OUTP:SMOD" not in sent6,
          "it is a per-run panel choice, defaulting to NORMal")
    check("error queue drained in one query, not a poll loop",
          sum(1 for s in t6.sent if s.upper().startswith("SYST:ERR:ALL")) >= 1
          and sum(1 for s in t6.sent if s.upper() == "SYST:ERR?") == 0)


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

    # ---------------------------------------------------------------
    # K. corrections forced by the detailed command reference
    # ---------------------------------------------------------------


def test_matches_the_detailed_reference(check):
    t8 = GSMTransport()
    smu8 = GWInstekGSM20H10(t8)
    smu8.set_source_function("voltage")
    smu8.start_linear_sweep("voltage", 0.0, 1.0, 5, 0.0)
    sent8 = " | ".join(t8.sent)
    check("arm count is pinned to 1", "ARM:COUN 1" in sent8)
    check("concurrent is enabled BEFORE both functions are turned on",
          t8.sent.index("SENS:FUNC:CONC ON")
          < t8.sent.index('SENS:FUNC:ON "VOLT","CURR"'))
    check("buffer feed is set before storage is armed",
          t8.sent.index("TRAC:FEED SENS1") < t8.sent.index("TRAC:FEED:CONT NEXT"))

    smu8.set_source_delay(5000)
    check("source delay clamps to the 999.9999 s maximum",
          any("SOUR:DEL 999.99990" in x for x in t8.sent),
          [x for x in t8.sent if x.startswith("SOUR:DEL ")][-1])


def test_nan_sentinels_are_not_data(check):
    # +9.91e37 parses as a perfectly ordinary float. Left in, one of these
    # drags a least-squares fit entirely to itself.
    t9 = GSMTransport(understands_sweep=True)
    smu9 = GWInstekGSM20H10(t9)
    smu9.set_source_function("voltage")
    t9.nan_points = {3, 7}
    smu9.start_linear_sweep("voltage", -1.0, 1.0, 11, 0.0)
    sourced9, measured9 = smu9.read_sweep(11)
    check("the two NAN points are dropped", len(measured9) == 9,
          f"got {len(measured9)}")
    check("columns stay aligned after dropping",
          len(sourced9) == len(measured9))
    check("no sentinel survives into the data",
          all(abs(v) < 9e37 for v in measured9))
    r9 = fit_resistance(sourced9, measured9, "voltage")
    check("the resistor is still recovered from what remains",
          abs(r9 - SAMPLE_OHM) / SAMPLE_OHM < 5e-4,
          f"{r9:.4f} ohm vs {SAMPLE_OHM}")
    check("the drop is reported, not silent",
          "NAN" in smu9.sweep_note().upper(), smu9.sweep_note())

    t10 = GSMTransport()
    smu10 = GWInstekGSM20H10(t10)
    t10.level = 9.91e37
    volts10, amps10 = smu10.measure()
    check("a single NAN reading becomes None, not 1e37",
          volts10 is None or abs(volts10) < 9e37, f"{volts10}")

    # ---------------------------------------------------------------
    # The sweep must leave the instrument able to take a single reading
    # ---------------------------------------------------------------


def test_sweep_restores_single_shot_state(check):
    # Found on the bench, not here: the staircase sets TRIG:COUN to the
    # point count, and nothing put it back. The next plain READ? then
    # triggered that many readings - invisible at low NPLC, and at NPLC 10
    # a reply five times longer than measure()'s timeout, surfacing as a
    # USB timeout that reads like a cable fault.
    t = GSMTransport()
    smu = GWInstekGSM20H10(t)
    smu.reset()
    smu.set_source_function("voltage")
    smu.start_linear_sweep("voltage", 0.0, 0.1, 5, 0.0)
    smu.read_sweep(5)

    after = " | ".join(t.sent[t.sent.index("TRIG:COUN 5"):])
    check("the trigger count goes back to 1 after a sweep",
          "TRIG:COUN 1" in after,
          "otherwise the next READ? triggers one reading per sweep point")
    check("and the arm count with it", "ARM:COUN 1" in after)
    check("the source returns to fixed mode", "SOUR:VOLT:MODE FIX" in after)

    order = [x for x in t.sent if x.startswith(("TRIG:COUN", "SOUR:VOLT:MODE"))]
    check("the restore happens after the sweep was configured, not before",
          order.index("TRIG:COUN 1") > order.index("TRIG:COUN 5"),
          f"{order}")

    # ---------------------------------------------------------------
    # The software fallback must leave the source able to be stepped
    # ---------------------------------------------------------------


def test_fallback_restores_fixed_source(check):
    # Found on the bench, and the worst kind of bug: the staircase setup was
    # refused (-140), the driver correctly fell back to the software sweep -
    # and left the source in SWE mode. The software sweep steps by sending
    # `SOUR:VOLT <level>`, which in SWE mode is read as a sweep ENDPOINT
    # rather than a level to hold. So the source never moved: five points
    # returned, no error reported, every point at 0 V. The fallback that was
    # supposed to rescue the run was the thing that broke it.


    class RejectsStaircase(GSMTransport):
        """Accepts the connect-time probe, refuses the real setup."""

        def __init__(self, bad_command="SOUR:SWE:RANG BEST"):
            super().__init__()
            self.bad_command = bad_command
            self.probing = True

        def _write(self, text):
            super()._write(text)
            if not self.probing and text.startswith(self.bad_command):
                self.errors.append((-140, "Character data error"))


    t = RejectsStaircase()
    smu = GWInstekGSM20H10(t)
    smu.reset()
    t.probing = False          # the probe has run; now refuse the real thing
    smu.set_source_function("voltage")

    sourced, measured = run_software_sweep(smu, "voltage", 0.0, 0.1, 5)

    check("the fallback still returns the right number of points",
          len(sourced) == 5, f"{len(sourced)}")
    span = max(sourced) - min(sourced)
    check("AND THE SOURCE ACTUALLY MOVED",
          span > 0.05, f"span {span:.6g} V of a requested 0.1 V")

    after = t.sent[t.sent.index("SOUR:VOLT:MODE SWE"):]
    check("fixed source mode is restored before any level is sent",
          "SOUR:VOLT:MODE FIX" in after
          and after.index("SOUR:VOLT:MODE FIX")
          < min(i for i, x in enumerate(after) if x.startswith("SOUR:VOLT ")),
          "otherwise every level is read as a sweep endpoint")
    check("the trigger count is put back too", "TRIG:COUN 1" in after,
          "a stale count makes the next READ? take that many readings")
    check("and the arm count", "ARM:COUN 1" in after)

    note = smu.sweep_note()
    check("the note reports the rejection", "rejected" in note, note)
    check("and names the command that caused it",
          "SOUR:SWE:RANG BEST" in note,
          f"-140 names a KIND of error, not which of fifteen commands "
          f"made it. Got: {note}")

    # a different offender is named correctly too
    t2 = RejectsStaircase("SOUR:SWE:DIR")
    smu2 = GWInstekGSM20H10(t2)
    smu2.reset()
    t2.probing = False
    smu2.set_source_function("voltage")
    run_software_sweep(smu2, "voltage", 0.0, 0.1, 5)
    check("a different rejected command is named correctly",
          "SOUR:SWE:DIR" in smu2.sweep_note(), smu2.sweep_note())

    # ---------------------------------------------------------------
    # The buffer feed token differs from the Keithley spelling
    # ---------------------------------------------------------------


def test_buffer_storage_is_disarmed_first(check):
    # The command list is explicit: "TRACe:FEED cannot be changed while
    # buffer storage is active." Every sweep setup arms storage with
    # `CONT NEXT` at the end, so from the second sweep onward it is still
    # armed when the next one begins - and the feed command is refused,
    # taking the whole staircase down with it. That is the likeliest reading
    # of the -140 seen on the bench, ahead of any spelling difference.


    class RefusesFeedWhileArmed(GSMTransport):
        """Enforces the documented constraint."""

        def __init__(self):
            super().__init__()
            self.storage_armed = False

        def _write(self, text):
            super()._write(text)
            upper = text.strip().upper()
            if upper.startswith("TRAC:FEED:CONT"):
                self.storage_armed = upper.endswith("NEXT")
            elif upper.startswith("TRAC:FEED ") and self.storage_armed:
                self.errors.append((-140, "Character data error"))


    t = RefusesFeedWhileArmed()
    smu = GWInstekGSM20H10(t)
    smu.reset()
    smu.set_source_function("voltage")

    check("reset disarms storage by name, not by assuming *RST did it",
          "TRAC:FEED:CONT NEV" in t.sent)

    run_software_sweep(smu, "voltage", 0.0, 0.1, 5)
    check("the first sweep configures cleanly",
          "rejected" not in smu.sweep_note(), smu.sweep_note())

    # The second sweep is the one that used to fail: storage was left
    # armed by the first.
    run_software_sweep(smu, "voltage", 0.0, 0.1, 5)
    check("AND SO DOES THE SECOND, with storage armed by the first",
          "rejected" not in smu.sweep_note(),
          f"this is the case the ordering fix exists for: {smu.sweep_note()}")

    feeds = [i for i, x in enumerate(t.sent) if x.startswith("TRAC:FEED ")]
    for i in feeds:
        disarms = [j for j, x in enumerate(t.sent[:i])
                   if x.strip().upper() == "TRAC:FEED:CONT NEV"]
        arms = [j for j, x in enumerate(t.sent[:i])
                if x.strip().upper() == "TRAC:FEED:CONT NEXT"]
        ok = disarms and (not arms or max(disarms) > max(arms))
        check(f"storage is disarmed before the feed at index {i}", bool(ok))

    check("the documented SENS1 token is the one used",
          all(x.strip().upper() == "TRAC:FEED SENS1"
              for x in t.sent if x.startswith("TRAC:FEED ")),
          f"{sorted(set(x for x in t.sent if x.startswith('TRAC:FEED ')))}")


def test_buffer_feed_token(check):
    # Found on the bench: firmware V1.16 rejects `TRAC:FEED SENS1` - the
    # 2400 spelling - with -140, "Character data error", and wants the
    # un-numbered `SENS`. That one word was refusing the entire staircase
    # setup, dropping every sweep to the software path.


    class RejectsNumberedFeed(GSMTransport):
        """Accepts TRAC:FEED SENS, refuses TRAC:FEED SENS1."""

        def _write(self, text):
            super()._write(text)
            if text.strip().upper() == "TRAC:FEED SENS1":
                self.errors.append((-140, "Character data error"))


    t = RejectsNumberedFeed()
    smu = GWInstekGSM20H10(t)
    smu.reset()
    smu.set_source_function("voltage")
    sourced, measured = run_software_sweep(smu, "voltage", 0.0, 0.1, 5)

    used = [x for x in t.sent if x.startswith("TRAC:FEED S")]
    check("a working token is found after the refused one",
          used and used[-1].strip().upper() != "TRAC:FEED SENS1", f"{used}")
    check("and the hardware sweep is NOT abandoned",
          "rejected" not in smu.sweep_note(),
          f"one rejected token should not cost the whole staircase: "
          f"{smu.sweep_note()}")
    check("the sweep still returns its points", len(sourced) == 5)
    check("and the source moved", max(sourced) - min(sourced) > 0.05,
          f"span {max(sourced) - min(sourced):.4g} V")

    # probed once, not on every sweep
    before = sum(1 for x in t.sent if x.startswith("TRAC:FEED SENS1"))
    run_software_sweep(smu, "voltage", 0.0, 0.1, 5)
    after = sum(1 for x in t.sent if x.startswith("TRAC:FEED SENS1"))
    check("the rejected token is not retried on later sweeps",
          after == before, f"{before} -> {after}")

    class RejectsBothNumberedForms(GSMTransport):
        """Only the un-numbered token works - the last resort in the chain."""

        def _write(self, text):
            super()._write(text)
            if text.strip().upper() in ("TRAC:FEED SENS1", "TRAC:FEED SENSE1"):
                self.errors.append((-140, "Character data error"))


    t7 = RejectsBothNumberedForms()
    smu7 = GWInstekGSM20H10(t7)
    smu7.reset()
    smu7.set_source_function("voltage")
    run_software_sweep(smu7, "voltage", 0.0, 0.1, 5)
    check("the un-numbered token is reached when both numbered forms fail",
          any(x.strip().upper() == "TRAC:FEED SENS" for x in t7.sent),
          f"{[x for x in t7.sent if x.startswith('TRAC:FEED S')]}")
    check("and the hardware sweep still survives",
          "rejected" not in smu7.sweep_note(), smu7.sweep_note())

    # -140 is a CHARACTER DATA error - a complaint about the parameter,
    # not the instrument's state - so the literal long form the manual
    # prints is tried too, in case this implementation matches exactly
    # rather than honouring the SCPI abbreviation.
    class OnlyAcceptsLongForm(GSMTransport):
        def _write(self, text):
            super()._write(text)
            if text.strip() == "TRAC:FEED SENS1":
                self.errors.append((-140, "Character data error"))


    t3 = OnlyAcceptsLongForm()
    smu3 = GWInstekGSM20H10(t3)
    smu3.reset()
    smu3.set_source_function("voltage")
    run_software_sweep(smu3, "voltage", 0.0, 0.1, 5)
    check("the manual's literal long form is tried when the short form is "
          "refused",
          any(x.strip() == "TRAC:FEED SENSe1" for x in t3.sent),
          f"{[x for x in t3.sent if x.startswith('TRAC:FEED S')]}")
    check("and the hardware sweep survives",
          "rejected" not in smu3.sweep_note(), smu3.sweep_note())

    # ---------------------------------------------------------------


def test_buffer_capacity(check):
    # The command list gives 2500 as the buffer maximum, and the staircase
    # stores one reading per point.
    from drivers.gwinstek_gsm20h10 import MAX_BUFFER_POINTS

    check("the documented capacity is declared", MAX_BUFFER_POINTS == 2500)

    t4 = GSMTransport()
    smu4 = GWInstekGSM20H10(t4)
    smu4.reset()
    smu4.set_source_function("voltage")
    message = ""
    try:
        smu4.start_linear_sweep("voltage", 0.0, 1.0, MAX_BUFFER_POINTS + 1, 0.0)
    except ValueError as exc:
        message = str(exc)
    check("a sweep beyond the buffer is refused", bool(message))
    check("with the limit and the request both named",
          "2500" in message and "2501" in message, message)
    check("and nothing was configured on the instrument",
          not any(x.startswith("TRAC:POIN ") for x in t4.sent),
          "the instrument's own complaint would be a bare code attached to "
          "a command the operator never typed")

    t5 = GSMTransport()
    smu5 = GWInstekGSM20H10(t5)
    smu5.reset()
    smu5.set_source_function("voltage")
    smu5.start_linear_sweep("voltage", 0.0, 1.0, MAX_BUFFER_POINTS, 0.0)
    check("exactly at the limit is allowed",
          f"TRAC:POIN {MAX_BUFFER_POINTS}" in t5.sent)


def test_sweep_direction_semantics(check):
    # The command list: "Selecting UP restores sweep operation to the normal
    # start to stop direction." So a descending sweep is start > stop with
    # DIR left at UP. DOWn would reverse it again and return the data
    # backwards with nothing to say so.
    t6 = GSMTransport()
    smu6 = GWInstekGSM20H10(t6)
    smu6.reset()
    smu6.set_source_function("voltage")
    smu6.start_linear_sweep("voltage", 1.0, -1.0, 5, 0.0)
    check("a descending sweep still sends DIR UP",
          "SOUR:SWE:DIR UP" in t6.sent and "SOUR:SWE:DIR DOWN" not in t6.sent)
    check("and expresses the direction through START > STOP",
          any(x.startswith("SOUR:VOLT:STAR 1") for x in t6.sent)
          and any(x.startswith("SOUR:VOLT:STOP -1") for x in t6.sent),
          f"{[x for x in t6.sent if ':STAR' in x or ':STOP' in x]}")

    # an instrument that takes the Keithley spelling keeps using it
    t2 = GSMTransport()
    smu2 = GWInstekGSM20H10(t2)
    smu2.reset()
    smu2.set_source_function("voltage")
    run_software_sweep(smu2, "voltage", 0.0, 0.1, 5)
    check("an instrument that accepts SENS1 still gets SENS1",
          any(x.strip().upper() == "TRAC:FEED SENS1" for x in t2.sent),
          f"{[x for x in t2.sent if 'FEED' in x]}")

    # ---------------------------------------------------------------
    # The buffer's element count is read back, not assumed
    # ---------------------------------------------------------------


def test_buffer_element_layout(check):
    global t2
    # Found on the bench, and it is the nastiest bug in this driver so far
    # because the wrong data looked right. Told `FORM:ELEM VOLT,CURR`, the
    # instrument accepted it, queued no error, and returned THREE numbers
    # per reading - voltage, current, resistance. A fixed stride of two
    # turned 5 readings (15 numbers) into 7 pairs; 4 held the resistance
    # NAN and were dropped; the 3 that survived were readings 1, 3 and 5 -
    # genuine V/I pairs. A silently decimated sweep that fits a straight
    # line perfectly well. Only the point-count check caught it.


    class ThreeElementBuffer(GSMTransport):
        """Returns V, I, R per reading whatever FORM:ELEM asked for - AND
    misreports its own element list when asked.

    This is what the instrument actually does. `FORM:ELEM VOLT,CURR` is
    accepted and ignored; `FORM:ELEM?` then answers `VOLT,CURR`, which
    is the list it was given rather than the one it sends. Reading the
    configuration back is therefore no better than asking for it - both
    describe an instrument that does not exist. Only counting the
    numbers works.
    """

        def _read(self, timeout_s):
            last = self.sent[-1] if self.sent else ""
            if "FORM:ELEM?" in last.upper():
                return "VOLT,CURR"          # the lie
            if "TRAC:DATA" in last.upper():
                out = []
                for i in range(5):
                    volts = 0.025 * i
                    out += [f"{volts:.6e}", f"{volts / 470.0:.6e}", "+9.910000E+37"]
                return ",".join(out)
            return super()._read(timeout_s)


    t = ThreeElementBuffer()
    smu = GWInstekGSM20H10(t)
    smu.reset()
    smu.set_source_function("voltage")
    sourced, measured = run_software_sweep(smu, "voltage", 0.0, 0.1, 5)

    check("the stride is counted from the data, not asked for",
          any("TRAC:POIN:ACT?" in x for x in t.sent),
          "the reading count is the denominator that turns a flat list of "
          "numbers into a stride")
    check("all five readings survive a three-element buffer",
          len(sourced) == 5, f"got {len(sourced)} - a fixed stride gives 3")
    check("no resistance NAN leaks into the data",
          all(abs(v) < 1e30 for v in sourced + measured))
    check("and the values are the real ones",
          abs(max(sourced) - 0.1) < 1e-9
          and abs(max(measured) - 0.1 / 470.0) < 1e-9,
          f"V {max(sourced):.6g}, I {max(measured):.6g}")

    # The ordinary two-element case must be untouched.
    t2 = GSMTransport()
    smu2 = GWInstekGSM20H10(t2)
    smu2.reset()
    smu2.set_source_function("voltage")
    sourced2, measured2 = run_software_sweep(smu2, "voltage", -1.0, 1.0, 11)
    check("a two-element buffer still parses as before", len(sourced2) == 11,
          f"{len(sourced2)}")

    # An instrument that will not answer FORM:ELEM? must not break.
    class NoElementQuery(GSMTransport):
        def _read(self, timeout_s):
            last = self.sent[-1] if self.sent else ""
            if "FORM:ELEM?" in last.upper():
                raise TimeoutError("no reply")
            return super()._read(timeout_s)


    # The layout arithmetic on its own, including the cases a whole sweep
    # cannot easily produce.
    layout = GWInstekGSM20H10(GSMTransport())._buffer_layout
    check("2 values over 1 reading is a plain pair",
          layout(1, [0.0, 0.0]) == (2, 0, 1))
    check("15 values over 5 readings is a stride of 3, V then I",
          layout(5, [0.0] * 15) == (3, 0, 1))
    check("25 values over 5 readings is a stride of 5, V and I still first",
          layout(5, [0.0] * 25) == (5, 0, 1),
          "canonical order is VOLT, CURR, RES, TIME, STAT")
    check("a count of zero falls back rather than dividing by it",
          layout(0, [0.0] * 10) == (2, 0, 1))
    check("a ragged reply falls back rather than guessing",
          layout(4, [0.0] * 15) == (2, 0, 1),
          "15 does not divide by 4, so the stride is unknown")
    check("an empty reply falls back", layout(5, []) == (2, 0, 1))
    check("a stride of 1 is refused - there would be no current column",
          layout(5, [0.0] * 5) == (2, 0, 1))

    t3 = NoElementQuery()
    smu3 = GWInstekGSM20H10(t3)
    smu3.reset()
    smu3.set_source_function("voltage")
    sourced3, _ = run_software_sweep(smu3, "voltage", -1.0, 1.0, 11)
    check("an unanswerable element query falls back to a plain pair",
          len(sourced3) == 11, f"{len(sourced3)}")

    check("and the note says the buffer is wider than requested",
          "3 values per reading" in smu.sweep_note(), smu.sweep_note()[:80])
    check("naming it as an instrument quirk, not a transfer fault",
          "accepted and ignored" in smu.sweep_note())

    # The decisive point: believing FORM:ELEM? would have given the wrong
    # answer here, because it reports the requested list.
    check("a misreported element list does not mislead the parse",
          len(sourced) == 5,
          "FORM:ELEM? said VOLT,CURR while the buffer sent three columns")


def test_elements_are_set_before_storage_is_armed(check):
    # Sent after `CONT NEXT` it is accepted, queues no error, and has no
    # effect - the same shape as the TRACe:FEED rule the manual states
    # outright.
    order = [x for x in t2.sent
             if x.startswith("FORM:ELEM ") or x == "TRAC:FEED:CONT NEXT"]
    check("FORM:ELEM precedes the arming of storage",
          order and order[0].startswith("FORM:ELEM "), order)
