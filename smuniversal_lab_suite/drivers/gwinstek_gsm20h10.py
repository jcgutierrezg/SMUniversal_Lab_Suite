"""
GW Instek GSM-20H10 Source Measure Unit - third SCPI dialect in the suite.

Ported from `IV_Meas_20H10.py`. The instrument was never named in that
script; it was identified from the commented-out resource string
`USB0::8580::125::gew852313::0::INSTR` - 8580 is 0x2184, GW Instek's USB
vendor ID, and `gew...` is their serial prefix.

Why this needs its own file
---------------------------
It is SCPI, like the 2450 and the 2401 next door, and it is *nearly*
the 2400 dialect - but "nearly" is the problem. Compare compliance:

    2450    :SOUR:VOLT:ILIM 1e-3
    2401    :SENS:CURR:PROT 1e-3
    GSM     :SENS:CURR:DC:PROT:LEV 1e-3

Three spellings of one idea. Send the wrong one and the instrument logs
an error, ignores the command, and carries on at its previous
compliance - no exception, no warning, just a sample cooked at the last
setting somebody happened to leave it on. That silent-ignore behaviour
is the entire reason drivers exist as separate files rather than one
class with `if model ==` branches.

Envelope
--------
+/-210 V, +/-1.05 A, 22 W, four-quadrant. Same corner shape as the 2450:
21 V at 1.05 A *or* 210 V at 105 mA, never both maxima at once.

Sweeps
------
Stepped from the PC, through BaseSMU's software sweep - which is what
the original script did too. The GSM has a sequence engine (linear
staircase, up to 2500 points in its buffer), and from 2026-08 to
2026-10-15 this driver ran its sweeps on it. That was retired, by the
lab's choice of consistent over fast: `TRAC:POIN:ACT?` is not answered
until the staircase has finished, so progress could not be observed
and Stop and output-off waited behind the poll for the length of the
sweep; and the staircase had cost three bench-found deviations on the
way (the buffer feed spelling, an `INIT` refused under some
configurations, and a buffer count that is the high-water mark of every
sweep since the last clear rather than this one's). See
docs/instruments/gwinstek-gsm20h10.md.
"""
from smuniversal_lab_suite.core.limits import SMULimits
from smuniversal_lab_suite.core.ranges import AUTO, NOT_SOURCED
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised

from .base_smu import BaseSMU


