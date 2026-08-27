"""
Adapter transport for the Undalogic miniSMU MS01.

Every other transport in this package moves *text*: the driver hands
down a string, the transport puts it on a wire, a string comes back.
The miniSMU doesn't offer that interface. Its documented control path is
a Python library, `minismu_py`, which opens the serial port or the TCP
socket itself and exposes the instrument as method calls.

So there is nothing here for `SerialTransport` to do, and no string for
`VisaTransport` to send.

Why adapt rather than reimplement
---------------------------------
The instrument does speak a SCPI-style protocol underneath - the spec
sheet says so, and the library's source shows the spellings
(`SOUR1:VOLT 1.0`, `MEAS1:VOLT:CURR?`, `SOUR1:SWEEP:EXECUTE`). Writing a
native text driver against those is possible.

It would also be a mistake. Those spellings are not published as a
command reference; they are an implementation detail of a library that
is still changing. And the library carries hard-won handling this
codebase would have to reproduce: chunked USB reads, JSON responses that
arrive fragmented over TCP, a firmware-dependent command terminator
(1.4.6+ requires LF, earlier tolerates either), and detection of sweep
data truncated by the firmware's ~5.7 kB TCP response limit. Its 0.4.0
release fixed CSV sweep retrieval returning a single point, sweep
completion polling that could exit early or spin forever, and device
errors being silently swallowed. Reimplementing that from a README is
how you get all of those bugs back.

What this class is
------------------
The thinnest possible shim that lets the rest of the app treat the
miniSMU like any other instrument. It satisfies the *lifecycle* half of
the Transport contract - connect, close, is_connected, list_available -
and holds the library object as `.client`, which
`drivers/undalogic_minismu.py` calls directly.

The text half is deliberately not implemented. `_write` and `_read`
raise, because a silent no-op there would be a driver appearing to
configure an instrument that never heard it. The single exception is
`*IDN?`, which is mapped to `client.get_identity()` - that is what lets
`drivers/registry.identify()` auto-detect the miniSMU through
exactly the same path as every other instrument, instead of the app
needing a special case for it.

This is the same judgement as `devices/temperature_control.py`: hardware
that doesn't fit the abstraction gets its own shape rather than the
abstraction being bent to fit it. The difference is that the miniSMU is
a real SMU and experiments must be able to drive it, so it still needs
to arrive as a driver.
"""
from .base import Transport

# Imported lazily in connect(), so the suite - and every experiment that
# never touches a miniSMU - runs without the library installed.
try:
    from serial.tools import list_ports
except ImportError:
    list_ports = None

# The library version this driver was written against. Below this,
# sweeps and error reporting behave differently enough to matter.
MINIMUM_LIBRARY_VERSION = (0, 4, 0)

DEFAULT_TCP_PORT = 3333


class MiniSMUTransport(Transport):
    """Owns a `minismu_py.SMU` and exposes it as `.client`.

    Address forms:
        "COM3", "/dev/ttyACM0"      -> USB
        "192.168.1.106"             -> WiFi, default TCP port
        "192.168.1.106:3333"        -> WiFi, explicit port
    """

    def __init__(self):
        super().__init__()
        self.client = None
        self.address = None
        self.is_network = False

    # ---- address handling ----
    @staticmethod
    def looks_like_host(address):
        """True when an address should be read as a network host.

        Deliberately narrow: a dotted quad, optionally with a port. A
        serial port name never looks like this, on Windows or on Linux,
        so the two cases can't be confused - which matters because
        guessing wrong means trying to open a TCP socket to "COM3" and
        reporting a network error for a cable problem.
        """
        host = str(address).strip().split(":")[0]
        parts = host.split(".")
        if len(parts) != 4:
            return False
        for part in parts:
            if not part.isdigit() or not 0 <= int(part) <= 255:
                return False
        return True

    def connect(self, address, **kwargs):
        """Open the instrument. `address` is a serial port or an IP."""
        try:
            from minismu_py import SMU, ConnectionType
            import minismu_py
        except ImportError as exc:
            raise RuntimeError(
                "minismu_py is not installed. Run: uv add minismu_py"
            ) from exc

        version = getattr(minismu_py, "__version__", "0.0.0")
        if _version_tuple(version) < MINIMUM_LIBRARY_VERSION:
            # Not a hard failure - an older library still works for
            # simple sourcing - but the sweep paths this driver relies
            # on were unreliable before 0.4.0, so say so once, loudly,
            # rather than let it look like an instrument fault later.
            raise RuntimeError(
                f"minismu_py {version} is too old; this driver needs "
                f"{'.'.join(str(n) for n in MINIMUM_LIBRARY_VERSION)} or "
                f"later. Earlier versions returned only the first point of a "
                f"CSV sweep and could exit sweep polling early. "
                f"Run: uv add 'minismu_py>=0.4.0'")

        self.close()
        address = str(address).strip()
        self.is_network = self.looks_like_host(address)

        if self.is_network:
            host, _, port = address.partition(":")
            self.client = SMU(
                ConnectionType.NETWORK, host=host,
                tcp_port=int(port) if port else DEFAULT_TCP_PORT)
        else:
            self.client = SMU(ConnectionType.USB, port=address)

        self.address = address
        self._begin_session()
        self.connected = True

    def close(self):
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
        self.client = None
        self.connected = False

    # ---- the text half, which does not apply here ----
    def _write(self, text):
        raise NotImplementedError(
            "MiniSMUTransport carries method calls, not text. Use "
            "transport.client.<method>() from the driver.")

    def _read(self, timeout_s):
        raise NotImplementedError(
            "MiniSMUTransport carries method calls, not text.")

    def query(self, text, timeout_s=3.0):
        """Only `*IDN?` is answered, and only so that the registry's
        auto-detection works unchanged.

        Everything else raises rather than returning something
        plausible: a driver that thinks it queried an instrument and got
        an empty string back is worse off than one that crashed.
        """
        if str(text).strip().upper().rstrip(";") != "*IDN?":
            raise NotImplementedError(
                f"MiniSMUTransport cannot query {text!r}. Only '*IDN?' is "
                f"mapped, for driver auto-detection; everything else goes "
                f"through transport.client.")
        if self.client is None:
            raise ConnectionError("Not connected")
        with self.lock:
            return self.client.get_identity()

    # ---- discovery ----
    @staticmethod
    def list_available():
        """Serial ports, for the address dropdown.

        Network addresses can't be enumerated from here - the desktop
        app finds them by LAN broadcast, which is out of scope. Typing
        the IP works.
        """
        if list_ports is None:
            return []
        return [port.device for port in list_ports.comports()]


def _version_tuple(text):
    """'0.4.0' -> (0, 4, 0). Unparseable parts become 0."""
    parts = []
    for chunk in str(text).split(".")[:3]:
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)
