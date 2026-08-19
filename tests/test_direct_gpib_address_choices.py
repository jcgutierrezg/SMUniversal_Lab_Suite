"""Regression guards for the direct GPIB-HS manual-address picker.

The direct backend discovers the USB controller, not occupied IEEE-488
addresses. The GUI must therefore distinguish discovered resources from valid
manual address candidates instead of presenting an empty combobox.
"""

from core.gui import connection_panel
from core.transports.ni_gpib_usb_hs_transport import NIUSBGPIBTransport


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Combo:
    def __init__(self):
        self.values = ()

    def __setitem__(self, key, value):
        assert key == "values"
        self.values = tuple(value)


class _App:
    def __init__(self):
        self.conn_widgets = {
            "source": {
                "transport_var": _Var("candidate-test"),
                "address_var": _Var(""),
                "address_combo": _Combo(),
            }
        }
        self.lines = []

    def log(self, *parts):
        self.lines.append(" ".join(str(part) for part in parts))


def test_direct_gpib_address_choices_cover_primary_instrument_range():
    choices = NIUSBGPIBTransport.address_choices()

    assert choices == tuple(
        f"GPIB0::{primary}::INSTR" for primary in range(1, 31)
    )
    assert choices[8] == "GPIB0::9::INSTR"
    assert "GPIB0::0::INSTR" not in choices


def test_refresh_uses_manual_candidates_without_claiming_discovery(monkeypatch):
    candidates = ("GPIB0::1::INSTR", "GPIB0::9::INSTR")

    class CandidateTransport:
        @classmethod
        def list_available(cls):
            return []

        @classmethod
        def address_choices(cls):
            return candidates

        @classmethod
        def scan_summary(cls):
            return []

    monkeypatch.setitem(
        connection_panel.TRANSPORTS, "candidate-test", CandidateTransport
    )
    app = _App()

    connection_panel._refresh(app, "source")

    assert app.conn_widgets["source"]["address_combo"].values == candidates
    assert app.conn_widgets["source"]["address_var"].get() == ""
    assert "[source] 0 address(es) available" in app.lines