class GWInstekGSM20H10(BaseSMU):
    # This instrument reports "no reading" as a very large number
    # rather than as an error: +9.91e37 when a function was neither
    # sourced nor measured, +9.9e37 for an over-range reading. It was
    # the first driver here to handle that, and NAN_THRESHOLD has since
    # been promoted to BaseSMU because four other drivers turned out to
    # need it too. Inherited now; the reasoning is in base_smu.py.
    # The *IDN? reply was never captured - the original commented its
    # `*IDN?` query out. "GSM-20H10" is the model as printed; the
    # hyphenless and bare forms are fallbacks for reply strings that
    # punctuate differently. The registry prefers the longest match, so
    # the specific spelling wins wherever the full string is present.
    MODEL_IDS = ["GSM-20H10", "GSM20H10", "20H10"]
    DISPLAY_NAME = "GW Instek GSM-20H10"

    # Up to 210 V, and reset() disables its output-enable interlock: a run that can put more than 50 V on the terminals
    # starts only after the high-voltage warning has been acknowledged
    # (core/gui/high_voltage.py). Decided 2026-10-15, for every SMU here
    # that can exceed it.
    HAZARDOUS_ABOVE_V = 50.0

    # Software sweep, stepped from the PC. The staircase was retired on
    # 2026-10-15 - see the module docstring.
    SWEEP_KIND = "software"

    LIMITS = SMULimits(
        max_voltage=210.0,
        max_current=1.05,
        # Four source ranges and seven current ranges, per the manual's
        # range tables. Note there is no 20 mV range - the family starts
        # at 200 mV, unlike the 2450.
        voltage_ranges=[0.2, 2.0, 20.0, 200.0],
        current_ranges=[1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0],
        # 22 W four-quadrant: 21 V at 1.05 A, or 210 V at 105 mA
        power_envelope=[(21.0, 1.05), (210.0, 0.105)],
    )

    # Speed settings run Fast (0.01) to High (10) PLC, with anything in
    # between allowed via the manual "Other" option.
    NPLC_RANGE = (0.01, 10.0)

    # Overvoltage protection. The original pinned this at MIN with
    # `SOUR:VOLT:PROT DEF  # Higher voltage` commented out beside it, so
    # both tokens are known to be accepted. MIN stays first in the list
    # and so remains the default the panel offers - the original's
    # behaviour is preserved for anyone who doesn't touch the control.
    #
    # Overvoltage protection, now pinned down by the manual:
    #
    #   <n> = -210 to 210   any level in range (magnitude; sign ignored)
    #   NONE                disable OVP entirely
    #   MINimum             20 V      <- not "the smallest possible"
    #   DEFault / MAXimum   210 V
    #
    # Two corrections to what was here before. NONE *is* valid after all
    # - it was removed last round on the reasoning that a <n> parameter
    # wouldn't take a name, which the manual disproves. And MINimum is
    # specifically 20 V, not a floor.
    #
    # The MIN/DEF/MAX tokens are dropped from the menu in favour of the
    # numbers they stand for. They were the source of the confusion in
    # the first place, and "20 V" tells an operator what the instrument
    # will do where "MIN" does not. `IV_Meas_20H10.py` sent MIN, so 20 V
    # is first in the list and remains the default; its commented-out
    # DEF is the 210 V entry.
    #
    # The instrument accepts any level in range, not a ladder, so these
    # are conveniences rather than the permitted set.
    OVP_CHOICES = ["20", "40", "60", "80", "100", "120", "160", "200",
                   "210", "OFF"]

    # THIS INSTRUMENT DROPS COMMANDS THAT ARRIVE IN A BURST.
    #
    # Measured 2026-09-16 on V1.16 over vendor VISA, with the twenty-five
    # writes an IV sweep sends before its first query, then that query:
    #
    #   unpaced   7 of 10 never answered - not in 30 s, so not late but
    #             absent - and the 3 that did returned three DIFFERENT
    #             error queues from identical commands
    #   5 ms      10 of 10 answered, all with the same queue
    #
    # Identical input producing three outcomes is the evidence: commands
    # were being lost at random depths in the burst. When the lost one
    # was a setting, the run was configured by whatever survived; when
    # it was the query, no reply was ever generated, the read timed out,
    # the transport latched and the run was discarded.
    #
    # It is also why this went unseen for so long. `IV_Meas_20H10.py`
    # alternated a level write with a `MEAS?` and never built a burst;
    # the SCPI console, checking the error queue after every write,
    # paces itself the same way, which is why replaying a failing
    # session over it in August measured 9.9 ms and was recorded as not
    # reproducible. The suite is the only caller that sends twenty
    # commands without reading anything back.
    #
    # 5 ms is the tested value, not a measured threshold. It costs
    # 125 ms per configuration block.
    WRITE_DELAY_S = 0.005

    def __init__(self, transport):
        super().__init__(transport)
        # The fixed measurement range each axis was last asked for, or
        # None. Re-sent when that axis's compliance arrives - see
        # `_resend_measure_range()`.
        self._measure_ranges = {"current": None, "voltage": None}

    # ---- identity and housekeeping ----
    def reset(self):
        """Reset, clear the error queue, and re-enable the beeper.

        `SYST:CLE` empties the error queue specifically - distinct from
        `*CLS`, which clears the status registers. Both are sent so the
        error queue starts from a known-empty one.

        `OUTP:ENAB 0` disables the interlock line, matching the original
        and the 2401 driver next door. Without it an instrument with
        nothing wired to the interlock refuses to turn its output on.
        """
        self.transport.write("*CLS")
        self.transport.write("*RST")
        self.transport.write("SYST:CLE")
        self.transport.write("SYST:BEEP:STAT 1")
        self.transport.write("OUTP:ENAB 0")
        # Output-off mode is NOT set here. It is a per-run choice
        # driven from the panel via set_output_off_mode(), because the
        # manual warns against HIMPedance "for tests that turn the
        # output on and off frequently" and iv_sweep's periodic mode
        # does exactly that. *RST leaves this at NORMal, which is the
        # default the panel also offers.
        # NPLC is only worth setting if the instrument knows the mains
        # frequency - integrating over "one cycle" cancels hum only when
        # the cycle length is right. Auto-detect rather than hardcoding
        # 50 Hz, so this survives the rig being taken anywhere else.
        self.transport.write("SYST:LFR:AUTO 1")
        self.transport.write("SOUR:CLE:AUTO 0")
        self.transport.write("ROUT:TERM FRON")
        # Disarm buffer storage. Nothing here uses the buffer since the
        # staircase sweep was retired, and *RST is supposed to leave
        # storage off - but this instrument was found with it armed, so
        # it is turned off by name rather than by assumption, once,
        # where it costs nothing.
        self.transport.write("TRAC:FEED:CONT NEV")
        # Fix what a reading contains, rather than inheriting whatever
        # the front panel was left showing. Two fields, voltage first -
        # which is the order the original's MEAS? parsing assumed but
        # never actually set.
        self.transport.write("FORM:ELEM VOLT,CURR")
        # *RST discarded the ranges; re-sending a remembered one after
        # it would configure a setting nobody asked for since (fault 6).
        self._measure_ranges = {"current": None, "voltage": None}

    def read_error(self):
        """Pop one entry off the instrument's error queue.

        Returns (code, message). Code 0 means the queue was empty, i.e.
        everything sent so far was understood. A transport hiccup is
        reported as code 0 as well: failing to *read* the error queue is
        not evidence that a command failed, and treating it as such
        would disable the hardware sweep over a dropped reply.
        """
        try:
            reply = self.transport.query("SYST:ERR?", timeout_s=3.0)
        except TransportDesynchronised:
            raise
        except Exception:
            return (0, "")
        if not reply:
            return (0, "")
        head, _, tail = reply.partition(",")
        try:
            return (int(float(head.strip())), tail.strip().strip('"'))
        except ValueError:
            return (0, reply.strip())

    # ---- source configuration ----
    def set_source_function(self, mode):
        # Both sense functions stay on, with concurrent measurement
        # enabled, regardless of which quantity is being sourced.
        #
        # This matters more than it looks. With CONCurrent off, only one
        # function is actually measured and the other element of the
        # reply is filled in from the *source setting* rather than from
        # a measurement. Sourcing 1 V into a 4-wire rig, the voltage
        # field would read back exactly 1.000000 V - the number that was
        # asked for, not the number across the sample - so lead and
        # contact drops would vanish from the data and 4-wire sensing
        # would silently become a very convincing 2-wire measurement.
        #
        # The original never set this, so whatever the front panel was
        # last left in decided it.
        self.transport.write("SENS:FUNC:CONC ON")
        self.transport.write('SENS:FUNC:ON "VOLT","CURR"')

        if mode == "current":
            self.transport.write("SOUR:FUNC CURR")
        elif mode == "voltage":
            self.transport.write("SOUR:FUNC VOLT")
        else:
            raise ValueError(f"Unknown source mode: {mode!r}")
        # Hold the level between points instead of dropping to zero and
        # settling again, as the original did for both directions.
        self.transport.write("SOUR:CLE:AUTO 0")
        # A range remembered under the other function must not follow a
        # limit into this one. Setting the measurement range of the
        # quantity being sourced is `+823` here, and a plan for the new
        # function will say which ranges it wants.
        self._measure_ranges = {"current": None, "voltage": None}

    #: Counts across one source range, measured 2026-09-01.
    #:
    #: `tools/bench_envelope.py` pinned the source current range to
    #: 1e-4 A and halved down. The sign stopped being followed below
    #: **3.052e-09 A**, and
    #:
    #:     1e-4 A / 32768 = 3.0518e-09 A
    #:
    #: so the measured floor is one count of the range the sweep was on.
    #:
    #: This instrument is also the reason the *procedure* that produced
    #: the number can be believed. On 2026-08-28 an earlier version of
    #: the sweep reported "sign follows" for twenty-one halvings down to
    #: 95 pA on readings that never left +140 uA and +20 uA - a fixed
    #: offset sitting inside a window that shrank with the level. The
    #: bound that fixed it, and that the 09-01 figures were taken under,
    #: is in `sign_is_commanded()`: the two legs must land on opposite
    #: sides of zero and separate by about 2L, not merely by more than
    #: L.
    #:
    #: Current only. The bench procedure sources current and only
    #: current, so the voltage axis stays `unmeasured`.
    SOURCE_COUNTS_PER_RANGE = {"current": 32768, "voltage": None}

    SUB_COUNT_LEVELS = {"current": BaseSMU.SUB_COUNT_REFUSED,
                        "voltage": BaseSMU.SUB_COUNT_UNMEASURED}

    def set_current_level(self, amps):
        self.guard_source_level("current", amps, "A")
        self.transport.write(f"SOUR:CURR {amps:.6e}")

    def set_voltage_level(self, volts):
        # The original rounded each level to 4 decimals before sending
        # (`round(Vo + i*step, 4)`). Not reproduced: on the 200 mV range
        # that quantises the sweep to 0.1 mV steps, which is 100x coarser
        # than the instrument's 1 uV programming resolution. Same
        # decision, and same reasoning, as the 2401 driver.
        self.transport.write(f"SOUR:VOLT {volts:.6e}")

    def set_current_limit(self, amps):
        """Current compliance while sourcing voltage.

        This is the setting the original's dropdown drove - labelled
        "current range" in that GUI, but it is a compliance level.
        """
        self.transport.write(f"SENS:CURR:DC:PROT:LEV {amps:.6e}")
        self._resend_measure_range("current")

    def set_voltage_limit(self, volts):
        """Voltage compliance while sourcing current - the mirror of
        the above, and the one the original never used because it only
        ever swept voltage."""
        self.transport.write(f"SENS:VOLT:DC:PROT:LEV {volts:.6e}")
        self._resend_measure_range("voltage")

    def _resend_measure_range(self, quantity):
        """Send the remembered measurement range again, now its limit is in.

        ON THIS INSTRUMENT NEITHER ORDER IS SAFE ON ITS OWN.

        A limit sent before its range is clamped to the range in force -
        fault 15, and the reason every experiment ranges first. But a
        range sent before its limit is refused if it is wider than the
        compliance already there: `+824 Cannot exceed compliance range`,
        and the instrument **stays on the narrower range**. After `*RST`
        the current compliance is 105 uA, so an IV sweep asking for a
        100 mA measurement range had it refused on every first run after
        a connect, and measured current on 105 uA - overranging into a
        sentinel above that. Seen on 2026-08-20 at 10 uA, and named
        against `SENS:CURR:DC:RANG 1.000000e-01` on 2026-09-16, three
        runs out of three. It went unnoticed because the error-queue
        read that would have reported it was the query this instrument
        kept dropping.

        So the range goes first, as fault 15 requires, and again once
        the limit that has to hold it has arrived. Whatever order a
        caller uses, the second send meets the compliance the caller
        chose. If that compliance is narrower than the range, the
        second send is refused too and the narrower range stands -
        which is right: the compliance is the protection, and a range
        wider than it would only report readings the limit will never
        let happen.

        The first refusal stays in the error queue as `+824`. It is a
        true record of what the instrument did, and the range that
        matters is the one in force afterwards, which the checkup reads
        back.

        Only a fixed range is remembered. AUTO needs nothing re-sent,
        and a source axis is never touched here: `SOUR:CURR:RANG:AUTO`
        is the command that collapses this instrument's compliance
        (fault 23).

        The voltage axis is the mirror and is unmeasured. It is done
        anyway because the 2026-09-11 readback session asked for a 200 V
        measure-voltage range with the reset compliance of 21 V in
        force, saw it not taken, and did not read the queue - which is
        this refusal, if the rule is symmetric. The round's checkup
        answers that.
        """
        remembered = self._measure_ranges.get(quantity)
        if remembered is None:
            return
        axis = "CURR" if quantity == "current" else "VOLT"
        self.transport.write(f"SENS:{axis}:DC:RANG {remembered:.6e}")

    #: Verified at the bench, 2026-08-20. `SENS:CURR:DC:PROT:LEV?`
    #: returned `+1.050000e-04` after `*RST` - matching the manual's
    #: factory-defaults table - and `+1.000000e-09` immediately after
    #: `SOUR:CURR:RANG:AUTO ON`, matching the collapse that was then
    #: reproduced repeatedly in both source functions.
    #:
    #: Trusted despite `OUTP?` on this same instrument returning 0 with
    #: the output on and 10 V flowing. The two are different queries and
    #: the compliance one was checked directly against values known from
    #: two independent sources; the output one was believed for five
    #: rounds and never checked, which is the whole reason this flag
    #: exists.
    COMPLIANCE_READBACK_TRUSTED = True

    def _read_compliance(self, query):
        """One float from a compliance query, or `None`.

        Local rather than shared: the U2722A has a `_read_number` of its
        own that applies `drop_sentinel`, which is right for a
        *measurement* and wrong here. A compliance is a setting - if it
        ever came back as the no-reading sentinel that would be a fault
        to report, not a value to discard.
        """
        try:
            reply = self.transport.query(query, timeout_s=3.0)
            return float(str(reply).strip().split(",")[0])
        except TransportDesynchronised:
            raise
        except Exception:
            return None

    def read_current_limit(self):
        return self._read_compliance("SENS:CURR:DC:PROT:LEV?")

    def read_voltage_limit(self):
        return self._read_compliance("SENS:VOLT:DC:PROT:LEV?")

    # ---- ranging ----
    # ---- ranging: per-axis (wave 6d) ----
    def _render_not_sourced(self, value):
        """Send nothing on a source axis that is carrying nothing.

        `SOUR:CURR:RANG:AUTO ON` while sourcing voltage silently resets
        the current compliance from 105 uA to **1 nA**, and
        `SOUR:VOLT:RANG:AUTO ON` while sourcing current takes the
        voltage compliance from 21 V to 200 uV. Measured 2026-08-20,
        repeatable, in both source functions, with a clean error queue
        across the command that does it - see fault 23.

        The `+824` and `+826` errors that led to this were consequences
        landing on later, innocent commands: with the compliance at
        1 nA, narrowing a measurement range to 100 uA genuinely does
        exceed it. That is why `+826 Attempt to exceed power limit`
        appeared on a microwatt and never made sense.

        Runs were surviving it only because fault 15's ordering puts
        the experiment's own compliance *after* the ranging block, which
        restored it by accident rather than by design.

        Returning `None` means the hook makes no call at all. The
        instrument keeps whatever source range it had, which is correct:
        no level of that quantity will be sourced.
        """
        return None if value is NOT_SOURCED else value

    def _apply_source_current_range(self, amps):
        """Source ranging confirmed present; autorange ON at reset."""
        if amps is None:
            return          # not sourced - see _render_not_sourced
        if amps is AUTO:
            self.transport.write("SOUR:CURR:RANG:AUTO ON")
        else:
            self.transport.write("SOUR:CURR:RANG:AUTO OFF")
            self.transport.write(f"SOUR:CURR:RANG {amps:.6e}")

    def _apply_source_voltage_range(self, volts):
        if volts is None:
            return          # not sourced - see _render_not_sourced
        if volts is AUTO:
            self.transport.write("SOUR:VOLT:RANG:AUTO ON")
        else:
            self.transport.write("SOUR:VOLT:RANG:AUTO OFF")
            self.transport.write(f"SOUR:VOLT:RANG {volts:.6e}")

    def _apply_measure_current_range(self, amps):
        if amps is AUTO:
            self._measure_ranges["current"] = None
            self.transport.write("SENS:CURR:DC:RANG:AUTO ON")
        else:
            # Remembered before it is sent: it may be refused against
            # the compliance in force. See _resend_measure_range().
            self._measure_ranges["current"] = amps
            self.transport.write("SENS:CURR:DC:RANG:AUTO OFF")
            self.transport.write(f"SENS:CURR:DC:RANG {amps:.6e}")

    def _apply_measure_voltage_range(self, volts):
        if volts is AUTO:
            self._measure_ranges["voltage"] = None
            self.transport.write("SENS:VOLT:DC:RANG:AUTO ON")
        else:
            self._measure_ranges["voltage"] = volts
            self.transport.write("SENS:VOLT:DC:RANG:AUTO OFF")
            self.transport.write(f"SENS:VOLT:DC:RANG {volts:.6e}")

    #: The measurement-range readback, whose spelling came off this
    #: instrument rather than out of a manual: on 2026-08-20 asking for
    #: `SENS:CURR:DC:RANG 1.000000e-04` with the compliance at 10 uA
    #: gave `+824` and left `SENS:CURR:DC:RANG?` reading
    #: `1.050000E-05` - a range the operator did not choose, with no
    #: exception raised. That observation is the reason this exists and
    #: is also why it is **not** trusted: it shows the query answers and
    #: answers meaningfully, and it does not show the answer being
    #: checked against a range known independently.
    #:
    #: 2026-09-11 closed half of it. Measure current passed every leg
    #: of `tools/bench_readback.py`: it named a range set from the
    #: front panel and followed two bus changes. Measure voltage named
    #: the front-panel range but stayed on it when the bus asked for
    #: 200 V; the error queue was not read, so why is not known. The
    #: flag covers both axes, so it stays False.
    #:
    #: The two *source* range queries are deliberately absent. Nothing
    #: has ever asked this instrument for one, `SOUR:CURR:RANG:AUTO` is
    #: the command that silently resets its compliance (fault 23), and
    #: an unanswered query latches the transport - so a guess costs a
    #: run rather than a line in a report.
    RANGE_READBACK_TRUSTED = False

    def read_measure_current_range(self):
        return self._read_setting("SENS:CURR:DC:RANG?")

    def read_measure_voltage_range(self):
        return self._read_setting("SENS:VOLT:DC:RANG?")

    def _read_setting(self, query):
        """One float from a settings query, or `None`.

        Same shape and same reasoning as `_read_compliance` above, and
        deliberately not that method: a range and a compliance are
        different subsystems whose queries were confirmed at different
        times, and sharing a reader would let one's verification be read
        as the other's.
        """
        try:
            reply = self.transport.query(query, timeout_s=3.0)
            return float(str(reply).strip().split(",")[0])
        except TransportDesynchronised:
            raise
        except Exception:
            return None

    # ---- sensing ----
    def set_remote_sense(self, on=True):
        self.transport.write(f"SYST:RSEN {1 if on else 0}")

    def set_terminals(self, which="front"):
        """Front or rear terminals. Not part of BaseSMU - plenty of SMUs
        have no such switch. Note the output drops when this changes."""
        self.transport.write(
            f"ROUT:TERM {'FRON' if which == 'front' else 'REAR'}")

    # ---- protection ----
    def set_voltage_protection(self, choice):
        """Set the OVP ceiling.

        Distinct from compliance, and worth keeping straight: compliance
        limits the quantity you are *not* sourcing, whereas OVP is a
        hard ceiling on the source itself. The case it exists for is a
        4-wire sense lead falling off mid-run - the instrument sees 0 V
        at the sample, assumes it is undershooting, and winds the output
        up to compensate. OVP is what stops that at a chosen level
        instead of at the instrument's 210 V maximum.
        """
        token = str(choice).strip().upper()
        if token in ("OFF", "NONE", "DISABLE", ""):
            token = "NONE"
        self.transport.write(f"SOUR:VOLT:PROT {token}")

    #: Which protection trip reports compliance, per sourced quantity.
    #: The limit is always on the quantity you are NOT setting, and this
    #: instrument's manual says so in as many words: ":CURRent:
    #: PROTection:TRIPped? is used to check the compliance state of the
    #: V-Source, and the :VOLTage:PROTection:TRIPped? Command is used to
    #: check the compliance state of the I-Source."
    #:
    #: Same table, word for word, in the Keithley 2401 manual, so this
    #: is the SCPI convention rather than a GW Instek quirk - which is
    #: why the B2901A carries the same map under its own spellings.
    _TRIP_QUERY = {"VOLT": "SENS:CURR:DC:PROT:TRIP?",
                   "CURR": "SENS:VOLT:DC:PROT:TRIP?"}

    def compliance_tripped(self):
        """Ask the protection trip belonging to the quantity NOT sourced.

        This used to query both axes and OR them, on the argument that
        it cost one extra query and removed a way to get the answer
        wrong when the mode and the tripped function disagreed. Against
        the documented meaning of these queries it *added* one: on a
        voltage source, `SENS:VOLT:DC:PROT:TRIP?` reports the I-Source,
        which is not running. If that flag holds a value from the last
        time it was, the OR returns True for a clamp that is not
        happening - and the checkup's clamping check would then pass on
        a stale flag while the mechanism the experiments rely on was
        broken. A check that passes for free is worse than no check.

        (Whether these flags latch is still unmeasured; the manual's
        entry has no *Affected by* column. Selecting the axis makes the
        question moot for this answer, because the inactive flag is
        never read. It is still worth a probe: source current into an
        open circuit until it rides the voltage limit, then switch to
        sourcing voltage with nothing clamping and read both. The
        interesting answer is the second one.)

        The sourced function is read from the instrument rather than
        remembered, for the same reason the B2901A reads it: a local
        copy is one `reset()` or one front-panel change away from being
        wrong, and being wrong here means a confident False, which is
        worse than no answer.

        `MEMory` is a third source mode on this model - a saved sequence
        of setups, recalled in turn - and in it neither trip query
        describes what the instrument is doing. That returns None, which
        the report renders as "cannot say" rather than as a reassurance.
        """
        try:
            mode = self.transport.query("SOUR:FUNC?", timeout_s=3.0)
        except TransportDesynchronised:
            raise
        except Exception:
            return None
        # Long or short form, quoted or bare: `VOLTage`, `VOLT`, `"VOLT"`
        # are all the same answer.
        key = str(mode).strip().strip('"').upper()[:4]
        query = self._TRIP_QUERY.get(key)
        if query is None:
            return None                    # MEMory, or a reply we cannot read
        try:
            reply = self.transport.query(query, timeout_s=3.0)
            return bool(int(float(str(reply).strip().split(",")[0])))
        except TransportDesynchronised:
            raise
        except Exception:
            return None

    # ---- timing ----
    def set_source_delay(self, seconds):
        """Source delay in SECONDS, 0 to 999.9999 on this model.

        (An earlier comment here said 9999.999 - off by a factor of ten.
        The manual's figure is 999.9999, with a *RST default of 1 ms.)

        Auto delay is turned off first: left on, the instrument picks
        its own settle time from the selected range and ignores the
        value being set here, so a delay typed into the panel would do
        nothing.
        """
        self.transport.write("SOUR:DEL:AUTO 0")
        value = min(max(float(seconds), 0.0), 999.9999)
        self.transport.write(f"SOUR:DEL {value:.5f}")

    def set_nplc(self, nplc):
        """Integration time, on both sense functions.

        Note the `:DC:` infix - this family spells the sense subsystem
        `SENS:CURR:DC:...` where the 2450 and 2401 use `SENS:CURR:...`.
        The original sent `SENS:CURR:DC:NPLC 1` and it worked, which
        pins the spelling for the current side; the voltage side is the
        matching form.
        """
        value = self.clamp_nplc(nplc)
        self.transport.write(f"SENS:CURR:DC:NPLC {value:.4f}")
        self.transport.write(f"SENS:VOLT:DC:NPLC {value:.4f}")

    # ---- output ----
    def output_on(self):
        self.transport.write("OUTP 1")

    def output_off(self):
        self.transport.write("OUTP 0")

    HIGH_Z_OFF = True

    def set_output_off_mode(self, high_z=False):
        """HIMPedance opens the output relay; NORMal sources 0 V.

        ZERO and GUARd also exist on this model and are not exposed -
        ZERO is for generating 0 V/level waveforms with auto-clear, and
        GUARd is for 6-wire guarded ohms. Neither is what any experiment
        here is doing, and offering four options where two are wanted
        makes the common choice harder to see.
        """
        self.transport.write(
            f"OUTP:SMOD {'HIMP' if high_z else 'NORM'}")

    def beep(self, hertz=500, seconds=2):
        """Sound the front-panel beeper.

        The original beeped at the end of every sweep - genuinely useful
        when a long run is going and you are across the room. Exposed
        here rather than fired automatically, so the experiment decides.
        """
        self.transport.write(f"SYST:BEEP:IMM {int(hertz)},{int(seconds)}")

    # ---- measurement ----
    def measure(self, timeout_s=3.0):
        """One reading as (volts, amps).

        `READ?`, not `MEAS?` - and this is a change from the original.
        # DEVIATION 11

        `MEAS?` on this family means "configure, then read": it resets
        the ranging and compliance that were just set, on every single
        point of the sweep. `IV_Meas_20H10.py` set
        `SENS:CURR:DC:PROT:LEV` once before its loop and then called
        `MEAS?` at each point, so the compliance it carefully chose was
        being undone before the very first reading.

        Exactly the same fault was found in the 2401 original and fixed
        the same way - see docs/faults/01-meas-per-point.md. `READ?`
        triggers a reading against the configuration already in place,
        which is what a sweep wants.

        Pairs with `FORM:ELEM VOLT,CURR` in reset(), which fixes the
        reply to two fields in that order.
        """
        reply = self.transport.query("READ?", timeout_s=timeout_s)
        return self._parse_reading(reply)

    @classmethod
    def _clean(cls, value):
        """Map the instrument's NAN/overflow sentinels to None."""
        if value is None:
            return None
        return None if abs(value) >= cls.NAN_THRESHOLD else value

    @classmethod
    def _parse_reading(cls, reply):
        """Pull the leading numbers out of a reading reply as
        (voltage, current), with sentinels mapped to None."""
        if not reply:
            return (None, None)
        sep = "," if "," in reply else None
        parts = reply.split(sep) if sep else reply.split()
        nums = []
        for p in parts:
            try:
                nums.append(float(p))
            except ValueError:
                stripped = "".join(
                    ch for ch in p if (ch.isdigit() or ch in ".-+eE"))
                try:
                    nums.append(float(stripped))
                except ValueError:
                    pass
        if len(nums) >= 2:
            return (cls._clean(nums[0]), cls._clean(nums[1]))
        if len(nums) == 1:
            return (cls._clean(nums[0]), None)
        return (None, None)

    # ---- sweeps ----
    def sweep_note(self):
        """What the console says about this instrument at connect."""
        return ("GSM-20H10: software sweep, stepped from the PC (the "
                "instrument's staircase is not used - see its note).")
