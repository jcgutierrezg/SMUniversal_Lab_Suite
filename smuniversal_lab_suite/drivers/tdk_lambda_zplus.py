"""
TDK-Lambda Z+ bench power supplies - the Z36-24, over USB.

The Z36-24 is 0 to 36 V at 0 to 24 A, 864 W: the whole rectangle, so
there is no power envelope to declare. One output, constant voltage or
constant current with automatic crossover. Written from the *Z+ User
Manual, low-voltage models 10 V to 100 V* (chapter 7 for the commands,
chapter 9 for the registers) and from two probe sittings on the unit in
this lab, 2026-11-17, firmware 2.231, through `tools/bench_z36.py`. What
those sittings established is marked *measured*; anything not marked is
the manual's word. Both sittings are written up in
`docs/instruments/tdk-lambda-z36-24.md`.

It is here on the terms the Aim-TTi supplies are: an auxiliary, refused
by every experiment that has not invited one (`BaseSupply.ROLE_CAVEATS`).

The command set is plain SCPI, and the manual's account of it is
accurate. What the manual does not make plain, and this driver is built
around, is three things about the connection.

**Nothing is heard until the supply is selected.** "Selecting the power
supply (INSTrument:NSELect <address>) is necessary before using any
other command." *Measured:* that includes `*IDN?`, which goes
unanswered - and an unanswered query latches this suite's transport.
The selection then survives a reopened port and `*RST`, and is lost when
the supply is switched off. So it is sent at the start of `identify()`
and `reset()`, and `drivers/registry.identify()` sends it before its own
`*IDN?` to any serial port whose USB ids are in `USB_IDS` - which is how
auto-detection works on a supply switched on this morning. The address
is the front panel's, 1 to 31; `BUS_ADDRESS` is this bench's.

**A refused setting is ignored in silence until errors are enabled.**
*Measured:* with nothing sent first, `CURR 30`, `VOLT 40`, an unknown
header and a voltage above the trip's 95% were all ignored - the setting
left as it was - and `SYST:ERR?` and `*ESR?` both read clean after
every one. After `SYST:ERR:ENABle` the same commands are reported:
`-222,"Data Out Of Range;address 1"`, `+301,"PV Above OVP;address 1"`.
The enable survives `*RST` and is lost at power-off, so `reset()` sends
it on every connect. Without it every clean error check in this suite
would be meaningless, which is what `ERROR_PROBE` is there to catch.

**The voltage and the trip limit each other.** A voltage above 95% of
the over-voltage trip is refused (301), and so is a trip below 105% of
the voltage (304). *Measured, both.* The driver checks both before the
wire, so the operator reads the reason rather than an error number at
the end of a run.

Things the manual and the bench say that shape the driver
---------------------------------------------------------
  * **It accepts 5% over rated.** `VOLT? MAX` reads 37.8 and `CURR? MAX`
    25.2, and `VOLT 37` lands. The manual advises against using it, and
    `LIMITS` is the rated 36 V and 24 A.
  * **The current setting reaches zero.** `CURR 0` lands, so
    `MIN_CURRENT_A` is 0 - unlike the TSX-P's 10 mA.
  * **A setting lands just below what was sent.** *Measured:* `VOLT
    1.23456` reads back 1.2340, `VOLT 11` 10.9995, `CURR 0.123456`
    0.1232. Under a millivolt and under half a milliamp, always down.
    The full-precision level is sent and what the run records is what
    was read back (fault 4).
  * **Settings survive power-off, one step lower.** The supply starts
    with the output off (safe start) and the last settings - each read
    back a fraction of a millivolt lower than before the power cycle.
    `reset()` is what makes a session start from known values.
  * **The meter refreshes about every 210 ms.** *Measured:* a query
    takes 10 to 16 ms, but the reading changes in steps about 210 ms
    apart, so asking faster repeats it. The output itself is quicker -
    a 1 V to 5 V step was there by the next refresh, 5 V to 1 V took
    about 0.3 s, and off from 1 V fell to zero in about 0.26 s, all open
    circuit. `SETTLING_S` is two refreshes and some margin.
  * **The current meter is coarse.** The manual gives 0.1% of the
    reading plus 0.3% of rated - 72 mA on this model. *Measured* at open
    circuit it read 0.0000, five times out of five.
  * **`SYST:REM LOC` hands the front panel back.** *Measured:* the REM
    LED went out, a query left it out, and the next setting put the
    supply back in remote. `release_front_panel()` sends it when the app
    disconnects.

Never sent
----------
  * `*SAV`, `*RCL` and `LIST:LOAD`/`WAVE:LOAD`. A recall restores the
    output state with the levels, so it can energise from a command that
    reads like housekeeping.
  * `LIST`, `WAVE`, `TRIG`, `INIT` and `*TRG` - the sequencer. While
    `INIT:CONT` is on no setting can be changed at all, and this suite's
    sweeps are stepped from the PC, where each point's level is known.
  * The `GLOBal` commands. No acknowledgement, no error, and they act on
    every supply on the chain.
  * `FRST`, which changes the communication settings and drops the link.
  * `SYST:REM LLO`, which locks out the front panel - its OUTPUT key
    included - until a bus command or a power cycle.
  * `*PSC`, `*SRE`, `*ESE` and the `STAT` enable registers. An enabled
    register makes the supply send `!nn` down the serial line unasked,
    which the next query would take for its reply.
  * Foldback, UVP, the interlock, the relay pins, trigger out and
    auto-restart. Foldback shuts the output off at exactly the CV/CC
    crossover a supply's compliance is, and auto-restart switches the
    output back on after a power cut. `reset()` sends auto-restart *off*
    explicitly, which is the one setting of these it writes.
"""
import re
import time

