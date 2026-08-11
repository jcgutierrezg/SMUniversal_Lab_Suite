import pytest

pytestmark = [pytest.mark.gui]

import sys, os

"""Cross-driver contract: what every driver must do, and a signed-off
record of where they legitimately differ.

WHY THIS EXISTS
---------------
Drivers are the one place in this codebase where the same idea gets
written five times. That is deliberate - three SCPI dialects and a TSP
one genuinely cannot share an implementation - but it means a change to
one driver leaves four behind, silently. The originals died of exactly
this: six drifting copies of LabeledEntry, and function families
suffixed _2611/_2401 that differed only where somebody had fixed one.

So this file is not "assert all drivers are identical". They aren't, and
shouldn't be: the 2611A integrates to 25 NPLC where the SCPI boxes stop
at 10, and only the GSM has overvoltage protection. Demanding parity
would force fake capabilities, which is worse than having none.

WHAT IT DOES INSTEAD
--------------------
The gaps are written down. LEDGER below records, per driver, which
optional capability it has. The test compares the ledger against
reality and fails on any disagreement in either direction.

That makes the ledger the thing you have to edit. Add `set_nplc` to a
new driver and the test fails until the ledger says so. Add a brand-new
capability to one driver and the test fails for the other four until
each is either implemented or explicitly recorded as "not supported".
Either way the decision gets made once, on purpose, rather than
discovered on the bench a year later.

The checks, in order:

  A. Every registered driver is in the ledger (discovered from the
     registry, so a new driver cannot quietly opt out).
  B. Mandatory contract - the methods no SMU can do without.
  C. Capability ledger - declared gaps match reality.
  D. Declaration and implementation agree - the flag and the method
     travel together, in both directions.
  E. Informal capabilities - methods two or more drivers grew
     independently without any declaration behind them.
  F. Identity hygiene - MODEL_IDS resolve to their own driver and
     don't poach each other's.
  G. Limits are declared and internally consistent.
  H. Signature consistency, so experiments can call by keyword.
  I. reset() is actually invoked on connect. It wasn't, for months.
"""
import inspect
import tkinter as tk

from drivers.registry import KNOWN_DRIVERS, driver_for_idn
from core.transports.null_transport import NullTransport
from core.base_app import LabApp
from drivers.base_smu import BaseSMU
from experiments.iv_sweep.experiment import IVSweepExperiment


def overrides(cls, name):
    """True when `cls` defines `name` itself rather than inheriting the
    BaseSMU version. Walks the MRO so a driver subclassing another
    driver still counts as having it."""
    for klass in cls.__mro__:
        if klass is BaseSMU:
            return False
        if name in klass.__dict__:
            return True
    return False


# ---------------------------------------------------------------
# THE LEDGER - edit this when a driver gains or loses a capability
# ---------------------------------------------------------------
#
# True  = supported, and the declaration plus the method are both there
# False = genuinely not available on this model, and that is accepted
#
# A False is not a to-do. It is a decision someone made, and the reason
# belongs in the comment beside it.

