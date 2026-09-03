"""
Dummy SMU - a simulated instrument for development without hardware.

Behaves like a real SMU driving a resistive sample: sourcing current
produces a proportional voltage, compliance clamps that voltage, and
readings carry a little noise. That's enough to exercise every layer
above it - sequencing, averaging, file writing, the VdP solver, the
plots - with nothing plugged in.

The default sample is deliberately symmetric, which makes it a
self-check as well as a stand-in. For a Van der Pauw run where all four
positions read the same R, the sheet resistance has a closed-form
answer:

    Rh = Rv = R   =>   Rs = pi * R / ln(2)  ~=  4.5324 * R

So the default 1000 ohm sample must solve to 4532.36 ohm/square. If it
doesn't, something in the chain is wrong, and you'll know before you get
near a real sample. Set ANISOTROPY away from 1.0 when you want an
asymmetric case instead.

Not auto-detected on real hardware: MODEL_IDS matches only the ID string
that NullTransport returns, so plugging in a genuine instrument can never
land you in simulation by accident.
"""
import random

from core.limits import SMULimits

from .base_smu import BaseSMU

# --- simulated sample, tweak freely while developing ---
SAMPLE_RESISTANCE = 1000.0   # ohm, per contact pair
NOISE_FRACTION = 0.001       # 0.1% gaussian noise on each reading
ANISOTROPY = 1.0             # 1.0 = symmetric sample (analytic Rs applies)


