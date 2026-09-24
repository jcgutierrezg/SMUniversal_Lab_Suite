"""Guards that direct GPIB-HS stays an explicit, never-automatic path.

Its driver is installed on every machine now, like every instrument's
library. Installed is not selected: the transport is used only when it
is picked by hand, and nothing probes it on the way.

These are separate from test_ni_gpib_usb_hs_transport.py on purpose: that
file asks whether the transport moves bytes correctly; this one asks whether
the application can accidentally select, install, or probe it.
"""
import importlib.metadata
import re
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from smuniversal_lab_suite.core import addresses
from smuniversal_lab_suite.core.transports.ni_gpib_usb_hs_transport import (
    NIUSBGPIBTransport,
)

ROOT = Path(__file__).resolve().parent.parent
# The suite deliberately stubs transport discovery in some test groups so an
# offline run cannot touch bench hardware. Capture the production descriptor at
# collection time; tests that specifically exercise direct discovery restore it
# only inside a tightly scoped patch context.
_REAL_DIRECT_LIST_AVAILABLE = \
    NIUSBGPIBTransport.__dict__["list_available"].__func__


def test_the_direct_driver_is_installed_and_pinned():
    """Part of the one install, and pinned to the tested version.

    The pin is the part that matters: the transport reaches into the
    upstream driver's private timeout fields, so an exact version is a
    statement about a tested pairing rather than caution. It needs PyUSB
    underneath, and that is in the one install too.
    """
    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    normal = {re.split(r"[<>=!~\[; ]", spec, maxsplit=1)[0]: spec
              for spec in project["dependencies"]}

    assert normal.get("ni-gpib-usb-hs") == "ni-gpib-usb-hs==0.1.0", normal
    assert "pyusb" in normal, normal


def test_missing_optional_driver_fails_only_when_direct_connect_is_requested(
        monkeypatch):
    """Importing the transport stays cheap; connect gives the install hint."""
    def missing(_name):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(
        "smuniversal_lab_suite.core.transports.ni_gpib_usb_hs_transport.importlib.metadata.version",
        missing,
    )

    transport = NIUSBGPIBTransport()
    with pytest.raises(RuntimeError, match="uv sync"):
        transport.connect("GPIB0::26::INSTR")

    assert transport.connected is False


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Combo:
    def __init__(self, values=()):
        self.values = tuple(values)

    def __setitem__(self, key, value):
        assert key == "values"
        self.values = tuple(value)


class _App:
    def __init__(self, transport_name, address=""):
        self.conn_widgets = {
            "source": {
                "transport_var": _Var(transport_name),
                "address_var": _Var(address),
                "address_combo": _Combo(("stale",)),
            }
        }
        self.lines = []

    def log(self, *parts):
        self.lines.append(" ".join(str(p) for p in parts))


def test_connection_panel_defaults_to_visa_and_does_not_probe_direct(monkeypatch):
    """Refreshing the normal path must not touch the USB-HS probe."""
    from smuniversal_lab_suite.core.gui import connection_panel

    assert connection_panel.DEFAULT_TRANSPORT == "VISA"
    assert connection_panel.TRANSPORTS["NI GPIB-HS"] is NIUSBGPIBTransport

    app = _App(connection_panel.DEFAULT_TRANSPORT)
    visa_calls = []

    monkeypatch.setattr(
        connection_panel.VisaTransport,
        "list_available",
        classmethod(lambda cls: visa_calls.append(cls) or ["GPIB0::26::INSTR"]),
    )
    monkeypatch.setattr(
        connection_panel.VisaTransport,
        "scan_summary",
        classmethod(lambda cls: []),
    )

    with (
        patch.object(
            NIUSBGPIBTransport,
            "list_available",
            classmethod(_REAL_DIRECT_LIST_AVAILABLE),
        ),
        patch.object(
            NIUSBGPIBTransport,
            "_probe_adapters",
            staticmethod(lambda: pytest.fail(
                "direct GPIB-HS USB probe ran while VISA was selected")),
        ),
    ):
        connection_panel._refresh(app, "source")

    assert len(visa_calls) == 1
    assert app.conn_widgets["source"]["address_var"].get() == \
        "GPIB0::26::INSTR"


def test_selecting_direct_backend_is_the_explicit_probe_point():
    """The USB probe runs only after the operator selects NI GPIB-HS."""
    from smuniversal_lab_suite.core.gui import connection_panel

    calls = []
    app = _App("NI GPIB-HS", "GPIB0::5::INSTR")
    with (
        patch.object(
            NIUSBGPIBTransport,
            "list_available",
            classmethod(_REAL_DIRECT_LIST_AVAILABLE),
        ),
        patch.object(NIUSBGPIBTransport, "LAST_SCAN", []),
        patch.object(
            NIUSBGPIBTransport,
            "_probe_adapters",
            staticmethod(lambda: calls.append(True) or [object()]),
        ),
    ):
        connection_panel._transport_changed(app, "source")

    assert calls == [True]
    assert app.conn_widgets["source"]["address_var"].get() == ""
    # The candidates, labelled by `core/addresses.py` - this bench has
    # instruments on four of the thirty primary addresses.
    assert list(app.conn_widgets["source"]["address_combo"].values) == \
        addresses.filtered(NIUSBGPIBTransport.address_choices())[0]


def test_checkup_never_infers_the_direct_backend():
    """A GPIB resource without --transport must keep using VISA."""
    from tools import smu_checkup

    assert smu_checkup.TRANSPORTS["gpib-hs"] is NIUSBGPIBTransport
    assert smu_checkup.inferred_transport("GPIB0::26::INSTR") == "visa"
    assert smu_checkup.inferred_transport("USB0::1::INSTR") == "visa"
    assert smu_checkup.inferred_transport("COM3") is None
