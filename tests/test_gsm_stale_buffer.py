"""The GSM-20H10's buffer: old readings, a high-water count, a waiting query.

Measured 2026-09-16 with `tools/probes/20h10_stale_buffer.txt`:

- `TRAC:CLE`, `TRAC:POIN <n>` and *RST leave an earlier, longer sweep's
  readings in the buffer, and `TRAC:DATA?` returns them after the new
  ones. A 3-point sweep after a 10-point one returned 3 fresh readings
  and then readings 4-10 of the old sweep.
- `TRAC:POIN:ACT?` reports the buffer's high-water mark: 10 after that
  3-point sweep. `TRAC:CLE` zeroes it only until a reading lands.
- `TRAC:POIN:ACT?` sent during a staircase is not answered until the
  staircase finishes - 1034 ms for ten points at 100 ms.

The fake below keeps a buffer that behaves that way. The shared
GSMTransport answers from the last sweep alone, which is why nothing
failed with the bug in place.
"""
import pytest

from test_gsm20h10 import GSMTransport

from smuniversal_lab_suite.drivers.gwinstek_gsm20h10 import GWInstekGSM20H10


class KeepsOldReadings(GSMTransport):
    """A buffer that survives TRAC:CLE and *RST, three numbers a reading."""

    def __init__(self):
        super().__init__()
        self.buffer = []            # [(volts, amps)], persists
        self.count = 0              # what TRAC:POIN:ACT? reports
        self.act_budgets = []       # timeout_s each ACT? was given

    def _write(self, text):
        super()._write(text)
        upper = text.strip().upper()
        if upper == "TRAC:CLE":
            self.count = 0          # the count resets; the data does not
        if upper == "INIT" and self.sweep:
            start, stop, points = self.sweep
            step = (stop - start) / (points - 1) if points > 1 else 0.0
            for i in range(points):
                level = start + step * i
                reading = (level, level / 10000.0)
                if i < len(self.buffer):
                    self.buffer[i] = reading
                else:
                    self.buffer.append(reading)
            self.count = len(self.buffer)   # high-water mark

    def _read(self, timeout_s):
        upper = (self.sent[-1] if self.sent else "").upper()
        if upper.startswith("TRAC:POIN:ACT"):
            self.act_budgets.append(timeout_s)
            return str(self.count)
        if upper.startswith("TRAC:DATA"):
            return ",".join(f"{v:.6E},{i:.6E},+9.910000E+37"
                            for v, i in self.buffer)
        return super()._read(timeout_s)


@pytest.fixture
def gsm():
    transport = KeepsOldReadings()
    transport.connect("fake")
    smu = GWInstekGSM20H10(transport)
    smu.reset()
    smu.set_source_function("voltage")
    smu.output_on()
    return smu, transport


def sweep(smu, start, stop, points, delay=0.0):
    smu.start_linear_sweep("voltage", start, stop, points, delay)
    ready = smu.sweep_points_ready()
    return ready, smu.read_sweep(ready)


def test_a_shorter_sweep_does_not_return_the_longer_ones_tail(check, gsm):
    smu, t = gsm
    sweep(smu, 0.1, 1.0, 10)
    ready, (sourced, measured) = sweep(smu, 0.01, 0.05, 5)

    # The control: the fake really did hand back the old tail.
    check("the buffer held ten readings for the five-point sweep",
          len(t.buffer) == 10 and t.count == 10, (len(t.buffer), t.count))

    check("five points came back, not ten", len(sourced) == 5,
          len(sourced))
    check("all of them are this sweep's levels",
          all(0.009 <= v <= 0.051 for v in sourced), sourced)
    check("and the discard is said, not silent",
          "left over" in smu.sweep_note(), smu.sweep_note())


def test_the_poll_counts_this_sweeps_points(check, gsm):
    """The IV sweep passes the poll's count straight to read_sweep()."""
    smu, t = gsm
    sweep(smu, 0.1, 1.0, 10)
    smu.start_linear_sweep("voltage", 0.01, 0.03, 3, 0.0)

    ready = smu.sweep_points_ready()

    check("the instrument's own count was the high-water mark",
          t.count == 10, t.count)
    check("the poll reports the three points armed", ready == 3, ready)


def test_read_sweep_trusts_what_was_armed_over_what_it_was_told(check, gsm):
    """A caller passing the high-water count must still get this sweep."""
    smu, _ = gsm
    sweep(smu, 0.1, 1.0, 10)
    smu.start_linear_sweep("voltage", 0.01, 0.05, 5, 0.0)

    sourced, _ = smu.read_sweep(10)

    check("five points, from the sweep that was armed", len(sourced) == 5,
          len(sourced))


def test_a_same_length_sweep_is_untouched(check, gsm):
    smu, _ = gsm
    sweep(smu, 0.1, 1.0, 10)
    _, (sourced, _) = sweep(smu, 0.2, 2.0, 10)

    check("ten points", len(sourced) == 10, len(sourced))
    check("all from the second sweep", min(sourced) >= 0.199, sourced)
    check("and nothing was reported discarded",
          "left over" not in smu.sweep_note(), smu.sweep_note())


# ---------------------------------------------------------------------
# The query that waits for the sweep
# ---------------------------------------------------------------------

#: Seconds per reading at an NPLC, from the bench table of 2026-09-01.
MEASURED_READING_S = {0.01: 0.0103, 2.5: 0.269, 10.0: 1.06}


@pytest.mark.parametrize("points, delay, nplc", [
    (60, 0.1, 0.01),     # the 6 s IV sweep that would have latched
    (10, 0.0, 10.0),     # slow integration, no delay
    (200, 0.05, 2.5),
    (2, 0.0, 0.01),      # short sweeps keep the old floor
])
def test_the_poll_is_given_longer_than_the_sweep_takes(check, gsm, points,
                                                        delay, nplc):
    """Every ACT? budget must outlast the sweep it waits for.

    The first row is the discriminating one: with the fixed 5 s budget
    this driver used before, a 60-point sweep at 100 ms per point is
    still running when the read gives up.
    """
    smu, t = gsm
    smu.set_nplc(nplc)
    sweep(smu, 0.0, 0.1, points, delay)

    takes = points * (delay + MEASURED_READING_S[nplc])
    check("a budget was given to every count query", t.act_budgets,
          t.act_budgets)
    check(f"each outlasts the {takes:.2f} s sweep",
          all(b > takes for b in t.act_budgets),
          f"budgets {t.act_budgets}")
    check("and none is below the old 5 s floor",
          all(b >= 5.0 for b in t.act_budgets), t.act_budgets)


def test_a_reset_puts_the_nplc_estimate_back(check, gsm):
    """*RST returns NPLC to 1; a budget sized for NPLC 10 would linger."""
    smu, t = gsm
    smu.set_nplc(10.0)
    smu.reset()
    smu.set_source_function("voltage")
    smu.output_on()
    sweep(smu, 0.0, 0.1, 100, 0.0)
    slow = 100 * MEASURED_READING_S[10.0]
    check("the budget no longer assumes NPLC 10",
          max(t.act_budgets) < 2 * slow, t.act_budgets)
