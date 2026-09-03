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

from core.transports.base import TransportDesynchronised
from core.transports.minismu_transport import MiniSMUTransport
from core.transports.null_transport import NullTransport
from core.transports.serial_transport import SerialTransport
from core.transports.visa_transport import VisaPyTransport, VisaTransport
from drivers.registry import UnknownInstrumentError, identify

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
    except UnknownInstrumentError as exc:
        print(f"Not auto-detected ({exc}); error-queue checking is off.")
    except Exception as exc:
        print(f"Identity query failed: {exc}")
    if args.no_error_check:
        error_query = None
    if error_query:
        print(f"Error queue: {error_query}")
    print()

    try:
        if args.script:
            with open(args.script, encoding="utf-8") as handle:
                for line in handle:
                    if line.strip() and not line.strip().startswith("#"):
                        print(f">> {line.strip()}")
                    run_line(transport, line, error_query, args.timeout)
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
                run_line(transport, line, error_query, args.timeout)
    finally:
        try:
            transport.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
