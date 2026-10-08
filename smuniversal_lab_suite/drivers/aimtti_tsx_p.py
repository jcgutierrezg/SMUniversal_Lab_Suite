"""
Aim-TTi (Thurlby Thandar) TSX-P bench power supplies - the first drivers
that are neither an SMU nor a load.

Two models, one command set: the TSX3510P is 35 V at 10 A and the
TSX1820P is 18 V at 20 A, both about 360 W, single output, constant
voltage or constant current with automatic crossover. Written from the
*TSX-P Instruction Manual*, Issue 18, with no script behind it and
**before either unit had been asked anything** - so everything below is
the manual's word, and `docs/instruments/` records which of it a bench
has since confirmed. The PDF is not committed (see `manuals/README.md`);
the command and error tables are transcribed in
`docs/reference/manuals/tsx-p-commands.md`.

They are here as auxiliaries - something to hold a rail or drive a
heater while an SMU does the measuring - and are refused by every
experiment that has not invited one. See `BaseSupply.ROLE_CAVEATS`.

What this dialect does that no other driver here handles
--------------------------------------------------------
**It is not SCPI.** There is no command tree: `V 12.5`, `I 2`, `OP 1`,
`VO?`. Nothing is shared with the other drivers' spellings, which is why
`tests/test_tsx_p.py` asserts that no colon is ever sent.

**Replies come in two shapes, and both carry text.** A reading has its
unit on the end - `12.55V`, `0.934A`, `175.3W` - and a setting has its
header on the front - `V 12.55`, `I 1.000`, `OVP 33.00`. A bare
`float(reply)` raises on both, and worse than raising: `drop_sentinel()`
catches the `ValueError` and returns `None`, so a raw reply handed to it
becomes a silently discarded reading. `_parse()` takes the number off
first, and the unit it finds is checked rather than thrown away - a
reply to `VO?` that ends in `A` is the previous query's answer, and a
current recorded in the voltage column is fault 21.

**There is no error queue, but there is something to ask.** No
`SYST:ERR?`. Instead `*ESR?` says *that* something went wrong, by bit,
and two registers say what: `EER?` holds the number of the last
execution error (100 "maximum set voltage exceeded", 103 "minimum set
amps exceeded" and so on) and `QER?` the last query error. Each is one
value deep and cleared by reading it. `read_error()` folds the three
into the `(code, message)` shape the rest of the suite drains, so the
checkup and the end-of-run shutdown check work unchanged - but note
what one-deep means: of two rejected settings in a row, only the second
is still there to be read.

**"Did it clamp?" is an event, not a state.** `LSR?` reports that the
output *entered* current limit or voltage limit since the register was
last read, and reading clears it. There is no query for which mode the
supply is in now. `regulation()` therefore keeps the last entry it saw,
and says "cannot say" until it has seen one - see there for what the
manual leaves open.

Things the manual says that shape the driver
--------------------------------------------
  * **The current setting stops at 10 mA.** Asking for less is error
    103, not a small current. `MIN_CURRENT_A` refuses it at the gate.
  * **Settings survive power-off.** They are held in non-volatile
    memory, so fault 6 - inherited state - is the default condition, and
    `reset()` is the only thing that makes a session start from known
    values. It leaves the output off at 0 V, the minimum current and the
    widest over-voltage trip.
  * **Any command locks the front panel.** The first byte from the bus
    puts the instrument in remote; the LOCAL key releases it until the
    next command arrives. The older units have no bus command that
    hands control back.
  * **Off is not a disconnection.** The output switch is electronic and
    a capacitor stays across the terminals, so a short on a "limited"
    output still produces a pulse the current setting does not govern.
  * **Readback is slow.** The meters update at 4 Hz, and the manual
    gives 500 ms as what reading the output voltage back can cost. A
    sample is two queries, so this is not an instrument for fast traces.

Two generations under one name
------------------------------
This was written for the original TSX-P: GPIB and RS-232, `*IDN?`
carrying a literal `0` where a serial number would be. The Series II
units (USB and LAN, 2017 on) number every command by output - `V1`,
`V1O?`, `OP1` - and their manual says the spellings used here are still
accepted. Their settings answer with a numbered header (`V1 12.55`,
`VP1 33.00`), which `_parse()` reads the same way. None of that has
been tried on a Series II unit.

Never sent
----------
Each of these is in the command list, and each is absent for a reason
rather than by omission:

  * `INCV`, `DECV`, `INCI`, `DECI` and the `DELTAV`/`DELTAI` steps they
    use. A relative step that reaches the end of the range stops there
    and, in the manual's words, generates no error - so after one the
    level is no longer known without reading it back. An absolute
    setting does everything they do.
  * `*SAV` and `*RCL`. A recall restores the stored **output state**
    along with the levels, so recalling a store saved with the output on
    energises whatever is attached, from a command that reads like
    housekeeping. This suite's settings live in run metadata.
  * `*LRN?`, `LRN` and `STO`. Binary blocks, GPIB only, and the same
    hazard as a recall.
  * `BUZZER` and `BUZZ`.
  * `*SRE`, `*ESE`, `LSE` and `*PRE`. They arm a service request, and
    nothing here listens for one - the registers are polled.
  * The RS-232 addressing codes (02H, 12H, 14H and the rest of the
    daisy-chain protocol). A unit on a serial cable powers up
    unaddressed and is driven as an ordinary port.
"""
import re

