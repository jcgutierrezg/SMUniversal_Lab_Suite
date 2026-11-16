"""
Keysight (Agilent, HP) 34401A 6.5-digit multimeter - the first meter in
the suite.

Written from the *Agilent 34401A User's Guide* (`manuals/34401A/`, not
committed - see `manuals/README.md`) before the unit had been asked
anything. Every statement below is the manual's word until a bench
session marks it *measured*. The command and reset tables it was written
from are in `docs/reference/manuals/34401a-commands.md`, and the
questions only the instrument can answer are listed in its note,
`docs/instruments/keysight-34401a.md`.

It joins as a driver only: it is refused by every experiment (see
`BaseMeter.ROLE_CAVEATS`), and reads DC volts and nothing else until a
role asks for more.

Things the manual says that shape the driver
--------------------------------------------
  * **It identifies itself, so it is auto-detected.** The manual gives
    `HEWLETT-PACKARD,34401A,0,<firmware>`; later units say Agilent, and
    the unit's own badge says Keysight. `MODEL_IDS` matches on `34401A`
    alone so all three resolve. The bench's real reply goes in the note
    at the first checkup.
  * **The interface language must be SCPI.** The front panel offers two
    others (HP 3478A and Fluke 8840A emulation). In either, `*IDN?` is
    not a command and is never answered, which on this suite's
    transports latches the link at Connect. SCPI is the factory setting
    and is held in non-volatile memory; the note says where to set it.
  * **`CONFigure` and `MEASure?` reset the input resistance.** Both put
    the input back to 10 MOhm on every range, and both preset autozero,
    trigger and sample count with it. So neither is sent: the driver
    configures with the individual `[SENSe:]` commands, which leave the
    input mode alone, and reads with `READ?`. That is the shape of a
    software-stepped reading anyway - configure once, read per point.
  * **The high-impedance input exists only on the low ranges.**
    `INP:IMP:AUTO ON` gives more than 10 GOhm on 100 mV, 1 V and 10 V;
    on 100 V and 1000 V the input is the 10 MOhm divider regardless.
    `reset()` turns it on (the factory default is off): a meter in this
    suite reads films, and 10 MOhm across a 100 kOhm sample is a 1%
    error nothing would flag. The setting is recorded with the reading.
  * **The integration time is a menu**: 0.02, 0.2, 1, 10 or 100 power-
    line cycles. A value between two is moved up to the next entry here,
    so what is sent is always one the manual lists.
  * **The front/rear terminal switch is the front panel's alone.** It
    can be queried (`ROUT:TERM?`) and is recorded, but not set.
  * **Overload is the SCPI sentinel**, `+9.90000000E+37`, which
    `drop_sentinel()` turns into `None`.
  * **The error queue holds 20.** `SYST:ERR?` pops one, `*CLS` empties
    it.

Never sent
----------
  * `SYSTem:REMote`, `SYSTem:LOCal`, `SYSTem:RWLock` - RS-232 only. Over
    GPIB each is error 514, and none is needed: addressing the meter
    puts it in remote.
  * `L1`, `L2`, `L3` - they switch the interface language, and after
    `L2` or `L3` nothing this driver sends is understood.
  * `CONFigure` and `MEASure?` - see above.
  * `CALCulate` beyond switching it off. A null offset left on by a
    previous user subtracts silently from every reading, so `reset()`
    sends `CALC:STAT OFF`; nothing turns math on.
  * `TRIGger:SOURce BUS`. `READ?` with a bus trigger is the manual's
    "trigger deadlock": the reading never comes.
  * `CALibration:*`, `*TST?`, `DISPlay:TEXT`, the beeper and the status
    enable registers. Nothing here needs them, and `*TST?` takes long
    enough to look like a dead link.
"""
from smuniversal_lab_suite.core.limits import LimitError, SMULimits
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised

from .base_meter import BaseMeter

#: One power-line cycle at 50 Hz, in seconds - the slower of the two
#: mains frequencies, so a reading time worked out from it is never an
#: underestimate.
_PLC_S = 1.0 / 50.0


