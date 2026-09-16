"""
Send commands to an instrument and see exactly what comes back.

    uv run tools/scpi_console.py --address GPIB0::24::INSTR
    uv run tools/scpi_console.py --address GPIB0::24::INSTR --script probe.txt
    uv run tools/scpi_console.py --address COM5 --transport minismu

For the case the checkup cannot reach: a command that hangs, or one whose
effect depends on the four commands sent before it. The checkup walks a
fixed sequence; this lets you vary one thing at a time.

Behaviour:
  * Anything containing '?' is treated as a query and its reply printed.
  * Everything else is a write, followed by an error-queue check, so a
    rejected command is reported immediately rather than surfacing three
    commands later.
  * Every line is timed. A command that takes 10 s is as interesting as
    one that errors.
  * Ctrl-C aborts a hung read without killing the session, so you can
    keep going and try the next thing.

Script files are one command per line; '#' starts a comment, and a bare
'!' line sends a device clear.

*** This sends whatever you type. It does not check limits. Know what is
    connected before sourcing anything. ***
"""
import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smuniversal_lab_suite.core.transports.base import TransportDesynchronised
from smuniversal_lab_suite.core.transports.minismu_transport import (
    MiniSMUTransport,
)
from smuniversal_lab_suite.core.transports.null_transport import NullTransport
from smuniversal_lab_suite.core.transports.serial_transport import (
    SerialTransport,
)
from smuniversal_lab_suite.core.transports.visa_transport import (
    VisaPyTransport,
    VisaTransport,
)
from smuniversal_lab_suite.drivers.registry import (
    UnknownInstrumentError,
    identify,
)

TRANSPORTS = {
    "visa": VisaTransport,
    "visapy": VisaPyTransport,
    "serial": SerialTransport,
    "minismu": MiniSMUTransport,
    "demo": NullTransport,
}

# Error-queue query per dialect. The console does not know which
# instrument it is talking to until it has asked, and on a hung
# instrument it may never find out - so this is chosen from the driver
# when auto-detection works and left off when it does not.
ERROR_QUERIES = {
    "Keithley2450": ":SYST:ERR?",
    "Keithley2401": ":SYST:ERR?",
    "Keithley2611A": "print(errorqueue.next())",
    "GWInstekGSM20H10": "SYST:ERR:ALL?",
    "KeysightU2722A": "SYST:ERR?",
}


#: TSP has no query punctuation. `print(...)` and its relatives are the
#: only things that generate a response message, so they have to be
#: recognised explicitly.
TSP_QUERY = re.compile(r"\b(print|printbuffer|printnumber)\s*\(")


def looks_like_query(text):
    """Whether a line will produce a reply that must be read back.

    SCPI marks its queries with `?`. TSP does not mark them at all: a
    TSP instrument answers when the script calls `print()`, and stays
    silent otherwise.

    Getting this wrong on a TSP box is worse than getting no answer.
    The reply is generated regardless and sits in the output buffer, so
    the next query reads the *previous* line's answer and every result
    after it is off by one - silently, and looking entirely plausible.
    That is this project's recurring failure mode, in a diagnostic tool
    rather than a driver.
    """
    return "?" in text or bool(TSP_QUERY.search(text))


