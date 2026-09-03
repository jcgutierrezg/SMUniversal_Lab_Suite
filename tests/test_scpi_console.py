import os

"""The bench console.

It is a debugging tool, so the things worth testing are the ones that
matter when something has already gone wrong: a hung read must not end
the session, a rejected command must be reported at the command that
caused it rather than three later, and a timed-out read must trigger a
resync so everything after it is still trustworthy.
"""
import importlib.util

from core.transports.null_transport import NullTransport

spec = importlib.util.spec_from_file_location(
    "scpi_console",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "tools", "scpi_console.py"))
console = importlib.util.module_from_spec(spec)
spec.loader.exec_module(console)


class Recording(NullTransport):
    def __init__(self, hang_on=None, error_after=None):
        super().__init__()
        self.log = []
        self.cleared = 0
        self.hang_on = hang_on
        self.error_after = error_after
        self.pending_error = False

    def write(self, text):
        self.log.append(text)
        if self.error_after and text.strip() == self.error_after:
            self.pending_error = True

    def query(self, text, timeout_s=3.0):
        self.log.append(text)
        if self.hang_on and text.strip() == self.hang_on:
            raise TimeoutError("VI_ERROR_TMO: Timeout expired")
        if "ERR" in text.upper():
            if self.pending_error:
                self.pending_error = False
                return '-113,"Undefined header"'
            return '0,"No error"'
        return "1.234"

    def clear(self):
        self.cleared += 1
        return True


def test_query_vs_write(check):
    t = Recording()
    console.run_line(t, ":SOUR:VOLT 1", ":SYST:ERR?", 10.0)
    check("a write is followed by an error-queue check",
          t.log == [":SOUR:VOLT 1", ":SYST:ERR?"], t.log)

    t = Recording()
    console.run_line(t, ":READ?", ":SYST:ERR?", 10.0)
    check("a query is not, since it would be the newest thing in the queue",
          t.log == [":READ?"], t.log)

    check("anything with a '?' is a query", console.looks_like_query(":READ?"))
    check("and anything without one is not",
          not console.looks_like_query(":OUTP ON"))


def test_a_hung_read_does_not_end_the_session(check):
    t = Recording(hang_on=":READ?")
    keep_going = console.run_line(t, ":READ?", ":SYST:ERR?", 10.0)
    check("the session continues after a timeout", keep_going is True,
          "a bisect script has to reach the commands after the hang - they "
          "are the ones that identify the cause")
    check("and a device clear is sent", t.cleared == 1,
          "otherwise the late reply desynchronises everything after it")

    console.run_line(t, ":OUTP OFF", ":SYST:ERR?", 10.0)
    check("later commands still run", ":OUTP OFF" in t.log)


def test_errors_are_reported_at_the_command_that_caused_them(check):
    t = Recording(error_after=":BOGUS")
    console.run_line(t, ":BOGUS", ":SYST:ERR?", 10.0)
    check("the queue is checked immediately after each write",
          t.log.count(":SYST:ERR?") == 1, t.log)
    t2 = Recording()
    console.run_line(t2, ":SOUR:VOLT 1", None, 10.0)
    check("and the check is skipped when the dialect is unknown",
          t2.log == [":SOUR:VOLT 1"],
          "guessing an error-queue spelling would itself raise errors")


def test_control_lines(check):
    t = Recording()
    console.run_line(t, "!", ":SYST:ERR?", 10.0)
    check("'!' sends a device clear", t.cleared == 1 and not t.log)
    console.run_line(t, "# a comment", ":SYST:ERR?", 10.0)
    console.run_line(t, "   ", ":SYST:ERR?", 10.0)
    check("comments and blank lines send nothing", not t.log, t.log)


def test_error_queue_spellings(check):
    check("the TSP instrument gets the TSP query",
          console.ERROR_QUERIES["Keithley2611A"] == "print(errorqueue.next())",
          "the SCPI form would be swallowed by the TSP parser")
    check("the GSM gets its single-query drain",
          console.ERROR_QUERIES["GWInstekGSM20H10"] == "SYST:ERR:ALL?")
    check("the U2722A gets the un-prefixed form",
          console.ERROR_QUERIES["KeysightU2722A"] == "SYST:ERR?")
    check("the 2400-family get the colon-prefixed form",
          console.ERROR_QUERIES["Keithley2401"] == ":SYST:ERR?")


def test_probe_script_is_valid(check):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tools", "probes", "2401_current_mode.txt")
    check("the 2401 bisect script exists", os.path.exists(path))
    with open(path, encoding="utf-8") as handle:
        lines = [x.strip() for x in handle if x.strip()
                 and not x.strip().startswith("#")]
    check("it reproduces the failing sequence",
          ":SOUR:FUNC CURR" in lines and ":SOUR:CURR:LEV 1e-6" in lines
          and ":READ?" in lines)
    check("it leaves the output off at the end",
          lines[-2:] == [":OUTP OFF", ":SYST:ERR?"], lines[-2:])
    check("it turns the output on only after a source level is set",
          lines.index(":OUTP ON") > lines.index(":SOUR:VOLT:LEV 0"))
    check("and it probes the source range, which the driver never sets",
          any(x.startswith(":SOUR:CURR:RANG") for x in lines))
