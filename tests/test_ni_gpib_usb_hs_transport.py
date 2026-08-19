"""Offline contract tests for the opt-in direct GPIB-USB-HS path."""
import sys
from types import ModuleType
from unittest.mock import patch

from core.transports.ni_gpib_usb_hs_transport import NIUSBGPIBTransport
from core.transports.visa_transport import VisaTransport

# See test_direct_gpib_optional.py: the suite may stub public discovery methods
# to keep ordinary tests off real hardware. Preserve the production method so
# this transport-level contract test can exercise it in a local patch context.
_REAL_DIRECT_LIST_AVAILABLE = \
    NIUSBGPIBTransport.__dict__["list_available"].__func__


class FakeController:
    def __init__(self, serial="ABC", **kwargs):
        self.serial = serial
        self.kwargs = dict(kwargs, serial=serial)
        self._tcode = "connect-timeout"
        self._usb_ms = 21000
        self.writes = []
        self.reads = []
        self.commands = []
        self.ifc_pulses = 0
        self.closed = False

    def write(self, addr, data, eoi=True):
        self.writes.append((addr, data, eoi))

    def read(self, addr, length):
        self.reads.append((addr, length, self._tcode, self._usb_ms))
        return b"KEITHLEY INSTRUMENTS INC.,MODEL 2611A\n"

    def command(self, data):
        self.commands.append(list(data))

    def close(self):
        self.closed = True


def _install_fake(monkeypatch):
    made = []

    def factory(**kwargs):
        controller = FakeController(**kwargs)
        made.append(controller)
        return controller

    monkeypatch.setattr(
        NIUSBGPIBTransport,
        "_load_driver",
        staticmethod(lambda: (factory, lambda usec: f"timeout:{usec}")),
    )
    monkeypatch.setattr(
        NIUSBGPIBTransport,
        "_pulse_interface_clear",
        staticmethod(lambda controller: setattr(
            controller, "ifc_pulses", controller.ifc_pulses + 1)),
    )
    return made


def test_direct_transport_accepts_only_supported_primary_resource():
    assert NIUSBGPIBTransport._address_parts("gpib0::26::instr") == (0, 26)

    for address in (
            "GPIB1::26::INSTR",
            "GPIB0::26::96::INSTR",
            "GPIB0::31::INSTR",
            "USB0::1::INSTR"):
        try:
            NIUSBGPIBTransport._address_parts(address)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{address!r} should have been refused")


def test_connect_write_read_and_per_call_timeout(monkeypatch):
    made = _install_fake(monkeypatch)
    transport = NIUSBGPIBTransport()
    transport.connect("GPIB0::26::INSTR")

    assert transport.connected
    assert transport.address == "GPIB0::26::INSTR"
    assert made[0].kwargs["my_pad"] == 0
    assert made[0].kwargs["timeout_usec"] == 20_000_000
    assert made[0].ifc_pulses == 1

    assert transport.query("*IDN?", timeout_s=2.5).startswith("KEITHLEY")
    assert made[0].writes == [(26, "*IDN?\n", True)]
    assert made[0].reads == [(26, 65535, "timeout:2500000", 3500)]
    # The compatibility shim must not leak the per-call timeout into the
    # next operation.
    assert made[0]._tcode == "connect-timeout"
    assert made[0]._usb_ms == 21000


def test_clear_reopens_same_adapter_and_sends_selected_device_clear(monkeypatch):
    made = _install_fake(monkeypatch)
    transport = NIUSBGPIBTransport()
    transport.connect("GPIB0::26::INSTR", serial="ABC")
    first = made[0]

    assert transport.clear() is True
    assert first.closed is True
    assert len(made) == 2
    assert made[1].kwargs["serial"] == "ABC"
    assert made[1].ifc_pulses == 1
    assert made[1].commands == [[0x3F, 0x20 + 26, 0x04]]
    assert transport.connected is True


def test_failed_clear_marks_transport_disconnected(monkeypatch):
    made = _install_fake(monkeypatch)
    transport = NIUSBGPIBTransport()
    transport.connect("GPIB0::26::INSTR")

    def broken_factory(**kwargs):
        raise RuntimeError("USB reopen failed")

    transport._controller_factory = broken_factory
    assert transport.clear() is False
    assert made[0].closed is True
    assert transport.connected is False



def test_interface_clear_uses_bench_proven_ibsic_transaction(monkeypatch):
    class FakeUSBDevice:
        def __init__(self):
            self.writes = []
            self.reads = []

        def write(self, endpoint, payload, timeout):
            self.writes.append((endpoint, bytes(payload), timeout))
            return len(payload)

        def read(self, endpoint, length, timeout):
            self.reads.append((endpoint, length, timeout))
            return bytes.fromhex("0f 00 30 00 ff ff ff ff 04 00 00 00")

    class Controller:
        pass

    usb_module = ModuleType("usb")
    core_module = ModuleType("usb.core")
    core_module.Device = FakeUSBDevice
    usb_module.core = core_module
    monkeypatch.setitem(sys.modules, "usb", usb_module)
    monkeypatch.setitem(sys.modules, "usb.core", core_module)

    controller = Controller()
    controller._private_usb_handle = FakeUSBDevice()

    NIUSBGPIBTransport._pulse_interface_clear(controller)

    assert controller._private_usb_handle.writes == [(
        0x02,
        bytes.fromhex("0f 00 00 00 04 00 00 00"),
        1000,
    )]
    assert controller._private_usb_handle.reads == [(0x84, 16, 1000)]


def test_interface_clear_failure_closes_new_controller(monkeypatch):
    made = []

    def factory(**kwargs):
        controller = FakeController(**kwargs)
        made.append(controller)
        return controller

    monkeypatch.setattr(
        NIUSBGPIBTransport,
        "_load_driver",
        staticmethod(lambda: (factory, lambda usec: f"timeout:{usec}")),
    )
    monkeypatch.setattr(
        NIUSBGPIBTransport,
        "_pulse_interface_clear",
        staticmethod(lambda controller: (_ for _ in ()).throw(
            RuntimeError("IFC failed"))),
    )

    transport = NIUSBGPIBTransport()
    try:
        transport.connect("GPIB0::9::INSTR")
    except ConnectionError as exc:
        assert "IFC failed" in str(exc)
    else:
        raise AssertionError("failed IFC must fail the connection")

    assert len(made) == 1
    assert made[0].closed is True
    assert transport.connected is False

def test_direct_discovery_probes_adapter_without_inventing_gpib_addresses():
    calls = []
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
        # The discovery contract is deliberately narrow: probe the USB adapter,
        # but never fabricate occupied GPIB instrument addresses.
        assert NIUSBGPIBTransport.list_available() == []
        assert NIUSBGPIBTransport.LAST_SCAN == [
            "1 NI GPIB-USB-HS adapter visible; type "
            "GPIB0::<address>::INSTR manually",
        ]
    assert calls == [True]


def test_visa_and_direct_gpib_share_the_same_ownership_key():
    visa = VisaTransport()
    visa.address = "GPIB0::26::INSTR"
    direct = NIUSBGPIBTransport()
    direct.address = "gpib0::26::instr"

    assert visa.connection_key() == "GPIB:0:26"
    assert direct.connection_key() == visa.connection_key()


def test_non_gpib_visa_identity_keeps_transport_qualification():
    visa = VisaTransport()
    visa.address = "TCPIP0::192.0.2.10::INSTR"
    assert visa.connection_key() == \
        "VisaTransport:TCPIP0::192.0.2.10::INSTR"
