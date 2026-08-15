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

    Each field is either `AUTO` or a number in amps or volts. The number
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
            if value is AUTO:
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
                    f"{name} must be AUTO or a number, got {value!r} "
                    f"({type(value).__name__}). Convert at the form, not "
                    f"here. Every axis has to be stated - an unstated "
                    f"range is whatever the previous run left behind.")
            number = float(value)
            if number < 0:
                raise RangeError(
                    f"{name} is a magnitude, so it cannot be negative "
                    f"(got {number}). Pass abs() of the level.")
            object.__setattr__(self, name, number)

    def describe(self):
        """One line, for logs and run metadata."""
        def show(v):
            return "auto" if v is AUTO else f"{v:.6g}"
        return (f"source I={show(self.source_current)} "
                f"V={show(self.source_voltage)}, "
                f"measure I={show(self.measure_current)} "
                f"V={show(self.measure_voltage)}")

    def widest(self, first, second):
        """The wider of two axes, for instruments with one knob.

        `AUTO` wins over any fixed value: autoranging covers everything
        a fixed range would, and then some.
        """
        a = getattr(self, first)
        b = getattr(self, second)
        if a is AUTO or b is AUTO:
            return AUTO
        return max(a, b)
