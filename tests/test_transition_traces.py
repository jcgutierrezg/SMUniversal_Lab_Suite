
"""State-transition traces: what goes on the wire, and in what order.

Wave 6b, decision W6b-1. Review §33, whose acceptance criterion is that
*a change in command order that creates an unsafe or invalid transient
causes a test failure* - not merely that each command is present.

Two halves, because they catch different faults:

**Ordering invariants**, asserted on every driver from the shared `CASES`
table. These catch a sequence that energises before it protects, or
reconfigures something while the sample is live. They are the half §33
asks for.

**Exact spellings**, pinned per driver in `OUTPUT_COMMANDS` below. These
catch a command that was silently ignored. An instrument sent a command
it does not recognise logs it in a queue nobody reads, ignores it, and
leaves the previous setting in force - so "the output-off went out" is
not the same claim as "the output-off went out *in this instrument's
dialect*".

The per-driver test files already pin most spellings in detail. What is
pinned here is deliberately narrow: the output transitions, because they
are the ones where a silently-ignored command leaves a sample energised.
"""
import pytest
from test_checkup_all_drivers import CASES

from core.ranges import AUTO, RangePlan

#: driver name -> (exact commands for output_on, for output_off)
#:
#: Captured from the drivers and then pinned, which is the only honest
#: order: deriving the expectation from the code it checks would make
#: the test agree with whatever the code does.
#:
#: Two entries are `None`, for drivers with nothing to pin: the miniSMU
#: is driven through the vendor's Python library rather than a text
#: protocol, and the DummySMU has no instrument behind it. Named rather
#: than omitted so the coverage check below still sees them.
OUTPUT_COMMANDS = {
    "Keithley2450": ([":OUTP ON"], [":OUTP OFF"]),
    "Keithley2401": ([":OUTP ON"], [":OUTP OFF"]),
    "Keithley2611A": (["smu = smua", "smu.source.output = smu.OUTPUT_ON"],
                      ["smu.source.output = smu.OUTPUT_OFF"]),
    "Keithley2635B": (["smua.source.output = smua.OUTPUT_ON"],
                      ["smua.source.output = smua.OUTPUT_OFF"]),
    "GWInstekGSM20H10": (["OUTP 1"], ["OUTP 0"]),
    "KeysightU2722A": (["OUTP ON, (@1)"], ["OUTP OFF, (@1)"]),
    "KeysightB2901A": ([":OUTP ON"], [":OUTP OFF"]),
    "UndalogicMiniSMU": None,
    "DummySMU": None,
}

CONFIG_METHODS = ("set_source_function", "set_current_limit",
                  "set_voltage_limit", "set_remote_sense",
                  "set_source_delay")


def make(driver_cls, transport_factory):
    transport = transport_factory()
    if not getattr(transport, "connected", False):
        transport.connect("fake")
    return driver_cls(transport), transport


def sent(transport):
    return list(getattr(transport, "sent", []))


def index_of(calls, needle):
    for i, text in enumerate(calls):
        if needle.lower() in text.lower():
            return i
    return None


def test_every_driver_has_its_output_commands_pinned(check):
    missing = [n for n, _, _ in CASES if n not in OUTPUT_COMMANDS]
    check("every driver in CASES has an output-command entry",
          not missing, ", ".join(missing))


@pytest.mark.parametrize("name,driver_cls,transport_factory", CASES,
                         ids=[c[0] for c in CASES])
def test_output_transitions_use_this_instruments_dialect(
        check, name, driver_cls, transport_factory):
    expected = OUTPUT_COMMANDS.get(name)
    if expected is None:
        pytest.skip(f"{name} has no text output commands to pin")
    on_expected, off_expected = expected

    driver, transport = make(driver_cls, transport_factory)
    if not hasattr(transport, "sent"):
        pytest.skip(f"{name}'s fake transport does not record writes")

    transport.sent.clear()
    driver.output_on()
    check(f"{name}: output_on sends exactly its own dialect",
          sent(transport) == on_expected,
          f"sent {sent(transport)}")

    transport.sent.clear()
    driver.output_off()
    check(f"{name}: output_off sends exactly its own dialect",
          sent(transport) == off_expected,
          f"sent {sent(transport)}")