from smuniversal_lab_suite.core.limits import POSITIVE, SMULimits
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised

from .base_supply import CC, CROSSED, CV, BaseSupply

# ---- the standard event status register, read by `*ESR?` ----
ESR_QUERY_ERROR = 4
ESR_VERIFY_TIMEOUT = 8
ESR_EXECUTION_ERROR = 16
ESR_COMMAND_ERROR = 32
# Bit 0 (operation complete) and bit 7 (power on) are not errors and are
# ignored: the second is set by switching the instrument on.

# ---- the limit event status register, read by `LSR?` ----
LSR_ENTERED_CURRENT_LIMIT = 1
LSR_ENTERED_VOLTAGE_LIMIT = 2
LSR_TRIPPED = 4

#: What `EER?` reports, by number. Transcribed from the status section
#: of the manual, in its own words shortened.
EXECUTION_ERRORS = {
    1: "checksum error in non-volatile memory at power-on",
    2: "output stage failed to respond - possibly a system fault",
    3: "output stage has tripped and is trying to recover",
    100: "maximum set voltage exceeded",
    101: "maximum set current exceeded",
    102: "minimum set voltage exceeded",
    103: "minimum set current exceeded",
    104: "maximum delta voltage exceeded",
    105: "maximum delta current exceeded",
    107: "minimum set OVP exceeded",
    108: "maximum set OVP exceeded",
    109: "minimum delta current exceeded",
    110: "minimum delta voltage exceeded",
    114: "illegal bus address requested",
    115: "illegal store number",
    116: "recall of an empty store requested",
    117: "stored data is corrupt",
    118: "output stage has tripped (over-voltage or temperature)",
    119: "value out of range",
}

#: What `QER?` reports.
QUERY_ERRORS = {
    1: "interrupted - a new command arrived before a reply was read",
    2: "deadlock - the input filled while a reply was waiting",
    3: "unterminated - asked to talk with nothing to say",
}

