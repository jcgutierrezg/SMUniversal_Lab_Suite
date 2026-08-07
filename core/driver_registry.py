"""Deprecated home of the driver registry - moved to `drivers.registry`.

The registry imports every driver module, so while it lived under
`core/` the dependency ran core -> drivers, which is backwards: drivers
are meant to plug into the core, not the other way round. Anything
importing `core` dragged all seven driver modules in with it.

Moving the module fixes the direction of that import. It does not yet
remove it - `core.base_app` still reaches for a registry directly. That
last step is constructor injection (the app is handed a registry rather
than importing one), which lands in Wave 1 alongside the instrument
ownership manager, because both change how `LabApp` is built.

This shim keeps older scripts working. New code should import from
`drivers.registry`.
"""
import warnings

from drivers.registry import (  # noqa: F401
    KNOWN_DRIVERS,
    UnknownInstrumentError,
    all_driver_names,
    driver_by_display_name,
    driver_for_idn,
    identify,
)

warnings.warn(
    "core.driver_registry has moved to drivers.registry; the old name "
    "will be removed once the experiments are migrated",
    DeprecationWarning,
    stacklevel=2,
)
