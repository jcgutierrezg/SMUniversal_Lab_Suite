"""
Opt-in direct transport for a genuine NI GPIB-USB-HS (USB 3923:709b).

This is deliberately NOT part of VisaTransport's backend fallthrough.
Selecting it means "talk to this adapter directly through PyUSB/libusb",
which is a different hardware stack and must never replace VISA silently.
The third-party driver is imported only by connect(), so a normal install
and normal application startup do not require it.

The upstream 0.1.0 API covers the request/response subset this suite needs:
primary GPIB addressing plus command/write/read. It does not implement
secondary addressing, serial poll, SRQ, parallel poll, or multi-controller
sharing. Windows use is a commissioning item in docs/open/ because upstream
currently advertises macOS/Linux rather than Windows.
"""
from __future__ import annotations

import importlib.metadata
import threading

from .base import Transport, gpib_connection_key, parse_gpib_resource

NI_VID = 0x3923
NI_GPIB_USB_HS_PID = 0x709B
_DRIVER_VERSION = "0.1.0"
_INSTALL_HINT = "uv sync --extra direct-gpib"
# IEEE-488 command bytes used only for selected device clear.
_UNL = 0x3F
_SDC = 0x04
# NI USB-GPIB wire operation used by linux-gpib's interface-clear path.
# Upstream ni-gpib-usb-hs 0.1.0 initialises the TNT4882 but does not pulse
# IFC; on Windows that left a genuine GPIB-USB-HS returning NO_BUS until
# this IBSIC transaction was sent.
_IBSIC_PACKET = bytes((0x0F, 0x00, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00))
_IBSIC_RESPONSE_LENGTH = 12
_USB_BULK_OUT = 0x02
_USB_BULK_IN = 0x84
_USB_CONTROL_TIMEOUT_MS = 1000
_USB_FIND_PATCH_LOCK = threading.Lock()