def run_line(transport, line, error_query, timeout_s):
    """Send one line and report what happened. Returns False to stop."""
    line = line.strip()
    if not line or line.startswith("#"):
        return True
    if line == "!":
        ok = transport.clear()
        print(f"   device clear -> {'sent' if ok else 'not supported'}")
        return True

    # ALREADY LATCHED IS NOT THE SAME AS NO REPLY.
    #
    # A transport latches on its first failed exchange and every query
    # after it raises instantly. Writes are still permitted, so without
    # this check a script runs its whole burst into a dead link, reaches
    # the query, and reports "no reply" for a question that was never
    # asked - at 0.0 ms, which is the only thing that gave it away. Ten
    # runs of a probe were spent that way.
    if transport.is_desynchronised:
        print("   -- skipped: the link was already out of step before "
              "this line. Nothing below was asked.")
        return False

    started = time.perf_counter()
    try:
        if looks_like_query(line):
            reply = transport.query(line, timeout_s=timeout_s)
            elapsed = time.perf_counter() - started
            print(f"   {elapsed * 1000:8.1f} ms  -> {str(reply).strip()}")
        else:
            transport.write(line)
            elapsed = time.perf_counter() - started
            print(f"   {elapsed * 1000:8.1f} ms  (write)")
    except KeyboardInterrupt:
        elapsed = time.perf_counter() - started
        print(f"   {elapsed * 1000:8.1f} ms  ** interrupted **")
        print("   sending a device clear to resynchronise...")
        transport.clear()
        return True
    except TransportDesynchronised:
        # HOW LONG IT WAITED IS THE MEASUREMENT.
        #
        # The transport latches here and this line ends the session,
        # which is right. Re-raising in silence also threw away the one
        # number the failure carried: "no reply" and "no reply within
        # 30 s" are different findings, and only the second one says
        # whether a bigger budget would have helped. The traceback names
        # the command and not the wait.
        elapsed = time.perf_counter() - started
        print(f"   {elapsed * 1000:8.1f} ms  ** no reply; link latched **")
        raise
    except Exception as exc:
        elapsed = time.perf_counter() - started
        print(f"   {elapsed * 1000:8.1f} ms  !! {type(exc).__name__}: {exc}")
        # A timed-out read leaves the reply in the output buffer, which
        # would desynchronise everything after it.
        transport.clear()
        return True

    # Check the error queue after a write. Skipped after a query,
    # because the query itself would be the most recent thing in it.
    if error_query and not looks_like_query(line):
        try:
            reply = str(transport.query(error_query, timeout_s=3.0)).strip()
            if reply and not reply.startswith(("0,", "+0,", "0\t")):
                print(f"              !! error queue: {reply}")
        except TransportDesynchronised:
            raise
        except Exception:
            pass
    return True


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--transport", default=None, choices=TRANSPORTS)
    parser.add_argument("--script", default=None,
                        help="file of commands, one per line")
    parser.add_argument("--timeout", type=float, default=10.0,
                        help="read timeout in seconds (default 10)")
    parser.add_argument("--no-error-check", action="store_true")
    parser.add_argument("--write-delay", type=float, default=None,
                        help="milliseconds to hold the link after each "
                             "write (default: whatever the detected "
                             "driver declares, as the app would; 0 sends "
                             "an unpaced burst)")
    args = parser.parse_args()

    if args.transport is None:
        import re
        args.transport = "visa" if re.match(
            r"^(USB|GPIB|TCPIP|ASRL|PXI|VXI)\d*::", args.address, re.I) \
            else None
        if args.transport is None:
            parser.error(
                f"{args.address!r} is not a VISA resource string; state "
                f"--transport (minismu or serial).")

    transport = TRANSPORTS[args.transport]()
    print(f"Connecting to {args.address} over {args.transport}...")
    transport.connect(args.address)

    error_query = None
    try:
        driver, idn = identify(transport)
        print(f"Detected: {type(driver).DISPLAY_NAME}")
        print(f"Identity: {idn}")
        error_query = ERROR_QUERIES.get(type(driver).__name__)
        if error_query is None:
            # Three states, and they used to be one silence. A tool
            # whose job is to report what the instrument said must not
            # be quiet about not having asked (fault 45).
            if not driver.supports_error_queue():
                print("Error queue: THIS INSTRUMENT HAS NONE. A rejected "
                      "command is ignored in silence, so nothing below is "
                      "evidence that anything was understood - read the "
                      "setting back instead.")
            else:
                print(f"Error queue: no query spelling is wired up for "
                      f"{type(driver).__name__} in this tool, so nothing "
                      f"below is checked. The instrument HAS a queue; "
                      f"add it to ERROR_QUERIES.")
    except UnknownInstrumentError as exc:
        print(f"Not auto-detected ({exc}); error-queue checking is off.")
    except TransportDesynchronised as exc:
        # The first query of the session failed, so the link was broken
        # before anything under test was sent. Carrying on would run the
        # script into it and report the failure at whatever line
        # happened to query first.
        print(f"\nTHE LINK WAS DEAD ON ARRIVAL: {exc}\n")
        print("Nothing was run. This is not the intermittent fault - it "
              "is the link failing at the very first query, which a "
              "previous session can leave behind. Power-cycle the "
              "instrument (or unplug and replug the USB lead), then "
              "start again.")
        transport.close()
        return 1
    except Exception as exc:
        print(f"Identity query failed: {exc}")
    # PACING, and which one is in force. The detected driver has already
    # set its own on the transport, so by default this sends exactly the
    # traffic the app does. An explicit --write-delay overrides it
    # through the same mechanism, which is the only way to reproduce an
    # instrument's burst fault now that the driver guards against it -
    # and the tool says which of the two you are getting, because a
    # probe that silently disagreed with the app about pacing would be
    # measuring a different run from the one that failed.
    declared = transport.write_delay_s
    if args.write_delay is not None:
        transport.write_delay_s = args.write_delay / 1000.0
        print(f"Write pacing: {args.write_delay:g} ms after each write "
              f"(--write-delay; the driver declares "
              f"{declared * 1000:g} ms).")
    elif declared:
        print(f"Write pacing: {declared * 1000:g} ms after each write, as "
              f"the driver declares. Pass --write-delay 0 to send an "
              f"unpaced burst.")
    if args.no_error_check:
        error_query = None
        print("Error queue: checking disabled by --no-error-check.")
    elif error_query:
        print(f"Error queue: {error_query}")
    print()

    try:
        if args.script:
            with open(args.script, encoding="utf-8") as handle:
                for line in handle:
                    if line.strip() and not line.strip().startswith("#"):
                        print(f">> {line.strip()}")
                    if not run_line(transport, line, error_query,
                                    args.timeout):
                        break
        else:
            print("One command per line. '!' sends a device clear, "
                  "blank line or Ctrl-D exits.\n")
            while True:
                try:
                    line = input(">> ")
                except EOFError:
                    break
                if not line.strip():
                    break
                if not run_line(transport, line, error_query,
                                args.timeout):
                    break
    finally:
        try:
            transport.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