from smuniversal_lab_suite.core.limits import POSITIVE, LimitError, SMULimits
from smuniversal_lab_suite.core.transports.base import TransportDesynchronised

from .base_supply import CC, CV, BaseSupply

#: The fault register, `STAT:QUES:COND?`, by bit (manual table 9-1).
#: Bit 6, "output off", is left out: it is not a fault, and *measured* it
#: read 0 with the output off anyway.
FAULT_BITS = {
    2: "AC fail",
    4: "over-temperature",
    8: "foldback",
    16: "over-voltage",
    32: "shut off from the rear panel",
    128: "interlock open",
    256: "under-voltage",
}
FAULT_MASK = sum(FAULT_BITS)

#: A voltage above this fraction of the trip is refused (error 301), and
#: a trip below the voltage times `TRIP_OVER_VOLTAGE` (error 304).
VOLTAGE_UNDER_TRIP = 0.95
TRIP_OVER_VOLTAGE = 1.05

#: `-222,"Data Out Of Range;address 1"` and `+304,"OVP Below PV;address
#: 1"`. The quotes and the address suffix are optional, so a reply in
#: the manual's own form - `0,"No error"` - parses too.
_ERROR = re.compile(r'^\s*([-+]?\d+)\s*,\s*"?(.*?)"?\s*$')
_ADDRESS_SUFFIX = re.compile(r";\s*address\s*\d+\s*$", re.IGNORECASE)