@pytest.mark.parametrize("name,driver_cls,transport_factory", CASES,
                         ids=[c[0] for c in CASES])
def test_a_configured_output_on_protects_before_it_energises(
        check, name, driver_cls, transport_factory):
    """Compliance reaches the instrument before the output does.

    Scope, stated plainly after a mutation round showed the naive
    reading of this test to be nearly tautological: the test calls
    `set_current_limit()` before `output_on()`, so of course the trace
    comes out in that order. Reordering the *caller* is not something
    this test can catch, and it should not be quoted as if it were.

    What it does catch is a driver that **defers** configuration -
    batching writes and flushing them after the output-on, or building
    a command string that is only sent later. That is not hypothetical
    on instruments with a trigger model, and it would defeat every
    ordering check at the experiment layer, because the experiment's
    call order would be correct while the wire order was not.

    Caller ordering is `test_house_rule_12.py`'s job, and it is proven
    discriminating there by mutation. This is the other half.
    """
    driver, transport = make(driver_cls, transport_factory)
    if not hasattr(transport, "sent"):
        pytest.skip(f"{name}'s fake transport does not record writes")

    transport.sent.clear()
    try:
        driver.set_source_function("voltage")
        driver.apply_ranges(RangePlan(source_current=AUTO,
                                      source_voltage=2.0,
                                      measure_current=1e-3,
                                      measure_voltage=2.0),
                            log=lambda m: None)
        driver.set_current_limit(1e-3)
        driver.output_on()
    except NotImplementedError as exc:
        pytest.skip(f"{name}: {exc}")

    calls = sent(transport)
    if not calls:
        pytest.skip(f"{name} sends nothing for these calls")

    on_at = index_of(calls, "OUTPUT_ON")
    if on_at is None:
        on_at = index_of(calls, "OUTP")
    check(f"{name}: the output-on is identifiable in the trace",
          on_at is not None, f"{calls}")
    if on_at is None:
        return

    # The compliance must be somewhere before it, not merely present.
    limit_at = None
    for i, text in enumerate(calls[:on_at]):
        low = text.lower()
        if "limit" in low or "prot" in low or "lim" in low:
            limit_at = i
            break
    check(f"{name}: a compliance command precedes the output-on",
          limit_at is not None,
          f"nothing limit-shaped before index {on_at}: {calls[:on_at]}")


@pytest.mark.parametrize("name,driver_cls,transport_factory", CASES,
                         ids=[c[0] for c in CASES])
def test_a_driver_does_not_energise_on_its_own(
        check, name, driver_cls, transport_factory):
    """No configuration call turns the output on as a side effect.

    The B2901A trap in reverse: a driver whose `set_source_function()`
    quietly energised would defeat every ordering check above and every
    experiment-level one, because the sequence would look correct and
    the sample would be live anyway.
    """
    driver, transport = make(driver_cls, transport_factory)
    if not hasattr(transport, "sent"):
        pytest.skip(f"{name}'s fake transport does not record writes")

    on_expected = OUTPUT_COMMANDS.get(name)
    if on_expected is None:
        pytest.skip(f"{name} has no text output commands to pin")
    energising = [c for c in on_expected[0] if "output" in c.lower()
                  or "outp" in c.lower()]

    offences = []
    for method in CONFIG_METHODS:
        fn = getattr(driver, method, None)
        if fn is None:
            continue
        transport.sent.clear()
        try:
            if method == "set_source_function":
                fn("voltage")
            elif method == "set_remote_sense":
                fn(True)
            elif method == "set_source_delay":
                fn(0.0)
            else:
                fn(1e-3)
        except (NotImplementedError, ValueError):
            continue
        for text in sent(transport):
            if any(e.lower() == text.lower() for e in energising):
                offences.append(f"{method} sent {text!r}")

    check(f"{name}: no configuration call energises the output",
          not offences, "; ".join(offences))
