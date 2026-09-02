"""
Seeeduino Xiao (SAMD21) hot/cold stage - serial side channel.

Why this does NOT use core/transports/SerialTransport
-----------------------------------------------------
Every SMU in this repo is request-response: write a command, read its
reply, the two paired under one lock. That is exactly what Transport
models.

The Xiao doesn't work that way. It free-runs a status line at 10 Hz and
never acknowledges anything:

    TEMP:24.8,SP:25.0,STATE:HEATING
    TEMP:24.9,SP:25.0,STATE:HEATING
    ...

Calling query("SET:25.0") on that would return whichever status line
happened to arrive next - not a reply, just the next tick of an unrelated
broadcast. The SMUs are phone calls; this is a radio station that also
takes requests. Forcing it through Transport would mean lying about what
a "reply" is.

So this class owns its own serial port plus a reader thread that keeps
the most recent status line. Commands are fire-and-forget. Reads never
touch the wire - they return the last thing the board broadcast.

The one piece of SerialTransport still reused is list_available(), for
the port dropdown - that part is genuinely shared.

Protocol (from the firmware)
----------------------------
    Host -> board:   SET:<temp_c>\\n     set PID target, one decimal
                     ON\\n               start the PID loop
                     OFF\\n              stop it

    Board -> host:   TEMP:<c|FAULT>,SP:<c>,STATE:<HEATING|COOLING|IDLE|FAULT>
"""
import threading
import time
from dataclasses import dataclass

# The same three-valued vocabulary the SMU shutdown path already uses.
# Imported rather than re-declared so that "confirmed", "uncertain" and
# "not attempted" mean one thing across the application: an operator
# reading two warnings side by side must not have to work out whether
# two words describe the same state.
from core.run_control import ShutdownStatus

try:
    import serial  # pyserial
except ImportError:
    serial = None  # let the rest of the app run without pyserial installed


DEFAULT_BAUDRATE = 115200
READ_TIMEOUT_S = 0.5        # how long readline() blocks before rechecking the stop flag

# The board reports at 10 Hz. If nothing has arrived for this long, the
# link is effectively dead (cable out, board reset, firmware wedged) even
# though the OS still thinks the port is open. Surfacing that is the
# difference between "23.4 °C" and "23.4 °C, from eight seconds ago".
STALE_AFTER_S = 1.0

# Stage envelope. Enforced here rather than only in the GUI so that any
# future caller - a temperature sweep, a script - gets the same refusal.
MIN_SETPOINT_C = -15.0
MAX_SETPOINT_C = 105.0

# The states in which the board says it is putting energy into the
# sample. Anything else - IDLE, and any state a later firmware adds that
# is not one of these - is not driving.
#
# The set names the *dangerous* states rather than the safe ones on
# purpose. A firmware that grew a `STATE:BOOSTING` would then read as
# "not driving" here, which is wrong but visible; naming the safe ones
# instead would make every unrecognised state read as dangerous and turn
# the warning into noise nobody reads. Neither default is free, and a
# warning that fires on every close is a warning that stops working.
DRIVING_STATES = frozenset({"HEATING", "COOLING"})

# How long confirm_pid_off() will wait for the board to broadcast a
# status line it produced *after* the OFF. The board reports at 10 Hz,
# so this is roughly fifteen lines - generous against a board that has
# just been asked to do something, short enough that the close path
# stays responsive when the stage is not there at all.
PID_OFF_CONFIRM_S = 1.5

# How often that wait re-reads the snapshot. Reading is free (it never
# touches the wire), so this only bounds how late the answer arrives.
PID_OFF_POLL_S = 0.02