class NIUSBGPIBTransport(Transport):
    """Direct, explicitly selected NI GPIB-USB-HS transport."""

    LAST_SCAN = []

    def __init__(self):
        super().__init__()
        self.address = None
        self.gpib_address = None
        self.controller_pad = 0
        self.serial = None
        self.timeout_ms = 20000
        self.read_length = 65535
        self.write_termination = "\n"
        self._controller = None
        self._controller_factory = None
        self._timeout_code = None

    def connection_key(self):
        """Use the same physical GPIB identity as VisaTransport."""
        key = gpib_connection_key(self.address)
        return key if key is not None else super().connection_key()

    @staticmethod
    def _address_parts(address):
        parsed = parse_gpib_resource(address)
        if parsed is None:
            raise ValueError(
                "Direct GPIB-USB-HS expects GPIB0::<address>::INSTR, "
                f"got {address!r}")
        board, primary, secondary = parsed
        if board != 0:
            raise ValueError(
                "Direct GPIB-USB-HS exposes one controller as GPIB0; "
                f"got board GPIB{board}")
        if secondary is not None:
            raise ValueError(
                "ni-gpib-usb-hs 0.1.0 does not support secondary GPIB "
                f"addresses; got {address!r}")
        if not 0 <= primary <= 30:
            raise ValueError(f"GPIB primary address must be 0..30, got {primary}")
        return board, primary

    @staticmethod
    def _load_driver():
        """Load the optional dependency and force the bundled libusb backend.

        ni-gpib-usb-hs 0.1.0 calls usb.core.find() without a backend
        argument. On Windows that can miss the DLL carried by
        libusb-package. The small factory below supplies that backend only
        while the controller constructor runs, then restores PyUSB's global
        function immediately.
        """
        try:
            found = importlib.metadata.version("ni-gpib-usb-hs")
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError(
                "Direct GPIB-USB-HS support is optional and is not installed. "
                f"Run: {_INSTALL_HINT}") from exc
        if found != _DRIVER_VERSION:
            raise RuntimeError(
                "Direct GPIB-USB-HS is pinned to ni-gpib-usb-hs "
                f"{_DRIVER_VERSION}; found {found}. Run: {_INSTALL_HINT}")

        try:
            import libusb_package
            import usb.core
            from ni_gpib_usb_hs import NIUSBGPIB
            from ni_gpib_usb_hs.controller import _timeout_code
        except ImportError as exc:
            raise RuntimeError(
                "Direct GPIB-USB-HS needs ni-gpib-usb-hs, PyUSB and "
                f"libusb-package. Run: {_INSTALL_HINT}") from exc

        backend = libusb_package.get_libusb1_backend()
        if backend is None:
            raise RuntimeError(
                "libusb-package could not provide a libusb-1.0 backend")

        def factory(**kwargs):
            # The upstream constructor resolves the USB device immediately.
            # Serialise this temporary PyUSB hook so two direct connection
            # attempts cannot restore each other's version of usb.core.find.
            with _USB_FIND_PATCH_LOCK:
                original_find = usb.core.find

                def find_with_bundled_libusb(*args, **find_kwargs):
                    find_kwargs.setdefault("backend", backend)
                    return original_find(*args, **find_kwargs)

                usb.core.find = find_with_bundled_libusb
                try:
                    return NIUSBGPIB(**kwargs)
                finally:
                    usb.core.find = original_find

        return factory, _timeout_code

    @staticmethod
    def _pulse_interface_clear(controller):
        """Pulse GPIB IFC through the adapter's NIUSB IBSIC operation.

        ni-gpib-usb-hs 0.1.0 performs the TNT4882 register initialisation
        but does not expose/interface-clear the bus. On a genuine
        GPIB-USB-HS under Windows/WinUSB that leaves command transfers
        returning NO_BUS. The linux-gpib reference driver sends IBSIC
        (0x0f) when a master controller is brought back up; the same packet
        was bench-proven to make UNL and *IDN? work on the Windows path.

        The upstream controller keeps its PyUSB Device as private state and
        does not publish a bulk-operation hook, so locate that Device by type
        rather than pinning another private attribute name. The package is
        already pinned exactly to 0.1.0 for the timeout compatibility shim.
        """
        import usb.core

        device = next(
            (value for value in vars(controller).values()
             if isinstance(value, usb.core.Device)),
            None,
        )
        if device is None:
            raise RuntimeError(
                "ni-gpib-usb-hs controller did not expose its PyUSB Device; "
                "the pinned 0.1.0 compatibility shim no longer matches")

        written = device.write(
            _USB_BULK_OUT,
            _IBSIC_PACKET,
            timeout=_USB_CONTROL_TIMEOUT_MS,
        )
        if int(written) != len(_IBSIC_PACKET):
            raise IOError(
                "GPIB-USB-HS IFC pulse wrote "
                f"{written} of {len(_IBSIC_PACKET)} USB bytes")

        response = bytes(device.read(
            _USB_BULK_IN,
            16,
            timeout=_USB_CONTROL_TIMEOUT_MS,
        ))
        if (len(response) != _IBSIC_RESPONSE_LENGTH or
                response[0] != 0x0F or
                response[-4:] != b"\x04\x00\x00\x00"):
            raise IOError(
                "Unexpected GPIB-USB-HS IFC response: " + response.hex(" "))

    def _new_controller(self):
        controller = self._controller_factory(
            my_pad=self.controller_pad,
            master=True,
            timeout_usec=int(self.timeout_ms * 1000),
            # The USB transfer must be allowed to outlive the GPIB timeout
            # long enough to collect the adapter's timeout status packet.
            usb_timeout_ms=max(1000, int(self.timeout_ms) + 1000),
            serial=self.serial,
        )
        try:
            # System-controller register state is not enough on the Windows
            # userspace path: pulse IFC so the adapter actually becomes CIC
            # before the first command/addressing transfer. Do this on every
            # reopen as well, because clear() reconstructs the controller.
            self._pulse_interface_clear(controller)
        except Exception:
            try:
                controller.close()
            except Exception:
                pass
            raise
        return controller

    def connect(self, address, timeout_ms=20000, write_termination="\n",
                serial=None, controller_pad=0, read_length=65535, **kwargs):
        """Open the direct adapter and target one primary GPIB address.

        ``address`` deliberately keeps VISA spelling so drivers, ownership,
        reports, and the operator all name the same physical endpoint.
        The transport supports only GPIB0 primary addressing because that is
        the scope of ni-gpib-usb-hs 0.1.0.
        """
        self.close()
        _, primary = self._address_parts(address)
        controller_pad = int(controller_pad)
        if not 0 <= controller_pad <= 30:
            raise ValueError(
                f"GPIB controller address must be 0..30, got {controller_pad}")
        if primary == controller_pad:
            raise ValueError(
                "Instrument GPIB address cannot equal the controller address "
                f"({controller_pad})")
        timeout_ms = int(timeout_ms)
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        read_length = int(read_length)
        if not 1 <= read_length <= 65535:
            raise ValueError("read_length must be 1..65535")

        factory, timeout_code = self._load_driver()
        self._controller_factory = factory
        self._timeout_code = timeout_code
        self.controller_pad = controller_pad
        self.serial = serial
        self.timeout_ms = timeout_ms
        self.read_length = read_length
        self.write_termination = write_termination

        try:
            controller = self._new_controller()
        except Exception as exc:
            self._controller_factory = None
            self._timeout_code = None
            detail = f"{type(exc).__name__}: {exc}"
            raise ConnectionError(
                "Could not open the NI GPIB-USB-HS directly. On Windows the "
                "adapter must be bound to WinUSB (for example with Zadig), "
                "not the NI driver. " + detail) from exc

        self._controller = controller
        # Preserve the selected adapter across timeout recovery when the
        # upstream driver could read its serial number.
        self.serial = getattr(controller, "serial", None) or serial
        self.gpib_address = primary
        self.address = str(address).strip().upper()
        self._begin_session()
        self.connected = True

    def close(self):
        controller = self._controller
        self._controller = None
        if controller is not None:
            try:
                controller.close()
            except Exception:
                pass
        self.connected = False

    def _write(self, text):
        payload = str(text)
        termination = self.write_termination
        if termination is not None and not payload.endswith(termination):
            payload += termination
        self._controller.write(self.gpib_address, payload, eoi=True)

    def _read(self, timeout_s):
        timeout_s = float(timeout_s)
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")

        controller = self._controller
        old_tcode = controller._tcode
        old_usb_ms = controller._usb_ms
        # 0.1.0 exposes timeout only at construction time. Its transfer
        # methods use these two fields, so temporarily changing them is the
        # narrow compatibility shim that keeps Transport._read's per-call
        # timeout contract. The dependency is pinned exactly because these
        # are private names.
        controller._tcode = self._timeout_code(int(timeout_s * 1_000_000))
        controller._usb_ms = max(1000, int(timeout_s * 1000) + 1000)
        try:
            raw = controller.read(self.gpib_address, self.read_length)
        finally:
            controller._tcode = old_tcode
            controller._usb_ms = old_usb_ms
        return raw.decode(errors="replace").rstrip("\r\n")

    def clear(self):
        """Reopen the adapter and send Selected Device Clear.

        Teardown housekeeping, and **not** a recovery for a
        desynchronised session - see `Transport.clear()`. It deliberately
        does not call `_begin_session()`: reopening the adapter is not a
        new session, because nothing has re-run the driver's reset() and
        the instrument's state is still unvouched for. Whether this
        sequence realigns a stream at all is an open question nobody has
        put to hardware.

        If either operation fails the transport is marked disconnected;
        pretending recovery succeeded would make later results unsafe.
        """
        with self.lock:
            if not self.connected or self._controller_factory is None:
                return False

            old = self._controller
            self._controller = None
            try:
                if old is not None:
                    old.close()
            except Exception:
                pass

            new_controller = None
            try:
                new_controller = self._new_controller()
                new_controller.command([
                    _UNL,
                    0x20 + self.gpib_address,  # listener address
                    _SDC,
                ])
            except Exception:
                if new_controller is not None:
                    try:
                        new_controller.close()
                    except Exception:
                        pass
                self.connected = False
                return False

            self._controller = new_controller
            self.connected = True
            return True

    @staticmethod
    def _probe_adapters():
        import libusb_package
        return list(libusb_package.find(
            find_all=True,
            idVendor=NI_VID,
            idProduct=NI_GPIB_USB_HS_PID,
        ))

    @classmethod
    def address_choices(cls):
        """Return valid primary-address candidates for the connection GUI.

        These are not discovery results. The direct backend can confirm that
        the USB controller is present, but it does not scan the IEEE-488 bus
        for occupied addresses. PAD 0 belongs to the controller, so offer the
        normal instrument primary-address range 1..30.
        """
        return tuple(f"GPIB0::{primary}::INSTR" for primary in range(1, 31))

    @classmethod
    def list_available(cls):
        """Probe only the USB adapter; never guess GPIB instrument addresses."""
        try:
            count = len(cls._probe_adapters())
        except Exception as exc:
            cls.LAST_SCAN = [f"direct adapter probe failed: {exc}"]
            return []

        if count:
            noun = "adapter" if count == 1 else "adapters"
            cls.LAST_SCAN = [
                f"{count} NI GPIB-USB-HS {noun} visible; type "
                "GPIB0::<address>::INSTR manually",
            ]
        else:
            cls.LAST_SCAN = [
                "no NI GPIB-USB-HS (3923:709b) visible through libusb; "
                "on Windows check the WinUSB binding",
            ]
        return []

    @classmethod
    def scan_summary(cls):
        return list(cls.LAST_SCAN)
