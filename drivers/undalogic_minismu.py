"""
Undalogic miniSMU MS01 - the first driver that isn't a command dialect.

Every other driver here writes strings. This one calls methods on
`minismu_py`, reached through `MiniSMUTransport` (see that file for why
the library is wrapped rather than reimplemented). The class still
implements the same BaseSMU contract, so `IVSweepExperiment` cannot tell
the difference.

Envelope: 2 channels, 4-quadrant, +/-12 V, +/-180 mA, 2.1 W per channel.
Five current ranges: 1 uA, 25 uA, 650 uA, 15 mA, 180 mA.

---------------------------------------------------------------------
THE 12 V DC ADAPTER IS REQUIRED
---------------------------------------------------------------------
Running the MS01 from USB-C alone limits it to **50 mA per channel**
instead of 180 mA, and the instrument does not report which supply it is
on - there is no command to ask. So this driver assumes the included
12 V adapter is plugged in, declares the full 180 mA envelope, and says
so in the console every time it connects.

Getting this wrong is not dangerous, it is just confusing: on bus power
a sweep that asks for more than 50 mA silently folds back, and the
resulting curve looks like a sample going into compliance at a current
nobody set. The connect-time note exists so that possibility is on
screen before the first sweep rather than diagnosed afterwards.

---------------------------------------------------------------------
DO NOT CALL client.reset() FROM HERE
---------------------------------------------------------------------
`minismu_py.SMU.reset()` sends `*RST`, and on this instrument that
**reboots the device**. Over USB it then re-enumerates, so the serial
port this connection is holding disappears and every later call fails.
The library's own docstring says to construct a new SMU afterwards.

That matters more here than it would elsewhere, because
`LabApp._initialise_driver()` calls `driver.reset()` on *every* connect.
Wiring the obvious thing through would have made connecting to a miniSMU
kill the connection it had just opened, every single time, and the
symptom - everything fails immediately after a successful connect -
looks like a cable fault rather than a software one.

So `reset()` below puts the channel into a known state with ordinary
commands and never sends `*RST`. `reboot()` exists separately, is not
called by anything, and says what it does.

---------------------------------------------------------------------
Known characteristic: a small voltage offset
---------------------------------------------------------------------
Measured on the bench 2026-08-05: about **-1.5 mV** of voltage offset,
seen three ways that agree - the checkup read -1.65 mV with 0 V
sourced, and 10 kohm sweeps fitted intercepts of -1.36 mV (2-wire) and
-1.88 mV (4-wire).

It is an offset, so it cancels in anything derived from a *slope*:
resistance from an IV fit is unaffected, and both of those sweeps
recovered the resistor to better than 0.1%. It does not cancel in a
single-point voltage reading, which is worth knowing before using this
instrument for anything measuring microvolts - a 4-point-probe or Hall
voltage sits well below this offset.

Polarity is conventional: positive sourced current gives positive
measured voltage, R = +9.95 kohm on a 10 kohm resistor. (Noted because
the checkup's open-circuit compliance reading rails negative, which
briefly looked like an inverted sign convention and is not one - a
railed output is not regulating, so its sign means nothing.)

---------------------------------------------------------------------
Firmware gates capability, not just model
---------------------------------------------------------------------
Two features depend on the firmware in the box rather than on which box
it is:

    onboard I-V sweep    firmware 1.3.4+
    4-wire Kelvin mode   firmware 1.4.3+

The version is in the `*IDN?` reply, so it is read at connect and both
features degrade rather than fail: no onboard sweep means the inherited
software sweep, and no 4-wire means the sensing control is declared as
unavailable, exactly as on an instrument that never had it.

This is the first driver whose capabilities are decided at runtime by
something other than the instrument's answer to a probe. The GSM asks
"do you understand this command?"; this one asks "what version are you?".

---------------------------------------------------------------------
Sweep kind varies per run, not per instrument
---------------------------------------------------------------------
The onboard sweep is **voltage-only** - `SOUR<n>:SWEEP:VOLT:START` and
`:END`, with no current equivalent. So a voltage sweep runs on the
instrument's own timebase and a current sweep falls back to BaseSMU's
point-by-point software sweep on the same connection.

`sweep_kind()` is therefore an instance method that answers for the mode
currently selected, and the experiment already stamps its answer into
every run's CSV. Two runs off this instrument can legitimately differ,
and the file says which is which.

---------------------------------------------------------------------
Integration time: OSR mapped onto the NPLC control
---------------------------------------------------------------------
There is no NPLC setting. The knob is `MEAS<n>:OSR`, an oversampling
ratio of 0-15 giving roughly 2^OSR samples. Same job - average longer,
get a quieter reading - so it is exposed through the existing NPLC
control rather than growing a second one beside it.

The mapping treats a requested NPLC as an integration *window*
(NPLC / line frequency) and picks the OSR whose window is closest in
log space. `clamp_nplc()` then returns the window actually achievable,
expressed back in power line cycles, so what lands in the CSV is what
the instrument really integrated over rather than what was typed.

**Two honest differences, both worth knowing before comparing
datasets.**

True NPLC integrates over a whole number of mains periods, which is what
makes 50 Hz hum on the leads average to zero. The miniSMU's oversampling
is not synchronised to the mains, so an "equivalent 1 NPLC" here rejects
hum less well than 1 NPLC on a Keithley. The number in the file is a
truthful integration *time*; it is not a promise of the same noise
floor.

**The `nplc` this driver records for the miniSMU is not a measured
integration time and should not be treated as one.** A six-point timing
scan showed reading cost is not proportional to the sample count at all
- an eightfold increase in samples costs about 2.2x the time, and the
implied conversion rate climbs from 10 kS/s to 210 kS/s across the
ladder. Whatever `MEAS:OSR` does on this instrument, it is not "average
N samples at a fixed rate".

So the figure in the file orders the OSR settings correctly - more is
more integration - but its absolute value is unfounded, and comparing it
with a true-NPLC instrument's is meaningless. What is solid is the OSR
itself, which is reported in sweep_note() for exactly this reason.

Note also that this instrument tops out at 16.4 PLC equivalent on the
current scale. Asking for more integration than that on the panel is not
refused, it is clamped - and the clamped value is what lands in the
file.
"""
import math
import re
import time

