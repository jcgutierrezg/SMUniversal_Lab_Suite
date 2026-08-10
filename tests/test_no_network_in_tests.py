"""
The suite must not reach for real hardware.

`_no_instrument_discovery` in `conftest.py` stubs transport scanning for
every test that does not explicitly opt out. It is autouse, so it is
invisible - and an invisible fixture that silently stops working is
worse than no fixture at all, because the network dependency would come
back with nothing to show for it but a slower suite.

So these assert the stub is in force. They are cheap, they need no Tk,
and they fail loudly if someone renames a transport method, adds a
transport that scans by another name, or removes the fixture.

Why it matters, in one sentence: every GUI test here connects a
`NullTransport` and touches no instrument, but before this fixture
existed each `LabApp(...)` first asked the lab's network what was
plugged in - and on CI, asked GitHub's.
"""
from core.gui.connection_panel import TRANSPORTS


def test_no_transport_reports_any_address(check):
    """Every registered transport is stubbed, not just the VISA ones.

    Iterating `TRANSPORTS` rather than naming classes is deliberate: a
    transport added later is covered without anyone remembering to come
    back here, and if it cannot be stubbed this fails on the day it is
    added rather than the day CI goes red.
    """
    for name, cls in sorted(TRANSPORTS.items()):
        found = cls.list_available()
        check(f"{name} reports no addresses under test", found == [],
              f"{found!r} - discovery stub is not in force")


def test_scan_summaries_are_empty(check):
    """The console breakdown is stubbed too.

    `_refresh()` calls `scan_summary()` straight after `list_available()`,
    and on the VISA transports that is a *second* walk of every backend.
    Stubbing only the first would have halved the problem and hidden the
    rest.
    """
    for name, cls in sorted(TRANSPORTS.items()):
        summary = getattr(cls, "scan_summary", None)
        if summary is None:
            continue
        lines = summary()
        check(f"{name} reports no scan summary under test", lines == [],
              f"{lines!r} - discovery stub is not in force")


def test_the_opt_out_marker_is_registered(pytestconfig, check):
    """A marker typo would fail open.

    `get_closest_marker("instrument_discovery")` returns None for a name
    nobody registered, so a misspelling in `conftest.py` would silently
    stub the one file that must not be stubbed - and
    `test_visa_backends.py` would then be testing the stub rather than
    the merging logic it exists for. `--strict-markers` is not on, so
    pytest would not catch it either.
    """
    declared = pytestconfig.getini("markers")
    names = [line.split(":", 1)[0].strip() for line in declared]
    check("instrument_discovery is declared in pyproject.toml",
          "instrument_discovery" in names, str(names))