#: The number on the end of a reply, and whatever letters follow it.
#:
#: Anchored at the end, so a setting's header is skipped whatever it
#: contains: `V 12.55`, `OVP 33.00`, and the Series II spellings with a
#: digit in them, `V1 12.55` and `VP1 33.00`, all yield the last number.
_TRAILING_NUMBER = re.compile(
    r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([A-Za-z]*)\s*$")


class AimTTiTSXP(BaseSupply):
    """Everything the two models share. Not registered itself: it has
    no `MODEL_IDS` and no envelope, and each model below supplies both.
    """

    #: Setting and readback both move in these steps, on both models.
    RESOLUTION = {"voltage": 0.01, "current": 0.01}

    #: "The current limit can be set ... down to 10mA." Below it the
    #: instrument answers with execution error 103.
    MIN_CURRENT_A = 0.01

    #: A current setting of zero, which is below the 10 mA floor and
    #: must come back as execution error 103. Chosen because accepting
    #: it would be harmless: a supply told to limit at nothing drives
    #: nothing.
    ERROR_PROBE = ("I 0", 103)

    # ---- what these models do not have ----
    #: No integration-time setting. `DAMPING` averages the current
    #: meter and is a different thing - see `set_meter_damping()`.
    NPLC_RANGE = None
    #: The over-voltage trip is a continuous value, not a menu. See
    #: `BaseSupply.OVP_RANGE_V` for why that is not expressed here.
    OVP_CHOICES = []
    #: The output switch is electronic, and a capacitor stays across the
    #: terminals with it off.
    HIGH_Z_OFF = False
    #: Remote sense is two links on the rear terminal block. Software
    #: cannot see them or change them, so what is recorded is the rule
    #: rather than a claim about a wiring nobody here has looked at.
    REMOTE_SENSE_CONTROL = False
    FIXED_SENSE = ("set by the rear-terminal links (2-wire with the links "
                   "fitted, 4-wire with them removed)")

    # ---- timing, from the specification and not yet from a bench ----
    #: How long after a voltage command the output is within a digit of
    #: its new value: up to 50 ms to act on the command, then about
    #: seven of the 22 ms output time constant. For a step **down** this
    #: holds only with an amp or more flowing - the supply cannot sink,
    #: so at a light load the output capacitor discharges through
    #: whatever is attached, however long that takes.
    SETTLING_S = 0.2
    #: How long to wait before believing a readback of a level that has
    #: just changed. The meters update at 4 Hz and the manual gives
    #: 500 ms as the cost of reading the output back.
    READBACK_SETTLE_S = 1.0
    #: How long a verified voltage set may take before the instrument
    #: gives up on it, plus margin for the reply.
    VERIFY_TIMEOUT_S = 8.0

    def __init__(self, transport):
        super().__init__(transport)
        #: `CV`, `CC`, `CROSSED` or None - the last entry `LSR?`
        #: reported, kept because the register itself is cleared by
        #: being read.
        self._regulation = None
        self._trip_seen = False
        #: Errors decoded from one `*ESR?` and not yet handed out. One
        #: read of the register can carry several, and the register is
        #: empty afterwards, so they are held here until drained.
        self._pending_errors = []
        #: What this driver last set. There is no query for it.
        self.meter_damping = False

    # ---- parsing, which is where a reading is won or lost ----
    @staticmethod
    def _parse(reply):
        """`(number, unit)` from the end of a reply, or `(None, "")`.

        Runs before `drop_sentinel()` and never after: a raw `'12.55V'`
        handed to the sentinel check parse-fails inside its `except` and
        comes back `None` - a reading that exists, thrown away, with
        nothing raised and nothing logged.
        """
        if reply is None:
            return None, ""
        match = _TRAILING_NUMBER.search(str(reply).strip())
        if match is None:
            return None, ""
        try:
            return float(match.group(1)), match.group(2).upper()
        except ValueError:
            return None, ""

    def _reading(self, command, unit, timeout_s=3.0):
        """One readback, in `unit`, or None where the instrument reports
        no reading.

        The unit on the reply is checked. A bare number is accepted - it
        cannot be shown to be wrong - but a reply carrying the *other*
        unit is the answer to a different question, which means the
        replies are out of step with the queries and every number after
        this one is in the wrong column.
        """
        reply = self.transport.query(command, timeout_s=timeout_s)
        value, got = self._parse(reply)
        if value is None:
            return None
        if got and got != unit:
            raise RuntimeError(
                f"{self.DISPLAY_NAME}: {command} was answered with "
                f"{str(reply).strip()!r}, which is in {got} and not "
                f"{unit}. That is the reply to a different query - the "
                f"link is out of step, and a reading taken now would be "
                f"recorded as the wrong quantity.")
        return self.drop_sentinel(value)

    def _setting(self, command):
        """One setting read back, or None. The reply's header is not
        checked: it differs between the two generations."""
        value, _ = self._parse(self.transport.query(command))
        return self.drop_sentinel(value)

    def _register(self, command, timeout_s=3.0):
        """One status register as an int, or raise on a reply that is
        not one. Raising is right here: a register that cannot be read
        is not a register reading zero."""
        reply = self.transport.query(command, timeout_s=timeout_s)
        text = str(reply).strip()
        try:
            return int(float(text))
        except ValueError:
            raise ValueError(
                f"{command} answered {text!r}, which is not a register "
                f"value") from None

    # ---- reset ----
    def reset(self):
        """Return the instrument to known settings and say so explicitly.

        `*RST` sets the output off, the voltage to its minimum, the
        current to its minimum, the over-voltage trip to its maximum
        and meter damping off; `*CLS` clears the four status registers.

        The trip and the damping are then **sent anyway**. A default
        that is never sent is a default nobody chose (fault 17), and the
        over-voltage trip is the one setting here whose reset value is
        the least protective one available - so it appears in the trace
        as a decision rather than as an absence.

        This matters more than a reset usually does: settings are held
        in non-volatile memory, so without it a session starts from
        whatever the last person left, output state aside.
        """
        self.transport.write("*RST")
        self.transport.write("*CLS")
        self._output_enabled = False
        self._source_function = None
        self._regulation = None
        self._trip_seen = False
        self._pending_errors = []
        if self.OVP_RANGE_V is not None:
            self._send_overvoltage_trip(self.OVP_RANGE_V[1])
        self.set_meter_damping(False)

    # ---- the two knobs ----
    def set_output_voltage(self, volts):
        """`V <volts>`. The full-precision level is sent and the
        instrument rounds it to its 10 mV grid (fault 4)."""
        self.transport.write(f"V {float(volts):.6g}")

    def set_output_current(self, amps):
        """`I <amps>` - the current limit, which on a supply is also the
        constant-current level."""
        self.transport.write(f"I {float(amps):.6g}")

    def set_voltage_verified(self, volts):
        """Set the voltage and wait for the output to get there.

        `VV` is the instrument's own settle check: it holds the next
        command until the output is within 5% or three counts of the
        target, and gives up after five seconds. Returns True if it
        settled and False if the instrument timed out - which happens
        with a large capacitance across the output and a low current
        setting, where the output is still charging.

        The verdict is the time-out bit of `*ESR?`. Anything else that
        register was carrying is kept for `read_error()` rather than
        lost with the read.
        """
        volts = self._checked_voltage(volts)
        self.transport.write(f"VV {volts:.6g}")
        status = self._register("*ESR?", timeout_s=self.VERIFY_TIMEOUT_S)
        self._queue_events(status & ~ESR_VERIFY_TIMEOUT)
        return not status & ESR_VERIFY_TIMEOUT

    # ---- output ----
    def _switch_output(self, on):
        """`OP 1` / `OP 0`.

        There is no `OP?` on these units, so the output state cannot be
        read back; what confirms a switch-off is the error registers
        staying clean, which `core.run_control.confirm_output_off()`
        asks.

        Going on, the limit register is read once first and thrown
        away. It is an event register, so anything in it was entered
        before this energising - and left there it would be the first
        answer `compliance_tripped()` gives about a run it predates.
        """
        if on:
            try:
                self._register("LSR?")
            except TransportDesynchronised:
                raise
            except Exception:
                # A flush that could not be read flushed nothing, and
                # the regulation state below is reset to "cannot say"
                # either way. The output switch still has to be sent.
                pass
            self._trip_seen = False
        self._regulation = None
        self.transport.write(f"OP {1 if on else 0}")

    # ---- the over-voltage trip ----
    def _send_overvoltage_trip(self, volts):
        self.transport.write(f"OVP {float(volts):.6g}")

    # ---- reading settings back ----
    def read_voltage_setpoint(self):
        """`V?` -> `V 12.55`."""
        return self._setting("V?")

    def read_current_setpoint(self):
        """`I?` -> `I 1.000`."""
        return self._setting("I?")

    def read_overvoltage_trip(self):
        """`OVP?` -> `OVP 33.00`."""
        return self._setting("OVP?")

    # ---- which knob is in charge ----
    def _poll_limit_events(self):
        """Read `LSR?` and fold what it says into the kept state.

        The register says the output *entered* a limit since it was
        last read. Entering current limit and entering voltage limit are
        the two halves of one crossover, so the most recent entry is the
        mode the supply is in - provided only one of them happened. Both
        bits together mean it went there and back between two polls, and
        which side it ended on is not in the register.

        **What the manual does not say** is whether a bit comes back
        after being cleared while the supply is still in that limit. If
        it does, every poll reports the present mode directly. If it
        does not, a poll with neither bit set means "no change", and the
        kept state is the answer. This reads both the same way, and
        differs only after a `CROSSED`: there the kept state is dropped,
        so the next quiet poll answers "cannot say" rather than
        asserting a mode nobody observed.
        """
        value = self._register("LSR?")
        if value & LSR_TRIPPED:
            self._trip_seen = True
        entered_cc = bool(value & LSR_ENTERED_CURRENT_LIMIT)
        entered_cv = bool(value & LSR_ENTERED_VOLTAGE_LIMIT)
        if entered_cc and entered_cv:
            self._regulation = CROSSED
        elif entered_cc:
            self._regulation = CC
        elif entered_cv:
            self._regulation = CV
        elif self._regulation == CROSSED:
            self._regulation = None
        return value

    def regulation(self):
        """`CV`, `CC`, `CROSSED`, or None before any entry has been seen.

        One query. A register that cannot be read answers None - being
        unable to ask is not evidence the supply is in constant voltage.
        """
        try:
            self._poll_limit_events()
        except TransportDesynchronised:
            raise
        except Exception:
            return None
        return self._regulation

    def protection_tripped(self):
        """True once a trip has been reported since the output last went
        on, or since `reset()`.

        A trip is the over-voltage protection, the thermal cut-out or
        the sense-miswiring detector, and the register does not say
        which. The instrument shuts the output down and then tries to
        recover by itself, so this is latched here rather than read
        live: a trip that came and went mid-run still has to be in the
        record.
        """
        try:
            self._poll_limit_events()
        except TransportDesynchronised:
            raise
        except Exception:
            return None
        return self._trip_seen

    # ---- timing and sensing ----
    def set_source_delay(self, seconds):
        """Accepted, and applied by the host rather than the instrument.

        There is no settle-time command. The software sweep waits
        `delay_s` between setting a level and measuring, on the host, so
        a delay an experiment asks for is honoured one layer up. See
        `SETTLING_S` for how long this instrument actually needs.
        """

    def set_remote_sense(self, on=True):
        """Refused, because software cannot honour it.

        Sensing is two links on the rear terminal block. Accepting a
        request here would write a sensing mode into the CSV that the
        measurement may not have used - the U2722A's reasoning exactly.
        """
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no remote-sense command. Sensing is "
            f"{self.FIXED_SENSE}, and this driver records that rather "
            f"than claiming a control it does not have.")

    def set_meter_damping(self, on):
        """`DAMPING 1` / `DAMPING 0` - average the current meter.

        A front-panel convenience for a load that draws in pulses.
        **Whether it changes what `IO?` returns is not in the manual**,
        which describes it as damping the meter; until a bench says, a
        trace taken with it on should say so. Off after `reset()`.
        """
        self.transport.write(f"DAMPING {1 if on else 0}")
        self.meter_damping = bool(on)

    # ---- measurement ----
    def measure(self, timeout_s=3.0):
        """One reading, `(volts, amps)`, as the instrument's own meters
        report them.

        Two queries, because there is no combined read - so the pair are
        not from the same instant, and at this instrument's readback
        speed they can be a good fraction of a second apart.

        Current out of the positive terminal is positive, which is this
        suite's convention for a source, so nothing is negated.
        """
        volts = self._reading("VO?", "V", timeout_s=timeout_s)
        amps = self._reading("IO?", "A", timeout_s=timeout_s)
        return volts, amps

    def measure_power(self, timeout_s=3.0):
        """The instrument's own power reading, in watts.

        Not part of any contract. Whether it is a third measurement or
        the product of the other two is not stated.
        """
        return self._reading("POWER?", "W", timeout_s=timeout_s)

    # ---- errors ----
    def _queue_events(self, status):
        """Turn one `*ESR?` value into `(code, message)` entries.

        Codes are the instrument's own where it has them: an execution
        error is reported under its `EER?` number. The three conditions
        it reports only as a bit have no number of their own, and are
        filed under the **negative of the bit** - -32, -8, -4 - so they
        cannot be mistaken for something the instrument said.
        """
        if status & ESR_COMMAND_ERROR:
            self._pending_errors.append((
                -ESR_COMMAND_ERROR,
                "command error - the instrument could not parse something "
                "it was sent, and does not say what"))
        if status & ESR_EXECUTION_ERROR:
            number = self._register("EER?")
            if number:
                message = EXECUTION_ERRORS.get(
                    number, "execution error (not in the manual's list)")
            else:
                message = ("execution error flagged, but EER? reported no "
                           "number")
            self._pending_errors.append(
                (number or -ESR_EXECUTION_ERROR, message))
        if status & ESR_VERIFY_TIMEOUT:
            self._pending_errors.append((
                -ESR_VERIFY_TIMEOUT,
                "a verified voltage set did not settle within 5 s"))
        if status & ESR_QUERY_ERROR:
            number = self._register("QER?")
            self._pending_errors.append((
                -ESR_QUERY_ERROR,
                "query error: " + QUERY_ERRORS.get(
                    number, f"number {number}")))

    def read_error(self):
        """Pop one error, as `(code, message)`. Code 0 means none.

        Built from three registers rather than a queue - see the module
        docstring. One `*ESR?` can report several conditions and is
        empty once read, so they are decoded together and handed out one
        per call, which is what lets a caller drain this the way it
        drains every other driver's.

        Follows the contract's two rules: a failure to *read* the
        registers is code 0 with the reason as the message, and an
        unparseable reply is code 0 with the raw text.
        """
        if not self._pending_errors:
            try:
                self._queue_events(self._register("*ESR?"))
            except TransportDesynchronised:
                raise
            except Exception as exc:
                return 0, (f"could not read the event registers "
                           f"({type(exc).__name__}: {exc})")
        if self._pending_errors:
            return self._pending_errors.pop(0)
        return 0, "No error"

    def read_status_byte(self):
        """`*STB?`, as an int. Bit 0 is the limit summary and bit 5 the
        event summary - but both only reflect conditions whose enable
        bits are set, and this driver sets none, so on its own this
        answers little. Here for a bench session."""
        return self._register("*STB?")