from core.limits import SMULimits
from core.ranges import AUTO
from .base_smu import BaseSMU

# Which channel the rig uses. The MS01 has two, and 4-wire mode consumes
# the second as a sense channel, so channel 1 is the only sensible
# default for a 4-wire rig.
DEFAULT_CHANNEL = 1

# Mains frequency, used only to convert between the NPLC the panel talks
# in and the integration window the instrument actually offers. Not sent
# to the instrument - it has no line-frequency setting, which is part of
# why its averaging is not mains-synchronised.
LINE_FREQUENCY_HZ = 50.0

# Conversion rate used to turn an OSR into an integration window.
#
# ---------------------------------------------------------------------
# THIS CONSTANT IS KNOWN TO BE WRONG. See the warning below.
# ---------------------------------------------------------------------
#
# A six-point timing scan on 2026-08-06 disproved the model this
# constant belongs to. If a reading cost `overhead + samples / rate`,
# the rate implied by each point would be the same. It is not:
#
#     OSR   samples   reading   minus overhead   implied rate
#       0         1    6.2 ms            0 ms    -
#       3         8    6.2 ms            0 ms    -
#       6        64   12.4 ms          6.2 ms     10 kS/s
#       9       512   34.4 ms         28.2 ms     18 kS/s
#      12      4096   75.0 ms         68.8 ms     60 kS/s
#      15     32768  162.6 ms        156.4 ms    210 kS/s
#
# The implied rate climbs twentyfold across the range, and an eightfold
# increase in samples costs only about 2.2x the time. So no single
# conversion rate describes this instrument, and the whole NPLC
# equivalence rests on a premise the hardware does not honour.
#
# The value is kept only because the mapping needs *some* scale to
# order the OSR ladder by, and 100 kS/s is the least wrong single
# number available - it comes from the widest-spaced pair. It should
# not be read as a measured property of the instrument.
SAMPLE_RATE_HZ = 100000.0

