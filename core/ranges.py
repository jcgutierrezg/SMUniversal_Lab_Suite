"""
Ranging intent, declared once and in full.

Two different things were both called "range", and one method name did
for both:

  * the **source range** is the size of the container being poured from.
    It caps the level that can be set - too small and the level clamps,
    which is fault 4: no error, a plausible number, wrong by the clamp
    ratio.

  * the **measure range** is the size of the measuring jug. Too small
    and the reading overranges into a sentinel; too large and
    resolution is thrown away.

Same units, same word, different jobs. `set_current_range()` meant the
first on the 2450 and U2722A, the second on the 2401, 2611A, 2635B,
GSM-20H10 and B2901A, and both on the miniSMU. Nothing produced a wrong
number only because every current-sourcing experiment poured and
measured the same litre - Van der Pauw sources 1 mA and measures that
same 1 mA, so both readings of the method gave the right answer by
coincidence.

That coincidence holds only while the sourced and measured quantities
are the same. An experiment letting the operator choose to source
voltage and measure voltage breaks it, and breaks it silently.

Why a plan rather than four setters
-----------------------------------
Four independent setters can be interleaved with an output-on, which
house rule 12 forbids. A plan is declared once, before energising, and
carries the whole intent - which also lets an instrument with one
range knob for both jobs *see* that it has been asked for two different
things, rather than silently keeping whichever arrived last.

Why every field is required
---------------------------
There is no "leave it as it is". A field nobody sets is a range
inherited from whatever the previous run left behind - which is fault 6,
and the reason `AUTO` exists as a spelling. Saying `AUTO` is a decision;
saying nothing is not.
"""
from dataclasses import dataclass


class _Auto:
    """Sentinel: let the instrument choose this range for itself.

    A class rather than `None` so that a plan cannot be built by
    accident out of missing values - `None` is what an unset variable
    looks like, and this has to be something someone typed.
    """

    __slots__ = ()

    def __repr__(self):
        return "AUTO"

    def __bool__(self):
        # Deliberately truthy. `if plan.source_current:` should not
        # quietly mean "not auto".
        return True


AUTO = _Auto()


class _NotSourced:
    """Sentinel: this quantity is not being sourced at all.

    Distinct from `AUTO`, and the distinction is the whole point.

    `AUTO` is a request: *choose a range for me*. This is a statement
    about the experiment: *nothing is coming out of this axis, so there
    is no range to choose*. They were spelled the same until 2026-08-20,
    and a driver receiving `AUTO` had no way to tell "please autorange"
    from "I am not sourcing this" - so it did whatever autoranging means
    on that instrument, to an axis that was never going to carry
    anything.

    The commissioning round across all seven instruments found that
    harmless on five and damaging on two, in opposite ways:

      * **GSM-20H10** - `AUTO` rendered as `SOUR:CURR:RANG:AUTO ON`
        while sourcing voltage, which silently resets the current
        compliance from 105 uA to 1 nA. See fault 23.
      * **U2722A** - has no autorange at all, so `AUTO` had to be
        substituted with something concrete and the driver chose the
        widest fixed range. The requested compliance was then too small
        a fraction of it to be settable, `-222 Data out of range`, and
        sweeps failed outright with nothing sourced.

    And on two it is genuinely load-bearing: the 2611A and 2635B put the
    compliance on the source side, so `source.autorangei` while sourcing
    volts is the *compliance's own range*, which must keep being sent.
    That is why this is a new value rather than a rule about `AUTO` -
    a blanket "do not send anything for AUTO on the unsourced axis"
    would have broken the TSP pair to fix the other two.

    Rendering is each driver's decision, recorded in the contract
    ledger. `BaseSMU` treats it as `AUTO`, so the five instruments that
    were never harmed keep the behaviour they were commissioned with.
    """

    __slots__ = ()

    def __repr__(self):
        return "NOT_SOURCED"

    def __bool__(self):
        # Truthy for the same reason AUTO is: `if plan.source_current:`
        # must not quietly mean "not auto" or "not sourced".
        return True


#: The source axis of the quantity a run is not sourcing.
NOT_SOURCED = _NotSourced()


class RangeError(ValueError):
    """A ranging plan this instrument cannot carry out.

    Distinct from LimitError, which means the requested *source point*
    is outside the hardware envelope. This means the requested
    *ranging* cannot be expressed - for example a fixed range on an
    instrument that only autoranges.
    """


