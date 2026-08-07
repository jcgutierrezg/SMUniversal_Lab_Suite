"""
Temperature stage: status-line parsing, setpoint gating, and command
wire format - all against a fake serial port, so this needs no Xiao
attached.

The parser is the part worth testing hardest. A mis-parsed status line
doesn't crash; it silently shows the wrong temperature next to a
measurement, which is the failure you'd never catch by eye.
"""
import sys
import threading
import time

import devices.temperature_control as tc
from devices.temperature_control import (
    TemperatureController, _parse_status_line,
    MIN_SETPOINT_C, MAX_SETPOINT_C,
)


# ---- fake serial port ----
class FakeSerial:
    """Just enough pyserial to drive the reader thread: readline() hands
    back queued lines then blocks, and write() records what was sent."""

    def __init__(self, lines):
        self._lines = list(lines)
        self.written = []
        self.closed = False
        self._lock = threading.Lock()

    def readline(self):
        with self._lock:
            if self._lines:
                return (self._lines.pop(0) + "\n").encode()
        time.sleep(0.02)          # mimic a read timeout
        return b""

    def write(self, data):
        self.written.append(data.decode())
        return len(data)

    def flush(self):
        pass

    def reset_input_buffer(self):
        pass

    def close(self):
        self.closed = True


class FakeSerialModule:
    """Stands in for the `serial` module inside temperature_control."""

    def __init__(self, lines):
        self.lines = lines
        self.last = None

    def Serial(self, port, baudrate, timeout, write_timeout):
        self.last = FakeSerial(self.lines)
        return self.last


def make_controller(lines):
    """A connected controller reading from a scripted line list."""
    fake = FakeSerialModule(lines)
    tc.serial = fake
    controller = TemperatureController()
    controller.connect("COM_TEST")
    return controller, fake


# ---- parsing ----
PARSE_CASES = [
    # (line, expected temp, expected setpoint, expected state, expected fault)
    ("TEMP:24.8,SP:25.0,STATE:HEATING", 24.8, 25.0, "HEATING", False),
    ("TEMP:80.0,SP:25.0,STATE:COOLING", 80.0, 25.0, "COOLING", False),
    ("TEMP:25.0,SP:25.0,STATE:IDLE", 25.0, 25.0, "IDLE", False),
    ("TEMP:-14.3,SP:-15.0,STATE:COOLING", -14.3, -15.0, "COOLING", False),
    # thermocouple faulted: temperature must come back as None, never 0.0
    ("TEMP:FAULT,SP:25.0,STATE:FAULT", None, 25.0, "FAULT", True),
    # unknown extra field: must be ignored, not fatal, so firmware can grow
    ("TEMP:30.0,SP:30.0,STATE:IDLE,DUTY:42", 30.0, 30.0, "IDLE", False),
]

REJECT_CASES = [
    "",                              # nothing
    "P:24.8,SP:25.0,STATE:IDLE",     # fragment of a line already in flight
    "Booting firmware v1.2",         # startup chatter
    "TEMP:,SP:25.0,STATE:IDLE",      # empty value
    "TEMP:abc,SP:25.0,STATE:IDLE",   # unparseable value
]


def _collect_parsing():
    bad = []
    for line, temp, setpoint, state, fault in PARSE_CASES:
        got = _parse_status_line(line)
        if got is None:
            bad.append((line, "rejected a valid line"))
            continue
        if got.temp_c != temp:
            bad.append((line, f"temp {got.temp_c} != {temp}"))
        if got.setpoint_c != setpoint:
            bad.append((line, f"setpoint {got.setpoint_c} != {setpoint}"))
        if got.state != state:
            bad.append((line, f"state {got.state} != {state}"))
        if got.fault != fault:
            bad.append((line, f"fault {got.fault} != {fault}"))

    for line in REJECT_CASES:
        if _parse_status_line(line) is not None:
            bad.append((line, "accepted a line it should have rejected"))
    return bad


