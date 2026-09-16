"""Instrument checkup - what the offline test suite cannot prove.

`tests/` proves every driver has the right *shape* and sends the right
strings to a fake. It cannot prove a real instrument agrees. Every
command spelling in the U2722A and miniSMU drivers was written from a
manual and has never been answered by hardware; the ones in the older
drivers were read off working scripts but have since been reordered,
retimed and re-ranged.

This module is the other half: it drives a connected instrument through
the whole BaseSMU contract and asks, at every step, whether the
instrument understood. `tools/smu_checkup.py` is the front end.

---------------------------------------------------------------------
IT ASSUMES NOTHING IS CONNECTED TO THE OUTPUT
---------------------------------------------------------------------
Every level it sources is chosen to be safe into an open circuit, and
the expected results are the open-circuit ones: source a small voltage,
measure approximately no current. That is not a limitation, it is the
point - an open circuit is a *known* DUT, so the readings can be checked
rather than merely recorded. With a sample connected, "0.1 V produced
2 uA" proves nothing without knowing the sample.

Connect a sample and the measurement checks will report failures that
are not faults. The report says so at the top.

**Sensing is forced to 2-wire wherever the driver allows it.** With
nothing connected, an SMU in 4-wire mode has open sense leads and many
will slew the output to compliance trying to servo a voltage they cannot
see. Two instruments cannot be forced: the U2722A is hardwired 4-wire,
and the miniSMU's 4-wire mode is system-wide. Both are noted in the
report rather than silently skipped.

---------------------------------------------------------------------
Three tiers
---------------------------------------------------------------------
1. Identity and declarations - output off, nothing sourced.
2. Configuration syntax     - output off, every contract method called
                              and the error queue checked after each.
3. Live measurement         - sources at small levels into open circuit.

Tier 3 stops at the first failure in tiers 1-2 severe enough to make
sourcing unwise, and never runs if the output could not be turned off.

Split by tier and by reporting in Wave E (review A-08). The public
names are all importable from here, as they always were.
"""
from smuniversal_lab_suite.core.checkup.base import CheckupBase, Result
from smuniversal_lab_suite.core.checkup.load import LoadCheckup
from smuniversal_lab_suite.core.checkup.probes import (
    COMMANDS_LISTED_WITH_AN_ERROR,
    COMPLIANCE_CEILING,
    COMPLIANCE_FLOOR,
    OPEN_CIRCUIT_MAX_A,
    PROBE_COMPLIANCE_I,
    PROBE_COMPLIANCE_V,
    PROBE_CURRENT,
    PROBE_VOLTAGE,
    SETTLE_TOLERANCE_FRACTION,
    SETTLE_TOLERANCE_V,
    SWEEP_POINTS,
    TIMED_READINGS,
    ProbeLevels,
    probe_levels_for,
)
from smuniversal_lab_suite.core.checkup.report import build_report
from smuniversal_lab_suite.core.checkup.tier1 import Tier1Checks
from smuniversal_lab_suite.core.checkup.tier2 import Tier2Checks
from smuniversal_lab_suite.core.checkup.tier3 import Tier3Checks


class Checkup(Tier1Checks, Tier2Checks, Tier3Checks, CheckupBase):
    """Runs the checks and collects Results.
    
    Takes a live driver. Does not open or close the transport - the
    caller owns the connection, same rule the experiments follow.
    """


def checkup_for(driver, **kwargs):
    """The right checkup for whichever fleet this driver belongs to.

    One entry point rather than two, so a bench tool does not have to
    know - and so a load cannot be put through the SMU checkup by
    accident, which would run to completion and prove nothing.
    """
    from smuniversal_lab_suite.drivers.base_smu import BaseSMU

    if isinstance(driver, BaseSMU):
        return Checkup(driver, **kwargs)
    return LoadCheckup(driver, **kwargs)


__all__ = [
    "Checkup",
    "LoadCheckup",
    "checkup_for",
    "CheckupBase",
    "Result",
    "build_report",
    "COMMANDS_LISTED_WITH_AN_ERROR",
    "COMPLIANCE_CEILING",
    "COMPLIANCE_FLOOR",
    "OPEN_CIRCUIT_MAX_A",
    "PROBE_COMPLIANCE_I",
    "PROBE_COMPLIANCE_V",
    "PROBE_CURRENT",
    "PROBE_VOLTAGE",
    "ProbeLevels",
    "SETTLE_TOLERANCE_FRACTION",
    "SETTLE_TOLERANCE_V",
    "SWEEP_POINTS",
    "TIMED_READINGS",
    "probe_levels_for",
]
