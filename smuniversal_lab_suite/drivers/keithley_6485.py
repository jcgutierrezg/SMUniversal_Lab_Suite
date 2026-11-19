"""
Keithley 6485 picoammeter - the second meter in the suite, and the first
that reads current.

Written from the *Model 6485 Picoammeter Instruction Manual* (2001,
`manuals/6485/`, not committed - see `manuals/README.md`) before the
unit had been asked anything. Every statement below is still the
manual's word; the first bench session will mark the ones it confirms
as *measured*, as the 34401A's were. The command and reset tables are in
`docs/reference/manuals/6485-commands.md`, and the bench answers will go
in the note, `docs/instruments/keithley-6485.md`.

It joins as a driver only (decided 2026-11-19): it is refused by every
experiment (see `BaseMeter.ROLE_CAVEATS`). The role a picoammeter is
for - in series with a source, reading the current far below what an
SMU resolves - is the suite's first two-role experiment, and its own
discussion.

Things the manual says that shape the driver
--------------------------------------------
  * **It sources nothing.** One input, one function - current, 20 fA to
    21 mA - and no voltage source. That is why it is a meter and not a
    `BaseSMU` like the 487 and the B2987A, which each have a voltage
    source beside their ammeter.
  * **It identifies itself, so it is auto-detected.** SCPI answers
    `*IDN?` with `KEITHLEY INSTRUMENTS INC.,MODEL 6485,<serial>,<rev>`.
    `MODEL_IDS` matches `MODEL 6485`, which no other reply contains
    (the 6487, a 6485 with a source, says `MODEL 6487`).
  * **The language must be SCPI.** The front panel's COMM menu offers
    SCPI, 488.1 and DDC (Model 485 emulation) on GPIB. In DDC `*IDN?` is
    not a command and is never answered, which on this suite's
    transports latches the link at Connect. 488.1 still takes SCPI
    commands. RS-232 is SCPI only, and ASCII only.
  * **`*RST` leaves zero check ON.** With zero check on, the input is
    shunted to low inside the meter and every reading is the meter's
    own offset - a plausible few femtoamps, not an error, not NaN. The
    same trap as the 487's factory `C1` and the B2987A's ammeter input
    left off. So `reset()` turns it off **last**, after everything that
    shapes a reading, and the checkup reads it back.
  * **Zero check goes back on when the session ends.** The manual: leave
    zero check on while connecting or disconnecting the input. So
    `release_front_panel()` - the hook the app calls at disconnect and
    the checkup calls when it finishes - turns it on. Switching it
    either way puts a short transient on the input through an internal
    resistance (11 MOhm on the nA ranges, 500 Ohm on the mA ranges,
    Table I-2); the manual offers no way around it.
  * **Zero correct is not used** (decided 2026-11-19, as for the 487).
    `reset()` turns it off explicitly, so a value acquired by a previous
    user is not silently subtracted.
  * **Eight ranges**, 2 nA to 20 mA in decades of 2, 20 and 200, each
    reading to 105%. Autorange is the `*RST` state.
  * **The integration time is continuous**, not a menu: 0.01 PLC to
    5 PLC at 50 Hz (6 at 60 Hz) by the SCPI table. The specifications
    page says 50 PLC; the SCPI table is the one followed here, and 5 is
    the ceiling at either mains frequency.
  * **Autozero is on at `*RST`**, and the manual says to switch it off
    only for short periods: the zero and gain references drift. Off
    reads up to three times faster.
  * **Overflow is the SCPI sentinel.** An overflowed or overvoltage
    reading is `+9.9E37`, an invalid element `+9.91E37`; both become
    `None`.
  * **What it must not be given**: 21 mA or 220 V peak at the input
    damages it, and input LO is safe only up to 42 V from chassis. On
    the 2 mA and 20 mA ranges an input above 60 V switches it from a
    current limit to a 1-3 MOhm input (OVRVOLT). None of that is a
    setting; it is for whoever pairs it with a source.

Never sent
----------
  * `*SAV`, `*RCL`, `SYSTem:POSetup`, `SYSTem:PRESet` - a recalled or
    preset setup is a setup nobody here chose (and `PRESet` leaves the
    autorange off and the byte order swapped).
  * `SYSTem:REMote`, `SYSTem:LOCal`, `SYSTem:RWLock` - RS-232 only.
  * `SYSTem:ZCORrect:ACQuire` - see zero correct, above.
  * `CALCulate` beyond switching it off: mX+b, reciprocal and log
    (`CALC1`), Rel (`CALC2:NULL`), limit tests (`CALC2:LIM`), buffer
    statistics (`CALC3`). A Rel value left on by a previous user
    subtracts silently from every reading.
  * `TRACe` (the buffer), `DISPlay:ENABle OFF` and `DISPlay:TEXT`, the
    trigger link, `FORMat:DATA` other than ASCII, `CALibration:*`,
    `SYSTem:KEY` and the status enable registers.
"""
from smuniversal_lab_suite.core.limits import LimitError, SMULimits
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised

