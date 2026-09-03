"""
Driver registry - maps what an instrument says it is to the class that
knows how to drive it.

Every SCPI and TSP instrument answers *IDN? with a string like:

    KEITHLEY INSTRUMENTS,MODEL 2450,04412345,1.7.12b

so connecting becomes: open the transport, ask who's there, look up the
driver. Plug in whatever's on the bench and the app works out the rest.

Adding a model:
    1. Write drivers/<model>.py implementing BaseSMU, with MODEL_IDS and
       LIMITS set, plus whichever optional capabilities it has
       (NPLC_RANGE, OVP_CHOICES, HIGH_Z_OFF, SWEEP_KIND).
    2. Add it to KNOWN_DRIVERS below.
    3. Add it to LEDGER in tests/test_driver_contract.py, recording each
       capability as True or False. That test fails until you do, which
       is the point: it makes you decide what happens to the other
       drivers when this one gains something they lack.
Nothing in experiments/ changes. Full walkthrough in
docs/workflow/adding-an-smu.md,
"Adding the next SMU".
"""
from drivers.dummy_smu import DummySMU
from drivers.gwinstek_gsm20h10 import GWInstekGSM20H10
from drivers.keithley_2401 import Keithley2401
from drivers.keithley_2450 import Keithley2450
from drivers.keithley_2611a import Keithley2611A
from drivers.keithley_2635b import Keithley2635B
from drivers.keysight_b2901a import KeysightB2901A
from drivers.keysight_u2722a import KeysightU2722A
from drivers.undalogic_minismu import UndalogicMiniSMU

KNOWN_DRIVERS = [
    Keithley2450,
    Keithley2401,
    Keithley2611A,
    Keithley2635B,
    GWInstekGSM20H10,
    KeysightU2722A,
    KeysightB2901A,
    UndalogicMiniSMU,
    # Simulated. Its MODEL_IDS only match the ID string NullTransport
    # returns, so real hardware can never resolve to it by accident.
    DummySMU,
]


class UnknownInstrumentError(RuntimeError):
    """Raised when *IDN? works but no driver claims the reply. The app
    catches this and offers a manual driver dropdown, so an unrecognised
    instrument is an inconvenience rather than a dead end."""

    def __init__(self, idn):
        super().__init__(
            f"No driver matches this instrument.\n\n*IDN? returned:\n  {idn}\n\n"
            f"Pick a driver manually, or add one to drivers/ and register it "
            f"in drivers/registry.py."
        )
        self.idn = idn


def driver_for_idn(idn):
    """Return the driver class matching an *IDN? string, or None.

    Matching is a case-insensitive substring test against each driver's
    MODEL_IDS. Longer IDs are tried first so that a specific match like
    'MODEL 2611A' wins over a looser '2611' if both are registered.
    """
    if not idn:
        return None
    haystack = idn.upper()
    candidates = []
    for cls in KNOWN_DRIVERS:
        for model_id in cls.MODEL_IDS:
            if model_id.upper() in haystack:
                candidates.append((len(model_id), cls))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates[0][1]


def identify(transport):
    """Query the instrument on `transport` and build the right driver.

    Returns (driver_instance, idn_string).
    Raises UnknownInstrumentError if nothing matches.
    """
    idn = transport.query("*IDN?").strip()
    cls = driver_for_idn(idn)
    if cls is None:
        raise UnknownInstrumentError(idn)
    return cls(transport), idn


def all_driver_names():
    """Display names of every registered driver, for the manual-override
    dropdown shown when auto-detection fails."""
    return [cls.DISPLAY_NAME for cls in KNOWN_DRIVERS]


def driver_by_display_name(name):
    """Look up a driver class by its DISPLAY_NAME, for manual override."""
    for cls in KNOWN_DRIVERS:
        if cls.DISPLAY_NAME == name:
            return cls
    return None