class DummySMU(BaseSMU):
    MODEL_IDS = ["DUMMY SMU"]
    DISPLAY_NAME = "Dummy SMU (simulated)"

    # Simulates an instrument-side sweep, so demo mode exercises the
    # hardware path. The software fallback in BaseSMU is covered
    # separately by test_sweep_fallback.py.
    SWEEP_KIND = "hardware"

    # generous envelope - the point is not to get in your way while
    # developing, though the limit gate still functions against it
    LIMITS = SMULimits(
        max_voltage=200.0,
        max_current=1.0,
        voltage_ranges=[0.02, 0.2, 2.0, 20.0, 200.0],
        current_ranges=[1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0],
        power_envelope=[(20.0, 1.0), (200.0, 0.1)],
    )

    def __init__(self, transport, resistance=SAMPLE_RESISTANCE,
                 noise_fraction=NOISE_FRACTION, anisotropy=ANISOTROPY):
        super().__init__(transport)
        self.resistance = resistance
        self.noise_fraction = noise_fraction
        self.anisotropy = anisotropy

        # simulated instrument state
        self._source_mode = "current"
        self._current_level = 0.0
        self._voltage_level = 0.0
        self._voltage_limit = 20.0
        self._current_limit = 0.1
        self._output_on = False
        self._reading_count = 0
        self._nplc = 1.0
        self._ovp = "20"
        self._high_z_off = False

    # ---- identity ----
    def reset(self):
        """Return the simulated instrument to defaults."""
        self._output_on = False
        self._current_level = 0.0
        self._voltage_level = 0.0
        self._reading_count = 0

    # ---- source configuration ----
    def set_source_function(self, mode):
        if mode not in ("current", "voltage"):
            raise ValueError(f"Unknown source mode: {mode!r}")
        self._source_mode = mode

    def set_current_level(self, amps):
        self._current_level = amps

    def set_voltage_level(self, volts):
        self._voltage_level = volts

    def set_current_limit(self, amps):
        self._current_limit = abs(amps)

    def set_voltage_limit(self, volts):
        self._voltage_limit = abs(volts)

    # ---- ranging and sensing: accepted and ignored ----
    # ---- ranging: per-axis (wave 6d) ----
    def _apply_source_current_range(self, amps):
        """No-op: a simulated sample has no ranging hardware."""

    def _apply_source_voltage_range(self, volts):
        """No-op, as above."""

    def _apply_measure_current_range(self, amps):
        """No-op, as above."""

    def _apply_measure_voltage_range(self, volts):
        """No-op, as above."""


    #: There is no converter, so there is no bottom count to fall below.
    #: Declared rather than inherited: the BaseSMU default is
    #: `unmeasured`, which is the honest answer for a real instrument
    #: nobody has probed and a false one here - "nobody has measured the
    #: simulated instrument's counts" would be a warning with no
    #: hardware behind it, and a warning that can never be resolved is a
    #: warning people learn to ignore.
    SUB_COUNT_LEVELS = {"current": BaseSMU.SUB_COUNT_NOT_APPLICABLE,
                        "voltage": BaseSMU.SUB_COUNT_NOT_APPLICABLE}

    def set_remote_sense(self, on=True):
        """No-op - the simulated sample has no lead resistance to
        exclude, so 2-wire and 4-wire read the same."""

    def set_source_delay(self, seconds):
        """Recorded but not slept on. The experiment already does its
        own host-side settle, and doubling it would make demo runs
        needlessly slow."""
        self._source_delay = seconds

    # Declared so demo mode exercises the NPLC and OVP controls rather
    # than showing them greyed out - a control that only ever appears
    # on the bench is a control nobody tests at the desk.
    HIGH_Z_OFF = True

    def set_output_off_mode(self, high_z=False):
        """Recorded, so demo mode exercises the control."""
        self._high_z_off = bool(high_z)

    NPLC_RANGE = (0.01, 10.0)
    # Mirrors the shape of a real instrument's list. MIN/MAX were
    # removed when the GSM's were corrected against its manual; this
    # copy kept them until the contract test caught the drift.
    OVP_CHOICES = ["20", "40", "100", "200", "210", "OFF"]

    def set_nplc(self, nplc):
        """Recorded, and used to scale the simulated noise so the
        speed/noise tradeoff is visible in demo: more integration
        cycles, quieter readings, exactly as on real hardware."""
        self._nplc = self.clamp_nplc(nplc)

    def set_voltage_protection(self, choice):
        """Recorded. The simulated sample never runs away, so there is
        nothing to clamp - but the setting still lands in the CSV,
        which is what a demo run is for."""
        self._ovp = choice

    # ---- output ----
    def output_on(self):
        self._output_on = True

    def output_off(self):
        self._output_on = False

    # ---- measurement ----
    def read_error(self):
        """Always empty. There is no instrument to have complained.

        Deliberately not made settable from outside: a demo-mode error
        queue would be a fiction with no failure behind it, and the
        checkup's job is to report what real hardware says.
        """
        return (0, "")

    def measure(self, timeout_s=3.0):
        """Return a simulated (volts, amps) pair.

        Sourcing current: V = I * R, clamped at the voltage compliance
        limit. Clamping is modelled because hitting compliance is a real
        and easy-to-hit condition - a demo that silently ignored it would
        hide a class of bug you actually want to catch.
        """
        if not self._output_on:
            return (0.0, 0.0)

        r = self.resistance * self.anisotropy
        self._reading_count += 1

        if self._source_mode == "current":
            current = self._current_level
            voltage = current * r
            if abs(voltage) > self._voltage_limit:
                # in compliance: voltage pins, current falls back
                voltage = self._voltage_limit * (1 if voltage >= 0 else -1)
                current = voltage / r if r else 0.0
        else:
            voltage = self._voltage_level
            current = voltage / r if r else 0.0
            if abs(current) > self._current_limit:
                current = self._current_limit * (1 if current >= 0 else -1)
                voltage = current * r

        return (self._noisy(voltage), self._noisy(current))

    # ---- hardware sweeps ----
    def start_linear_sweep(self, mode, start, stop, points, delay_s):
        """Simulate an instrument-side sweep.

        The whole sweep is computed up front, but sweep_points_ready()
        releases it gradually against the wall clock, at the same
        per-point rate a real instrument would manage. That matters:
        it means demo mode genuinely exercises the polling loop rather
        than handing back a finished sweep on the first call, so a bug
        in the wait logic shows up at the desk instead of on the bench.
        """
        import time as _time

        if mode not in ("voltage", "current"):
            raise ValueError(f"Unknown sweep mode: {mode!r}")

        points = int(points)
        if points < 2:
            raise ValueError("A sweep needs at least 2 points.")

        step = (stop - start) / (points - 1)
        levels = [start + step * i for i in range(points)]

        r = self.resistance * self.anisotropy
        sourced, measured = [], []
        for level in levels:
            if mode == "voltage":
                voltage = level
                current = voltage / r if r else 0.0
                if abs(current) > self._current_limit:
                    current = self._current_limit * (1 if current >= 0 else -1)
                measured.append(self._noisy(current))
            else:
                current = level
                voltage = current * r
                if abs(voltage) > self._voltage_limit:
                    voltage = self._voltage_limit * (1 if voltage >= 0 else -1)
                measured.append(self._noisy(voltage))
            # a real SMU lands very close to, but not exactly on, the
            # requested level - which is the reason source values get
            # read back rather than assumed
            sourced.append(level + (step * 1e-6 if step else 0.0))

        self._sweep_sourced = sourced
        self._sweep_measured = measured
        self._sweep_points = points
        self._sweep_delay = max(float(delay_s), 0.0)
        self._sweep_started = _time.monotonic()
        self._output_on = True

    def sweep_points_ready(self):
        """How many simulated points have 'completed' so far."""
        import time as _time

        if not getattr(self, "_sweep_points", 0):
            return 0
        if self._sweep_delay <= 0:
            return self._sweep_points
        elapsed = _time.monotonic() - self._sweep_started
        return min(self._sweep_points, int(elapsed / self._sweep_delay))

    def read_sweep(self, points):
        """Hand back the simulated sweep."""
        n = min(int(points), getattr(self, "_sweep_points", 0))
        return (list(self._sweep_sourced[:n]), list(self._sweep_measured[:n]))

    def abort_sweep(self):
        """Forget the in-flight sweep and drop the output.

        Returns True: this model has no worker thread, so once the
        in-flight sweep is forgotten nothing can source.
        """
        self._sweep_points = 0
        self._output_on = False
        return True

    def _noisy(self, value):
        """Add proportional gaussian noise, so averaging over points
        does something visible instead of returning the same number N
        times."""
        if not self.noise_fraction or value == 0:
            return value
        # Longer integration averages more mains cycles, so noise falls
        # as 1/sqrt(NPLC) - the same square-root-of-samples law that
        # governs any averaging. Modelled so a demo run at 10 NPLC
        # visibly beats one at 0.01, as it would on the bench.
        nplc = getattr(self, "_nplc", 1.0) or 1.0
        spread = abs(value) * self.noise_fraction / (nplc ** 0.5)
        return value + random.gauss(0.0, spread)

    # ---- helper for verifying a demo run ----
    @property
    def expected_sheet_resistance(self):
        """The Rs a symmetric Van der Pauw run on this sample should
        produce: pi * R / ln(2). Returns None when anisotropy is set,
        since the closed form no longer applies."""
        import math
        if self.anisotropy != 1.0:
            return None
        return math.pi * self.resistance / math.log(2)