LEDGER = {
    "Keithley2450": {
        "nplc": True,
        "ovp": False,           # 2450 sets protection via source limit, no OVP menu
        "high_z": True,
        "remote_sense_control": True,   # :SYST:RSEN
        "compliance_trip": False,   # no trip query wired up yet; would be :SENS:CURR:PROT:TRIP?
        "hardware_sweep": False,    # inherits the BaseSMU software sweep
    },
    "Keithley2401": {
        "nplc": True,
        "ovp": False,
        "high_z": True,
        "remote_sense_control": True,   # :SYST:RSEN
        "compliance_trip": False,
        "hardware_sweep": False,    # its hardware sweep was abandoned in the original
    },
    "Keithley2611A": {
        "nplc": True,
        "ovp": False,           # TSP exposes limits differently; no OVP menu
        "high_z": True,
        "remote_sense_control": True,   # smu.sense = REMOTE/LOCAL
        "compliance_trip": True,    # smu.source.compliance, a Lua boolean;
                                    # the 2600A page describes it per source
                                    # function and does not mention limitp
        "hardware_sweep": True,
    },
    "Keithley2635B": {
        "nplc": True,               # 0.001 to 25 NPLC, as the 2611A
        "ovp": False,           # TSP exposes limits differently; no OVP menu
        "high_z": True,         # smua.source.offmode = OUTPUT_HIGH_Z
        "remote_sense_control": True,   # smua.sense = REMOTE/LOCAL
        "compliance_trip": True,    # smuX.source.compliance, a Lua boolean;
                                    # covers the voltage, current AND power
                                    # limits, so True means "a ceiling was
                                    # reached", not necessarily the one the
                                    # experiment set
        "hardware_sweep": False,    # the TSP sweep factories are the same
                                    # family the 2611A uses and would very
                                    # likely work, but "very likely" is how
                                    # the GSM earned three bench-found
                                    # deviations - not wired until this
                                    # instrument has been on a bench
    },
    "GWInstekGSM20H10": {
        "nplc": True,
        "ovp": True,
        "high_z": True,
        "remote_sense_control": True,   # SYST:RSEN
        "compliance_trip": True,
        "hardware_sweep": True,     # probed at connect, falls back to software
    },
    "KeysightU2722A": {
        "nplc": True,               # integer 1-255 PLC
        "ovp": False,               # no overvoltage protection command
        "high_z": False,            # OUTPut[:STATe] only, no off-state mode
        "compliance_trip": False,   # Questionable register has one bit, and
                                    # it is over-temperature, not compliance
        "hardware_sweep": False,    # no staircase; the memory-list sequencer
                                    # is U2723A only
        "remote_sense_control": False,  # no command exists; the SENSE
                                        # terminals are strapped and this
                                        # unit is wired 4-wire
    },
    "KeysightB2901A": {
        "nplc": True,                # 4E-4 to 100 PLC at 50 Hz
        "ovp": False,               # :OUTP:PROT is an on/off enable for
                                    # over-voltage/current protection, not a
                                    # menu of ceilings; a boolean does not
                                    # fit OVP_CHOICES and faking one would be
                                    # worse than declaring none
        "high_z": True,             # :OUTP:OFF:MODE ZERO|HIZ|NORMal
        "remote_sense_control": True,   # :SENS:REM, and it resets to OFF
        "compliance_trip": True,    # :SENS:CURR:PROT:TRIP?
        "hardware_sweep": False,    # the staircase is documented and
                                    # deliberately not wired up until this
                                    # instrument has been on a bench - the
                                    # GSM's cost three bench-found deviations
    },
    "UndalogicMiniSMU": {
        "nplc": True,               # OSR mapped onto the NPLC control
        "ovp": False,               # no overvoltage protection command
        "high_z": False,            # OUTP<n> ON/OFF only
        "compliance_trip": False,   # no trip query in the library
        "hardware_sweep": True,     # onboard, VOLTAGE sweeps only, fw 1.3.4+;
                                    # current sweeps use the software fallback
        "remote_sense_control": True,   # 4-wire mode, fw 1.4.3+, and it
                                        # takes over channel 2
    },
    "DummySMU": {
        "nplc": True,
        "ovp": True,
        "high_z": True,
        "remote_sense_control": True,   # accepted and ignored; nothing to model
        "compliance_trip": False,   # the simulated sample never runs away
        "hardware_sweep": True,
    },
}

# capability name -> (declaration attribute test, implementing method)
CAPABILITIES = {
    "nplc": (lambda c: c.NPLC_RANGE is not None, "set_nplc"),
    "ovp": (lambda c: bool(c.OVP_CHOICES), "set_voltage_protection"),
    "high_z": (lambda c: c.HIGH_Z_OFF, "set_output_off_mode"),
    "compliance_trip": (None, "compliance_tripped"),
    "hardware_sweep": (lambda c: c.SWEEP_KIND == "hardware", None),
    # Declaration-only, like hardware_sweep: set_remote_sense() is a
    # mandatory method that every driver has, so its presence proves
    # nothing. What varies is whether calling it does anything.
    "remote_sense_control": (lambda c: c.REMOTE_SENSE_CONTROL, None),
}