class Keysight34401A(BaseMeter):
    MODEL_IDS = ["34401A"]
    DISPLAY_NAME = "Keysight 34401A"

    #: The input's ratings, not a source envelope - a meter has none.
    #: DC volts from 100 mV to 1000 V, every range reading to 120% except
    #: 1000 V. The current ranges are declared because the instrument
    #: has them; this driver does not read current, and the smallest is
    #: 10 mA.
    LIMITS = SMULimits(
        max_voltage=1000.0,
        max_current=3.0,
        voltage_ranges=[0.1, 1.0, 10.0, 100.0, 1000.0],
        current_ranges=[0.01, 0.1, 1.0, 3.0],
    )

    NPLC_RANGE = (0.02, 100.0)
    NPLC_CHOICES = (0.02, 0.2, 1.0, 10.0, 100.0)
    HIGH_IMPEDANCE_MAX_RANGE_V = 10.0

    #: An undefined header, which every SCPI parser must refuse with
    #: -113 and which would do nothing if it were somehow accepted.
    ERROR_PROBE = ("SYSTem:BOGus", -113)

    #: The integration time `*RST` leaves, in power-line cycles.
    RESET_NPLC = 10.0

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
        """`*RST`, `*CLS`, and then every setting a reading depends on,
        sent explicitly.

        `*RST` already leaves DC volts, autorange, 10 PLC, autozero on,
        immediate trigger, one sample, automatic trigger delay and math
        off - and each is sent anyway, because a default nobody sent is
        a default nobody chose (fault 17), and because these are held in
        volatile memory a previous session may have changed.

        The input mode is sent **last**, after everything that could
        reset it, and is the one deliberate departure from the reset
        state - see the module docstring.
        """
        self.transport.write("*RST")
        self.transport.write("*CLS")
        self.transport.write('FUNC "VOLT:DC"')
        self.transport.write("VOLT:DC:RANG:AUTO ON")
        self._voltage_range = None
        self.set_nplc(self.RESET_NPLC)
        self.set_autozero(True)
        self.transport.write("TRIG:SOUR IMM")
        self.transport.write("TRIG:DEL:AUTO ON")
        self.transport.write("TRIG:COUN 1")
        self.transport.write("SAMP:COUN 1")
        self.transport.write("CALC:STAT OFF")
        self.set_high_impedance(True)

    # ---- configuration ----
    def set_voltage_range(self, volts=None):
        """Autorange on `None`; otherwise the smallest range that holds
        `volts`. Autorange is switched off explicitly before the range
        is sent, rather than left to the range command to imply."""
        if volts is None:
            self.transport.write("VOLT:DC:RANG:AUTO ON")
            self._voltage_range = None
            return None
        wanted = abs(float(volts))
        ranges = sorted(self.LIMITS.voltage_ranges)
        chosen = next((r for r in ranges if r >= wanted * (1 - 1e-9)), None)
        if chosen is None:
            raise LimitError(
                f"{self.DISPLAY_NAME}: {wanted:.6g} V is above its highest "
                f"DC range ({ranges[-1]:g} V).")
        self.transport.write("VOLT:DC:RANG:AUTO OFF")
        self.transport.write(f"VOLT:DC:RANG {chosen:g}")
        self._voltage_range = chosen
        return chosen

    def set_nplc(self, nplc):
        """`VOLT:DC:NPLC`, with the request moved up onto the menu.

        Returns what was sent, so a caller can record the integration
        time actually in force rather than the one typed.
        """
        snapped = self.snap_nplc(nplc)
        self.transport.write(f"VOLT:DC:NPLC {snapped:g}")
        self._nplc = snapped
        return snapped

    def set_autozero(self, on=True):
        self.transport.write(f"ZERO:AUTO {'ON' if on else 'OFF'}")
        self._autozero = bool(on)

    def set_high_impedance(self, on=True):
        self.transport.write(f"INP:IMP:AUTO {'ON' if on else 'OFF'}")
        self._high_impedance = bool(on)

    # ---- readbacks ----
    def read_function(self):
        """`FUNC?`, quotes removed: `VOLT` for DC volts in SCPI's short
        form - the exact spelling is one of the note's open questions,
        so it is returned as sent rather than mapped."""
        reply = self.transport.query("FUNC?")
        return str(reply).strip().strip('"').upper() or None

    def read_voltage_range(self):
        return self._number("VOLT:DC:RANG?")

    def read_autorange(self):
        return self._flag("VOLT:DC:RANG:AUTO?")

    def read_nplc(self):
        return self._number("VOLT:DC:NPLC?")

    def read_autozero(self):
        """`ZERO:AUTO?` answers 0 for both OFF and ONCE."""
        return self._flag("ZERO:AUTO?")

    def read_high_impedance(self):
        return self._flag("INP:IMP:AUTO?")

    def read_terminals(self):
        reply = str(self.transport.query("ROUT:TERM?")).strip().strip('"')
        return {"FRON": "front", "REAR": "rear"}.get(reply.upper(), reply)

    # ---- reading ----
    def reading_time_s(self):
        """How long one reading should take, from what was last sent.

        Integration at 50 Hz, doubled with autozero on (the meter takes
        a zero reading for every signal reading), plus an allowance for
        autoranging. Before `reset()` has run nothing is known, so it
        assumes the reset state.
        """
        nplc = self._nplc if self._nplc is not None else self.RESET_NPLC
        autozero = True if self._autozero is None else self._autozero
        seconds = nplc * _PLC_S * (2 if autozero else 1)
        if self._voltage_range is None:
            seconds += 0.1
        return seconds

    def measure(self, timeout_s=3.0):
        """One DC voltage reading, as `(volts, None)`.

        `READ?` - trigger and fetch, with the configuration already in
        force - and never `MEAS?`, which would re-preset the input to
        10 MOhm on every point.

        The timeout grows with the integration time. At 100 PLC with
        autozero a reading takes about 4 s, longer than the 3 s default
        every other driver here is called with, and a reading that
        outlives its timeout desynchronises the link.
        """
        timeout = max(float(timeout_s), 2.0 * self.reading_time_s() + 1.0)
        reply = self.transport.query("READ?", timeout_s=timeout)
        text = str(reply).strip() if reply is not None else ""
        if not text:
            return (None, None)
        if "," in text:
            # One sample per trigger was sent at reset. More than one
            # number means that setting is not in force, and which of
            # them is "the" reading is a guess.
            raise RuntimeError(
                f"{self.DISPLAY_NAME}: READ? returned several readings "
                f"({text[:60]!r}); the sample count is not 1.")
        try:
            return (self.drop_sentinel(float(text)), None)
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
