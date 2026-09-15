"""The line between the two fleets, and what may cross it.

WHY THIS EXISTS
---------------
`BaseSMU` and `BaseLoad` are siblings on `BaseInstrument`. The whole
point of that split is a rule that cannot be expressed as a class
relationship:

    Nothing in experiments/ or core/gui/ may know which kind of
    instrument it is talking to.

They ask about declared *capabilities* - `supports_nplc()`,
`supports_ovp()`, `supports_sweep()` - never about a class. There is not
one `isinstance` check against a driver type anywhere in the package,
and that was true before the split; what was missing was anything
holding it true. A method added to `BaseSMU` and called from an
experiment would work perfectly on all nine SMUs and raise
`AttributeError` on the first load, at the bench, mid-run.

So this scans the code rather than trusting the convention, and the
scan is the test. `SMU_ONLY_CALLS` below is the ledger of what is
allowed across the line and why - the same mechanism as `LEDGER` in
`test_driver_contract.py`, for the same reason: the cost of reaching
past the shared surface is paid by writing down why, at the moment of
doing it, rather than by someone debugging a load six months later.
"""
import ast
import collections
import pathlib

from smuniversal_lab_suite.core import provenance
from smuniversal_lab_suite.drivers.base_instrument import BaseInstrument
from smuniversal_lab_suite.drivers.base_smu import BaseSMU
from smuniversal_lab_suite.drivers.registry import (
    KNOWN_DRIVERS,
    KNOWN_LOADS,
    KNOWN_SMUS,
)

PKG = pathlib.Path(__file__).resolve().parent.parent / "smuniversal_lab_suite"

#: Where a driver instance is in scope under a name this scan can follow.
SCANNED = ("experiments", "core/gui")

#: The local names an experiment or panel binds a driver to. Both
#: spellings are in use and neither is wrong; what matters is that the
#: scan follows whatever is actually written.
DRIVER_NAMES = {"smu", "driver"}

# ---------------------------------------------------------------
# THE LEDGER - what may be called on an SMU but not on any instrument
# ---------------------------------------------------------------
#
# Every entry is a promise that the call site is guarded, or a debt that
# is recorded rather than hidden. Adding one is a decision; the reason
# beside it is the decision.

SMU_ONLY_CALLS = {
    # Both compliance setters. A load has no compliance: its OCP and OPP
    # are *trips* that shut the input down, not ceilings it regulates
    # at, and wiring a setter to one would be fault 11 written on
    # purpose - a command accepted and ignored, with the previous
    # setting left in force.
    #
    # GUARDED, and in exactly one place: `widgets.apply_compliance()`
    # checks `supports_compliance()` before either call and returns a
    # written reason when there is none, which the experiment records.
    # Four experiments used to carry their own if/else around these two
    # lines; the scan finding them at a single call site is the evidence
    # that they no longer do.
    "set_current_limit": "guarded by supports_compliance() in apply_compliance()",
    "set_voltage_limit": "guarded by supports_compliance() in apply_compliance()",

    # The four-axis RangePlan. A load has no source range and no
    # independent measurement range; on the 72-13200 the per-quantity
    # ceilings are entered at the front panel and cannot be set over the
    # bus at all. The plan is absorbed by the driver rather than
    # branched on here - the U2722A precedent, where one instrument's
    # ordering constraint was met inside the driver rather than by
    # changing five experiments.
    "apply_ranges": "absorbed by the driver; a load reports what it read",

    # Returns None on any instrument that cannot say, which is already
    # the honest answer for a load and needs no guard. It is SMU-only
    # because the *name* is about a compliance, not because the call
    # would break: promoting it to BaseInstrument would put a
    # compliance word in the shared surface.
    "compliance_tripped": "safe - returns None where it cannot be asked",
}


def _driver_attribute_uses():
    """Every attribute reached through a driver-bound name, and where.

    A deliberately shallow scan: attributes of a bare local called `smu`
    or `driver`. It does not follow `self.app.instruments[...]` or a
    driver passed under another name, so it under-reports rather than
    over-reports - and under-reporting is the right direction for a
    check whose failure mode is a false accusation against a working
    call site. What it catches is the ordinary case, which is every
    call site in the package today.
    """
    uses = collections.defaultdict(set)
    for rel in SCANNED:
        for path in (PKG / rel).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id in DRIVER_NAMES):
                    uses[node.attr].add(
                        str(path.relative_to(PKG)).replace("\\", "/"))
    return uses


