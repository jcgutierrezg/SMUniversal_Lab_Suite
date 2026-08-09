import sys, os

"""Multi-backend VISA handling.

The bug this exists to prevent: an instrument that is plugged in,
powered on and working does not appear in the address dropdown, because
the backend the app happened to use cannot see it. The Keysight U2722A
is the live example - a USB modular instrument that a vendor VISA
library will not necessarily enumerate, and whose original script forced
`ResourceManager('@py')` with two Keysight DLL paths commented out
beside it.

There are four ways for a resource to go missing and they need different
fixes, so they are tested separately:

  - only one backend can see it              -> merge the listings
  - one backend is broken or absent entirely -> keep going, report why
  - it enumerates as ::RAW, not ::INSTR      -> widen the list pattern
  - a backend can see it but not open it     -> fall through at connect

pyvisa is faked, so this runs anywhere. The point is the merging and
fallback logic, not pyvisa itself.
"""
import pytest

import core.transports.visa_transport as vt
from core.transports.visa_transport import VisaTransport, VisaPyTransport

# Captured before anything in this file runs, and it has to be: the
# first call to VisaPyTransport.list_available() assigns cls.LAST_SCAN
# and thereby *creates* the separate cache, so after that point the
# declaration and its absence are indistinguishable. In a fresh process
# - which is what the app is - the declaration is the only thing
# keeping the two apart until the subclass is first refreshed.
PY_DECLARES_OWN_CACHE = "LAST_SCAN" in VisaPyTransport.__dict__


class FakeResource:
    def __init__(self, name):
        self.name = name
        self.timeout = 0
        self.read_termination = None
        self.write_termination = None
        self.closed = False

    def close(self):
        self.closed = True


class FakeRM:
    """One backend's view of the world."""

    def __init__(self, resources, openable=None, reject_wide_pattern=False):
        self.resources = resources
        self.openable = resources if openable is None else openable
        self.reject_wide_pattern = reject_wide_pattern
        self.closed = False
        self.visalib = "fake"

    def list_resources(self, pattern="?*::INSTR"):
        if pattern == "?*" and self.reject_wide_pattern:
            raise ValueError("this implementation rejects '?*'")
        if pattern == "?*":
            return tuple(self.resources)
        return tuple(r for r in self.resources if r.upper().endswith("INSTR"))

    def open_resource(self, address):
        if address not in self.openable:
            raise OSError(f"cannot open {address}")
        return FakeResource(address)

    def close(self):
        self.closed = True


class FakePyvisa:
    def __init__(self, per_backend):
        self.per_backend = per_backend      # spec -> FakeRM or Exception
        self.asked = []

    def ResourceManager(self, spec=""):
        self.asked.append(spec)
        entry = self.per_backend.get(spec)
        if entry is None:
            raise ValueError(f"no backend {spec!r}")
        if isinstance(entry, Exception):
            raise entry
        return entry


def install(per_backend):
    """Swap in a fake pyvisa and reset cached scans."""
    fake = FakePyvisa(per_backend)
    vt.pyvisa = fake
    VisaTransport.LAST_SCAN = []
    # Only reset the subclass's cache if it genuinely has one of its
    # own. Assigning unconditionally would *create* the separate cache
    # that the code under test is supposed to declare, which would make
    # this fixture hide the very bug it is here to expose.
    if "LAST_SCAN" in VisaPyTransport.__dict__:
        VisaPyTransport.LAST_SCAN = []
    return fake


real_pyvisa = vt.pyvisa

# This file *is* the test of `list_available()`, so it opts out of the
# conftest stub that stops every other test reaching for real hardware.
# It still never touches a network: `install()` swaps in a fake pyvisa
# before anything is asked. See `_no_instrument_discovery` in
# `tests/conftest.py`.
pytestmark = [pytest.mark.instrument_discovery]

# ---------------------------------------------------------------
# A. the U2722A case: only pyvisa-py can see it
# ---------------------------------------------------------------


