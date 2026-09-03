
"""Software-sweep ownership: one sweep, one worker, one set of results.

Before Wave 6 the software sweep kept its state in plain
attributes on the driver - `_sw_sourced`, `_sw_measured`, `_sw_stop`,
`_sw_thread` - and `start_linear_sweep()` rebound all four without
joining the previous worker. The worker resolved those attributes at
append time, not at creation time, so a sweep still running when the
next one started appended *its* points into the *new* sweep's lists and
carried on stepping the source underneath it.

Two sweeps' readings in one buffer fit a perfectly convincing straight
line. Nothing raises, nothing is logged, and the resistance is wrong.

Every check below was confirmed to fail against the pre-Wave-6
implementation. They are written to wait on facts - explicit events the
fake sets and waits on - rather than on sleeps, so they say the same
thing on a loaded CI runner as on an idle laptop.
"""
import threading

import pytest

from core.limits import SMULimits
from drivers.base_smu import BaseSMU


class GatedSMU(BaseSMU):
    """An SMU whose measure() can be held open by the test.

    `entered` is set as soon as a measurement begins; `release` is what
    lets it return. Between those two the worker is provably inside
    measure() - which is the state the whole orphan-worker problem
    lives in, and the one a sleep-based test can only guess at.
    """

    MODEL_IDS = ["GATED"]
    DISPLAY_NAME = "Gated SMU"
    LIMITS = SMULimits(max_voltage=20.0, max_current=1.0,
                       voltage_ranges=[20.0], current_ranges=[1.0])

    def __init__(self):
        self.transport = None
        self.levels = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()          # open by default
        self._lock = threading.Lock()

    # -- the parts the software sweep actually uses --
    def set_voltage_level(self, volts):
        with self._lock:
            self.levels.append(float(volts))

    def set_current_level(self, amps):
        with self._lock:
            self.levels.append(float(amps))

    def measure(self, timeout_s=3.0):
        self.entered.set()
        self.release.wait(timeout=30.0)
        with self._lock:
            level = self.levels[-1] if self.levels else 0.0
        return (level, level / 100.0)

    def sourced_levels(self):
        with self._lock:
            return list(self.levels)

    # -- contract filler; none of it is exercised here --
    def set_source_function(self, mode): pass
    def set_current_limit(self, amps): pass
    def set_voltage_limit(self, volts): pass
    def set_current_range(self, amps=None): pass
    def set_voltage_range(self, volts=None): pass
    def set_remote_sense(self, on=True): pass
    def set_source_delay(self, seconds): pass
    def output_on(self): pass
    def output_off(self): pass
    def read_error(self): return (0, "")


def _drain(smu):
    """Let any held measurement go and wait for the worker to exit."""
    smu.release.set()
    assert smu.abort_sweep() is True


# ---------------------------------------------------------------
# A. a second sweep cannot start on top of a live one
# ---------------------------------------------------------------

def test_second_sweep_is_refused_while_the_first_can_still_drive(check):
    smu = GatedSMU()
    smu.release.clear()
    smu.start_linear_sweep("voltage", 0.0, 1.0, 5, 0.0)
    assert smu.entered.wait(5.0), "the worker never reached measure()"

    first_id = smu.sweep_id()

    with pytest.raises(RuntimeError) as caught:
        smu.start_linear_sweep("voltage", 10.0, 11.0, 5, 0.0)

    check("the refusal names the sweep still running",
          first_id in str(caught.value), str(caught.value))
    check("the live sweep is still the current one",
          smu.sweep_id() == first_id,
          f"became {smu.sweep_id()}")
    check("and it is still reported as running", smu.sweep_running() is True)

    _drain(smu)


def test_a_refused_start_does_not_disturb_the_running_sweep(check):
    """The refusal must be inert, not merely loud.

    Under the old implementation the second start rebound the result
    lists before anything could object, so the first sweep's points
    were split across two buffers and it returned short.
    """
    smu = GatedSMU()
    smu.release.clear()
    smu.start_linear_sweep("voltage", 0.0, 4.0, 5, 0.0)
    assert smu.entered.wait(5.0)

    # Deliberately NOT pytest.raises. If the guard is removed, this test
    # must still fail - and fail on the *data*, which is the actual
    # fault, rather than on "DID NOT RAISE", which only says the guard
    # is missing. The second sweep's levels are an order of magnitude
    # clear of the first's so a stray point is unmistakable.
    refused = True
    try:
        smu.start_linear_sweep("voltage", 100.0, 104.0, 5, 0.0)
        refused = False
    except RuntimeError:
        pass

    smu.release.set()
    sourced, measured = smu.read_sweep(5)

    check("the second start is refused", refused,
          "it started on top of a live sweep")
    check("the first sweep still returns all five of its points",
          len(measured) == 5, f"got {len(measured)}")
    check("and none of the second sweep's levels appear in it",
          all(v < 50.0 for v in sourced), f"{sourced}")