# ---- setpoint gate ----
def _collect_setpoint_limits():
    """Out-of-envelope setpoints must be refused before they reach the
    wire, the same way the SMU limit gate refuses a source point."""
    controller, fake = make_controller([])
    bad = []
    try:
        for value in (MIN_SETPOINT_C, 25.0, MAX_SETPOINT_C, "25", -0.5):
            try:
                controller.set_setpoint(value)
            except ValueError as e:
                bad.append((value, f"refused a legal setpoint: {e}"))

        for value in (MIN_SETPOINT_C - 0.1, MAX_SETPOINT_C + 0.1, 1000, -273, "hot"):
            try:
                controller.set_setpoint(value)
                bad.append((value, "accepted an illegal setpoint"))
            except ValueError:
                pass

        # nothing illegal reached the port
        for sent in fake.last.written:
            if sent.startswith("SET:"):
                value = float(sent[4:])
                if not (MIN_SETPOINT_C <= value <= MAX_SETPOINT_C):
                    bad.append((sent, "illegal setpoint reached the wire"))
    finally:
        controller.close()
    return bad


# ---- wire format ----
def _collect_command_format():
    """Commands must match the firmware exactly - one decimal on SET,
    bare ON/OFF, newline-terminated."""
    controller, fake = make_controller([])
    bad = []
    try:
        controller.set_setpoint(25)
        controller.set_setpoint(-3.25)
        controller.pid_on()
        controller.pid_off()

        expected = ["SET:25.0\n", "SET:-3.2\n", "ON\n", "OFF\n"]
        if fake.last.written != expected:
            bad.append((fake.last.written, f"!= {expected}"))
    finally:
        controller.close()
    return bad


# ---- reader thread and staleness ----
def _collect_reader_and_staleness():
    """The live snapshot must follow the stream, and must flag itself
    stale once the board stops talking - a frozen number presented as
    current is worse than no number."""
    bad = []
    controller, _ = make_controller([
        "garbage before the stream starts",
        "TEMP:20.0,SP:25.0,STATE:HEATING",
        "TEMP:22.5,SP:25.0,STATE:HEATING",
    ])
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if controller.status().temp_c == 22.5:
                break
            time.sleep(0.02)

        status = controller.status()
        if status.temp_c != 22.5:
            bad.append(("latest reading", f"{status.temp_c} != 22.5"))
        if status.state != "HEATING":
            bad.append(("state", status.state))
        if status.is_stale:
            bad.append(("freshness", "fresh reading reported as stale"))

        # stream has run dry - after the stale window it must say so
        time.sleep(tc.STALE_AFTER_S + 0.3)
        if not controller.status().is_stale:
            bad.append(("staleness", "silent board not flagged as stale"))
    finally:
        controller.close()

    if controller.is_connected():
        bad.append(("close()", "still reports connected after close"))
    return bad


def _collect_disconnected_commands():
    """Commanding a stage that isn't there must raise ConnectionError,
    not fail silently."""
    tc.serial = FakeSerialModule([])
    controller = TemperatureController()
    bad = []
    for name, call in (("set_setpoint", lambda: controller.set_setpoint(25)),
                       ("pid_on", controller.pid_on),
                       ("pid_off", controller.pid_off)):
        try:
            call()
            bad.append((name, "did not raise when disconnected"))
        except ConnectionError:
            pass
        except Exception as e:
            bad.append((name, f"raised {type(e).__name__}, expected ConnectionError"))
    return bad


TESTS = [
    ("status line parsing", _collect_parsing),
    ("setpoint limits", _collect_setpoint_limits),
    ("command wire format", _collect_command_format),
    ("reader thread / staleness", _collect_reader_and_staleness),
    ("commands while disconnected", _collect_disconnected_commands),
]

if __name__ == "__main__":
    failures = 0
    for name, fn in TESTS:
        bad = fn()
        print(f"  {'ok  ' if not bad else 'FAIL'}  {name}")
        for item in bad:
            print(f"          {item}")
        failures += len(bad)

    print(f"\n{'PASS' if not failures else f'{failures} FAILURE(S)'}")
    sys.exit(1 if failures else 0)


# --- Wave 0a: these used to return a list of failures that only the
# --- __main__ block inspected. Under pytest a returned value is
# --- ignored, so without these wrappers all of them would pass
# --- unconditionally. The collectors above are unchanged.

def test_parsing():
    bad = _collect_parsing()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_setpoint_limits():
    bad = _collect_setpoint_limits()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_command_format():
    bad = _collect_command_format()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_reader_and_staleness():
    bad = _collect_reader_and_staleness()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_disconnected_commands():
    bad = _collect_disconnected_commands()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"