# Methods without which an SMU cannot be driven at all. Inheriting one
# of these from BaseSMU means inheriting a NotImplementedError.
MANDATORY = [
    "set_source_function", "set_current_level", "set_voltage_level",
    "set_current_limit", "set_voltage_limit", "set_current_range",
    "set_voltage_range", "set_remote_sense", "set_source_delay",
    "output_on", "output_off", "measure",
    # Promoted from INFORMAL: tools/smu_checkup.py needs to ask any
    # instrument "did you understand that?" without knowing the model.
    "read_error",
]

# Methods two or more drivers grew on their own, with no capability
# declaration behind them. Listed here as accepted rather than
# unnoticed; promote one to the contract if an experiment ever needs to
# call it without knowing the model.
INFORMAL = {
    "set_terminals": ["Keithley2450", "GWInstekGSM20H10"],
    # The console note printed at connect. iv_sweep already calls this
    # via getattr(), so it is a contract in practice - left informal
    # only because the drivers that have nothing to say don't need it.
    "sweep_note": ["GWInstekGSM20H10", "Keithley2611A", "Keithley2635B",
                   "KeysightB2901A", "KeysightU2722A",
                   "UndalogicMiniSMU"],
}


# ---------------------------------------------------------------
# A. every driver is accounted for
# ---------------------------------------------------------------


def test_every_registered_driver_is_in_the_ledger(check):
    registered = {c.__name__ for c in KNOWN_DRIVERS}
    missing = sorted(registered - set(LEDGER))
    extra = sorted(set(LEDGER) - registered)
    check("no registered driver is missing from the ledger", not missing,
          f"add to LEDGER: {missing}" if missing else "")
    check("the ledger has no entries for drivers that no longer exist",
          not extra, f"remove from LEDGER: {extra}" if extra else "")

    # ---------------------------------------------------------------
    # B. the mandatory contract
    # ---------------------------------------------------------------


def test_mandatory_contract(check):
    for cls in KNOWN_DRIVERS:
        absent = [m for m in MANDATORY if not overrides(cls, m)]
        check(f"{cls.__name__} implements every mandatory method", not absent,
              f"inherits NotImplementedError for: {absent}" if absent else "")

    # ---------------------------------------------------------------
    # C. the capability ledger matches reality
    # ---------------------------------------------------------------


def test_capability_ledger(check):
    for cls in KNOWN_DRIVERS:
        recorded = LEDGER.get(cls.__name__, {})
        unlisted = sorted(set(CAPABILITIES) - set(recorded))
        check(f"{cls.__name__} has a ledger entry for every capability",
              not unlisted,
              f"unrecorded: {unlisted} - implement or record as False"
              if unlisted else "")

        for cap, (declared, method) in CAPABILITIES.items():
            if cap not in recorded:
                continue
            actual = declared(cls) if declared else overrides(cls, method)
            check(f"{cls.__name__}.{cap} matches the ledger",
                  bool(actual) == bool(recorded[cap]),
                  f"ledger says {recorded[cap]}, driver says {bool(actual)}")

    # ---------------------------------------------------------------
    # D. declaration and implementation travel together
    # ---------------------------------------------------------------


def test_declaration_implies_implementation(check):
    for cls in KNOWN_DRIVERS:
        for cap, (declared, method) in CAPABILITIES.items():
            if declared is None or method is None:
                continue
            says = bool(declared(cls))
            does = overrides(cls, method)
            # Both directions. Declaring without implementing means the GUI
            # offers a control that raises; implementing without declaring
            # means a working control stays greyed out forever, which is
            # the quieter and therefore worse of the two.
            check(f"{cls.__name__}: {cap} declaration and {method}() agree",
                  says == does,
                  f"declares={says} implements={does}")

    # ---------------------------------------------------------------
    # E. informal capabilities stay logged
    # ---------------------------------------------------------------


def test_informal_capabilities(check):
    base_public = {n for n in dir(BaseSMU) if not n.startswith("_")}
    grown = {}
    for cls in KNOWN_DRIVERS:
        for name in dir(cls):
            if name.startswith("_") or name in base_public:
                continue
            if not callable(getattr(cls, name, None)):
                continue
            grown.setdefault(name, []).append(cls.__name__)

    shared = {n: sorted(v) for n, v in grown.items() if len(v) >= 2}
    for name, owners in sorted(shared.items()):
        check(f"'{name}' on {owners} is a recorded informal capability",
              name in INFORMAL and sorted(INFORMAL[name]) == owners,
              "two or more drivers grew this independently - add it to "
              "INFORMAL, or promote it to BaseSMU with a capability flag")
    for name in sorted(INFORMAL):
        check(f"INFORMAL entry '{name}' is still real", name in shared,
              "no longer shared by 2+ drivers - remove it from INFORMAL")

    # ---------------------------------------------------------------
    # F. identity hygiene
    # ---------------------------------------------------------------


