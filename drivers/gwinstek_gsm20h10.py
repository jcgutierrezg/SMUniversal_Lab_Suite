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
Unlike the 2401 - whose hardware sweep the original script abandoned -
this one is implemented, because the GSM has a genuine sequence engine
(linear staircase, log staircase, custom, SRC-MEM; up to 2500 points).
The original script never touched it and stepped the source from Python
instead, which is why `sweep_kind` matters here: two runs off the same
instrument can now have been taken two different ways.

**The staircase command spellings are an inference and are verified at
runtime rather than trusted.** They are the standard 2400-family
sequence commands, which is what the GSM's documented command
compatibility implies, but nobody has confirmed them against this
instrument on a bench. So `_probe_sweep_support()` sends one distinctive
sweep command at connect and then reads the error queue: if the
instrument complains, the driver quietly reports itself as
`sweep_kind() == "software"` and inherits the point-by-point fallback
from BaseSMU. The failure mode this defends against is precisely the
silent-ignore described above - the difference is that here the driver
*asks* whether it was understood instead of assuming.

If the probe turns out to be wrong in either direction, the fix is in
this file and nothing in experiments/ changes.
"""
from core.limits import SMULimits
from core.ranges import AUTO
from .base_smu import BaseSMU


# Reading buffer capacity, from the command list. The staircase
# stores one reading per sweep point, so this is also the largest
# hardware sweep the instrument can run in one go.
MAX_BUFFER_POINTS = 2500

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

    # Provisional: downgraded to "software" by the connect-time probe if
    # the instrument doesn't recognise the staircase commands. See
    # sweep_kind() below - it is an instance method on this driver, not
    # the class-level constant the other drivers use, because the answer
    # is only known once there is something on the other end of the wire.
    SWEEP_KIND = "hardware"

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

    def __init__(self, transport):
        super().__init__(transport)
        # None until probed; then "hardware" or "software".
        self._sweep_mode = None
        self._sweep_points = 0
        self._sweep_note = ""
        self._feed_token = None
        self._buffer_stride = None

    # ---- identity and housekeeping ----
    def reset(self):
        """Reset, clear the error queue, and re-enable the beeper.

        `SYST:CLE` empties the error queue specifically - distinct from
        `*CLS`, which clears the status registers. Both are sent because
        the sweep probe below reads the error queue and needs to start
        from a known-empty one.

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
        # Disarm buffer storage. The command list is explicit that
        # `TRACe:FEED cannot be changed while buffer storage is active`,
        # and a sweep setup has to change it. *RST is supposed to leave
        # storage off, but this instrument was rejecting `TRAC:FEED`
        # anyway - so it is turned off by name rather than by
        # assumption, once, where it costs nothing.
        self.transport.write("TRAC:FEED:CONT NEV")
        # Fix what a reading contains, rather than inheriting whatever
        # the front panel was left showing. Two fields, voltage first -
        # which is the order the original's MEAS? parsing assumed but
        # never actually set.
        self.transport.write("FORM:ELEM VOLT,CURR")
        self._sweep_mode = None

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
        except Exception:
            return (0, "")
        if not reply:
            return (0, "")
        head, _, tail = reply.partition(",")
        try:
            return (int(float(head.strip())), tail.strip().strip('"'))
        except ValueError:
            return (0, reply.strip())

    def _drain_errors(self):
        """Empty the error queue, returning everything found.

        `:SYST:ERR:ALL?` returns the whole queue in one reply, which the
        original bounded polling loop was a workaround for not knowing
        about. One round trip instead of up to ten, and no risk of an
        instrument that errors on every query spinning here.

        Reply shape is repeated `code,"message"` pairs, so the split is
        on commas and the codes are whatever parses as a number.
        """
        try:
            reply = self.transport.query("SYST:ERR:ALL?", timeout_s=3.0)
        except Exception:
            return []
        if not reply:
            return []

        found = []
        parts = [p.strip() for p in str(reply).split(",")]
        i = 0
        while i < len(parts):
            try:
                code = int(float(parts[i]))
            except (ValueError, IndexError):
                i += 1
                continue
            message = parts[i + 1].strip('"') if i + 1 < len(parts) else ""
            if code != 0:
                found.append((code, message))
            i += 2
        return found

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

    def set_current_level(self, amps):
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

    def set_voltage_limit(self, volts):
        """Voltage compliance while sourcing current - the mirror of
        the above, and the one the original never used because it only
        ever swept voltage."""
        self.transport.write(f"SENS:VOLT:DC:PROT:LEV {volts:.6e}")

    # ---- ranging ----
    # ---- ranging: per-axis (wave 6d) ----
    def _apply_source_current_range(self, amps):
        """Source ranging confirmed present; autorange ON at reset."""
        if amps is AUTO:
            self.transport.write("SOUR:CURR:RANG:AUTO ON")
        else:
            self.transport.write("SOUR:CURR:RANG:AUTO OFF")
            self.transport.write(f"SOUR:CURR:RANG {amps:.6e}")

    def _apply_source_voltage_range(self, volts):
        if volts is AUTO:
            self.transport.write("SOUR:VOLT:RANG:AUTO ON")
        else:
            self.transport.write("SOUR:VOLT:RANG:AUTO OFF")
            self.transport.write(f"SOUR:VOLT:RANG {volts:.6e}")

    def _apply_measure_current_range(self, amps):
        if amps is AUTO:
            self.transport.write("SENS:CURR:DC:RANG:AUTO ON")
        else:
            self.transport.write("SENS:CURR:DC:RANG:AUTO OFF")
            self.transport.write(f"SENS:CURR:DC:RANG {amps:.6e}")

    def _apply_measure_voltage_range(self, volts):
        if volts is AUTO:
            self.transport.write("SENS:VOLT:DC:RANG:AUTO ON")
        else:
            self.transport.write("SENS:VOLT:DC:RANG:AUTO OFF")
            self.transport.write(f"SENS:VOLT:DC:RANG {volts:.6e}")


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

    def compliance_tripped(self):
        """Ask whether either protection limit was reached.

        Both are checked rather than just the one matching the source
        mode: it costs one extra query and removes a way to get this
        wrong when the mode and the tripped function disagree.
        """
        for query in ("SENS:CURR:DC:PROT:TRIP?", "SENS:VOLT:DC:PROT:TRIP?"):
            try:
                reply = self.transport.query(query, timeout_s=3.0)
            except Exception:
                return None
            try:
                if int(float(str(reply).strip().split(",")[0])):
                    return True
            except (ValueError, IndexError):
                return None
        return False

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
        the same way - see the 2401 driver and PORTING_NOTES. `READ?`
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
    def sweep_kind(self):
        """'hardware' or 'software', probed rather than declared.

        Deliberately an *instance* method here where every other driver
        uses the class-level SWEEP_KIND constant, because on this model
        the honest answer isn't known until an instrument has been asked.
        Calling GWInstekGSM20H10.sweep_kind() on the class will not work;
        nothing does, and the alternative - claiming "hardware" and
        finding out mid-run - is worse.
        """
        if self._sweep_mode is None:
            self._probe_sweep_support()
        return self._sweep_mode

    def sweep_note(self):
        """Human-readable outcome of the probe, for the console."""
        if self._sweep_mode is None:
            self._probe_sweep_support()
        return self._sweep_note

    def _probe_sweep_support(self):
        """Ask the instrument whether it understands the staircase
        commands, and remember the answer.

        Two commands, both harmless on their own - a spacing mode and a
        point count, neither of which sources anything. The error queue
        is drained first so anything found afterwards is attributable to
        the probe rather than to whatever was sent before it.
        """
        try:
            self._drain_errors()
            self.transport.write("SOUR:SWE:SPAC LIN")
            self.transport.write("SOUR:SWE:POIN 2")
            complaints = self._drain_errors()
        except Exception as exc:
            self._sweep_mode = "software"
            self._sweep_note = (
                f"sweep probe failed ({exc}); using the point-by-point "
                f"software sweep")
            return

        if complaints:
            code, message = complaints[0]
            self._sweep_mode = "software"
            self._sweep_note = (
                f"instrument rejected the staircase commands "
                f"({code}: {message}); using the point-by-point software "
                f"sweep instead")
        else:
            self._sweep_mode = "hardware"
            self._sweep_note = ("instrument staircase sweep accepted "
                                "(runs off the SMU's own timebase)")

    def start_linear_sweep(self, mode, start, stop, points, delay_s):
        """Begin a linear staircase sweep and return immediately.

        Falls through to BaseSMU's software sweep when the probe said
        the instrument won't take these commands, so the caller gets a
        working sweep either way and never branches on the answer.
        """
        if self.sweep_kind() != "hardware":
            return super().start_linear_sweep(mode, start, stop, points,
                                              delay_s)

        if mode == "voltage":
            source = "VOLT"
        elif mode == "current":
            source = "CURR"
        else:
            raise ValueError(f"Unknown sweep mode: {mode!r}")

        points = int(points)
        if points < 2:
            raise ValueError("A sweep needs at least 2 points.")
        if points > MAX_BUFFER_POINTS:
            # The buffer tops out at 2500 readings and the staircase
            # stores one per point. Caught here with a message naming
            # the limit, rather than at `TRAC:POIN` where the
            # instrument's own complaint would be a bare error code
            # attached to a command the operator never typed.
            raise ValueError(
                f"The {self.DISPLAY_NAME} buffer holds at most "
                f"{MAX_BUFFER_POINTS} readings; {points} points were "
                f"requested. Use fewer points, or split the sweep.")
        self._sweep_points = points
        self._last_sweep_mode = mode

        # Resolved BEFORE the error queue is cleared for the staircase.
        # It probes by writing and checking the queue, so running it
        # mid-setup would swallow a complaint about an earlier command -
        # and the setup check at the end would then see a clean queue
        # and fire a half-configured sweep. That is precisely the
        # failure the check exists to catch.
        feed = self._buffer_feed_command()

        self._drain_errors()

        # Staircase definition. Start/stop/points rather than a step
        # size: a step that doesn't divide the span exactly leaves the
        # last point somewhere unintended, and the experiment already
        # thinks in points.
        setup = [
            f"SOUR:{source}:STAR {float(start):.6e}",
            f"SOUR:{source}:STOP {float(stop):.6e}",
            "SOUR:SWE:SPAC LIN",
            f"SOUR:SWE:POIN {points}",
            "SOUR:SWE:DIR UP",
        ]
        for command in setup:
            self.transport.write(command)
        # UP means "start level to stop level", NOT "ascending".
        # Confirmed against the command list, which is unambiguous:
        # "Normally, a sweep is run from the start level to the stop
        # level... With DOWn selected, the sweep will begin at the stop
        # level and end at the start level. Selecting UP restores sweep
        # operation to the normal start to stop direction."
        #
        # So a descending sweep is expressed as start > stop with
        # DIRection left at UP; DOWn would reverse it back again and run
        # the sweep the wrong way round, silently returning the data
        # backwards. The panel allows start > stop, so this is
        # load-bearing.
        # BEST picks one fixed range covering the whole sweep. AUTO
        # would range-change mid-sweep, and each change carries its own
        # settling time - which is exactly the timing consistency the
        # hardware sweep is being used for in the first place.
        setup += ["SOUR:SWE:RANG BEST", f"SOUR:{source}:MODE SWE"]
        self.transport.write("SOUR:SWE:RANG BEST")
        self.transport.write(f"SOUR:{source}:MODE SWE")

        setup.append(f"SOUR:DEL {max(float(delay_s), 0.0):.5f}")
        self.transport.write(f"SOUR:DEL {max(float(delay_s), 0.0):.5f}")
        # Total readings is arm count MULTIPLIED BY trigger count, not
        # the trigger count alone. *RST leaves arm count at 1, but this
        # driver never assumes the instrument was reset by us - a stale
        # arm count of 2 would run the whole sweep twice and overfill
        # the buffer, with no error to say so.
        for command in ("ARM:COUN 1", f"TRIG:COUN {points}",
                        # Storage OFF before anything about the buffer
                        # is changed. The command list: "TRACe:FEED
                        # cannot be changed while buffer storage is
                        # active." Every sweep arms storage with
                        # `CONT NEXT` at the end of this block, so from
                        # the second sweep onward it is still armed when
                        # the next one starts - and the feed command is
                        # refused, taking the whole staircase setup down
                        # with it.
                        "TRAC:FEED:CONT NEV",
                        "TRAC:CLE", f"TRAC:POIN {points}", feed,
                        # Elements BEFORE storage is armed. On this
                        # instrument, sent after `CONT NEXT` it is
                        # accepted, queues no error, and has no effect -
                        # the buffer still came back with a resistance
                        # column. Same shape as the TRACe:FEED rule the
                        # manual states outright.
                        "FORM:ELEM VOLT,CURR", "TRAC:FEED:CONT NEXT"):
            # Buffer: storage off, cleared, sized, fed, then armed.
            # Sizing before feeding matters too - the instrument won't
            # resize a buffer that already holds readings.
            setup.append(command)
            self.transport.write(command)

        complaints = self._drain_errors()
        if complaints:
            # Configuration was refused after the probe passed. Rather
            # than fire a sweep that has been half-configured, drop to
            # the software path for this run and every run after it.
            code, message = complaints[0]
            culprit = self._find_rejected_command(setup)
            self._sweep_mode = "software"
            self._sweep_note = (
                f"staircase setup rejected ({code}: {message})"
                + (f" on `{culprit}`" if culprit else "")
                + "; switched to the point-by-point software sweep")

            # THE SOURCE MUST COME OUT OF SWEEP MODE FIRST.
            #
            # This was the bug the bench found. `SOUR:<x>:MODE SWE` had
            # already been sent by the time the setup was refused, and
            # falling straight through to the software sweep left it
            # there. The software sweep steps by sending
            # `SOUR:VOLT <level>` - which, in SWE mode, the instrument
            # reads as a sweep *endpoint* rather than a level to hold.
            #
            # So the source never moved. The run completed, returned
            # the right number of points, reported no error, and every
            # point sat at 0 V. A flat line from a working instrument,
            # with the fallback that was supposed to rescue the run
            # being the thing that broke it.
            self._restore_fixed_source(source)
            return super().start_linear_sweep(mode, start, stop, points,
                                              delay_s)

        self.transport.write("INIT")

    # Feed-source tokens, in the order they are tried.
    #
    # The command list documents the parameter as `SENSe1` and gives
    # `:TRACe:FEED SENSe1` as its example. By SCPI convention the
    # capitals are the short form, so `SENS1` should be equivalent - but
    # the error this instrument returned was **-140, Character data
    # error**, which is specifically a complaint about the *parameter*,
    # not about the instrument's state. A settings conflict would
    # normally be -221.
    #
    # So both readings stay in play and both are covered:
    #
    #   SENS1   documented short form, tried first
    #   SENSe1  the long form exactly as the manual prints it, in case
    #           this implementation matches literally rather than
    #           honouring the abbreviation
    #   SENS    un-numbered, in case the suffix is the problem
    #
    # Separately, the manual also states that "TRACe:FEED cannot be
    # changed while buffer storage is active", and the setup was arming
    # storage with `CONT NEXT` and never turning it off - so a rejected
    # setup left the buffer armed and waiting forever, and every later
    # run then failed on a command that had nothing to do with the
    # original fault. That is fixed independently (see reset() and the
    # setup block); this probe covers the parameter question.
    BUFFER_FEED_TOKENS = ("SENS1", "SENSe1", "SENS")

    def _buffer_feed_command(self):
        """`TRAC:FEED <token>`, using whichever token this box accepts.

        Probed once and cached. Storage is disarmed first, because that
        is the documented precondition for changing the feed at all -
        without it the probe would reject a perfectly good token and
        cache the wrong answer for the session.

        If neither token is accepted the last one is returned anyway:
        the setup check downstream will see the error, name it, and fall
        back cleanly. Better that than raising here and losing the sweep
        entirely.
        """
        if self._feed_token is not None:
            return f"TRAC:FEED {self._feed_token}"

        for token in self.BUFFER_FEED_TOKENS:
            self._drain_errors()
            try:
                self.transport.write("TRAC:FEED:CONT NEV")
                self.transport.write(f"TRAC:FEED {token}")
            except Exception:
                continue
            if not self._drain_errors():
                self._feed_token = token
                return f"TRAC:FEED {token}"

        self._feed_token = self.BUFFER_FEED_TOKENS[-1]
        return f"TRAC:FEED {self._feed_token}"

    def _restore_fixed_source(self, source):
        """Undo the staircase configuration.

        Three things, all of which bite silently if left:
        `MODE SWE` makes later level-setting a no-op; a trigger count
        above 1 makes the next `READ?` take that many readings; and an
        arm count above 1 multiplies it again.
        """
        for command in (f"SOUR:{source}:MODE FIX", "TRIG:COUN 1",
                        "ARM:COUN 1"):
            try:
                self.transport.write(command)
            except Exception:
                pass
        self._drain_errors()

    def _find_rejected_command(self, setup):
        """Replay the setup one command at a time to name the offender.

        Only ever runs on the failure path, so the extra round trips
        cost nothing in normal use. Worth it because "-140: Character
        data error" names a *kind* of mistake and not the command that
        made it, and the staircase block is fifteen commands long -
        several of which carry character parameters this instrument may
        simply not accept (`SPAC LIN`, `DIR UP`, `RANG BEST`,
        `MODE SWE`, `FEED SENS1`).
        """
        self._drain_errors()
        for command in setup:
            try:
                self.transport.write(command)
            except Exception:
                return command
            if self._drain_errors():
                return command
        return None

    def sweep_points_ready(self):
        """How many readings have landed in the instrument's buffer."""
        if self.sweep_kind() != "hardware":
            return super().sweep_points_ready()
        try:
            reply = self.transport.query("TRAC:POIN:ACT?", timeout_s=5.0)
            return int(float(reply.strip().split(",")[0]))
        except (ValueError, IndexError, AttributeError):
            return 0

    # The order the 2400 family returns elements in, regardless of the
    # order they were requested. Used when the instrument's own account
    # of its element list cannot be believed - see _buffer_layout().
    CANONICAL_ELEMENTS = ("VOLT", "CURR", "RES", "TIME", "STAT")

    def _buffer_layout(self, count, values):
        """How many numbers per reading, and where V and I sit.

        **Counted from the data, not asked for and not read back.**

        Both of the obvious approaches fail on this instrument. Sending
        `FORM:ELEM VOLT,CURR` does not restrict the reply: it is
        accepted, queues no error, and the buffer still comes back with
        a resistance column. And querying `FORM:ELEM?` does not reveal
        that - it answers `VOLT,CURR`, matching what was asked rather
        than what it sends. The instrument's account of itself is wrong
        in both directions, so neither can be trusted.

        What cannot lie is arithmetic: the buffer reports how many
        readings it holds, and the reply contains a certain quantity of
        numbers. Their ratio is the stride. Which column is which then
        comes from the canonical element order the family documents,
        truncated to that stride.

        Falls back to a plain V,I pair when the count is unknown or the
        division is not exact, which is what every other instrument here
        does.
        """
        if not count or not values or len(values) % count:
            return (2, 0, 1)

        stride = len(values) // count
        if stride < 2:
            return (2, 0, 1)

        names = list(self.CANONICAL_ELEMENTS[:stride])
        if "VOLT" not in names or "CURR" not in names:
            return (2, 0, 1)
        return (stride, names.index("VOLT"), names.index("CURR"))

    def read_sweep(self, points):
        """Collect a finished sweep as (source_values, measured_values).

        The buffer is unpacked using the element list the instrument
        *reports*, not the one that was asked for - see
        `_buffer_layout()`. The pairs are then assigned to
        source/measure by mode rather than by position.

        Found on the bench: this instrument returned three numbers per
        reading (voltage, current, resistance) after being told
        `FORM:ELEM VOLT,CURR`, and the fixed stride of two turned 5
        readings into 15 numbers read as 7 pairs. Four of those
        contained the resistance NAN and were dropped, leaving 3 -
        which were readings 1, 3 and 5, genuine V/I pairs, and
        therefore looked entirely plausible. Only the point-count check
        caught it.

        Reading the element list back does not help: `FORM:ELEM?`
        answers `VOLT,CURR` while the buffer sends three columns. The
        stride is therefore counted, not asked for.
        """
        if self.sweep_kind() != "hardware":
            return super().read_sweep(points)

        # How many readings the instrument says it took. Asked before
        # the data is fetched, because it is the denominator that turns
        # a flat list of numbers into a stride.
        try:
            actual = int(float(str(self.transport.query(
                "TRAC:POIN:ACT?", timeout_s=5.0)).strip().split(",")[0]))
        except Exception:
            actual = int(points)

        reply = self.transport.query("TRAC:DATA?", timeout_s=30.0)
        values = []
        for chunk in str(reply).replace("\n", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                values.append(float(chunk))
            except ValueError:
                pass

        stride, v_index, i_index = self._buffer_layout(actual, values)
        if stride != 2:
            self._sweep_note = (
                f"the buffer returns {stride} values per reading, not 2 - "
                f"`FORM:ELEM VOLT,CURR` is accepted and ignored on this "
                f"model, and `FORM:ELEM?` reports the requested list "
                f"rather than the one it sends. Stride counted from "
                f"{len(values)} values over {actual} readings")

        volts = values[v_index::stride]
        amps = values[i_index::stride]
        # Ragged tail: an interrupted transfer can leave one orphan
        # number. Trim to matched pairs rather than pad, on the same
        # principle as the software sweep - fewer real points beats
        # inventing one.
        n = min(len(volts), len(amps))
        volts, amps = volts[:n], amps[:n]

        # Drop NAN/overflow pairs. One of these left in a sweep is
        # worse than a missing point: at 1e37 it dominates the
        # least-squares sum completely, so the fitted line runs to that
        # single point and the real data becomes noise around zero.
        # Dropped in pairs so the two columns stay aligned.
        kept_v, kept_i, dropped = [], [], 0
        for v, i in zip(volts, amps):
            if self._clean(v) is None or self._clean(i) is None:
                dropped += 1
                continue
            kept_v.append(v)
            kept_i.append(i)
        if dropped:
            self._sweep_note = (
                f"{dropped} of {n} sweep points came back as "
                f"NAN/over-range and were dropped")
        volts, amps = kept_v, kept_i

        # Put the source back in fixed mode. Left in SWE, the next
        # `SOUR:VOLT <level>` is read as a sweep endpoint rather than a
        # level to hold - which would break the bias-hold path between
        # periodic sweeps, and do it silently.
        source = "VOLT" if self._sweep_source_mode() == "voltage" else "CURR"
        try:
            self.transport.write(f"SOUR:{source}:MODE FIX")
            # And put the trigger count back. This one was found on the
            # bench: `TRIG:COUN <points>` above is what makes the
            # staircase fire N times, and leaving it there means the
            # next plain `READ?` triggers N readings instead of one. It
            # is silent at low NPLC - just slow - and at NPLC 10 the
            # reply takes five times the aperture and blows through
            # measure()'s timeout as a USB error that looks like a
            # cable fault. Every bias-hold reading between periodic
            # sweeps went through this path.
            self.transport.write("TRIG:COUN 1")
            self.transport.write("ARM:COUN 1")
        except Exception:
            pass

        if self._sweep_source_mode() == "voltage":
            return volts, amps
        return amps, volts

    def _sweep_source_mode(self):
        """Which quantity the last started sweep sourced."""
        return getattr(self, "_last_sweep_mode", "voltage")

    def abort_sweep(self):
        """Stop a running sweep and drop the output.

        `:TRIG:CLE`, not `:ABOR`. Settled on the bench 2026-08-14:
        `:ABOR` is rejected with `-113: Undefined header`, against a
        control that proved the error queue was reporting. The manual's
        `:MEASure?` description mentions an abort being performed
        internally, but there is no bus command for it on this model.
        `:TRIGger:CLEar` is documented outright, clears the pending
        trigger, and is what stops a sweep here.

        Note `:SOUR:SWE:CABort` is *not* the abort action despite the
        name - it is a setting that configures what a sweep does when
        it hits compliance.
        """
        if self.sweep_kind() != "hardware":
            return super().abort_sweep()
        try:
            self.transport.write("TRIG:CLE")
            self.transport.write("OUTP 0")
        except Exception:
            return False
        return True
