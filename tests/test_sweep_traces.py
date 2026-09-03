
"""Sweep and recovery traces. Wave 6c.

Three transitions that 6b left alone, and one it could not reach:

  * **hardware sweep setup and completion** - a sweep is configured,
    armed, run and read, and the order matters in a way no single
    command reveals.
  * **no reconfiguration mid-sweep** - house rule 12 applied to the
    sweep itself. A range change part way through leaves a step in the
    data where the two segments were sourced with different gain and
    offset errors, and a straight line fitted across that step absorbs
    it as slope. Slope is resistance.
  * **error-queue hygiene** - `read_error()` is the only way anything
    above the driver can ask "did you understand that?". A driver that
    reports a code once and then keeps reporting it, or one that
    reports nothing because it never drains, makes every downstream
    check meaningless.
  * **abort uses the command that model accepts** - settled on the
    bench for the GSM-20H10, where `:ABOR` is rejected with
    `-113 Undefined header` and `:TRIG:CLE` is the documented route.

Software-sweep cancellation is *not* here: `test_sweep_ownership.py`
covers it from Wave 6a, including the orphan-worker corruption, and
duplicating it would create two places to update.
"""
import time

import pytest
from test_checkup_all_drivers import CASES

from core.ranges import RangePlan

#: Anything that reconfigures the instrument rather than stepping it.
#: Sweeping is allowed to set levels and to read; it is not allowed to
#: change what protects the sample or what scale it is measured on.
CONFIG_MARKERS = (
    "rang", "nplc", "func", "lim", "prot", "sens:", "sense",
    "autorange", "rsen", "aper",
)

#: Commands that legitimately appear inside a sweep, and would
#: otherwise trip CONFIG_MARKERS on a substring.
SWEEP_EXEMPT = ("swe", "trig", "init", "read", "fetc", "outp", "abor",
                "trac", "arm", "meas", "nvbuffer", "sweeplinmeasure")


def make(driver_cls, transport_factory):
    transport = transport_factory()
    if not getattr(transport, "connected", False):
        transport.connect("fake")
    return driver_cls(transport), transport


def configured(driver):
    """Put a driver into the state an experiment would leave it in."""
    driver.set_source_function("voltage")
    driver.apply_ranges(
        RangePlan.for_sourcing("voltage", source_range=1.0,
                               measure_range=1e-3),
        log=lambda m: None)
    driver.set_current_limit(1e-3)


def drive_sweep(driver, points=5, timeout=10.0):
    """Run one sweep to completion, whichever kind the driver has."""
    driver.start_linear_sweep("voltage", 0.0, 1.0, points, 0.0)
    deadline = time.monotonic() + timeout
    while driver.sweep_points_ready() < points and time.monotonic() < deadline:
        time.sleep(0.005)
    return driver.read_sweep(points)


def looks_like_configuration(text):
    low = text.lower()
    if any(token in low for token in SWEEP_EXEMPT):
        return False
    return any(marker in low for marker in CONFIG_MARKERS)


# ---------------------------------------------------------------
# A. a sweep does not reconfigure the instrument underneath itself
# ---------------------------------------------------------------

@pytest.mark.parametrize("name,driver_cls,transport_factory", CASES,
                         ids=[c[0] for c in CASES])
def test_arming_never_re_enables_autorange_for_the_sourced_quantity(
        check, name, driver_cls, transport_factory):
    """Arming may range. It may not hand ranging back to the instrument.

    The distinction matters and a cruder rule gets it wrong in both
    directions.

    Setting an explicit source range while arming is correct - the
    U2722A does exactly that, choosing one range that covers both ends
    of the sweep so resolution does not change partway through a
    dataset. Forbidding it would break the only instrument here that
    cannot autorange.

    Re-enabling *autorange* is not. It silently discards the source
    range the experiment fixed through its RangePlan, and a sweep is
    the operation that then walks across range boundaries. Each
    crossing leaves a step where the two segments were sourced with
    different gain and offset errors; a straight line fitted across it
    absorbs the step as slope, and slope is resistance. The 2611A did
    this until Wave 6c - harmless until 6d-ii, because until then
    nothing set a source range for it to override.
    """
    driver, transport = make(driver_cls, transport_factory)
    if not hasattr(transport, "sent"):
        pytest.skip(f"{name}'s fake transport does not record writes")

    configured(driver)
    transport.sent.clear()
    try:
        driver.start_linear_sweep("voltage", 0.0, 1.0, 5, 0.0)
    except (NotImplementedError, RuntimeError) as exc:
        pytest.skip(f"{name}: {exc}")

    offenders = [t for t in transport.sent
                 if "autorange" in t.lower()
                 and ("on" in t.lower() or "auto on" in t.lower())
                 and "measure" not in t.lower()]
    check(f"{name}: arming does not re-enable source autoranging",
          not offenders, "; ".join(offenders))
    driver.abort_sweep()


@pytest.mark.parametrize("name,driver_cls,transport_factory", CASES,
                         ids=[c[0] for c in CASES])