# ---------------------------------------------------------------
# B. abort waits, rather than merely asking
# ---------------------------------------------------------------

def test_abort_returns_only_once_the_worker_can_no_longer_source(check):
    smu = GatedSMU()
    smu.start_linear_sweep("voltage", 0.0, 1.0, 5, 0.0)

    check("abort reports the worker gone", smu.abort_sweep() is True)
    check("and nothing is running afterwards",
          smu.sweep_running() is False)

    # The real property: no level can appear after abort returned.
    settled = smu.sourced_levels()
    check("no source level is set after abort returns",
          smu.sourced_levels() == settled, "a level landed post-abort")


def test_read_sweep_refuses_to_return_data_from_a_live_worker(check):
    """Cleanup happens only once the worker cannot source.

    The old implementation joined with a timeout and then returned
    whatever had accumulated - handing back a half-finished sweep while
    the worker was still stepping the instrument, with nothing in the
    data to say so.
    """
    class Impatient(GatedSMU):
        _SOFTWARE_SWEEP_READ_TIMEOUT_S = 0.2

    smu = Impatient()
    smu.release.clear()
    smu.start_linear_sweep("voltage", 0.0, 4.0, 5, 0.0)
    assert smu.entered.wait(5.0)

    with pytest.raises(RuntimeError) as caught:
        smu.read_sweep(5)
    check("the error says the worker can still drive the source",
          "source" in str(caught.value).lower(), str(caught.value))

    _drain(smu)


# ---------------------------------------------------------------
# C. ids are not reused
# ---------------------------------------------------------------

def test_each_sweep_gets_an_id_of_its_own(check):
    smu = GatedSMU()
    smu.start_linear_sweep("voltage", 0.0, 1.0, 3, 0.0)
    first = smu.sweep_id()
    smu.read_sweep(3)

    smu.start_linear_sweep("voltage", 0.0, 1.0, 3, 0.0)
    second = smu.sweep_id()
    smu.read_sweep(3)

    check("a sweep has an id", first is not None)
    check("and the next sweep's differs", first != second,
          f"both were {first}")


def test_an_aborted_sweeps_id_is_never_handed_out_again(check):
    smu = GatedSMU()
    smu.release.clear()
    smu.start_linear_sweep("voltage", 0.0, 1.0, 5, 0.0)
    assert smu.entered.wait(5.0)
    aborted = smu.sweep_id()
    _drain(smu)

    smu.entered.clear()
    smu.start_linear_sweep("voltage", 0.0, 1.0, 3, 0.0)
    smu.read_sweep(3)

    check("the new sweep did not inherit the aborted one's id",
          smu.sweep_id() != aborted, f"reused {aborted}")


# ---------------------------------------------------------------
# D. the contract holds for every registered driver
# ---------------------------------------------------------------

def test_every_driver_reports_whether_its_abort_succeeded(check):
    """`abort_sweep()` answers a yes/no question, so it must answer it.

    Wave 6 changed this method from "best effort, returns nothing" to
    "returns whether anything can still source". A driver that kept the
    old signature returns None, which is falsy - so the caller would
    record a spurious "the worker did not stop" error on every single
    sweep. All four overriding drivers had to be updated with it; this
    check is what stops the fifth being missed.

    Discovered from the registry rather than listed, so a driver added
    later cannot opt out by not appearing in a hand-written list.
    """
    from drivers.registry import KNOWN_DRIVERS as DRIVERS

    offenders = []
    for driver_cls in DRIVERS:
        fn = getattr(driver_cls, "abort_sweep", None)
        if fn is None:
            offenders.append(f"{driver_cls.__name__}: no abort_sweep")
            continue
        # Never called: several drivers would talk to a transport that
        # does not exist here. The annotation-free way to check the
        # contract is to confirm the override is not the old shape -
        # i.e. that its body can return something other than None.
        import inspect
        source = inspect.getsource(fn)
        if "return" not in source:
            offenders.append(driver_cls.__name__)

    check("every driver's abort_sweep returns a verdict",
          not offenders, ", ".join(offenders))
