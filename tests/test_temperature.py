"""
Temperature stage: status-line parsing, setpoint gating, and command
wire format - all against a fake serial port, so this needs no Xiao
attached.

The parser is the part worth testing hardest. A mis-parsed status line
doesn't crash; it silently shows the wrong temperature next to a
measurement, which is the failure you'd never catch by eye.

`confirm_pid_off()` is the second part worth testing hardest, and for
the same reason with a worse ending. The board never acknowledges a
command, so "OFF was written" and "the heater stopped" are separate
claims, and the close path is the one caller with nobody watching the
readout afterwards. Its failure endings each get a case below.
"""
import sys
import threading
import time

import devices.temperature_control as tc
from core.run_control import ShutdownStatus
from devices.temperature_control import (
    MAX_SETPOINT_C,
    MIN_SETPOINT_C,
    TemperatureController,
    _parse_status_line,
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


# ---- confirming the PID actually went off ----
class BroadcastingSerial:
    """A board that keeps repeating one status line until told otherwise.

    `FakeSerial` above hands back a fixed script and then goes quiet,
    which is right for the parser and wrong here: the question
    `confirm_pid_off()` asks is whether a line arrived *after* the OFF,
    so a port whose script has already run dry can only ever produce the
    silent ending.

    Set `line` to None to make the board stop talking, and
    `write_error` to make the wire fail.
    """

    def __init__(self, line=None, write_error=None):
        self.line = line
        self.write_error = write_error
        self.written = []
        self.closed = False

    def readline(self):
        time.sleep(0.01)              # the board reports at 10 Hz
        line = self.line
        if line is None:
            return b""
        return (line + "\n").encode()

    def write(self, data):
        if self.write_error is not None:
            raise self.write_error
        self.written.append(data.decode())
        return len(data)

    def flush(self):
        pass

    def reset_input_buffer(self):
        pass

    def close(self):
        self.closed = True


class BroadcastingSerialModule:
    def __init__(self, port):
        self.port = port

    def Serial(self, port, baudrate, timeout, write_timeout):
        return self.port


def _broadcasting_controller(port):
    tc.serial = BroadcastingSerialModule(port)
    controller = TemperatureController()
    controller.connect("COM_TEST")
    return controller


def _wait_for_a_line(controller, timeout=2.0):
    """Block until the reader thread has parsed at least one line."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if controller.status().age_s is not None:
            return True
        time.sleep(0.01)
    return False


def _collect_confirm_pid_off():
    """The four endings, each injected rather than argued for.

    The two that matter most are the ones a fire-and-forget write cannot
    tell apart: a board that keeps saying HEATING after OFF, and a board
    that says nothing at all. Both had the write succeed.
    """
    bad = []

    # 1. a board that reports IDLE after the OFF - the only CONFIRMED.
    port = BroadcastingSerial("TEMP:25.0,SP:25.0,STATE:IDLE")
    controller = _broadcasting_controller(port)
    try:
        report = controller.confirm_pid_off(timeout_s=1.0)
        if report.status is not ShutdownStatus.CONFIRMED:
            bad.append(("idle board", f"{report.status}: {report.detail}"))
        if "OFF\n" not in port.written:
            bad.append(("idle board", f"OFF never written: {port.written}"))
    finally:
        controller.close()

    # 2. the write itself fails. Nothing was commanded, so nothing can
    #    be assumed - this is the "PID write failure on close" ending.
    port = BroadcastingSerial("TEMP:80.0,SP:100.0,STATE:HEATING",
                              write_error=OSError("ClearCommError failed"))
    controller = _broadcasting_controller(port)
    try:
        report = controller.confirm_pid_off(timeout_s=0.2)
        if report.status is not ShutdownStatus.UNCERTAIN:
            bad.append(("write fails", str(report.status)))
        if "could not be sent" not in report.detail:
            bad.append(("write fails", f"detail does not say so: "
                                       f"{report.detail}"))
    finally:
        controller.close()

    # 3. the write lands and the board goes on heating. The dangerous
    #    one, and the one a return-nothing pid_off() reported as success.
    port = BroadcastingSerial("TEMP:80.0,SP:100.0,STATE:HEATING")
    controller = _broadcasting_controller(port)
    try:
        report = controller.confirm_pid_off(timeout_s=0.4)
        if report.status is not ShutdownStatus.UNCERTAIN:
            bad.append(("still heating", str(report.status)))
        if "HEATING" not in report.detail:
            bad.append(("still heating", f"detail does not name the state: "
                                         f"{report.detail}"))
    finally:
        controller.close()

    # 4. the board was idle, and then the link dies between the last
    #    line and the write. The stale line must NOT be accepted as
    #    evidence: it was produced before the board could have seen the
    #    OFF, so reading it would be a probe whose answer was fixed
    #    before the question was asked.
    port = BroadcastingSerial("TEMP:25.0,SP:25.0,STATE:IDLE")
    controller = _broadcasting_controller(port)
    try:
        if not _wait_for_a_line(controller):
            bad.append(("goes silent", "the fake board never spoke at all"))
        port.line = None                     # cable out
        report = controller.confirm_pid_off(timeout_s=0.3)
        if report.status is not ShutdownStatus.UNCERTAIN:
            bad.append(("goes silent", f"a pre-OFF line was accepted as "
                                       f"proof: {report.status}"))
    finally:
        controller.close()

    # 5. never connected. Nothing was opened, so nothing was driven -
    #    an honest NOT_ATTEMPTED rather than a warning on every close.
    tc.serial = BroadcastingSerialModule(BroadcastingSerial())
    report = TemperatureController().confirm_pid_off(timeout_s=0.1)
    if report.status is not ShutdownStatus.NOT_ATTEMPTED:
        bad.append(("never connected", str(report.status)))
    if report.uncertain or report.confirmed:
        bad.append(("never connected", "reported as a shutdown attempt"))

    return bad


def _collect_pid_off_stays_a_bare_command():
    """`pid_off()` must keep raising when the stage is not there.

    The panel's OFF button calls it and an operator is watching the
    readout; the close path calls `confirm_pid_off()` instead. Two
    callers, two contracts - and the one this checks is the one
    `_collect_disconnected_commands` above depends on.
    """
    port = BroadcastingSerial("TEMP:25.0,SP:25.0,STATE:IDLE")
    controller = _broadcasting_controller(port)
    bad = []
    try:
        if controller.pid_off() is not None:
            bad.append(("pid_off", "returned something; it is a bare command"))
        if port.written != ["OFF\n"]:
            bad.append(("pid_off", f"wrote {port.written}"))
    finally:
        controller.close()
    return bad


TESTS = [
    ("status line parsing", _collect_parsing),
    ("setpoint limits", _collect_setpoint_limits),
    ("command wire format", _collect_command_format),
    ("reader thread / staleness", _collect_reader_and_staleness),
    ("commands while disconnected", _collect_disconnected_commands),
    ("confirming the PID went off", _collect_confirm_pid_off),
    ("pid_off stays a bare command", _collect_pid_off_stays_a_bare_command),
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

def test_confirm_pid_off():
    bad = _collect_confirm_pid_off()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"

def test_pid_off_stays_a_bare_command():
    bad = _collect_pid_off_stays_a_bare_command()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"
