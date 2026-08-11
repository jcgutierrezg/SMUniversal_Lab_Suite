"""
Keithley 2611A SourceMeter - TSP dialect.

Included now, before the IV experiments are ported, because it's the
proof that the driver seam actually holds. The 2611A doesn't speak SCPI
at all - it speaks TSP, a Lua-flavoured language where you assign to
attributes instead of sending colon-delimited commands:

    2450 (SCPI):  :SOUR:CURR:LEV 1e-4
    2611A (TSP):  smu.source.leveli = 1e-4

Same method call from the experiment's point of view. If the abstraction
survives a gap that wide, brand differences within SCPI are easy.

Commands here are taken from the existing IV_Meas_2611A scripts, so
porting those later is a matter of moving sequencing logic, not
rediscovering syntax.

Reset defaults this driver overrides
------------------------------------
Added after the 2635B was written from the 2600B manual and surfaced two
faults this driver had been carrying since it was ported. Both were
inherited-state problems that the original scripts also had, so neither
showed up as a departure from working code.

1. **Replies were truncated to six significant figures.**
   `format.asciiprecision` governs `print`, `printnumber` *and*
   `printbuffer`, and it resets to 6. Nothing in this codebase had ever
   set it, so every reading this driver has taken came back at six
   figures - through `measure()` and, because the hardware sweep reads
   back with `printbuffer`, through every sweep point as well.

   The Hall experiment pins `VOLTAGE_FIGURES = 9` precisely because V_H
   sits under a resistive offset 100-1000x larger and is recovered by
   subtracting nearly-equal numbers; six figures put a ~0.1% floor on
   V_H before any physics, arriving as slightly-wrong data rather than
   as an error. Now set to 16 on every reset.

   **Any Hall or high-resistance result taken with this driver before
   this change should be treated as carrying that floor.**

2. **"Output off" was a driven 0 V source, not a disconnection.**
   `offmode` resets to `OUTPUT_NORMAL`, which on a 2611A sources 0 V
   into the sample with `offlimiti` (1 mA) available. The suite's
   Stop-de-energises guarantee was true in letter and misleading in
   spirit. Both attributes are now stated on every reset.

   Note the family difference: the 2600B adds an `offfunc` attribute
   choosing between a 0 V and a 0 A off-state. **The 2600A has no
   `offfunc`** - normal-off is always a 0 V source - so this driver
   states two attributes where `keithley_2635b.py` states three. Same
   fault, different shape, which is why the two drivers are separate
   files.

Also added: `localnode.linefreq` is read before being written (writing
it disables automatic detection permanently), `compliance_tripped()` now
that the attribute page has been read, and the error queue is split on
tabs rather than whitespace.

Two faults checked and found absent
------------------------------------
- **Fault 11 does not apply to ranging.** The manual states that
  explicitly setting a source or measurement range disables autoranging
  for that function, so the fixed-range writes below need no
  `AUTORANGE_OFF` first.
- **Fault 16 does not apply.** Unlike the 2635B, this model's source and
  measure current ranges are the same set - the range table gives both
  columns for every range from 100 nA up. The 10 A range is pulse-mode
  only and is correctly absent from LIMITS.
"""
from core.limits import SMULimits
from .base_smu import BaseSMU


