"""
Keysight B2901A Precision Source/Measure Unit.

The first driver here written from the manual alone - there was no
working script to port, so nothing in this file inherits a decision from
the lab. Everywhere a default was chosen rather than carried over, the
comment says so and says why.

WHAT MAKES THIS INSTRUMENT DIFFERENT FROM THE REST OF THE BENCH

**It reaches 3 A DC.** Double the 2611A, triple the 2450, twenty-five
times the U2722A. If a measurement needs real current, this is the only
instrument in the suite that can supply it - and the only one that can
measure it without a shunt.

**Its compliance lives on the sense side.** `:SENS:CURR:PROT`, not a
source limit. The mental model is genuinely different from the Keithleys
and it is the reason the limit-setting methods here look nothing like
`keithley_2401.py`.

**It has two command sets.** The B2900 can be switched into a mode that
answers many of the Keithley 2400's commands, which is tempting and is
not what this driver does. "Partially supported" is where a command gets
accepted, logged as fine, and quietly does something other than its 2400
meaning - and the switch is a remembered setting, so which dialect the
instrument is listening in would depend on how the last person left it.
This driver speaks the native set throughout.

THREE RESET DEFAULTS THIS DRIVER OVERRIDES, AND WHY

`*RST` is mandatory on connect (A9), so anything reset clobbers has to
be re-asserted afterwards or it is not set at all. Three matter:

1. **`:OUTP:ON:AUTO` resets to ON**, which means the instrument turns
   its own output on when `:INIT` or `:READ` is sent. The suite's
   guarantee is that the output is energised only when a run asked for
   it, and Stop de-energising is load-bearing. HANDOFF records having
   already seen "OFF turns the output off and the worker turns it
   straight back on" on a bench; here the *instrument* would do it,
   with no command to trace it to. Forced off.

2. **`:SENS:REM` resets to OFF**, so 4-wire is off after every reset.
   The IV sweep defaults to 4-wire. Left alone, a Kelvin-wired rig would
   silently return 2-wire numbers that look entirely reasonable.

3. **`:FORM:ELEM:SENS` resets to all six elements** (voltage, current,
   resistance, time, status, source). Pinned to two, so the reply shape
   is known - though `measure()` still counts what arrived rather than
   trusting that, because an instrument agreeing to an element list and
   then sending something else is a fault this project has already been
   bitten by.

THE SENTINEL

A measurement function that is not enabled does not raise and does not
return nothing. It returns +9.91e37, the SCPI "not a number" value. That
parses as a perfectly ordinary float, so it enters the data as a point
37 orders of magnitude out, dragging a least-squares fit to a
meaningless slope while still reporting a healthy R-squared. Anything at
or above NAN_THRESHOLD is treated as "no reading" and dropped.

This is *better* than the Keithley 2400 family's behaviour, where the
unmeasured column is filled from the source setting instead - ask for
1 V and read back exactly 1.000000 V, with the lead drops vanished. A
sentinel is detectable; a plausible number is not. But it is only
detectable by code that knows to look.

WHAT IS DELIBERATELY NOT HERE

**The hardware staircase sweep.** The instrument has one, fully
documented (`:SOUR:VOLT:MODE SWE`, `:SOUR:SWE:*`, `:TRIG:ACQ:COUN`,
`:INIT`, `:FETC:ARR?`, with `:TRAC:POIN:ACT?` to poll the real count).
It is not implemented, and that is a judgement rather than an oversight:
the GSM's hardware sweep cost three separate bench-found deviations -
state left behind by the sweep, a buffer setting that only applies
before arming, and an element list accepted and ignored - none of which
an offline test suite could have found. This instrument has not been on
a bench yet. The software sweep inherited from BaseSMU is correct from
day one and every level it sources is read back rather than assumed.
Upgrading later is one file and nothing in experiments/ changes.
"""
from core.limits import SMULimits
from .base_smu import BaseSMU