class TDKLambdaZPlus(BaseSupply):
    """The Z+ command set. Not registered itself: a model declares its
    identity, its envelope and its error probe."""

    #: The USB ids its rear USB port enumerates with. *Measured:* Windows
    #: binds its own "USB Serial Device" driver to it - TDK's is not
    #: needed. The registry sends `greeting()` before `*IDN?` to a serial
    #: port with these ids, and to no other.
    USB_IDS = ((0x2504, 0x0001),)

    #: The address set at the front panel (REM, then ADR), 1 to 31.
    #: **This bench's, not a fact about the model:** the factory setting
    #: is 6 and this unit is at 1. Change the front panel and this has
    #: to follow, or nothing the supply is sent will be heard.
    BUS_ADDRESS = 1

    #: Setting and readback steps. The readback answers to 0.1 mV and
    #: 0.1 mA, and a setting lands up to about 0.6 mV and 0.4 mA below
    #: what was sent - so a millivolt and a milliamp is one step of
    #: tolerance either way, and the readback check is graded on it.
    RESOLUTION = {"voltage": 0.001, "current": 0.001}

    #: `CURR 0` lands (measured). A floor of zero is a declared floor,
    #: not a missing one.
    MIN_CURRENT_A = 0.0

    #: Not yet: a value set at the front panel has not been read back
    #: over the bus. Same rule as every other driver here.
    SETPOINT_READBACK_TRUSTED = False
    OVP_READBACK_TRUSTED = False

    NPLC_RANGE = None
    #: A continuous trip, not a menu - see `BaseSupply.OVP_RANGE_V`.
    OVP_CHOICES = []
    #: The output switch does not disconnect the terminals.
    HIGH_Z_OFF = False
    #: Sensing is the rear J2 connector's wiring. Software cannot see it.
    REMOTE_SENSE_CONTROL = False
    FIXED_SENSE = ("set by the rear J2 sense connector (local sense with "
                   "the factory jumpers fitted, remote sense with them "
                   "removed and leads to the load)")

    #: Two meter refreshes (about 210 ms each, measured) and margin. The
    #: output itself settled faster than that open circuit.
    SETTLING_S = 0.5
    READBACK_SETTLE_S = 0.5

    #: `*CLS` takes 150 ms to execute, in the manual's words.
    CLS_SETTLE_S = 0.15

    #: Held after every write. Not measured either way: every write in
    #: both probe sittings was followed by at least 150 ms before the
    #: next, and the MP710772 lost writes sent back to back. The first
    #: checkup is where a shorter one can be tried.
    WRITE_DELAY_S = 0.05

    ROLE_CAVEATS = {
        "power_supply_grade": (
            "It is a bench power supply, not a source-measure unit: its "
            "current reading is specified to within tens of milliamps, "
            "and it works in one quadrant only - positive voltage, "
            "current out, no sinking."),
    }

    def __init__(self, transport):
        super().__init__(transport)
        #: What this driver last set the trip and the voltage to, for
        #: the two rules that tie them. None until `reset()` has run, in
        #: which case each guard asks the instrument instead.
        self._trip_v = None
        self._voltage_v = None
        #: A fault seen since the output last went on.
        self._fault_seen = 0

    # ---- selection ----
    @classmethod
    def greeting(cls):
        """What has to be sent before this supply hears anything."""
        return (f"INST:NSEL {int(cls.BUS_ADDRESS)}",)

    def _select(self):
        for line in self.greeting():
            self.transport.write(line)

    def identify(self):
        """`*IDN?`, after selecting the supply - so a driver chosen by
        hand, which the registry never greeted, is heard too."""
        self._select()
        return self.transport.query("*IDN?").strip()

    # ---- parsing ----
    def _number(self, command, timeout_s=3.0):
        """One numeric reply, or None. Replies are bare and zero-padded -
        `01.2340`, `000.00` - so `float()` takes them as they come."""
        reply = self.transport.query(command, timeout_s=timeout_s)
        try:
            value = float(str(reply).strip())
        except ValueError:
            return None
        return self.drop_sentinel(value)

    # ---- reset ----
    def reset(self):
        """Select, reset, enable errors, and say the safe settings.

        `*RST` leaves the output off at 0 V and 0 A with the trip at its
        maximum and auto-restart off (measured, apart from auto-restart,
        which read off before and after). It also returns the front
        panel to local.

        `SYST:ERR:ENAB` is the line that matters: without it every
        refusal is silent. It is sent after `*CLS`, which the manual
        says clears "the entire status structure".

        The trip and auto-restart are then sent anyway. A default that
        is never sent is a default nobody chose (fault 17); the trip's
        reset value is the least protective one available, and
        auto-restart is the setting that would switch the output on by
        itself after a power cut.
        """
        self._select()
        self.transport.write("*RST")
        self.transport.write("*CLS")
        time.sleep(self.CLS_SETTLE_S)
        self.transport.write("SYST:ERR:ENAB")
        self._output_enabled = False
        self._source_function = None
        self._fault_seen = 0
        self._voltage_v = 0.0
        if self.OVP_RANGE_V is not None:
            self._send_overvoltage_trip(self.OVP_RANGE_V[1])
        self.transport.write("OUTP:PON 0")

    # ---- the two knobs ----
    def _trip(self):
        if self._trip_v is None:
            self._trip_v = self.read_overvoltage_trip()
        return self._trip_v

    def _voltage(self):
        if self._voltage_v is None:
            self._voltage_v = self.read_voltage_setpoint()
        return self._voltage_v

    def set_output_voltage(self, volts):
        """`VOLT <volts>`, refused first if it is above 95% of the trip -
        the instrument would ignore it, and the output would stay at the
        last level with only an error number to say so."""
        volts = float(volts)
        trip = self._trip()
        if trip is not None and volts > trip * VOLTAGE_UNDER_TRIP + 1e-9:
            raise LimitError(
                f"{self.DISPLAY_NAME}: {volts:.6g} V is above 95% of the "
                f"over-voltage trip ({trip:.6g} V), and the supply refuses "
                f"that. Raise the trip to at least "
                f"{volts / VOLTAGE_UNDER_TRIP:.4g} V first.")
        self.transport.write(f"VOLT {volts:.6g}")
        self._voltage_v = volts

    def set_output_current(self, amps):
        """`CURR <amps>` - the current limit, which on a supply is also
        the constant-current level."""
        self.transport.write(f"CURR {float(amps):.6g}")

    # ---- output ----
    def _switch_output(self, on):
        """`OUTP 1` / `OUTP 0`. `OUTP?` reads the state back - see
        `read_output_state()`."""
        if on:
            self._fault_seen = 0
        self.transport.write(f"OUTP {1 if on else 0}")

    def read_output_state(self):
        """True, False, or None if the reply is not 0 or 1."""
        value = self._number("OUTP?")
        return None if value not in (0.0, 1.0) else bool(value)

    def release_front_panel(self):
        """`SYST:REM LOC`: the front panel back to the operator.

        Not part of any contract. The app sends it when it disconnects,
        after the output is off. A setting sent later takes the supply
        back into remote by itself (measured), so this cannot strand a
        session."""
        self.transport.write("SYST:REM LOC")

    # ---- the over-voltage trip ----
    def _send_overvoltage_trip(self, volts):
        """`VOLT:PROT:LEV <volts>`, refused first if it is below 105% of
        the voltage setting - the instrument would keep the old trip."""
        volts = float(volts)
        voltage = self._voltage()
        if voltage is not None and volts < voltage * TRIP_OVER_VOLTAGE - 1e-9:
            raise LimitError(
                f"{self.DISPLAY_NAME}: an over-voltage trip of {volts:.6g} V "
                f"is below 105% of the voltage setting ({voltage:.6g} V), "
                f"and the supply refuses that. Lower the voltage first.")
        self.transport.write(f"VOLT:PROT:LEV {volts:.6g}")
        self._trip_v = volts

    # ---- reading settings back ----
    def read_voltage_setpoint(self):
        """`VOLT?` -> `01.2340`."""
        return self._number("VOLT?")

    def read_current_setpoint(self):
        """`CURR?` -> `00.1232`."""
        return self._number("CURR?")

    def read_overvoltage_trip(self):
        """`VOLT:PROT:LEV?` -> `40.00`."""
        return self._number("VOLT:PROT:LEV?")

    # ---- which knob is in charge ----
    def regulation(self):
        """`OUTP:MODE?`: `CV`, `CC`, or None.

        A state, read now - unlike the TSX-P's limit events, there is no
        "since the last poll", so `CROSSED` never comes from here. `OFF`
        is None: with the output off nothing is being regulated. A reply
        that cannot be read is None too; being unable to ask is not
        constant voltage.
        """
        try:
            reply = str(self.transport.query("OUTP:MODE?")).strip().upper()
        except TransportDesynchronised:
            raise
        except Exception:
            return None
        return {"CV": CV, "CC": CC}.get(reply)

    def protection_tripped(self):
        """True once a fault has been seen since the output last went on.

        The fault register is live - a bit clears when its cause does -
        so a trip that came and went between polls is latched here
        rather than lost. Which fault it was is in `read_error()`, where
        the supply files 320 to 327 ("Over-Voltage Shutdown" and so on).
        """
        try:
            value = self._number("STAT:QUES:COND?")
        except TransportDesynchronised:
            raise
        except Exception:
            return None
        if value is None:
            return None
        self._fault_seen |= int(value) & FAULT_MASK
        return bool(self._fault_seen)

    def faults(self):
        """The names of the faults latched by `protection_tripped()`."""
        return [name for bit, name in FAULT_BITS.items()
                if self._fault_seen & bit]

    # ---- timing and sensing ----
    def set_source_delay(self, seconds):
        """Accepted, and applied by the host: there is no settle-time
        command. The software sweep waits `delay_s` between setting a
        level and measuring."""

    def set_remote_sense(self, on=True):
        """Refused: sensing is the rear connector's wiring, and accepting
        a request would record a mode the measurement may not have
        used."""
        raise NotImplementedError(
            f"{self.DISPLAY_NAME} has no remote-sense command. Sensing is "
            f"{self.FIXED_SENSE}, and this driver records that rather than "
            f"claiming a control it does not have.")

    # ---- measurement ----
    def measure(self, timeout_s=3.0):
        """`(volts, amps)` from `MEAS:VOLT?` and `MEAS:CURR?`.

        Two queries, so not one instant - but the meter only refreshes
        every 210 ms or so, and the pair takes about 25 ms. Current out
        of the positive terminal is positive, as for every source here.
        """
        volts = self._number("MEAS:VOLT?", timeout_s=timeout_s)
        amps = self._number("MEAS:CURR?", timeout_s=timeout_s)
        return volts, amps

    def measure_power(self, timeout_s=3.0):
        """`MEAS:POW?`, in watts. Not part of any contract."""
        return self._number("MEAS:POW?", timeout_s=timeout_s)

    # ---- errors ----
    def read_error(self):
        """Pop one entry off `SYST:ERR?`, as `(code, message)`.

        A real queue, ten deep, once `reset()` has enabled it. The
        supply appends `;address 1` to each message, which is dropped.
        Follows the contract's two rules: a failure to ask is code 0
        with the reason, and an unparseable reply is code 0 with the
        raw text.
        """
        try:
            reply = str(self.transport.query("SYST:ERR?")).strip()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            return 0, (f"could not read the error queue "
                       f"({type(exc).__name__}: {exc})")
        match = _ERROR.match(reply)
        if match is None:
            return 0, reply
        message = _ADDRESS_SUFFIX.sub("", match.group(2)).strip()
        return int(match.group(1)), message


class TDKLambdaZ36_24(TDKLambdaZPlus):
    MODEL_IDS = ["Z36-24"]
    DISPLAY_NAME = "TDK-Lambda Z36-24"

    #: Rated 36 V and 24 A, both available together (864 W). The supply
    #: accepts 5% more of each (measured); the envelope is the rating.
    LIMITS = SMULimits(
        max_voltage=36.0,
        max_current=24.0,
        voltage_ranges=[36.0],
        current_ranges=[24.0],
        voltage_polarity=POSITIVE,
        current_polarity=POSITIVE,
    )

    #: Manual table 7-9 for the 36 V models. *Measured:* `VOLT:PROT:LEV
    #: 1` is refused, `VOLT:PROT:LEV? MAX` reads 40.00, and `MIN` puts the
    #: trip 5% above the voltage setting.
    OVP_RANGE_V = (2.0, 40.0)

    #: A current above the 25.2 A the supply accepts. Harmless if it
    #: landed - a limit above the rating, with the output off - and
    #: *measured*: `-222,"Data Out Of Range;address 1"`, once errors are
    #: enabled, and nothing at all before.
    ERROR_PROBE = ("CURR 30", -222)
