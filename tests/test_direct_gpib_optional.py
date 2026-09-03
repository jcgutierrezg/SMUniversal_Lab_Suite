"""Guards that direct GPIB-HS stays an explicit, optional path.

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

from core.transports.ni_gpib_usb_hs_transport import NIUSBGPIBTransport

ROOT = Path(__file__).resolve().parent.parent
# The suite deliberately stubs transport discovery in some test groups so an
# offline run cannot touch bench hardware. Capture the production descriptor at
# collection time; tests that specifically exercise direct discovery restore it
# only inside a tightly scoped patch context.
_REAL_DIRECT_LIST_AVAILABLE = \
    NIUSBGPIBTransport.__dict__["list_available"].__func__


def test_direct_dependency_is_optional_not_a_normal_install():
    """A normal ``uv sync`` must not install the experimental backend."""
    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    normal = {re.split(r"[<>=!~\[; ]", spec, maxsplit=1)[0]
              for spec in project["dependencies"]}
    extras = project.get("optional-dependencies", {})
    direct = extras.get("direct-gpib", [])

    assert "ni-gpib-usb-hs" not in normal
    assert "ni-gpib-usb-hs==0.1.0" in direct, direct

    # Review A-11 added the USB layer to this extra, and the pin is the
    # part that matters: the transport reaches into the upstream
    # driver's private timeout fields, so an exact version is a
    # statement about a tested pairing rather than caution.
    assert not any(spec.startswith("ni-gpib-usb-hs")
                   and spec != "ni-gpib-usb-hs==0.1.0" for spec in direct)

    # It carries `usb` rather than assuming it. Selecting this transport
    # without PyUSB underneath would otherwise fail one level deeper
    # than the thing that was actually missing.
    assert "smuniversal-lab-suite[usb]" in direct, direct

    # And this extra is still not what a bench machine gets by default.
    assert not any("direct-gpib" in spec for spec in extras.get("bench", []))


def test_missing_optional_driver_fails_only_when_direct_connect_is_requested(
        monkeypatch):
    """Importing the transport stays cheap; connect gives the install hint."""
    def missing(_name):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(
        "core.transports.ni_gpib_usb_hs_transport.importlib.metadata.version",
        missing,
    )

    transport = NIUSBGPIBTransport()
    with pytest.raises(RuntimeError, match="uv sync --extra direct-gpib"):
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
    from core.gui import connection_panel

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
    from core.gui import connection_panel

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
    assert app.conn_widgets["source"]["address_combo"].values == \
        NIUSBGPIBTransport.address_choices()


def test_checkup_never_infers_the_direct_backend():
    """A GPIB resource without --transport must keep using VISA."""
    from tools import smu_checkup

    assert smu_checkup.TRANSPORTS["gpib-hs"] is NIUSBGPIBTransport
    assert smu_checkup.inferred_transport("GPIB0::26::INSTR") == "visa"
    assert smu_checkup.inferred_transport("USB0::1::INSTR") == "visa"
    assert smu_checkup.inferred_transport("COM3") is None