# Highest OSR the NPLC control will select. The hardware maximum is 15,
# and at the measured rate that is 32768 samples in 328 ms - about 16.4
# power line cycles, comfortably inside what the rest of the suite
# offers. So the whole hardware range is usable and this is no longer a
# self-imposed cap: 16.4 PLC is simply the most integration this
# instrument can do.
MAX_USABLE_OSR = 15

# Firmware floors, from the library's documentation.
FIRMWARE_ONBOARD_SWEEP = (1, 3, 4)
FIRMWARE_FOUR_WIRE = (1, 4, 3)

# Onboard sweep bounds enforced by the library itself.
MAX_SWEEP_POINTS = 1000
MAX_DWELL_MS = 10000

# Sweep points that fit in the firmware's ~5.7 kB TCP response, CSV
# format, on firmware 1.5.0 and earlier. Over USB there is no such
# limit. Used for a warning, not a refusal - the operator may well have
# newer firmware.
TCP_CSV_POINT_WARNING = 175


class UndalogicMiniSMU(BaseSMU):
    # Confirmed on the bench 2026-08-05:
    #     Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)
    # Note the model field carries a hardware revision and the serial is
    # a word-triplet rather than digits - neither is matched on.
    MODEL_IDS = ["MINISMU MS01", "MINISMU", "MS01"]
    DISPLAY_NAME = "Undalogic miniSMU MS01"

    # Provisional, like the GSM's: downgraded to "software" when the
    # firmware is too old for the onboard sweep, and reported per-mode by
    # the instance method below. Kept as a class attribute so the
    # capability ledger has something to read.
    SWEEP_KIND = "hardware"

    LIMITS = SMULimits(
        max_voltage=12.0,
        max_current=0.18,
        # The voltage "ranges" this model exposes are the tokens AUTO,
        # LOW and HIGH, and the manual does not say what LOW and HIGH
        # are in volts. These are therefore menu conveniences for the
        # compliance dropdown, not a hardware range ladder - see
        # set_voltage_range() below, which always selects AUTO.
        voltage_ranges=[0.1, 1.0, 5.0, 12.0],
        # These are real, and they are the library's own table.
        current_ranges=[1e-6, 25e-6, 650e-6, 15e-3, 180e-3],
        # 2.1 W per channel: 12 V tops out at 175 mA, and 180 mA tops
        # out at 11.6 V. The corner barely binds, but a sweep to 12 V
        # with a 180 mA compliance is outside it and the gate should say
        # so rather than let the instrument fold back mid-run.
        power_envelope=[(12.0, 0.175), (11.6, 0.18)],
    )

    # What the current ceiling would be on bus power. Not used to narrow
    # LIMITS - the adapter is a stated requirement, not an option - but
    # kept so the console note can name the number it is warning about.
    BUS_POWERED_MAX_CURRENT = 0.05

    # Equivalent-NPLC window, derived from the OSR ladder rather than
    # declared: OSR 0 is 1 ms (0.05 PLC at 50 Hz) and MAX_USABLE_OSR is
    # 512 ms (25.6 PLC).
    NPLC_RANGE = (
        (2 ** 0) / SAMPLE_RATE_HZ * LINE_FREQUENCY_HZ,
        (2 ** MAX_USABLE_OSR) / SAMPLE_RATE_HZ * LINE_FREQUENCY_HZ,
    )

    # No overvoltage-protection command, and no output-off mode: the
    # only output control is OUTP<n> ON/OFF.
    OVP_CHOICES = []
    HIGH_Z_OFF = False

    # 4-wire is switchable in software - unlike the U2722A - but it is a
    # system-wide mode that takes over channel 2, and it needs firmware
    # 1.4.3+. Both facts are handled in set_remote_sense().
    REMOTE_SENSE_CONTROL = True
    FIXED_SENSE = None

    def __init__(self, transport, channel=DEFAULT_CHANNEL):
        # This driver calls methods on minismu_py; it does not send
        # text. So it needs MiniSMUTransport, which owns that library
        # object and exposes it as `.client`.
        #
        # Checked here rather than left to fail later, because the
        # failure it prevents is genuinely confusing. The MS01 answers
        # `*IDN?` over a plain serial connection, so opening it with
        # SerialTransport *succeeds*, auto-detection then correctly
        # identifies a miniSMU, and this driver is handed a transport it
        # cannot use. The first method call then reports "miniSMU
        # transport is not connected" - about a transport that is
        # connected, and working, and simply the wrong kind.
        if not hasattr(transport, "client"):
            raise TypeError(
                f"{self.DISPLAY_NAME} is driven through the minismu_py "
                f"library rather than a text protocol, so it needs "
                f"MiniSMUTransport - got {type(transport).__name__}. The "
                f"instrument does answer *IDN? over plain serial, which is "
                f"why this got as far as it did. In the app, pick "
                f"\"miniSMU\" in the transport dropdown; on the command "
                f"line, pass --transport minismu.")
        super().__init__(transport)
        self.channel = int(channel)
        self._firmware = None          # (major, minor, patch) or None
        self._source_mode = "voltage"
        self._four_wire = False
        self._osr = None
        self._sweep_points = 0
        self._sweep_mode = "voltage"
        self._sweep_running = False
        self._note = ""

    # ---- the library object ----
    @property
    def client(self):
        """The `minismu_py.SMU` this driver drives.

        Reached through the transport rather than held directly so that
        `LabApp.disconnect_role()` closing the transport really does
        close the instrument - a second reference here would keep a
        dead connection alive and make reconnecting fail.
        """
        client = getattr(self.transport, "client", None)
        if client is None:
            raise ConnectionError("miniSMU transport is not connected.")
        return client

    # ---- identity ----
    def identify(self):
        idn = self.client.get_identity()
        self._firmware = self._parse_firmware(idn)
        return str(idn).strip()

    @staticmethod
    def _parse_firmware(idn):
        """Pull (major, minor, patch) out of an *IDN? reply, or None.

        Repeated here rather than imported from the library, because
        `SMU.firmware_version` is only populated automatically on
        network connections - over USB it stays None and this driver's
        firmware gates would silently fall to their safe side forever.

        **The LAST version-shaped token wins, not the first.** The real
        reply is:

            Undalogic Ltd,miniSMU MS01 v1.1,lunar-tuvok-7966,v1.4.6(6b82396)

        There are two `v`-prefixed versions in there: a *hardware*
        revision in the model field and the firmware at the end. The
        first only escaped being matched because it has two components
        rather than three. A hardware v1.1.2 would have been read as
        firmware 1.1.2, which is below both feature gates - so the
        onboard sweep and 4-wire would have silently switched
        themselves off on a perfectly capable instrument, and the
        report would have said "firmware 1.1.2" without anything
        looking wrong.
        """
        if not idn:
            return None
        matches = re.findall(r"v(\d+)\.(\d+)\.(\d+)", str(idn))
        if not matches:
            return None
        return tuple(int(g) for g in matches[-1])

    def firmware(self):
        """Firmware version tuple, reading it if it isn't known yet."""
        if self._firmware is None:
            try:
                self.identify()
            except Exception:
                return None
        return self._firmware

    def _firmware_at_least(self, wanted):
        """True when the firmware is known to be new enough.

        Unknown counts as *not* new enough. An unparseable identity is
        not evidence of a recent build, and the consequence of guessing
        high is a feature that fails mid-run instead of a fallback that
        works.
        """
        version = self.firmware()
        return version is not None and version >= wanted

    def reset(self):
        """Put the channel into a known state WITHOUT rebooting.

        See the module docstring: `client.reset()` sends `*RST`, which
        reboots the instrument and invalidates this connection, and the
        app calls reset() on every connect.

        What a reset needs to achieve is that nothing inherited from the
        last session changes what this session measures - so the output
        goes off, autoranging goes back on, and the voltage range
        returns to AUTO. Everything else (mode, levels, compliance, OSR)
        is set explicitly on every run by the experiment.
        """
        self.output_off()
        self.client.set_autorange(self.channel, True)
        self.client.set_voltage_range(self.channel, "AUTO")

        # Leaving 4-wire enabled from a previous session would silently
        # commandeer channel 2 and change what a "voltage" reading
        # means. Only touched when the firmware has the feature at all.
        if self._firmware_at_least(FIRMWARE_FOUR_WIRE):
            try:
                if self.client.get_fourwire_mode():
                    self.client.disable_fourwire_mode()
            except Exception:
                pass
        self._four_wire = False
        self._osr = None

    def reboot(self):
        """Actually send `*RST`, rebooting the instrument.

        Not called by anything. After this the connection is dead and
        the transport must be reopened - which is exactly why it is not
        what reset() does.
        """
        self.client.reset()

    # ---- source configuration ----
    def set_source_function(self, mode):
        """FVMI (force voltage, measure current) or FIMV (the reverse)."""
        if mode == "voltage":
            self.client.set_mode(self.channel, "FVMI")
        elif mode == "current":
            self.client.set_mode(self.channel, "FIMV")
        else:
            raise ValueError(f"Unknown source mode: {mode!r}")
        self._source_mode = mode

    def set_current_level(self, amps):
        self.client.set_current(self.channel, float(amps))

    def set_voltage_level(self, volts):
        self.client.set_voltage(self.channel, float(volts))

    def set_current_limit(self, amps):
        """Current compliance while sourcing voltage."""
        self.client.set_current_protection(self.channel, abs(float(amps)))

    def set_voltage_limit(self, volts):
        """Voltage compliance while sourcing current."""
        self.client.set_voltage_protection(self.channel, abs(float(volts)))

    # ---- ranging ----
    # ---- ranging: per-axis (wave 6d) ----
    #: The vendor library exposes one range per quantity, chosen by the
    #: limit it has to carry, and it serves both source and measure.
    INDEPENDENT_SOURCE_RANGE = False
    HAS_MEASURE_RANGE = False

    def _apply_source_current_range(self, amps):
        if amps is AUTO:
            self.client.set_autorange(self.channel, True)
            return
        self.client.set_current_range_by_limit(self.channel, abs(float(amps)))

    def _apply_source_voltage_range(self, volts):
        """The instrument takes AUTO, LOW or HIGH and publishes no
        thresholds, so AUTO is the only honest choice - see
        `set_voltage_range`. A fixed request is accepted and mapped to
        AUTO rather than refused, because autoranging genuinely covers
        it; the alternative would be guessing at a threshold."""
        self.client.set_voltage_range(self.channel, "AUTO")

    def set_current_range(self, amps=None):
        """Fix the current range, or pass None for autoranging.

        Unlike the U2722A this model really does autorange, and it is
        the default. `set_current_range_by_limit()` picks the smallest
        of the five ranges that fits and turns autoranging off in the
        same call.
        """
        if amps is None:
            self.client.set_autorange(self.channel, True)
            return
        self.client.set_current_range_by_limit(self.channel, abs(float(amps)))

    def set_voltage_range(self, volts=None):
        """Always selects AUTO.

        The instrument takes AUTO, LOW or HIGH, and no published
        document says what LOW and HIGH mean in volts. Mapping a
        requested level onto them would be a guess, and guessing wrong
        gives a clipped sweep that still looks like a clean measurement.
        AUTO is correct in every case and merely gives up some
        resolution, so that is what gets sent until the breakpoints are
        confirmed.
        """
        self.client.set_voltage_range(self.channel, "AUTO")

    # ---- sensing ----
    def set_remote_sense(self, on=True):
        """4-wire Kelvin mode, which is system-wide rather than
        per-channel.

        Enabling it makes channel 2 the sense channel: CH2 commands are
        blocked, and OUTP1 then switches both channels together. So this
        is not just a sensing preference, it costs the second channel
        for the duration.

        Refused while a sweep is running, because the instrument refuses
        it too - better a clear message here than an SMUException from
        two layers down.
        """
        want = bool(on)
        if want and not self._firmware_at_least(FIRMWARE_FOUR_WIRE):
            version = self.firmware()
            raise NotImplementedError(
                f"4-wire sensing needs miniSMU firmware "
                f"{'.'.join(str(n) for n in FIRMWARE_FOUR_WIRE)} or later; "
                f"this unit reports "
                f"{'.'.join(str(n) for n in version) if version else 'an unknown version'}."
                f" Update the firmware or untick 4-wire.")
        if want and self._sweep_running:
            raise RuntimeError(
                "4-wire mode cannot be changed while a sweep is running.")

        if want == self._four_wire:
            return
        if want:
            self.client.enable_fourwire_mode()
        else:
            self.client.disable_fourwire_mode()
        self._four_wire = want

    def supports_remote_sense_control(self):
        """Instance override: on this model the answer depends on the
        firmware in the box, not on the class.

        The base version is a classmethod, and the capability ledger
        reads it as one - which is right, because the *model* has the
        feature. What varies is whether the unit in front of you does.
        """
        return self._firmware_at_least(FIRMWARE_FOUR_WIRE)

    # ---- timing ----
    def set_source_delay(self, seconds):
        """No-op: there is no instrument-side source delay outside the
        onboard sweep, where it is the dwell time and is passed to
        `configure_iv_sweep()` directly.

        The panel's delay field still works for software sweeps, which
        settle host-side.
        """

    @classmethod
    def clamp_nplc(cls, nplc):
        """Snap a requested NPLC to the nearest achievable OSR window.

        Returns the value the instrument will actually integrate over,
        in power line cycles - not what was asked for. That is the whole
        point: the CSV should record what happened.
        """
        osr = cls.osr_for_nplc(nplc)
        return cls.nplc_for_osr(osr)

    @classmethod
    def osr_for_nplc(cls, nplc):
        """Closest OSR to a requested NPLC, chosen in log space.

        Log space rather than linear because the ladder is powers of
        two: halfway between 0.8 and 1.6 PLC is 1.13, not 1.2, and
        rounding a requested 1.0 the linear way would pick the slower
        setting for no reason.
        """
        window_s = max(float(nplc), 1e-9) / LINE_FREQUENCY_HZ
        samples = window_s * SAMPLE_RATE_HZ
        osr = int(round(math.log2(max(samples, 1.0))))
        return max(0, min(osr, MAX_USABLE_OSR))

    @staticmethod
    def nplc_for_osr(osr):
        """The integration window of an OSR, in power line cycles."""
        return (2 ** int(osr)) / SAMPLE_RATE_HZ * LINE_FREQUENCY_HZ

    def set_nplc(self, nplc):
        """Set integration time via the oversampling ratio."""
        osr = self.osr_for_nplc(nplc)
        self.client.set_oversampling_ratio(self.channel, osr)
        self._osr = osr

    def oversampling_ratio(self):
        """The OSR currently set, or None. Exposed because it is the
        number the instrument's own documentation talks in."""
        return self._osr

    # ---- output ----
    def output_on(self):
        self.client.enable_channel(self.channel)

    def output_off(self):
        self.client.disable_channel(self.channel)

    # ---- measurement ----
    def read_error(self):
        """The library raises rather than queueing, so this is always
        empty by the time anyone can ask.

        `minismu_py` 0.4.0+ turns a device-reported error into an
        `SMUException` at the call site instead of leaving it in a queue
        to be collected later. That is a better design - the failure
        arrives attached to the command that caused it - but it means
        there is nothing here to pop, and a checkup on this instrument
        gets its syntax verification from calls raising rather than from
        polling a queue.
        """
        return (0, "")

    def measure(self, timeout_s=3.0):
        """One reading as (volts, amps), in a single round trip.

        In 4-wire mode the voltage comes from channel 2's sense input
        and the current from channel 1, which is what makes it the true
        voltage across the sample rather than across the leads as well.
        """
        volts, amps = self.client.measure_voltage_and_current(self.channel)
        return (float(volts), float(amps))

    # ---- sweeps ----
    def sweep_kind(self):
        """'hardware' or 'software', for the mode currently selected.

        An instance method, like the GSM's, but for a different reason:
        there the answer depended on what the instrument understood,
        here it depends on which quantity is being sourced. The onboard
        sweep does voltage only.
        """
        if not self._firmware_at_least(FIRMWARE_ONBOARD_SWEEP):
            return "software"
        return "hardware" if self._source_mode == "voltage" else "software"

    def sweep_note(self):
        """Connect-time console note. Reuses the hook the GSM uses."""
        # First, and always: the one thing about this instrument that
        # software cannot check and that quietly changes what a sweep
        # means if it is wrong.
        parts = [
            f"requires the 12 V DC adapter - on USB-C power alone the "
            f"MS01 is limited to "
            f"{self.BUS_POWERED_MAX_CURRENT * 1000:g} mA per channel "
            f"rather than 180 mA, and reports no way to tell which it "
            f"is on"
        ]
        version = self.firmware()
        parts.append(f"firmware {'.'.join(str(n) for n in version)}"
                     if version else "firmware version not recognised")

        if self._firmware_at_least(FIRMWARE_ONBOARD_SWEEP):
            parts.append("onboard voltage sweeps available (current sweeps "
                         "still step point by point from the PC)")
        else:
            parts.append(
                f"onboard sweeps need firmware "
                f"{'.'.join(str(n) for n in FIRMWARE_ONBOARD_SWEEP)}+; "
                f"using the software sweep")

        if not self._firmware_at_least(FIRMWARE_FOUR_WIRE):
            parts.append(
                f"4-wire sensing needs firmware "
                f"{'.'.join(str(n) for n in FIRMWARE_FOUR_WIRE)}+ and is "
                f"unavailable on this unit")

        # The integration-time caveats. Said at connect, because they
        # change how a dataset from this instrument compares with one
        # from a Keithley and nothing else in the UI can carry them.
        parts.append("integration is set by oversampling, which is not "
                     "synchronised to the mains - an equivalent NPLC here "
                     "rejects 50 Hz hum less well than a true NPLC")
        if self._osr is not None:
            # The OSR is the only part of this that is certain. The PLC
            # equivalent is derived from a scale the hardware has been
            # shown not to follow, so the raw setting is worth having on
            # the record alongside it.
            parts.append(
                f"oversampling ratio {self._osr} (the NPLC equivalent "
                f"shown elsewhere orders these settings correctly but its "
                f"absolute value is not a measured integration time - see "
                f"the driver docstring)")

        if getattr(self.transport, "is_network", False):
            parts.append(
                f"connected over WiFi: firmware 1.5.0 and earlier truncate "
                f"sweep data beyond about {TCP_CSV_POINT_WARNING} points, so "
                f"use USB for longer sweeps")

        return "; ".join(parts)

    def start_linear_sweep(self, mode, start, stop, points, delay_s):
        """Begin a sweep and return immediately.

        Voltage sweeps go to the instrument's own sweep engine; current
        sweeps, and any sweep on firmware too old for it, fall through
        to BaseSMU's software sweep. The caller never branches.
        """
        self._sweep_mode = mode
        self._source_mode = mode

        if self.sweep_kind() != "hardware":
            self._sweep_running = True
            return super().start_linear_sweep(mode, start, stop, points,
                                              delay_s)

        points = int(points)
        if points < 2:
            raise ValueError("A sweep needs at least 2 points.")
        if points > MAX_SWEEP_POINTS:
            raise ValueError(
                f"The onboard sweep takes at most {MAX_SWEEP_POINTS} points; "
                f"{points} were requested.")

        dwell_ms = int(round(max(float(delay_s), 0.0) * 1000))
        if dwell_ms > MAX_DWELL_MS:
            raise ValueError(
                f"The onboard sweep dwell time tops out at "
                f"{MAX_DWELL_MS / 1000:g} s per point; {delay_s:g} s was "
                f"requested. Use a shorter delay, or fewer points with a "
                f"software sweep.")

        # auto_enable is left OFF so the experiment keeps control of the
        # output. It matters for the periodic bias-hold path, where the
        # output must stay on across the standby-to-sweep boundary -
        # letting the instrument switch it per sweep would discharge
        # whatever the bias was holding.
        self.client.configure_iv_sweep(
            channel=self.channel,
            start_voltage=float(start),
            end_voltage=float(stop),
            points=points,
            dwell_ms=dwell_ms,
            auto_enable=False,
            output_format="CSV",
        )
        self._sweep_points = points
        self._sweep_running = True
        self.client.execute_sweep(self.channel)

    def sweep_points_ready(self):
        """How many points the instrument says it has taken."""
        if self.sweep_kind() != "hardware":
            return super().sweep_points_ready()
        try:
            status = self.client.get_sweep_status(self.channel)
        except Exception:
            return 0
        if str(status.status).upper() == "COMPLETED":
            # Some firmware reports the final point index rather than
            # the count. Completion is the authoritative signal, so trust
            # it over the counter and hand back the full total - without
            # this the experiment's poll loop would run to its timeout on
            # a sweep that had already finished.
            return max(int(status.current_point), int(status.total_points))
        return max(int(status.current_point), 0)

    def read_sweep(self, points):
        """Collect a finished sweep as (voltages, currents).

        CSV rather than JSON: both truncate over TCP on firmware 1.5.0
        and earlier, but CSV fits roughly 175 points where JSON manages
        about 95, and the library verifies CSV completeness against the
        instrument's own point count before returning.
        """
        if self.sweep_kind() != "hardware":
            self._sweep_running = False
            return super().read_sweep(points)

        try:
            data = self.client.get_sweep_data_csv(self.channel)
        finally:
            self._sweep_running = False

        volts = [float(point.voltage) for point in data]
        amps = [float(point.current) for point in data]
        if points and len(volts) > points:
            volts, amps = volts[:points], amps[:points]
        # Voltage sweep only, so the sourced quantity is always volts.
        return volts, amps

    def abort_sweep(self):
        """Stop a running sweep, whichever kind it is.

        Returns True once nothing can still source: for the software
        path that is the base class's answer, for the hardware path it
        is whether the abort reached the instrument.
        """
        if self.sweep_kind() != "hardware":
            self._sweep_running = False
            return super().abort_sweep()
        try:
            self.client.abort_sweep(self.channel)
        except Exception:
            self._sweep_running = False
            return False
        self._sweep_running = False
        return True

    # ---- extras ----
    def temperatures(self):
        """(ADC, channel 1, channel 2) in degrees C, or None.

        Not part of the contract. Worth having because this instrument
        is small, passively cooled and rated to 2.1 W per channel, so a
        long bias run is a plausible way to warm it up - and a drifting
        measurement with a hot channel behind it is otherwise a mystery.
        """
        try:
            return tuple(float(t) for t in self.client.get_temperatures())
        except Exception:
            return None