def test_merges_backends(check):
    fake = install({
        "": FakeRM(["GPIB0::25::INSTR"]),
        "@py": FakeRM(["USB0::0x0957::0x4118::MY62030002::INSTR",
                       "TCPIP0::192.168.0.10::INSTR"]),
    })
    found = VisaTransport.list_available()
    check("both backends were asked", fake.asked == ["", "@py"], f"{fake.asked}")
    check("the GPIB instrument the vendor backend sees is listed",
          "GPIB0::25::INSTR" in found)
    check("and the U2722A only pyvisa-py sees is listed too",
          "USB0::0x0957::0x4118::MY62030002::INSTR" in found,
          "this is the whole bug: it was plugged in and missing from the "
          "dropdown")
    check("everything appears exactly once", len(found) == len(set(found)))

    summary = VisaTransport.scan_summary()
    check("the console breakdown names each backend",
          any(line.startswith("default:") for line in summary)
          and any(line.startswith("@py:") for line in summary), f"{summary}")

    # duplicates across backends collapse
    install({"": FakeRM(["GPIB0::25::INSTR"]),
             "@py": FakeRM(["GPIB0::25::INSTR"])})
    check("a resource both backends see is listed once",
          VisaTransport.list_available() == ["GPIB0::25::INSTR"])

    # ---------------------------------------------------------------
    # B. a broken backend must not take the others down
    # ---------------------------------------------------------------


def test_broken_backend_is_survivable(check):
    install({
        "": ImportError("Could not locate a VISA implementation"),
        "@py": FakeRM(["USB0::0x0957::0x4118::MY62030002::INSTR"]),
    })
    found = VisaTransport.list_available()
    check("the working backend's instruments still list",
          found == ["USB0::0x0957::0x4118::MY62030002::INSTR"], f"{found}")
    summary = VisaTransport.scan_summary()
    check("and the failure is reported rather than swallowed",
          any("unavailable" in line and "VISA implementation" in line
              for line in summary),
          f"{summary}")

    install({"": ImportError("no VISA"), "@py": ImportError("no pyvisa-py")})
    check("no backends at all gives an empty list, not a crash",
          VisaTransport.list_available() == [])
    check("with both failures explained",
          len(VisaTransport.scan_summary()) == 2)

    # ---------------------------------------------------------------
    # C. ::RAW resources hidden by the default pattern
    # ---------------------------------------------------------------


def test_raw_resources_are_found(check):
    install({"": FakeRM(["USB0::0x0957::0x4118::MY62030002::RAW"]),
             "@py": FakeRM([])})
    found = VisaTransport.list_available()
    check("a ::RAW instrument is listed",
          found == ["USB0::0x0957::0x4118::MY62030002::RAW"],
          "pyvisa's default '?*::INSTR' filter would have hidden it")

    # some implementations reject the wide pattern; that must not lose the
    # narrow one's results
    install({"": FakeRM(["GPIB0::25::INSTR"], reject_wide_pattern=True),
             "@py": FakeRM([])})
    check("a backend that rejects '?*' still contributes its ::INSTR list",
          VisaTransport.list_available() == ["GPIB0::25::INSTR"])

    # ---------------------------------------------------------------
    # D. connect falls through to whichever backend can open it
    # ---------------------------------------------------------------


def test_connect_falls_through(check):
    global address
    address = "USB0::0x0957::0x4118::MY62030002::INSTR"
    install({"": FakeRM([address], openable=[]),      # sees it, cannot open it
             "@py": FakeRM([address])})
    t = VisaTransport()
    t.connect(address)
    check("connecting succeeds via the second backend", t.connected)
    check("and the transport records which one worked", t.backend == "@py",
          f"{t.backend}")
    t.close()
    check("closing clears the recorded backend", t.backend is None)

    install({"": FakeRM([address]), "@py": FakeRM([address])})
    t = VisaTransport()
    t.connect(address)
    check("when the default works it is used, and pyvisa-py is not consulted",
          t.backend == "default")
    t.close()

    # an explicit pin skips the search entirely
    fake = install({"": FakeRM([address]), "@py": FakeRM([address])})
    t = VisaTransport()
    t.connect(address, backend="@py")
    check("pinning a backend uses only that one",
          t.backend == "@py" and fake.asked == ["@py"], f"{fake.asked}")
    t.close()

    # total failure explains itself
    install({"": FakeRM([address], openable=[]),
             "@py": FakeRM([address], openable=[])})
    t = VisaTransport()
    message = ""
    try:
        t.connect(address)
    except ConnectionError as exc:
        message = str(exc)
    check("failing on every backend raises", bool(message))
    check("and the message names each backend and its own error",
          "default" in message and "@py" in message and "cannot open" in message,
          f"got {message!r}")

    # ---------------------------------------------------------------
    # E. the pinned pyvisa-py transport
    # ---------------------------------------------------------------


