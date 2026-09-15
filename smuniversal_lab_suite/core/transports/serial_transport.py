"""
Raw pyserial transport.

Kept for two reasons:
  1. Plain serial devices that aren't VISA instruments at all - the
     Seeed Xiao temperature controller being the immediate one.
  2. A fallback for an SMU on a serial cable when a VISA layer isn't
     installed or isn't cooperating.

For SMUs, prefer VisaTransport. This is the escape hatch, not the
default.
"""
import time

from .base import Transport

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

PER_READ_TIMEOUT = 1.0


class SerialTransport(Transport):
    """Wraps a pyserial port, reading replies up to a newline."""

    def __init__(self):
        super().__init__()
        self.ser = None
        self.port = None

    def connect(self, address, baudrate=115200, write_timeout=3.0, **kwargs):
        """Open a serial port. `address` is a port name - 'COM3' on
        Windows, '/dev/ttyACM0' on Linux."""
        if serial is None:
            raise RuntimeError("pyserial is not installed. Run: pip install pyserial")

        self.close()
        self.ser = serial.Serial(
            port=address,
            baudrate=baudrate,
            timeout=PER_READ_TIMEOUT,
            write_timeout=write_timeout,
        )
        self.port = address
        self._begin_session()
        self.connected = True

    def close(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.connected = False

    def _write(self, text):
        self.ser.write((text + "\n").encode())
        self.ser.flush()

    def _read(self, timeout_s):
        """Accumulate bytes until a newline arrives, or `timeout_s`
        elapses. Each underlying read only blocks for PER_READ_TIMEOUT,
        so the deadline stays responsive instead of hanging.

        `read_until`, not `read(4096)`, and the difference is a factor
        of about 170.

        `pyserial.read(n)` returns when it has **n bytes** or when the
        port timeout expires - so asking for 4096 bytes of a 12-byte
        reply always waited out the full `PER_READ_TIMEOUT`. The loop
        then broke on the newline it already had, which is why nothing
        ever hung and nothing was ever obviously wrong: every reply
        simply arrived one second after it was ready.

        Measured on the 72-13200, 2026-09-15: 1010 ms per query through
        this method against 4-6 ms for the same query read with
        `read_until`. That instrument needs two queries per sweep point,
        so a 100-point sweep was paying 200 seconds of pure timeout.

        `read_until` returns as soon as the terminator lands, and still
        honours the port timeout when it never does - so a genuinely
        silent instrument fails exactly as before, at the same deadline.
        """
        deadline = time.time() + (timeout_s if timeout_s else 3.0)
        data = b""
        while True:
            chunk = self.ser.read_until(b"\n")
            if chunk:
                data += chunk
                if b"\n" in data:
                    break
            if time.time() > deadline:
                raise TimeoutError("serial read timed out")
        return data.decode(errors="ignore").strip()

    @staticmethod
    def list_available():
        """List serial ports, for the connection dropdown."""
        if list_ports is None:
            return []
        try:
            return [p.device for p in list_ports.comports()]
        except Exception:
            return []