class AimTTiTSX3510P(AimTTiTSXP):
    MODEL_IDS = ["TSX3510P"]
    DISPLAY_NAME = "Aim-TTi TSX3510P"

    #: From the specification: "0V to 35.3V", "0.01A to 10.2A". One
    #: range per quantity, both available together - 360 W is the whole
    #: rectangle, so there is no power envelope to declare.
    LIMITS = SMULimits(
        max_voltage=35.3,
        max_current=10.2,
        voltage_ranges=[35.3],
        current_ranges=[10.2],
        # One quadrant, and in this suite's convention current out of a
        # source is positive.
        voltage_polarity=POSITIVE,
        current_polarity=POSITIVE,
    )

    #: "OVP Range: 1V to 40V".
    OVP_RANGE_V = (1.0, 40.0)


class AimTTiTSX1820P(AimTTiTSXP):
    MODEL_IDS = ["TSX1820P"]
    DISPLAY_NAME = "Aim-TTi TSX1820P"

    #: From the specification: "0V to 18.15V", "0.01A to 20.2A".
    LIMITS = SMULimits(
        max_voltage=18.15,
        max_current=20.2,
        voltage_ranges=[18.15],
        current_ranges=[20.2],
        voltage_polarity=POSITIVE,
        current_polarity=POSITIVE,
    )

    #: "OVP Range: 1V to 25V".
    OVP_RANGE_V = (1.0, 25.0)
