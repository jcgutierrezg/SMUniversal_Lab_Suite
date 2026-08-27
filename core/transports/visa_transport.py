"""
pyvisa transport - the default for all SMUs.

Handles GPIB, USB, and TCPIP in one class, because VISA hides the
difference behind its resource strings:

    GPIB0::25::INSTR                      the 2611A on GPIB
    TCPIP0::169.254.43.121::5025::SOCKET  an SMU on raw ethernet (the
                                          address the VdP script used)
    TCPIP0::192.168.0.10::INSTR           an SMU speaking VXI-11/HiSLIP
    ASRL3::INSTR                          an SMU on a serial cable

Note the ::SOCKET form: that's a raw TCP socket, which is what the
original VdP notebook opened by hand. VISA needs read_termination set
explicitly for SOCKET resources - it can't infer it the way it can for
INSTR resources - which is handled in connect() below.

Backends
--------
"VISA" is an interface, not an implementation. On a given PC there may
be several implementations installed - NI-VISA, Keysight IO Libraries,
and the pure-Python pyvisa-py - and **they do not see the same
instruments**. A vendor backend generally knows about that vendor's
boxes and its own GPIB cards; pyvisa-py talks raw USB and sockets and
needs no vendor install at all.

The Keysight U2722A is where this stopped being academic: it is a USB
modular instrument, and the original script for it forced
`pyvisa.ResourceManager('@py')` with two Keysight `visa32.dll` paths
commented out beside it - someone had already lost time to exactly this.

So this class no longer assumes one backend. It asks each one in
BACKENDS what it can see, merges the answers for the dropdown, and at
connect time tries them in order until one opens the resource. An
instrument that only one backend can see now works without anybody
having to know which one that is.

Resource patterns
-----------------
pyvisa's `list_resources()` defaults to `?*::INSTR`, which hides
anything enumerating as `::RAW` or as a bare socket. Both patterns are
scanned here, because "the instrument is plugged in and working but
does not appear in the dropdown" is otherwise indistinguishable from a
dead cable.
"""
from .base import Transport, gpib_connection_key

try:
    import pyvisa
except ImportError:
    pyvisa = None