def test_experiments_and_gui_only_reach_the_shared_surface(check):
    """The rule itself.

    A call that is neither on `BaseInstrument` nor in the ledger is the
    failure this file exists for: it works on every SMU and breaks on
    the first load.
    """
    uses = _driver_attribute_uses()
    check("the scan found call sites at all", len(uses) > 20,
          f"only {len(uses)} attributes seen - has the scan stopped "
          f"following how a driver is named?")

    for name in sorted(uses):
        if hasattr(BaseInstrument, name):
            continue
        where = ", ".join(sorted(uses[name]))
        check(f"{name}() is on BaseInstrument or in the ledger",
              name in SMU_ONLY_CALLS,
              f"called on a driver in {where}, but it exists only on "
              f"BaseSMU. Either move it to BaseInstrument, guard the "
              f"call site with a capability check, or add it to "
              f"SMU_ONLY_CALLS with the reason.")


def test_the_ledger_has_no_stale_entries(check):
    """An entry for a call nobody makes any more.

    A ledger that only ever grows stops being a record of decisions and
    becomes a list of exemptions nobody can audit. Same guard as
    `test_the_exemptions_are_still_the_only_ones` in
    `test_sentinel_handling.py`.
    """
    uses = _driver_attribute_uses()
    for name in sorted(SMU_ONLY_CALLS):
        check(f"{name} is still called somewhere", name in uses,
              "no call site left - delete the ledger entry")
        check(f"{name} is still SMU-only", not hasattr(BaseInstrument, name),
              "it is on BaseInstrument now - delete the ledger entry")


def test_the_compliance_setters_have_exactly_one_call_site(check):
    """The ledger says both are guarded. This is that claim, checked.

    `widgets.apply_compliance()` is where `supports_compliance()` is
    consulted, so a second call site anywhere else is an unguarded one
    by construction - it would work on all nine SMUs and raise on the
    first load, which is the failure this whole file exists to prevent.

    Written as "one file" rather than "one line" deliberately: the
    helper legitimately calls each setter once, on opposite sides of an
    if/else.
    """
    uses = _driver_attribute_uses()
    for name in ("set_current_limit", "set_voltage_limit"):
        where = uses.get(name, set())
        check(f"{name} is called from one place", where == {"core/gui/widgets.py"},
              f"called from {sorted(where) or 'nowhere'}; it must go "
              f"through widgets.apply_compliance(), which is where "
              f"supports_compliance() is checked")


def test_every_registered_driver_is_a_base_instrument(check):
    for cls in KNOWN_DRIVERS:
        check(f"{cls.__name__} is a BaseInstrument",
              issubclass(cls, BaseInstrument))


def test_the_union_is_the_two_fleets(check):
    """`KNOWN_DRIVERS` is derived, not a third hand-kept list.

    A driver registered in a fleet and left out of identification would
    be invisible to `*IDN?` resolution while passing every contract
    suite - present and unreachable.
    """
    check("no driver is in both fleets",
          not (set(KNOWN_SMUS) & set(KNOWN_LOADS)))
    check("the union is exactly the two fleets",
          set(KNOWN_DRIVERS) == set(KNOWN_SMUS) | set(KNOWN_LOADS))
    for cls in KNOWN_SMUS:
        check(f"{cls.__name__} is a BaseSMU", issubclass(cls, BaseSMU))
    for cls in KNOWN_LOADS:
        check(f"{cls.__name__} is not an SMU", not issubclass(cls, BaseSMU),
              "a load on BaseSMU inherits a contract half of whose "
              "questions do not apply to it")


def test_the_staleness_fingerprint_covers_every_base(check):
    """Both base classes are in `SHARED_CODE_PATHS`.

    The split moved the software sweep, the sentinel handling and the
    readback grading out of `base_smu.py`. A shared-paths list still
    naming only that file would go on answering - it would simply stop
    covering the engine that steps every software sweep, so a change
    there would mark nothing stale and every note would keep reading
    `commissioned`.

    That is fault 31: a stamp that has stopped moving is indistinguish-
    able from one with nothing to report. This is what makes adding a
    third base class fail here rather than silently narrow the digest.
    """
    shared = set(provenance.SHARED_CODE_PATHS)
    for base in (BaseInstrument, BaseSMU):
        rel = f"drivers/{pathlib.Path(base.__module__.replace('.', '/')).name}.py"
        check(f"{base.__name__}'s file is fingerprinted", rel in shared,
              f"{rel} is not in SHARED_CODE_PATHS, so a change to it "
              f"would mark no driver stale")
    for rel in sorted(shared):
        check(f"{rel} exists", (PKG / rel).is_file(),
              "a path that is not there contributes nothing to the "
              "digest and says so nowhere")