@dataclass(frozen=True)
class RangePlan:
    """What ranges a run wants, on all four axes.

    Each field is `AUTO`, `NOT_SOURCED` or a number in amps or volts.
    `NOT_SOURCED` belongs only on a source axis, and only for the
    quantity the run is not sourcing. The number
    is the largest magnitude that axis has to accommodate, not a range
    name - drivers pick the smallest range that fits, so a plan does not
    need to know any instrument's range table.

    All four are required. There is no partial plan.
    """
    source_current: object
    source_voltage: object
    measure_current: object
    measure_voltage: object

    def __post_init__(self):
        for name in ("source_current", "source_voltage",
                     "measure_current", "measure_voltage"):
            value = getattr(self, name)
            if value is AUTO or value is NOT_SOURCED:
                continue
            # Numbers only, and not strings that happen to parse.
            # `float("1e-3")` succeeds, so a Tk StringVar would flow
            # straight in and be coerced - which is the fault class Wave
            # 2 existed to remove. Conversion belongs at the form
            # boundary where a bad value can be reported to the operator,
            # not here where it silently becomes a range.
            #
            # bool is excluded deliberately: it is a subclass of int, so
            # `source_current=True` would otherwise arrive as 1 amp.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RangeError(
                    f"{name} must be AUTO, NOT_SOURCED or a number, got "
                    f"{value!r} "
                    f"({type(value).__name__}). Convert at the form, not "
                    f"here. Every axis has to be stated - an unstated "
                    f"range is whatever the previous run left behind.")
            number = float(value)
            if number < 0:
                raise RangeError(
                    f"{name} is a magnitude, so it cannot be negative "
                    f"(got {number}). Pass abs() of the level.")
            object.__setattr__(self, name, number)

    @classmethod
    def for_sourcing(cls, mode, source_range, measure_range):
        """Build the only plan shape an SMU will actually accept.

        `mode` is the quantity being sourced, 'voltage' or 'current'.
        `source_range` is the largest magnitude that will be sourced;
        `measure_range` is the largest magnitude expected of the *other*
        quantity, which is the one actually being measured.

        The point of this constructor is the axis it does NOT let you
        set: **the measurement range of the quantity being sourced.**

        On the 2400 family the measured value of the sourced quantity is
        read back from the source, so it has no independent measurement
        range, and asking for one is rejected - error 823, "Invalid with
        source read-back on", seen on both the 2401 and the GSM-20H10
        (deviation 41). It is not a quirk to work around. Setting that
        range is meaningless on any SMU; those two models are simply the
        ones honest enough to say so.

        Building plans through here makes that mistake unrepresentable
        rather than merely detectable. Every experiment was written with
        it wrong on first attempt - including, in the same wave, the
        one whose whole purpose was to get ranging right.

        The source axis of the *other* quantity is `NOT_SOURCED`, not
        `AUTO`. Nothing is coming out of it, so there is no range to
        choose - and two instruments are damaged by being asked to
        choose one anyway. See `_NotSourced`.
        """
        if mode == "voltage":
            return cls(source_voltage=source_range,
                       source_current=NOT_SOURCED,
                       measure_current=measure_range,
                       # Read back from the source. Not ours to set.
                       measure_voltage=AUTO)
        if mode == "current":
            return cls(source_current=source_range,
                       source_voltage=NOT_SOURCED,
                       measure_voltage=measure_range,
                       measure_current=AUTO)
        raise RangeError(
            f"mode must be 'voltage' or 'current', got {mode!r}")

    def describe(self):
        """One line, for logs and run metadata."""
        def show(v):
            if v is AUTO:
                return "auto"
            if v is NOT_SOURCED:
                return "not sourced"
            return f"{v:.6g}"
        return (f"source I={show(self.source_current)} "
                f"V={show(self.source_voltage)}, "
                f"measure I={show(self.measure_current)} "
                f"V={show(self.measure_voltage)}")

    def widest(self, first, second):
        """The wider of two axes, for instruments with one knob.

        `NOT_SOURCED` loses to everything: an axis carrying nothing has
        no claim on a shared knob, and letting it win is what cost the
        U2722A its compliance. If both are `NOT_SOURCED` the knob is
        genuinely unconstrained and the answer is `AUTO`.

        `AUTO` then wins over any fixed value: autoranging covers
        everything a fixed range would, and then some.
        """
        a = getattr(self, first)
        b = getattr(self, second)
        if a is NOT_SOURCED and b is NOT_SOURCED:
            return AUTO
        if a is NOT_SOURCED:
            return b
        if b is NOT_SOURCED:
            return a
        if a is AUTO or b is AUTO:
            return AUTO
        return max(a, b)