class VisaTransport(Transport):
    """Wraps a pyvisa resource. One instance per instrument."""

    # Backend specs handed to pyvisa.ResourceManager(), in the order
    # they are tried. "" means "whatever pyvisa picks by default",
    # normally a vendor implementation if one is installed. "@py" is
    # pyvisa-py, which needs no vendor software but does need pyusb and
    # a libusb to see USB instruments.
    BACKENDS = ("", "@py")

    # Both are scanned and the results merged. The first is pyvisa's
    # own default; the second catches ::RAW and socket resources that
    # the default pattern silently omits.
    LIST_PATTERNS = ("?*::INSTR", "?*")

    # Filled in by list_available() so the connection panel can report
    # what each backend saw, rather than just showing a short list.
    LAST_SCAN = []

    def __init__(self):
        super().__init__()
        self.rm = None
        self.res = None
        self.address = None
        self.backend = None      # which backend actually opened it

    def connection_key(self):
        """Share physical GPIB ownership with the opt-in direct backend."""
        key = gpib_connection_key(self.address)
        return key if key is not None else super().connection_key()

    def connect(self, address, timeout_ms=20000, read_termination=None,
                write_termination="\n", backend=None, **kwargs):
        """Open a VISA resource, trying each backend in turn.

        `address` is a VISA resource string (see module docstring).
        `timeout_ms` matches the 20 s the IV scripts used - sweeps can
        take a while and a short timeout will abort them mid-run.

        `read_termination` defaults to "\\n" for ::SOCKET resources
        (which need it spelled out) and is left to VISA's default
        otherwise.

        `backend` pins a specific implementation - "" for the system
        default, "@py" for pyvisa-py. Left as None, every backend in
        BACKENDS is tried in order and the first that opens the resource
        wins. Pinning is for the case that ordering cannot fix: a
        backend that opens the instrument successfully and then
        misbehaves once it is talking to it.

        Failing to open on every backend raises with each backend's own
        error attached, because "could not connect" on its own does not
        distinguish a missing vendor library from a busy instrument from
        a wrong address.
        """
        if pyvisa is None:
            raise RuntimeError("pyvisa is not installed. Run: pip install pyvisa")

        self.close()
        candidates = (backend,) if backend is not None else tuple(self.BACKENDS)

        res = None
        failures = []
        for spec in candidates:
            rm = None
            try:
                rm = pyvisa.ResourceManager(spec) if spec \
                    else pyvisa.ResourceManager()
                res = rm.open_resource(address)
            except Exception as exc:
                if rm is not None:
                    try:
                        rm.close()
                    except Exception:
                        pass
                failures.append((spec or "default", exc))
                continue
            self.rm = rm
            self.backend = spec or "default"
            break

        if res is None:
            detail = "; ".join(f"{name}: {exc}" for name, exc in failures)
            raise ConnectionError(
                f"No VISA backend could open {address!r}. Tried "
                f"{len(failures)} backend(s) - {detail}")

        res.timeout = timeout_ms

        if read_termination is None and address.upper().endswith("SOCKET"):
            read_termination = "\n"
        if read_termination is not None:
            res.read_termination = read_termination
        if write_termination is not None:
            res.write_termination = write_termination

        self.res = res
        self.address = address
        self._begin_session()
        self.connected = True

    def close(self):
        if self.res is not None:
            try:
                self.res.close()
            except Exception:
                pass
        self.res = None
        self.backend = None
        # the ResourceManager is cheap to recreate and holding it open
        # can pin a busy GPIB board, so let it go too
        if self.rm is not None:
            try:
                self.rm.close()
            except Exception:
                pass
        self.rm = None
        self.connected = False

    def _write(self, text):
        self.res.write(text)

    def _read(self, timeout_s):
        """Read one reply. VISA owns the timeout (set at connect time),
        so `timeout_s` is applied per-call and then restored - this lets
        a slow sweep read use a longer window than a quick *IDN?."""
        if timeout_s is None:
            return self.res.read()
        previous = self.res.timeout
        try:
            self.res.timeout = int(timeout_s * 1000)
            return self.res.read()
        finally:
            self.res.timeout = previous

    def clear(self):
        """Send a VISA device clear, discarding any pending reply.

        Teardown housekeeping, not a cure for a desynchronised session -
        see Transport.clear(). A True return means the call did not
        raise, which is not the same as the stream being back in step.
        """
        if self.res is None:
            return False
        try:
            with self.lock:
                self.res.clear()
            return True
        except Exception:
            return False

    @classmethod
    def probe_backends(cls):
        """What each backend can see, and why it can't if it can't.

        Returns one dict per backend: name, ok, error, resources. This
        is the diagnostic behind list_available() - separated out
        because when an instrument is missing from the dropdown, the
        useful question is *which* backend failed and with what message,
        and a merged list of strings cannot answer that.
        """
        if pyvisa is None:
            return [{"backend": "none", "ok": False,
                     "error": "pyvisa is not installed", "resources": []}]

        report = []
        for spec in cls.BACKENDS:
            entry = {"backend": spec or "default", "ok": False,
                     "error": None, "resources": []}
            rm = None
            try:
                rm = pyvisa.ResourceManager(spec) if spec \
                    else pyvisa.ResourceManager()
                found = []
                for pattern in cls.LIST_PATTERNS:
                    try:
                        for name in rm.list_resources(pattern):
                            if name not in found:
                                found.append(name)
                    except Exception:
                        # One pattern failing is not the backend
                        # failing - some implementations reject "?*".
                        continue
                entry["ok"] = True
                entry["resources"] = found
            except Exception as exc:
                entry["error"] = str(exc)
            finally:
                if rm is not None:
                    try:
                        rm.close()
                    except Exception:
                        pass
            report.append(entry)
        return report

    @classmethod
    def list_available(cls):
        """Every address any backend can see, for the dropdown.

        Merged rather than taken from one backend, because the whole
        point is that they disagree: the U2722A shows up under
        pyvisa-py and a GPIB card shows up under the vendor library, and
        the operator should not have to know which is which to see their
        instrument in the list.
        """
        cls.LAST_SCAN = cls.probe_backends()
        merged = []
        for entry in cls.LAST_SCAN:
            for name in entry["resources"]:
                if name not in merged:
                    merged.append(name)
        return merged

    @classmethod
    def scan_summary(cls):
        """One line per backend, for the console after a refresh."""
        lines = []
        for entry in cls.LAST_SCAN or cls.probe_backends():
            if entry["ok"]:
                found = ", ".join(entry["resources"]) or "nothing"
                lines.append(f"{entry['backend']}: {found}")
            else:
                lines.append(f"{entry['backend']}: unavailable "
                             f"({entry['error']})")
        return lines


class VisaPyTransport(VisaTransport):
    """VisaTransport pinned to pyvisa-py.

    Offered separately in the connection panel because merging and
    ordering only solve the case where a backend cannot *find* or
    *open* the instrument. They do not help when a backend opens it
    happily and then goes wrong mid-session - which is the failure the
    U2722A has a history of. This is the escape hatch for that: pick it
    and the vendor library is never consulted.
    """

    BACKENDS = ("@py",)
    LAST_SCAN = []