def test_nothing_is_reconfigured_once_the_sweep_is_running(
        check, name, driver_cls, transport_factory):
    """House rule 12, applied to the sweep rather than to the run.

    The window opens once `start_linear_sweep()` has returned: arming
    is allowed to configure, stepping is not.
    """
    driver, transport = make(driver_cls, transport_factory)
    if not hasattr(transport, "sent"):
        pytest.skip(f"{name}'s fake transport does not record writes")

    configured(driver)
    driver.output_on()
    try:
        driver.start_linear_sweep("voltage", 0.0, 1.0, 5, 0.0)
    except (NotImplementedError, RuntimeError) as exc:
        pytest.skip(f"{name}: {exc}")

    transport.sent.clear()          # arming is over; stepping begins
    deadline = time.monotonic() + 10.0
    while (driver.sweep_points_ready() < 5
           and time.monotonic() < deadline):
        time.sleep(0.005)
    sourced, measured = driver.read_sweep(5)

    check(f"{name}: the sweep returned points to trust",
          len(measured) > 0, "no data, so the trace proves nothing")

    offenders = [t for t in transport.sent if looks_like_configuration(t)]
    check(f"{name}: nothing reconfigured while the sweep runs",
          not offenders, "; ".join(offenders[:4]))


# ---------------------------------------------------------------
# B. hardware sweeps configure before they arm
# ---------------------------------------------------------------

@pytest.mark.parametrize("name,driver_cls,transport_factory", CASES,
                         ids=[c[0] for c in CASES])
def test_a_hardware_sweep_is_configured_before_it_is_armed(
        check, name, driver_cls, transport_factory):
    """The sweep's own parameters must reach the instrument before the
    trigger does.

    An instrument armed first and configured second either runs on the
    previous sweep's parameters or errors - and on the models here it
    tends to be the former, which is the quiet failure this project
    exists to catch.
    """
    if driver_cls.SWEEP_KIND != "hardware":
        pytest.skip(f"{name} steps its sweep from the host")

    driver, transport = make(driver_cls, transport_factory)
    if not hasattr(transport, "sent"):
        pytest.skip(f"{name}'s fake transport does not record writes")

    configured(driver)
    transport.sent.clear()
    driver.start_linear_sweep("voltage", 0.0, 1.0, 5, 0.0)

    sent = transport.sent
    if not sent:
        # A simulated instrument has no wire to inspect. Skipped rather
        # than failed: there is no ordering to get wrong.
        pytest.skip(f"{name} puts nothing on a transport")

    def first_index(predicate):
        for i, text in enumerate(sent):
            if predicate(text.lower()):
                return i
        return None

    setup_at = first_index(lambda t: "swe" in t and "abor" not in t)
    trigger_at = first_index(
        lambda t: t.startswith("init") or ":init" in t
        or "sweeplinmeasure" in t or "trigger.initiate" in t)

    check(f"{name}: the sweep is described before it is started",
          setup_at is not None, f"no sweep setup found in {sent[:6]}")
    if setup_at is not None and trigger_at is not None:
        check(f"{name}: setup precedes the trigger",
              setup_at < trigger_at,
              f"setup at {setup_at}, trigger at {trigger_at}: {sent}")


# ---------------------------------------------------------------
# C. abort speaks the command this model accepts
# ---------------------------------------------------------------

#: Confirmed on the bench 2026-08-14 where noted. `:ABOR` is rejected by
#: the GSM-20H10 with -113 Undefined header, against a control that
#: proved the error queue was reporting.
ABORT_COMMANDS = {
    "GWInstekGSM20H10": ("TRIG:CLE", ":ABOR"),
    "Keithley2611A": ("abort", None),
}


@pytest.mark.parametrize("name,driver_cls,transport_factory", CASES,
                         ids=[c[0] for c in CASES])
def test_abort_uses_the_documented_command(check, name, driver_cls,
                                           transport_factory):
    expected = ABORT_COMMANDS.get(name)
    if expected is None:
        pytest.skip(f"{name} has no pinned abort spelling")
    wanted, forbidden = expected

    driver, transport = make(driver_cls, transport_factory)
    if not hasattr(transport, "sent"):
        pytest.skip(f"{name}'s fake transport does not record writes")

    configured(driver)
    driver.start_linear_sweep("voltage", 0.0, 1.0, 5, 0.0)
    transport.sent.clear()
    result = driver.abort_sweep()

    joined = " ".join(transport.sent).lower()
    check(f"{name}: abort sends {wanted}", wanted.lower() in joined,
          f"sent {transport.sent}")
    if forbidden:
        check(f"{name}: and never sends {forbidden}",
              forbidden.lower() not in joined,
              f"sent {transport.sent} - this model rejects it with -113")
    check(f"{name}: abort reports whether the worker is gone",
          isinstance(result, bool), f"returned {result!r}")


# ---------------------------------------------------------------
# D. the error queue drains
# ---------------------------------------------------------------

@pytest.mark.parametrize("name,driver_cls,transport_factory", CASES,
                         ids=[c[0] for c in CASES])
def test_the_error_queue_drains_rather_than_repeating(
        check, name, driver_cls, transport_factory):
    """`read_error()` must consume what it reports.

    A driver that reports the same code forever makes every caller
    that loops until the queue is empty hang, and one that never
    reports makes the checkup's whole "did you understand that?"
    premise false. Both have happened in this project's history, which
    is why read_error is in the mandatory contract.
    """
    driver, transport = make(driver_cls, transport_factory)

    seen = []
    for _ in range(5):
        try:
            code, text = driver.read_error()
        except NotImplementedError:
            pytest.skip(f"{name} has no error queue")
        except Exception as exc:
            check(f"{name}: read_error raised", False, str(exc))
            return
        seen.append(code)
        if not code:
            break

    check(f"{name}: a clean queue reports no error",
          seen and not seen[-1], f"codes seen: {seen}")
    check(f"{name}: and it terminates rather than repeating",
          len(seen) < 5, f"still reporting after 5 reads: {seen}")