@dataclass(frozen=True)
class StageShutdownReport:
    """The result of trying to put the stage's heater away.

    The counterpart of `core.run_control.ShutdownReport`, and shaped the
    same way for the same reason: whether the heater actually stopped
    decides what the operator has to do next, so it has to be a value
    the caller can branch on rather than the absence of an exception.

    `NOT_ATTEMPTED` is not a failure. It is the honest answer when this
    application never had the stage open, and therefore never turned a
    heater on that it now has to turn off.
    """

    status: ShutdownStatus = ShutdownStatus.NOT_ATTEMPTED
    detail: str = ""

    @property
    def confirmed(self):
        return self.status is ShutdownStatus.CONFIRMED

    @property
    def uncertain(self):
        return self.status is ShutdownStatus.UNCERTAIN


class TemperatureStatus:
    """One snapshot of what the board last reported.

    `temp_c` is None when the thermocouple is faulted (the firmware sends
    TEMP:FAULT), so callers must handle None rather than trusting a
    number that isn't there.
    """

    __slots__ = ("temp_c", "setpoint_c", "state", "fault", "age_s", "raw")

    def __init__(self, temp_c=None, setpoint_c=None, state="?",
                 fault=False, age_s=None, raw=""):
        self.temp_c = temp_c
        self.setpoint_c = setpoint_c
        self.state = state
        self.fault = fault
        self.age_s = age_s          # seconds since this line arrived; None = never
        self.raw = raw

    @property
    def is_stale(self):
        """True when the board has gone quiet - no fresh line recently."""
        return self.age_s is None or self.age_s > STALE_AFTER_S

    def temp_text(self, places=1):
        """Readout string for the GUI, covering both failure shapes:
        thermocouple faulted, and board not talking."""
        if self.fault:
            return "FAULT"
        if self.temp_c is None:
            return "--"
        return f"{self.temp_c:.{places}f}"