from .base_meter import BaseMeter

#: One power-line cycle at 50 Hz, in seconds - the slower of the two
#: mains frequencies, so a reading time worked out from it is never an
#: underestimate.
_PLC_S = 1.0 / 50.0

#: How much longer a reading takes with autozero on. The manual: off
#: "increases measurement speed up to 3 times".
_AUTOZERO_FACTOR = 3.0

#: An allowance for an autorange search, in seconds. Every autorange
#: searches the ranges between its limits, and the manual says only
#: that it "could slow down range change speed significantly".
_AUTORANGE_S = 0.3


class Keithley6485(BaseMeter):
    MODEL_IDS = ["MODEL 6485"]
    DISPLAY_NAME = "Keithley 6485"

    MEASURE_FUNCTIONS = ("current",)
    FIXED_SENSE = "2-wire (one BNC input)"

    #: The input's ratings, not a source envelope - a meter has none.
    #: 220 V peak is the most the input may be given and 21 mA the
    #: most it may carry (20 mA range + 5%); there is no voltage
    #: function, so no voltage ranges.
    LIMITS = SMULimits(
        max_voltage=220.0,
        max_current=0.021,
        current_ranges=[2e-9, 2e-8, 2e-7, 2e-6, 2e-5, 2e-4, 2e-3, 2e-2],
    )

    #: Continuous, so no `NPLC_CHOICES`: the SCPI table's 0.01 to 5 PLC
    #: at 50 Hz, which 60 Hz mains (up to 6) also accepts.
    NPLC_RANGE = (0.01, 5.0)

    #: An undefined header, which every SCPI parser must refuse with
    #: -113 and which would do nothing if it were somehow accepted.
    ERROR_PROBE = ("SYSTem:BOGus", -113)

    #: The integration time `reset()` sends, in power-line cycles: the
    #: `*RST` value at 50 Hz (SLOW), the lowest-noise setting.
    RESET_NPLC = 5.0

    #: The autorange limits `reset()` sends - the whole span. The
    #: manual lists 2.1e-2 and 2.1e-9 as the defaults; the range values
    #: themselves select the same ranges.
    AUTORANGE_LIMITS_A = (2e-9, 2e-2)

    #: Nothing has been checked at the bench yet.
    CONFIG_READBACK_TRUSTED = False

    def __init__(self, transport):
        super().__init__(transport)
        self._zero_check = None

    # ---- parsing ----
    def _number(self, command, timeout_s=3.0):
        """One numeric reply, or None for an empty or sentinel one."""
        reply = self.transport.query(command, timeout_s=timeout_s)
        text = str(reply).strip() if reply is not None else ""
        if not text:
            return None
        try:
            return self.drop_sentinel(float(text))
        except ValueError:
            raise ValueError(
                f"{self.DISPLAY_NAME}: {command} answered {text!r}, which "
                f"is not a number") from None

    def _flag(self, command):
        """A `0`/`1` reply as a bool. Anything else raises: a setting
        that cannot be read is not a setting reading off."""
        reply = str(self.transport.query(command)).strip()
        if reply in ("0", "1"):
            return reply == "1"
        try:
            return bool(int(float(reply)))
        except ValueError:
            raise ValueError(
                f"{self.DISPLAY_NAME}: {command} answered {reply!r}, which "
                f"is not 0 or 1") from None

    # ---- reset ----
    def reset(self):
        """`*RST`, `*CLS`, every setting a reading depends on sent
        explicitly, and zero check off last.

        `*RST` already leaves most of these - autorange, autozero on,
        filters and math off, one immediate trigger - and each is sent
        anyway, because a default nobody sent is a default nobody chose
        (fault 17). Three are not `*RST` states, or not clearly:

        * `FORM:ELEM READ` - the reading alone, no units, timestamp or
          status, so `READ?` answers one number.
        * the integration time, sent as `RESET_NPLC` so it is the same
          on 50 and 60 Hz mains;
        * the Rel value and zero correct, which the reset table does
          not clearly reset - both switched off.

        Zero check goes **last**: it connects the input to the circuit,
        and nothing should change how a reading is taken after that.
        """
        self.transport.write("*RST")
        self.transport.write("*CLS")
        self.transport.write("FORM:ELEM READ")
        self.transport.write("CURR:RANG:AUTO ON")
        low, high = self.AUTORANGE_LIMITS_A
        self.transport.write(f"CURR:RANG:AUTO:LLIM {low:g}")
        self.transport.write(f"CURR:RANG:AUTO:ULIM {high:g}")
        self._current_range = None
        self.set_nplc(self.RESET_NPLC)
        self.set_autozero(True)
        self.transport.write("MED OFF")
        self.transport.write("AVER OFF")
        self.transport.write("CALC1:STAT OFF")
        self.transport.write("CALC2:NULL:STAT OFF")
        self.transport.write("ARM:SOUR IMM")
        self.transport.write("ARM:COUN 1")
        self.transport.write("TRIG:SOUR IMM")
        self.transport.write("TRIG:COUN 1")
        self.transport.write("TRIG:DEL 0")
        self.transport.write("SYST:ZCOR OFF")
        self.set_zero_check(False)

    # ---- configuration ----
    def set_current_range(self, amps=None):
        """Autorange on `None`; otherwise the smallest range that holds
        `amps`, with autorange switched off first."""
        if amps is None:
            self.transport.write("CURR:RANG:AUTO ON")
            self._current_range = None
            return None
        wanted = abs(float(amps))
        ranges = sorted(self.LIMITS.current_ranges)
        chosen = next((r for r in ranges if r >= wanted * (1 - 1e-9)), None)
        if chosen is None:
            raise LimitError(
                f"{self.DISPLAY_NAME}: {wanted:.6g} A is above its highest "
                f"range ({ranges[-1]:g} A).")
        self.transport.write("CURR:RANG:AUTO OFF")
        self.transport.write(f"CURR:RANG {chosen:g}")
        self._current_range = chosen
        return chosen

    def set_nplc(self, nplc):
        """`CURR:NPLC`, clamped into `NPLC_RANGE`. Returns what was
        sent, so a caller records the integration time in force."""
        clamped = self.snap_nplc(nplc)
        self.transport.write(f"CURR:NPLC {clamped:g}")
        self._nplc = clamped
        return clamped

    def set_autozero(self, on=True):
        self.transport.write(f"SYST:AZER {'ON' if on else 'OFF'}")
        self._autozero = bool(on)

    def set_zero_check(self, on=True):
        """On shunts the input to low inside the meter; off measures
        the circuit. See the module docstring."""
        self.transport.write(f"SYST:ZCH {'ON' if on else 'OFF'}")
        self._zero_check = bool(on)

    def set_input_shunt(self, on=True):
        """The meter contract's name for zero check."""
        self.set_zero_check(on)

    def release_front_panel(self):
        """Zero check on, as the manual says to leave it while the input
        is rewired: called by the app at disconnect and by the checkup
        when it finishes. The hook's name is the Z+'s, which hands its
        front panel back; here it hands back an input that is safe to
        unplug. A write only, so it goes out on a link that has stopped
        answering."""
        self.set_zero_check(True)

    # ---- readbacks ----
    def read_current_range(self):
        return self._number("CURR:RANG?")

    def read_autorange(self):
        return self._flag("CURR:RANG:AUTO?")

    def read_nplc(self):
        return self._number("CURR:NPLC?")

    def read_autozero(self):
        return self._flag("SYST:AZER?")

    def read_input_connected(self):
        """`SYST:ZCH?` inverted: 0 (zero check off) is a connected
        input."""
        return not self._flag("SYST:ZCH?")

    # ---- reading ----
    def reading_time_s(self):
        """How long one reading should take, from what was last sent.

        Integration at 50 Hz, times three with autozero on, plus an
        allowance for an autorange search. Before `reset()` has run
        nothing is known, so it assumes the reset state.
        """
        nplc = self._nplc if self._nplc is not None else self.RESET_NPLC
        autozero = True if self._autozero is None else self._autozero
        seconds = nplc * _PLC_S * (_AUTOZERO_FACTOR if autozero else 1.0)
        if self._current_range is None:
            seconds += _AUTORANGE_S
        return seconds

    def measure(self, timeout_s=3.0):
        """One current reading, as `(None, amps)`.

        `READ?` - trigger and fetch with the configuration in force. No
        voltage, ever: the 6485 has no voltmeter. The timeout grows with
        the integration time so a slow reading cannot outlive it and
        desynchronise the link.
        """
        timeout = max(float(timeout_s), 2.0 * self.reading_time_s() + 1.0)
        reply = self.transport.query("READ?", timeout_s=timeout)
        text = str(reply).strip() if reply is not None else ""
        if not text:
            return (None, None)
        if "," in text:
            # `FORM:ELEM READ` was sent at reset. More than one element
            # means it is not in force, and which of them is the reading
            # would be a guess.
            raise RuntimeError(
                f"{self.DISPLAY_NAME}: READ? returned several elements "
                f"({text[:60]!r}); FORM:ELEM READ is not in force.")
        # The units element appends an `A`; strip it in case it is on.
        if text[-1:].upper() == "A":
            text = text[:-1]
        try:
            return (None, self.drop_sentinel(float(text)))
        except ValueError:
            return (None, None)

    # ---- errors ----
    def read_error(self):
        """One entry off the queue, `-113,"Undefined header"` style.

        A failure to ask reports code 0, per the contract; a
        desynchronised link is re-raised, as everywhere.
        """
        try:
            reply = self.transport.query("SYST:ERR?", timeout_s=3.0)
        except TransportDesynchronised:
            raise
        except Exception:
            return (0, "")
        if not reply:
            return (0, "")
        head, _, tail = str(reply).partition(",")
        try:
            return (int(float(head.strip())), tail.strip().strip('"'))
        except ValueError:
            return (0, str(reply).strip())
