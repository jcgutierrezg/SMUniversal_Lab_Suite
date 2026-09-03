"""Deprecated home of the driver registry - moved to `drivers.registry`.

The registry imports every driver module, so while it lived under
`core/` the dependency ran core -> drivers, which is backwards: drivers
are meant to plug into the core, not the other way round. Anything
importing `core` dragged all seven driver modules in with it.

Moving the module fixes the direction of that import. The move is
the job: `LabApp` is now *handed* a registry (`LabApp(root, cls,
registry=...)`) and reaches it through `self.registry`, with the real
one as a default argument so `main.py` is unchanged. `core.gui.
connection_panel` goes through `app.registry` for the same reason.
Nothing in `core/` imports a driver module any more.

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