class KeysightB2901A(BaseSMU):
    # Only the B2901A. The B2902A is the two-channel sibling and the
    # B2911A/B2912A add a 10 nA range this model does not have, so
    # claiming the series here would hand a B2911A a range table missing
    # its most useful range. An unclaimed instrument gets the manual
    # driver dropdown, which is an inconvenience; a wrongly claimed one
    # gets silently wrong limits, which is not.
    #
    # NOT YET CONFIRMED AGAINST A REAL REPLY. This is the model
    # designation as printed, not an observed *IDN?. First thing to
    # check at the bench - `tools/visa_doctor.py` prints it.
    MODEL_IDS = ["B2901A"]
    DISPLAY_NAME = "Keysight B2901A"

    LIMITS = SMULimits(
        max_voltage=210.0,
        max_current=3.03,
        voltage_ranges=[0.2, 2.0, 20.0, 200.0],
        # The 10 nA range is B2911A/B2912A only. The 10 A range is
        # pulse-only and must not appear here: everything downstream
        # treats these as DC-capable, and a software sweep would
        # otherwise offer a point the hardware can hold for a
        # millisecond.
        current_ranges=[1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1,
                        1.0, 1.5, 3.0],
        # 31.8 W, three corners. Unlike the two-corner Keithleys this
        # instrument trades voltage for current twice on the way down.
        power_envelope=[(6.0, 3.03), (21.0, 1.515), (210.0, 0.105)],
    )

    # NAN_THRESHOLD is inherited from BaseSMU - see the module
    # docstring here for what this instrument does, and base_smu.py for
    # why every driver gets the same threshold.

    # 4E-4 to 100 at 50 Hz, 4.8E-4 to 120 at 60 Hz, per the command
    # reference. Declared for 50 Hz - the narrower of the two, so a
    # value clamped to this window is valid on either mains.
    NPLC_RANGE = (4e-4, 100.0)

    # `:OUTP:PROT[:STAT]` is an on/off enable for the over-voltage and
    # over-current protection, not a menu of ceilings like the GSM's
    # `SOUR:VOLT:PROT`. OVP_CHOICES wants selectable ceilings, so this
    # instrument records no OVP rather than pretending a boolean is one.
    OVP_CHOICES = []

    HIGH_Z_OFF = True               # :OUTP:OFF:MODE ZERO|HIZ|NORMal
    REMOTE_SENSE_CONTROL = True     # :SENS:REM
    SWEEP_KIND = "software"         # see the module docstring

    # Mains frequency, for NPLC to mean anything. NPLC only cancels hum
    # if the instrument knows the mains period, so an integration time
    # set without this is worth less than it looks. 50 Hz because that
    # is where the bench is; a lab on 60 Hz sets this and nothing else
    # changes.
    LINE_FREQUENCY_HZ = 50

    def __init__(self, transport):
        super().__init__(transport)
        # Which spelling of the sense-function argument this instrument
        # accepted, resolved once at reset. None until then.
        self._sense_func_style = None
        self._sense_func_note = ""

    # ---- reset ----
    def reset(self):
        """`*RST`, then re-assert everything reset clobbers.

        The three overridden defaults are in the module docstring. This
        method is where fault 6 - state inherited rather than set - is
        actually paid for: every one of these settings is correct after
        reset only because it is sent again here.
        """
        self.transport.write("*RST")
        self.transport.write("*CLS")
        # Order matters. Auto-output-on goes first, so that nothing
        # sent afterwards can energise the output as a side effect
        # before it has been disabled.
        self.transport.write(":OUTP:ON:AUTO 0")
        self.transport.write(f":SYST:LFR {self.LINE_FREQUENCY_HZ}")
        self._enable_both_sense_functions()
        # Two elements, in the instrument's fixed order. The order of
        # the reply is voltage, current - documented as fixed, and NOT
        # the order the elements are named in.
        self.transport.write(":FORM:ELEM:SENS VOLT,CURR")
        self.transport.write(":FORM:DATA ASC")

    def _enable_both_sense_functions(self):
        """Enable voltage and current measurement, and confirm it took.

        The manual contradicts itself on whether the argument is quoted:
        the parameter table says `fctn="CURRent[:DC]"|...` with quotes,
        and the `:MEASure?` page's own worked example writes
        `:SENS:FUNC CURR` without them. Across the nine examples where
        the command appears, both spellings are used.

        Sending both and hoping is the one thing not to do - it would
        leave nobody able to say which spelling the instrument acted on,
        and the second send would silently redefine the function list
        set by the first. So this asks instead: send one, then read back
        `:SENS:FUNC:ON:COUN?` and expect 2. That is the GSM's
        `_probe_sweep_support()` pattern applied to a documentation
        ambiguity rather than a hardware one - a command that returns a
        fact beats a command that returns silence.

        If neither spelling gives exactly two enabled functions, the
        driver leaves the instrument alone and says so. It does not
        guess: with a function disabled every reading in that column
        comes back as the +9.91e37 sentinel, which `measure()` drops -
        so the failure is visible as missing data rather than as wrong
        data.

        The `:SENS:FUNC:OFF:ALL` first is load-bearing, and the first
        version of this method did not have it. Reset leaves *all six*
        functions enabled, so a count of "at least two" was already true
        before anything was sent - the probe returned a fact, but not a
        fact about whether the command had worked. Clearing first is
        what makes the count discriminating. It also stops the
        instrument measuring resistance on every point, which nothing
        here reads and which is not free.
        """
        for style, arg in (("quoted", '"VOLT","CURR"'),
                           ("bare", "VOLT,CURR")):
            try:
                self.transport.write(":SENS:FUNC:OFF:ALL")
                self.transport.write(f":SENS:FUNC:ON {arg}")
                reply = self.transport.query(":SENS:FUNC:ON:COUN?",
                                             timeout_s=3.0)
                if int(float(reply.strip())) == 2:
                    self._sense_func_style = style
                    self._sense_func_note = (
                        f"sense functions set with the {style} spelling")
                    return
            except Exception:
                continue
        self._sense_func_style = None
        self._sense_func_note = (
            "could not confirm both sense functions are enabled - "
            "one column may read as no-data")

    # ---- source configuration ----
    def set_source_function(self, mode):
        """Select the sourced quantity.

        Per the contract, the output state afterwards is undefined and
        the caller turns the output on after this, not before.
        """
        if mode == "current":
            self.transport.write(":SOUR:FUNC:MODE CURR")
        elif mode == "voltage":
            self.transport.write(":SOUR:FUNC:MODE VOLT")
        else:
            raise ValueError(f"Unknown source mode: {mode!r}")

    def set_current_level(self, amps):
        self.transport.write(f":SOUR:CURR {amps:.6e}")

    def set_voltage_level(self, volts):
        # Full float precision, not rounded. Two originals ported here
        # quantised levels before sending, which is invisible at ±1 V
        # and destroys a ±100 µV sweep while the saved x-axis still
        # claims evenly spaced points.
        self.transport.write(f":SOUR:VOLT {volts:.6e}")

    # ---- compliance ----
    #
    # Sense-side, which is the real departure from the Keithleys. Note
    # the plain `:PROT[:LEV]` form: the `:BOTH` keyword and the
    # `:NEGative`/`:POSitive` split-polarity variants need licence "SWS"
    # and firmware 3.1 or later, so a driver using them would work on
    # some B2901As and not others - and the failure would arrive as a
    # command error at run time on an instrument nobody had tested.

    def set_current_limit(self, amps):
        self.transport.write(f":SENS:CURR:PROT {amps:.6e}")

    def set_voltage_limit(self, volts):
        self.transport.write(f":SENS:VOLT:PROT {volts:.6e}")

    def compliance_tripped(self):
        """Whether the source hit its compliance limit.

        Worth having because a sweep in compliance still draws a neat
        line with a convincing R-squared: the instrument was clamping,
        so the fit describes the limit rather than the sample.

        Returns None if the instrument cannot be asked, rather than
        False - silence is not a reassurance.
        """
        try:
            reply = self.transport.query(":SENS:CURR:PROT:TRIP?",
                                         timeout_s=3.0)
            return bool(int(float(reply.strip())))
        except Exception:
            return None

    # ---- ranging ----
    #
    # Measurement ranges, not source ranges. Auto has to be switched off
    # explicitly before a fixed range means anything: `:SENS:*:RANG` is
    # documented as effective only when automatic ranging is off, so
    # setting a range while auto is on is accepted and ignored.

    def set_current_range(self, amps=None):
        if amps is None:
            self.transport.write(":SENS:CURR:RANG:AUTO ON")
        else:
            self.transport.write(":SENS:CURR:RANG:AUTO OFF")
            self.transport.write(f":SENS:CURR:RANG {amps:.6e}")

    def set_voltage_range(self, volts=None):
        if volts is None:
            self.transport.write(":SENS:VOLT:RANG:AUTO ON")
        else:
            self.transport.write(":SENS:VOLT:RANG:AUTO OFF")
            self.transport.write(f":SENS:VOLT:RANG {volts:.6e}")

    # ---- sensing ----
    def set_remote_sense(self, on=True):
        """4-wire (Kelvin) sensing.

        Resets to OFF, so this is sent on every run rather than once at
        connect. The instrument's remote-sense operating window is
        narrow - 3 V maximum between force and sense on each side, and
        1 kΩ maximum sense-lead resistance for rated accuracy - which is
        a wiring fact rather than a software one, recorded in
        INSTRUMENTS.md.
        """
        self.transport.write(f":SENS:REM {'ON' if on else 'OFF'}")

    # ---- timing ----
    def set_source_delay(self, seconds):
        """Settle time between sourcing a level and measuring it.

        `:TRIG:ACQ:DEL` is the trigger delay for the acquire device
        action, which is the right meaning: it sits between the source
        change and the measurement.

        UNVERIFIED ON HARDWARE: whether this delay applies to the
        `:MEAS?` spot-measurement path, or only to the `:INIT`/`:FETC`
        trigger path, is not stated in the command reference. It is on
        the bench list. The consequence of it not applying would be a
        settle that silently does not happen - readings taken before the
        source has settled, which look like ordinary noisy data.

        Deliberately not worked around by sleeping host-side: that would
        move where the settle happens, which is a measurement parameter
        rather than a UI detail, and that change is an open decision
        recorded in WAVE_PLAN rather than one to make quietly inside a
        driver.
        """
        self.transport.write(f":TRIG:ACQ:DEL {max(0.0, float(seconds)):.6f}")

    def set_nplc(self, nplc):
        """Integration time in power line cycles.

        Set on both measurement functions: the reference notes that
        NPLC and aperture share one underlying setting, so the last
        command written wins. Writing both keeps voltage and current
        integrating over the same window, which is the only way their
        ratio means anything.
        """
        value = self.clamp_nplc(nplc)
        self.transport.write(f":SENS:CURR:NPLC {value:.6g}")
        self.transport.write(f":SENS:VOLT:NPLC {value:.6g}")

    # ---- output ----
    def output_on(self):
        self.transport.write(":OUTP ON")

    def output_off(self):
        self.transport.write(":OUTP OFF")

    def set_output_off_mode(self, high_z=False):
        """What "output off" physically means.

        NORMal leaves the instrument connected across the sample;
        HIZ opens the output relay so the sample is genuinely isolated.
        The relay has a finite number of operations in it, which is why
        this is off by default and why a periodic run should not use it.
        """
        self.transport.write(f":OUTP:OFF:MODE {'HIZ' if high_z else 'NORM'}")

    # ---- measurement ----
    def read_error(self):
        """Pop one entry off the instrument's error queue.

        Code 0 means the queue was empty. A transport hiccup also
        reports 0: being unable to *ask* about errors is not evidence
        that a command failed, and treating it as one would abort runs
        over a dropped reply.
        """
        try:
            reply = self.transport.query(":SYST:ERR?", timeout_s=3.0)
        except Exception:
            return (0, "")
        if not reply:
            return (0, "")
        head, _, tail = reply.partition(",")
        try:
            return (int(float(head.strip())), tail.strip().strip('"'))
        except ValueError:
            return (0, reply.strip())

    def measure(self, timeout_s=3.0):
        """One reading, as (volts, amps).

        `:MEAS?` and not `:READ?`, for two independent reasons:

        - `:READ` and `:INIT` are the two commands that trigger the
          automatic output-on function. Reset turns that function off,
          but choosing a measurement path that was never exposed to it
          means the output state does not depend on one setup line
          having succeeded.
        - The reference states plainly that `:MEAS?` measures the
          parameters `:SENS:FUNC` specifies using conditions set
          beforehand. It is *not* the 2400 family's `MEAS?`, which is a
          hidden `:CONFigure` followed by `:READ?` and resets ranging
          and compliance on every point. That fault has turned up in two
          separate ported scripts; it does not apply here, and this
          comment exists so nobody has to re-derive that.

        The reply is counted rather than trusted. `:FORM:ELEM:SENS` was
        pinned to two elements at reset, but an instrument that accepts
        an element list, answers the query with the list it was given,
        and then sends a different shape is a fault already met on this
        bench.
        """
        reply = self.transport.query(":MEAS?", timeout_s=timeout_s)
        values = self._parse_reading(reply)
        if len(values) >= 2:
            return (values[0], values[1])
        if len(values) == 1:
            return (values[0], None)
        return (None, None)

    @classmethod
    def _parse_reading(cls, reply):
        """Numbers out of an ASCII reply, with sentinels dropped.

        A dropped sentinel becomes None rather than being omitted, so
        the column positions still line up: losing the voltage of a
        reading must not silently promote the current into its place.
        """
        if not reply:
            return []
        values = []
        for part in reply.split(","):
            try:
                number = float(part.strip())
            except ValueError:
                continue
            values.append(cls.drop_sentinel(number))
        return values

    # ---- console note ----
    def sweep_note(self):
        """What the console says about this instrument at connect.

        Three facts an operator cannot see from the panel, each of which
        has cost somebody a day somewhere: what it can actually source,
        which measurement path is in use, and whether the sense-function
        spelling was resolved.
        """
        parts = [
            "B2901A: 3 A DC / 210 V, the highest-current SMU on this bench.",
            "Software sweep (the instrument's staircase is not wired up yet).",
            "Automatic output-on disabled - the output is on only when asked.",
        ]
        if self._sense_func_note:
            parts.append(self._sense_func_note.capitalize() + ".")
        return " ".join(parts)