def test_identity(check):
    names = [c.DISPLAY_NAME for c in KNOWN_DRIVERS]
    check("DISPLAY_NAMEs are unique", len(names) == len(set(names)),
          "the manual-override dropdown looks them up by name")

    for cls in KNOWN_DRIVERS:
        check(f"{cls.__name__} declares at least one MODEL_ID",
              bool(cls.MODEL_IDS))
        for model_id in cls.MODEL_IDS:
            # A driver whose own ID resolves elsewhere would be
            # undetectable on the bench, and the failure looks like a
            # broken instrument rather than a registry problem.
            resolved = driver_for_idn(f"SOME VENDOR,{model_id},SN123,1.0")
            check(f"{cls.__name__}: '{model_id}' resolves to itself",
                  resolved is cls,
                  f"resolves to {resolved.__name__ if resolved else None}")

    # ---------------------------------------------------------------
    # G. limits
    # ---------------------------------------------------------------


def test_limits(check):
    for cls in KNOWN_DRIVERS:
        limits = cls.LIMITS
        if not check(f"{cls.__name__} declares LIMITS", limits is not None):
            continue
        check(f"{cls.__name__}: positive maxima",
              limits.max_voltage > 0 and limits.max_current > 0)
        check(f"{cls.__name__}: ranges are ascending and positive",
              limits.voltage_ranges == sorted(limits.voltage_ranges)
              and limits.current_ranges == sorted(limits.current_ranges)
              and all(v > 0 for v in limits.voltage_ranges)
              and all(a > 0 for a in limits.current_ranges))
        check(f"{cls.__name__}: no range exceeds its own maximum",
              max(limits.voltage_ranges) <= limits.max_voltage
              and max(limits.current_ranges) <= limits.max_current)
        if limits.power_envelope:
            check(f"{cls.__name__}: envelope corners sit within the maxima",
                  all(v <= limits.max_voltage and a <= limits.max_current
                      for v, a in limits.power_envelope))

    # ---------------------------------------------------------------
    # H. signatures
    # ---------------------------------------------------------------


def test_signature_consistency(check):
    for method in MANDATORY + ["set_nplc", "set_output_off_mode",
                               "set_voltage_protection"]:
        seen = {}
        for cls in KNOWN_DRIVERS:
            if not overrides(cls, method):
                continue
            params = tuple(
                inspect.signature(getattr(cls, method)).parameters)[1:]
            seen.setdefault(params, []).append(cls.__name__)
        check(f"{method}() has one signature across the suite", len(seen) <= 1,
              f"{ {p: n for p, n in seen.items()} }" if len(seen) > 1 else "")

    # ---------------------------------------------------------------
    # I. reset() is actually called on connect
    # ---------------------------------------------------------------


def test_reset_runs_on_connect(check):
    # This is here because it was NOT true for months. Every driver had a
    # reset(), each one carefully written, and nothing in the app ever
    # called it - so the GSM's interlock disable never ran and its output
    # would have refused to turn on at the bench.
    from drivers.dummy_smu import DummySMU

    calls = []
    original_reset = DummySMU.reset
    DummySMU.reset = lambda self: (calls.append(1), original_reset(self))[1]

    root = tk.Tk()
    app = LabApp(root, IVSweepExperiment)
    app.connect_role("source", NullTransport(), "<simulated>")
    root.update()
    DummySMU.reset = original_reset

    check("reset() was called exactly once on connect", len(calls) == 1,
          f"called {len(calls)} times")
    console = app.console.get("1.0", "end").lower()
    check("and the console says so", "reset" in console,
          "" if "reset" in console else "no reset line after connecting")
    try:
        root.destroy()
    except Exception:
        pass