def test_pyvisa_py_transport(check):
    check("it is a VisaTransport", issubclass(VisaPyTransport, VisaTransport))
    check("pinned to one backend", VisaPyTransport.BACKENDS == ("@py",))

    fake = install({"": FakeRM(["GPIB0::25::INSTR"]),
                    "@py": FakeRM([address])})
    found = VisaPyTransport.list_available()
    check("it lists only what pyvisa-py sees", found == [address], f"{found}")
    check("the vendor backend is never asked", fake.asked == ["@py"],
          "this is the escape hatch for a backend that opens an instrument "
          "and then misbehaves")

    fake = install({"": FakeRM([address]), "@py": FakeRM([address])})
    t = VisaPyTransport()
    t.connect(address)
    check("and connect goes straight to pyvisa-py",
          t.backend == "@py" and fake.asked == ["@py"])
    t.close()

    # The two classes must not share the cached scan. This matters in one
    # specific order: refresh under "VISA", then switch the dropdown to
    # "VISA (pyvisa-py)" and read the summary before refreshing again.
    # Without its own cache the subclass inherits the parent's, and the
    # console then reports the vendor backend's findings under the heading
    # of a transport that never consults it - a wrong answer that looks
    # exactly like a right one.
    check("the pinned transport declares its own cache in the class body",
          PY_DECLARES_OWN_CACHE,
          "without it, a fresh process reports the vendor backend's "
          "findings under the pyvisa-py transport until it is refreshed")

    install({"": FakeRM(["GPIB0::25::INSTR"]), "@py": FakeRM([address])})
    if "LAST_SCAN" in VisaPyTransport.__dict__ and not PY_DECLARES_OWN_CACHE:
        del VisaPyTransport.LAST_SCAN       # undo what an earlier call created
    VisaTransport.list_available()          # populate the parent only
    summary = VisaPyTransport.scan_summary()
    check("the pinned transport reports only pyvisa-py, even when the "
          "parent scanned first",
          all(not line.startswith("default:") for line in summary), f"{summary}")
    check("and it does report pyvisa-py's own findings",
          any(address in line for line in summary), f"{summary}")
    check("each transport keeps its own scan cache",
          VisaPyTransport.LAST_SCAN is not VisaTransport.LAST_SCAN)

    # ---------------------------------------------------------------
    # F. the panel offers both
    # ---------------------------------------------------------------


def test_device_clear(check):
    class ClearableRM(FakeRM):
        pass


    class ClearableResource(FakeResource):
        def __init__(self, name):
            super().__init__(name)
            self.cleared = 0

        def clear(self):
            self.cleared += 1


    install({"": FakeRM([address]), "@py": FakeRM([address])})
    t = VisaTransport()
    t.connect(address)
    t.res = ClearableResource(address)
    check("a connected VISA transport can send a device clear",
          t.clear() is True)
    check("and it reached the resource", t.res.cleared == 1)
    t.close()
    check("clearing when disconnected reports False rather than raising",
          VisaTransport().clear() is False,
          "the checkup uses the return value to decide whether later "
          "failures can be trusted")


def test_panel_offers_both(check):
    vt.pyvisa = real_pyvisa
    from core.gui.connection_panel import TRANSPORTS
    check("the plain VISA entry is present",
          TRANSPORTS.get("VISA") is VisaTransport)
    check("and the pinned pyvisa-py one",
          TRANSPORTS.get("VISA (pyvisa-py)") is VisaPyTransport)
    check("every transport can be asked what is available",
          all(hasattr(cls, "list_available") for cls in TRANSPORTS.values()))