class TemperatureController:
    """Serial link to the Xiao stage.

    Lifecycle: connect() -> set_setpoint()/pid_on()/pid_off() -> close().
    status() is safe to call at any time and from any thread; it never
    blocks on the wire.
    """

    def __init__(self):
        self.ser = None
        self.port = None
        self.connected = False

        self._lock = threading.Lock()       # guards _status/_last_rx
        self._write_lock = threading.Lock()  # serialises outgoing commands
        self._reader = None
        self._stop = threading.Event()

        self._status = TemperatureStatus()
        self._last_rx = None                 # time.monotonic() of last good line

    # ---- lifecycle ----
    def connect(self, port, baudrate=DEFAULT_BAUDRATE):
        """Open the port and start the reader thread.

        Does not wait for the first status line - the GUI shows "--"
        until one arrives, which is about 100 ms.
        """
        if serial is None:
            raise RuntimeError("pyserial is not installed. Run: uv add pyserial")

        self.close()

        self.ser = serial.Serial(port=port, baudrate=baudrate,
                                 timeout=READ_TIMEOUT_S, write_timeout=2.0)
        self.port = port
        self.connected = True

        # Whatever accumulated in the OS buffer while we weren't listening
        # is stale by definition - start from now.
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass

        self._stop.clear()
        with self._lock:
            self._status = TemperatureStatus()
            self._last_rx = None

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def close(self):
        """Stop the reader and close the port. Safe to call when already
        closed, and safe to call twice."""
        self._stop.set()

        reader = self._reader
        self._reader = None
        if reader is not None and reader.is_alive():
            # Bounded by READ_TIMEOUT_S, so this can't hang the GUI on exit.
            reader.join(timeout=READ_TIMEOUT_S * 3)

        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.connected = False

    def is_connected(self):
        """True between a successful connect() and the next close().

        Note this only reflects the port being open - it says nothing
        about whether the board is still talking. Check status().is_stale
        for that.
        """
        return self.connected

    # ---- reading ----
    def status(self):
        """The most recent status snapshot, with its age filled in.

        Never touches the serial port, so it's cheap enough to call from
        a GUI poll loop several times a second.
        """
        with self._lock:
            snapshot = self._status
            last = self._last_rx

        age = None if last is None else time.monotonic() - last
        return TemperatureStatus(
            temp_c=snapshot.temp_c,
            setpoint_c=snapshot.setpoint_c,
            state=snapshot.state,
            fault=snapshot.fault,
            age_s=age,
            raw=snapshot.raw,
        )

    def read_temperature(self):
        """Latest temperature in °C, or None if faulted / nothing yet."""
        return self.status().temp_c

    # ---- commands ----
    def set_setpoint(self, temperature_c):
        """Send a new PID target. Raises ValueError outside the stage's
        -15 to 105 °C envelope rather than letting the board be asked for
        something it can't reach."""
        try:
            value = float(temperature_c)
        except (TypeError, ValueError):
            raise ValueError(f"Setpoint must be a number, got {temperature_c!r}")

        if not (MIN_SETPOINT_C <= value <= MAX_SETPOINT_C):
            raise ValueError(
                f"Setpoint {value:g} °C is outside the stage range "
                f"{MIN_SETPOINT_C:g} to {MAX_SETPOINT_C:g} °C."
            )

        # One decimal, matching how the firmware prints setpointC back,
        # so the echoed SP: value compares cleanly against what was sent.
        self._send(f"SET:{value:.1f}")
        return value

    def pid_on(self):
        """Start the PID loop."""
        self._send("ON")

    def pid_off(self):
        """Stop the PID loop. Outputs go idle; this is the safe state.

        The bare command, and it stays bare: it raises if the stage is
        not connected and is otherwise fire-and-forget, which is what
        the panel's OFF button wants - the operator is looking at the
        readout and can see the state change for themselves.

        **Anything closing the application must call
        `confirm_pid_off()` instead.** Nobody is watching the readout
        then, so "the write did not raise" is the only evidence this
        method can offer, and it is not evidence that a heater stopped.
        """
        self._send("OFF")

    def confirm_pid_off(self, timeout_s=None):
        """Stop the PID loop and check the stage agreed it had stopped.

        The stage counterpart of `core.run_control.confirm_output_off()`,
        and it exists for the same reason: on the way out, "the command
        was written" and "the hardware is no longer driving the sample"
        are different claims, and only the second one is worth telling
        an operator who is about to walk away.

        **What is asked, and why it is that question.** The firmware
        never acknowledges a command, so there is nothing to read back.
        What it does do is broadcast its own state at 10 Hz, and the
        state is the quantity that matters: HEATING and COOLING mean
        energy is going into the sample, and any other state means it is
        not. So the confirmation is a status line the board sent *after*
        the OFF, reporting a state that is not one of the driving ones.

        The "after" is load-bearing. The most recent line at the moment
        OFF is written was produced before the board could have seen it,
        so accepting it would be a probe whose answer was already fixed
        before the question was asked - it would report CONFIRMED for a
        stage sitting at setpoint whether or not the OFF ever arrived.
        `_last_line_at()` is compared against the send time for exactly
        that reason.

        Four endings:

        `NOT_ATTEMPTED`
            The port was never open, so this application is not driving
            the stage and has nothing to switch off.
        `UNCERTAIN`, write failed
            OFF could not be sent. The PID may still be running.
        `UNCERTAIN`, board silent
            OFF was written but the board has said nothing since, so
            there is no evidence either way. A cable pulled out between
            the last status line and the write looks exactly like this.
        `UNCERTAIN`, still driving
            The board is talking and still reports HEATING or COOLING -
            or reports FAULT, where what the outputs are doing is not
            something the board is in a position to say.
        `CONFIRMED`
            A post-OFF line reporting a state that is not driving.

        `timeout_s` defaults to `PID_OFF_CONFIRM_S`, resolved when the
        call is made rather than when this function was defined - a
        bound baked into a default argument is one a test cannot
        shorten, and an unshortenable bound in a shutdown path is one
        nobody writes a failure test for.
        """
        if timeout_s is None:
            timeout_s = PID_OFF_CONFIRM_S

        if not self.is_connected():
            return StageShutdownReport(
                ShutdownStatus.NOT_ATTEMPTED,
                "the stage was not connected, so this application was "
                "not driving it")

        sent_at = time.monotonic()
        try:
            self._send("OFF")
        except Exception as exc:
            return StageShutdownReport(
                ShutdownStatus.UNCERTAIN,
                f"OFF could not be sent to the stage ({exc}), so the PID "
                f"loop may still be running")

        deadline = sent_at + max(0.0, timeout_s)
        last_state = None
        while True:
            arrived = self._last_line_at()
            if arrived is not None and arrived >= sent_at:
                snapshot = self.status()
                last_state = snapshot.state
                if snapshot.fault:
                    return StageShutdownReport(
                        ShutdownStatus.UNCERTAIN,
                        "OFF was sent, but the stage reports a fault, so "
                        "what its outputs are doing is not something it "
                        "can be asked")
                if snapshot.state not in DRIVING_STATES:
                    return StageShutdownReport(
                        ShutdownStatus.CONFIRMED,
                        f"the stage reports {snapshot.state} after OFF")
            if time.monotonic() >= deadline:
                break
            time.sleep(PID_OFF_POLL_S)

        if last_state is None:
            return StageShutdownReport(
                ShutdownStatus.UNCERTAIN,
                f"OFF was written, but the stage has broadcast nothing "
                f"since - it stopped answering within {timeout_s:g} s, so "
                f"whether the PID stopped is unknown")
        return StageShutdownReport(
            ShutdownStatus.UNCERTAIN,
            f"OFF was sent, and {timeout_s:g} s later the stage is still "
            f"reporting {last_state}")

    def _last_line_at(self):
        """`time.monotonic()` of the last parsed status line, or None.

        Separate from `status()`, which reports an *age* computed from
        its own clock read. An age is the right thing for a readout and
        the wrong thing for "did this line arrive after that write":
        subtracting one clock read from another to recover an absolute
        instant reintroduces the slack the comparison is trying to
        exclude.
        """
        with self._lock:
            return self._last_rx

    def _send(self, command):
        """Write one command line. Fire-and-forget - the board doesn't
        acknowledge, so confirmation comes from watching the next status
        line, not from a return value."""
        if not self.connected or self.ser is None:
            raise ConnectionError("Temperature controller is not connected.")
        with self._write_lock:
            self.ser.write((command + "\n").encode("ascii"))
            self.ser.flush()

    # ---- reader thread ----
    def _read_loop(self):
        """Consume status lines until stopped.

        Deliberately forgiving: a line that doesn't parse is skipped, not
        raised. The first read after opening a port is very often a
        fragment of a line that was already mid-transmission, and a
        half-line is not an error worth reporting.
        """
        while not self._stop.is_set():
            try:
                raw = self.ser.readline()
            except Exception:
                break                       # port pulled out from under us
            if not raw:
                continue                    # timeout - loop round and recheck _stop

            line = raw.decode("ascii", errors="ignore").strip()
            parsed = _parse_status_line(line)
            if parsed is None:
                continue

            with self._lock:
                self._status = parsed
                self._last_rx = time.monotonic()


def _parse_status_line(line):
    """Parse 'TEMP:24.8,SP:25.0,STATE:HEATING' into a TemperatureStatus,
    or None if it isn't a status line.

    Field-by-field rather than positional, so adding a field to the
    firmware later (humidity, duty cycle) won't break this parser - the
    unknown key is simply ignored.
    """
    if "TEMP:" not in line:
        return None

    fields = {}
    for chunk in line.split(","):
        key, sep, value = chunk.partition(":")
        if sep:
            fields[key.strip().upper()] = value.strip()

    temp_raw = fields.get("TEMP")
    if temp_raw is None:
        return None

    fault = temp_raw.upper() == "FAULT"
    temp_c = None if fault else _to_float(temp_raw)
    if temp_c is None and not fault:
        return None                         # 'TEMP:' present but unparseable

    return TemperatureStatus(
        temp_c=temp_c,
        setpoint_c=_to_float(fields.get("SP")),
        state=(fields.get("STATE") or "?").upper(),
        fault=fault or fields.get("STATE", "").upper() == "FAULT",
        raw=line,
    )


def _to_float(text):
    """float() that returns None instead of raising."""
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None