class Keithley2611A(BaseSMU):
    MODEL_IDS = ["MODEL 2611A", "2611A"]
    DISPLAY_NAME = "Keithley 2611A"

    # Runs the sweep itself, off its own timebase, into nvbuffer1 -
    # see start_linear_sweep() below. Overrides the software fallback
    # in BaseSMU.
    SWEEP_KIND = "hardware"

    LIMITS = SMULimits(
        max_voltage=200.0,
        max_current=1.5,
        voltage_ranges=[0.2, 2.0, 20.0, 200.0],
        current_ranges=[1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0, 1.5],
        # 200 V at 100 mA, or 20 V at 1.5 A - DC limits, not pulsed
        power_envelope=[(20.0, 1.5), (200.0, 0.1)],
    )

    def __init__(self, transport, channel="smua"):
        """`channel` selects which SMU channel on the mainframe. The
        2611A has one ('smua'); the dual-channel 2612A adds 'smub'."""
        super().__init__(transport)
        self.channel = channel
        self._line_freq_note = ""
        # the scripts all alias the channel to `smu` first, so every
        # later command can be written channel-agnostically
        self._alias_sent = False

    def _ensure_alias(self):
        """Send `smu = smua` once per connection, matching what the
        existing scripts do at the top of every routine."""
        if not self._alias_sent:
            self.transport.write(f"smu = {self.channel}")
            self._alias_sent = True

    #: Significant figures for every number the instrument prints.
    #: Resets to 6, which is below what the Hall experiment needs.
    ASCII_PRECISION = 16

    #: Compliance available while the output is "off" in normal mode.
    #: The instrument's own default, sent explicitly rather than
    #: inherited. Below 1 mA interferes with contact check, which this
    #: suite does not use.
    OFF_STATE_CURRENT_LIMIT_A = 1e-3

    #: Mains frequency this bench runs on. Read before it is written -
    #: see _sync_line_frequency().
    LINE_FREQUENCY_HZ = 50

    def reset(self):
        """TSP uses reset() rather than *RST for a full channel reset,
        then re-assert everything reset clobbers.

        Everything below this line was added in the 2635B follow-up
        wave. Each was inherited rather than set for the whole life of
        this driver, and the first one changed what the data meant.
        """
        self.transport.write("reset()")
        self._alias_sent = False
        self._ensure_alias()

        # 1. What "output off" physically means. Reset leaves offmode as
        #    OUTPUT_NORMAL, which on a 2611A sources 0 V into the sample
        #    with the offlimiti compliance available - a driven
        #    low-impedance path, not a disconnection. Unlike the 2600B
        #    family there is no `offfunc` here: normal-off is always a
        #    0 V source, so there are two attributes to state, not three.
        self.transport.write("smu.source.offmode = smu.OUTPUT_NORMAL")
        self.transport.write(
            f"smu.source.offlimiti = {self.OFF_STATE_CURRENT_LIMIT_A:.6e}")

        # 2. Reply precision, before anything is read back. See the
        #    class docstring - this is the correction that matters.
        self.transport.write("format.data = format.ASCII")
        self.transport.write(
            f"format.asciiprecision = {self.ASCII_PRECISION}")

        # 3. Autoranging. The manual says all four are enabled by
        #    default; sent anyway, because a default nobody sends is a
        #    default nobody chose and firmware revisions move them.
        self.transport.write("smu.source.autorangev = smu.AUTORANGE_ON")
        self.transport.write("smu.source.autorangei = smu.AUTORANGE_ON")
        self.transport.write("smu.measure.autorangev = smu.AUTORANGE_ON")
        self.transport.write("smu.measure.autorangei = smu.AUTORANGE_ON")

        self._sync_line_frequency()

    def _sync_line_frequency(self):
        """Read `localnode.linefreq`; write it only if it disagrees.

        Reading first matters more on this instrument than on the 2635B.
        The manual states that explicitly setting `linefreq` sets
        `autolinefreq` to false - permanently, in nonvolatile memory. So
        a driver that writes 50 Hz on every connect silently disables
        automatic detection on a box somebody may have deliberately left
        detecting, and nothing ever turns it back on.

        A failure to read is reported and does not fail the connection:
        being unable to ask is not evidence of a fault, and NPLC still
        works, it just rejects mains hum less well.
        """
        try:
            reply = self.transport.query("print(localnode.linefreq)",
                                         timeout_s=3.0)
            present = int(float(str(reply).strip().split()[0]))
        except Exception:
            self._line_freq_note = "could not read the line frequency setting"
            return
        if present == self.LINE_FREQUENCY_HZ:
            self._line_freq_note = f"line frequency already {present} Hz"
            return
        self.transport.write(f"localnode.linefreq = {self.LINE_FREQUENCY_HZ}")
        self._line_freq_note = (
            f"line frequency changed from {present} Hz to "
            f"{self.LINE_FREQUENCY_HZ} Hz (automatic detection is now off)")

    # ---- source configuration ----
    def set_source_function(self, mode):
        self._ensure_alias()
        if mode == "current":
            self.transport.write("smu.source.func = smu.OUTPUT_DCAMPS")
        elif mode == "voltage":
            self.transport.write("smu.source.func = smu.OUTPUT_DCVOLTS")
        else:
            raise ValueError(f"Unknown source mode: {mode!r}")

    def set_current_level(self, amps):
        self._ensure_alias()
        self.transport.write(f"smu.source.leveli = {amps:.6e}")

    def set_voltage_level(self, volts):
        self._ensure_alias()
        self.transport.write(f"smu.source.levelv = {volts:.6e}")

    def set_current_limit(self, amps):
        self._ensure_alias()
        self.transport.write(f"smu.source.limiti = {amps:.6e}")

    def set_voltage_limit(self, volts):
        self._ensure_alias()
        self.transport.write(f"smu.source.limitv = {volts:.6e}")

    # ---- ranging ----
    def set_current_range(self, amps=None):
        self._ensure_alias()
        if amps is None:
            self.transport.write("smu.measure.autorangei = smu.AUTORANGE_ON")
        else:
            self.transport.write(f"smu.measure.rangei = {amps:.6e}")

    def set_voltage_range(self, volts=None):
        self._ensure_alias()
        if volts is None:
            self.transport.write("smu.measure.autorangev = smu.AUTORANGE_ON")
        else:
            self.transport.write(f"smu.measure.rangev = {volts:.6e}")

    # ---- sensing ----
    def set_remote_sense(self, on=True):
        self._ensure_alias()
        mode = "smu.SENSE_REMOTE" if on else "smu.SENSE_LOCAL"
        self.transport.write(f"smu.sense = {mode}")

    # ---- timing ----
    def set_source_delay(self, seconds):
        """TSP's measure.delay is in seconds, same as the base contract."""
        self._ensure_alias()
        self.transport.write(f"smu.measure.delay = {seconds:.6f}")

    # TSP goes finer and coarser than the SCPI instruments here: the
    # 2611A accepts 0.001 to 25 NPLC where the 2400-series stop at
    # 0.01 and 10. Declared per model rather than assumed common,
    # which is the whole reason NPLC_RANGE is a driver attribute.
    HIGH_Z_OFF = True

    def set_output_off_mode(self, high_z=False):
        """TSP spells this as an attribute rather than a command."""
        self._ensure_alias()
        mode = ("smu.OUTPUT_HIGH_Z" if high_z else "smu.OUTPUT_NORMAL")
        self.transport.write(f"smu.source.offmode = {mode}")

    NPLC_RANGE = (0.001, 25.0)

    def set_nplc(self, nplc):
        """One attribute covers both measure functions on TSP, so
        unlike the SCPI drivers this needs a single write."""
        self._ensure_alias()
        value = self.clamp_nplc(nplc)
        self.transport.write(f"smu.measure.nplc = {value:.4f}")

    # ---- output ----
    def output_on(self):
        self._ensure_alias()
        self.transport.write("smu.source.output = smu.OUTPUT_ON")

    def output_off(self):
        self._ensure_alias()
        self.transport.write("smu.source.output = smu.OUTPUT_OFF")

    # ---- hardware sweeps ----
    def start_linear_sweep(self, mode, start, stop, points, delay_s):
        """Arm nvbuffer1 and fire one of TSP's built-in sweep factories.

        SweepVLinMeasureI / SweepILinMeasureV are library functions the
        2611A ships with; they run the whole sweep on the instrument and
        drop the readings into the buffer. This is exactly what the
        original scripts did.

        Two additions to what the scripts sent:

        `collectsourcevalues = 1` makes the instrument record the level
        it actually sourced at each step. The originals never asked for
        it and rebuilt the x-axis with np.arange() instead, which assumes
        the SMU hit every requested level exactly. Reading them back
        costs one extra query and removes the assumption.

        The buffer is cleared *before* collectsourcevalues is set,
        because TSP refuses to change the collect flags on a buffer that
        still holds readings.
        """
        self._ensure_alias()
        if mode == "voltage":
            self.transport.write("smu.source.func = smu.OUTPUT_DCVOLTS")
            self.transport.write("smu.source.autorangev = smu.AUTORANGE_ON")
            sweep = "SweepVLinMeasureI"
        elif mode == "current":
            self.transport.write("smu.source.func = smu.OUTPUT_DCAMPS")
            self.transport.write("smu.source.autorangei = smu.AUTORANGE_ON")
            sweep = "SweepILinMeasureV"
        else:
            raise ValueError(f"Unknown sweep mode: {mode!r}")

        self.transport.write("format.data = format.ASCII")
        self.transport.write("smu.nvbuffer1.clear()")
        self.transport.write("smu.nvbuffer1.appendmode = 1")
        self.transport.write("smu.nvbuffer1.collectsourcevalues = 1")

        self._sweep_points = int(points)
        self.transport.write(
            f"{sweep}(smu, {start:.6e}, {stop:.6e}, {delay_s:.6f}, {int(points)})")

    def sweep_points_ready(self):
        """Readings currently in nvbuffer1.

        `smu.nvbuffer1.n` is the instrument's own count, so this asks the
        SMU how far it has got rather than inferring it from elapsed
        time.
        """
        self._ensure_alias()
        reply = self.transport.query("print(smu.nvbuffer1.n)", timeout_s=5.0)
        try:
            return int(float(reply.strip().split()[0]))
        except (ValueError, IndexError):
            return 0

    def read_sweep(self, points):
        """Pull the readings and the matching source values out of
        nvbuffer1."""
        self._ensure_alias()
        n = int(points)
        measured = self._read_buffer(f"printbuffer(1, {n}, smu.nvbuffer1.readings)")
        sourced = self._read_buffer(
            f"printbuffer(1, {n}, smu.nvbuffer1.sourcevalues)")

        # If the instrument didn't record source values for any reason,
        # fall back to an empty list and let the caller reconstruct - a
        # sweep with data and an assumed x-axis beats losing the run.
        if len(sourced) != len(measured):
            sourced = []
        return sourced, measured

    def _read_buffer(self, command):
        """Query one printbuffer command and parse its comma-separated
        ASCII reply into floats."""
        reply = self.transport.query(command, timeout_s=20.0)
        values = []
        for chunk in reply.replace("\n", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                values.append(float(chunk))
            except ValueError:
                pass
        return values

    def abort_sweep(self):
        """Stop a running sweep and drop the output."""
        try:
            self._ensure_alias()
            self.transport.write("smu.abort()")
            self.transport.write("smu.source.output = smu.OUTPUT_OFF")
        except Exception:
            pass

    # ---- measurement ----
    def read_error(self):
        """Pop one entry off the error queue.

        TSP, not SCPI: `errorqueue.next()` returns a tuple, and print()
        renders it tab-separated as code, message, severity, node. The
        SCPI `:SYST:ERR?` spelling next door would be swallowed by the
        TSP parser as an unknown identifier, which is exactly the kind
        of mistake this method exists to catch elsewhere.
        """
        try:
            reply = self.transport.query(
                "print(errorqueue.next())", timeout_s=3.0)
        except Exception:
            return (0, "")
        text = str(reply or "").strip()
        if not text:
            return (0, "")

        # Split on TABS, not whitespace. print() separates multiple
        # arguments with a tab character, and errorqueue.next() returns
        # four of them - code, message, severity, node. Splitting on
        # whitespace put the severity and node on the end of the message
        # and broke multi-word messages across fields. Falls back to
        # whitespace only when there is no tab at all, so an instrument
        # answering unexpectedly is still shown to a human.
        fields = [f.strip() for f in text.split("\t")] if "\t" in text \
            else text.split(None, 1)
        try:
            code = int(float(fields[0]))
        except (ValueError, IndexError):
            return (0, text)
        message = fields[1].strip().strip('"') if len(fields) > 1 else ""
        return (code, message)

    def compliance_tripped(self):
        """Whether a configured limit is currently in control of the
        source.

        `true` means the limit function is driving the output rather
        than the source function - the instrument is clamping. On this
        family the manual describes it in terms of the two source
        functions: the voltage limit reached when sourcing current, or
        the current limit when sourcing voltage. (The 2600B wording adds
        the power limit; the 2600A page does not mention it, so nothing
        is claimed about `limitp` here.)

        Worth having because a sweep in compliance still produces a neat
        straight line and a convincing R-squared - the fit describes the
        limit rather than the sample.

        **An unparseable or missing reply returns None, not False.** The
        base contract draws that distinction deliberately: None is "this
        instrument cannot say", False is "everything was fine", and
        collapsing them turns a silence into a reassurance.

        Read-only - writing to it generates an error - and reading it
        updates the status model and the front-panel indicator as a
        documented side effect. Benign, but not something to poll in a
        tight loop.
        """
        try:
            reply = self.transport.query("print(smu.source.compliance)",
                                         timeout_s=3.0)
        except Exception:
            return None
        text = str(reply or "").strip().lower()
        if text.startswith("true"):
            return True
        if text.startswith("false"):
            return False
        return None

    def sweep_note(self):
        """What the console says about this instrument at connect."""
        parts = [
            "2611A: 200 V / 1.5 A DC, hardware sweep on the "
            "instrument's own timebase.",
            "The 200 V source range needs the interlock enabled.",
            'Output "off" sources 0 V with a '
            f"{self.OFF_STATE_CURRENT_LIMIT_A * 1e3:g} mA limit - tick "
            "high-Z to disconnect the sample instead.",
        ]
        if self._line_freq_note:
            parts.append(self._line_freq_note.capitalize() + ".")
        return " ".join(parts)

    def measure(self, timeout_s=3.0):
        """One reading as (volts, amps), via TSP's matched-pair call.

        `smu.measure.iv()` is TSP's equivalent of `:READ?` - an earlier
        version of this driver said there wasn't one and sent
        `print(smu.measure.v(), smu.measure.i())` instead. That works,
        but it is two separate measurements: the bench checkup timed a
        reading at 1034 ms with NPLC 25, which is exactly two 0.5 s
        apertures, so the voltage was integrated over the first half
        second and the current over the *next* one.

        Two consequences of that, and the second is the one that
        matters. It is twice as slow as it needs to be; and the pair is
        not simultaneous, so on a sample that drifts or self-heats the
        V and I of a single "point" describe two different moments. The
        Hall measurement cares about that more than the IV sweep does.

        **The first reading after a configuration change costs three
        apertures, not one.** Measured twice, a day apart, both times
        exactly 1.000 s longer at NPLC 25 than the readings that
        followed - two extra integrations. That is autozero: it measures
        an internal reference and zero alongside the signal whenever the
        configuration has moved.

        It shows up as a slow first point on a software sweep or a
        bias-hold reading (1.5 s rather than 0.5 s at NPLC 25), and it
        is not an error - the reading is if anything the better one. The
        hardware sweep absorbs it internally. Worth knowing before
        someone times a sweep, sees the first point take three times as
        long, and goes looking for a fault.

        Confirmed on the bench 2026-08-05: **one aperture per reading,**
        15.6 ms of GPIB overhead. 15.6 ms at NPLC 0.001 and 515.6 ms at
        NPLC 25 is a slope of exactly 1.00. So the change halved the
        cost as well as fixing the matched pair - 1034 ms down to
        516 ms at NPLC 25, a 200-point sweep from 3.4 minutes to 1.7.

        (For contrast, the U2722A measures 2.04 apertures per reading,
        because it genuinely has no combined read and pays for both.)

        **The return order is reversed from the old call.**
        `measure.iv()` gives **current first, then voltage** - the
        opposite of the `v(), i()` it replaces. Getting that wrong
        transposes every reading in every experiment while still
        producing plausible-looking numbers, so the order is pinned by
        test and, on the bench, by the checkup's open-circuit check:
        transposed, 0.1 V at ~0 A reads as 0 V at 0.1 A, which fails
        loudly rather than quietly.
        """
        self._ensure_alias()
        reply = self.transport.query("print(smu.measure.iv())",
                                     timeout_s=timeout_s)
        parts = reply.replace(",", " ").split()
        nums = []
        for p in parts:
            try:
                nums.append(float(p))
            except ValueError:
                pass
        # TSP reports no-reading with the same values SCPI does. See
        # BaseSMU.drop_sentinel.
        nums = [self.drop_sentinel(n) for n in nums]
        if len(nums) >= 2:
            # iv() returns (current, voltage); this contract is
            # (voltage, current).
            return (nums[1], nums[0])
        if len(nums) == 1:
            # A lone number cannot be assigned to a quantity with any
            # confidence, so neither is claimed.
            return (None, None)
        return (None, None)
