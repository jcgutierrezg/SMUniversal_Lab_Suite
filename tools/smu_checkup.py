"""
Commission an SMU before trusting it.

    uv run tools/smu_checkup.py --demo
    uv run tools/smu_checkup.py --list
    uv run tools/smu_checkup.py --address USB0::0x0957::0x4118::MY62030002::INSTR
    uv run tools/smu_checkup.py --address 192.168.1.106 --transport minismu
    uv run tools/smu_checkup.py --address GPIB0::26::INSTR --transport gpib-hs --tiers 1 --trace

Connects, auto-detects the driver exactly as the app does, walks the
whole BaseSMU contract, and writes a Markdown report plus a JSON sidecar
next to it.

*** NOTHING SHOULD BE CONNECTED TO THE OUTPUT TERMINALS. ***

The checks expect open-circuit behaviour, because an open circuit is a
DUT whose answers are known in advance: 0.1 V should draw no current,
and a sourced current should ride into the voltage limit. With a sample
attached those checks report warnings that are not faults.

Options:
    --address ADDR     what to connect to
    --transport NAME   visa, visapy, gpib-hs, serial, minismu, demo
    --tiers 1,2        run only some tiers; default is all three
    --out DIR          where to write the report (default: ./checkups)
    --list             list addresses each transport can see, and exit
    --demo             run against the simulated instrument, no hardware
    --quiet            only print the summary
"""
import sys, os, re, json, time, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.provenance import code_paths_for, describe
from core.checkup import Checkup, build_report
from drivers.registry import identify, UnknownInstrumentError
from core.transports.visa_transport import VisaTransport, VisaPyTransport
from core.transports.serial_transport import SerialTransport
from core.transports.minismu_transport import MiniSMUTransport
from core.transports.null_transport import NullTransport
from core.transports.ni_gpib_usb_hs_transport import NIUSBGPIBTransport

TRANSPORTS = {
    "visa": VisaTransport,
    "visapy": VisaPyTransport,
    "gpib-hs": NIUSBGPIBTransport,
    "serial": SerialTransport,
    "minismu": MiniSMUTransport,
    "demo": NullTransport,
}

# A VISA resource string always starts with an interface type and a
# board number. A "COM3" or "/dev/ttyACM0" never does - and picking the
# wrong transport for one of those is the most likely way to get an
# error about a backend that was never the problem.
VISA_RESOURCE = re.compile(r"^(USB|GPIB|TCPIP|ASRL|PXI|VXI|FIREWIRE)\d*::",
                           re.IGNORECASE)

# Which transports can plausibly own a plain port name. Listed in the
# refusal message below, because the tool cannot tell them apart from
# the address alone and guessing means writing bytes at an instrument
# on the strength of a hunch.
PORT_TRANSPORTS = ("minismu", "serial")


def inferred_transport(address):
    """Return only the transport the checkup may choose implicitly.

    VISA resource spelling means VISA, including GPIB. The direct USB-HS
    stack is intentionally absent: it must always be named explicitly.
    """
    text = str(address).strip()
    return "visa" if VISA_RESOURCE.match(text) else None


def install_trace(transport, sink):
    """Wrap write/query so every exchange is recorded.

    A result row says which *check* failed. When the failure is a
    timeout that says nothing about which command caused it - the
    2401's current-source reading times out somewhere between six
    commands, and the report cannot tell you which. This can.

    Wraps the public methods rather than the private _write/_read so
    the transport's own locking is left alone.
    """
    original_write = transport.write
    original_query = transport.query

    def write(text):
        started = time.perf_counter()
        try:
            result = original_write(text)
        except Exception as exc:
            sink.append((time.perf_counter() - started, text, f"!! {exc}"))
            raise
        sink.append((time.perf_counter() - started, text, ""))
        return result

    def query(text, timeout_s=3.0):
        started = time.perf_counter()
        try:
            reply = original_query(text, timeout_s=timeout_s)
        except Exception as exc:
            sink.append((time.perf_counter() - started, f"{text}  [?]",
                         f"!! {type(exc).__name__}: {exc}"))
            raise
        sink.append((time.perf_counter() - started, f"{text}  [?]",
                     str(reply).strip()[:120]))
        return reply

    transport.write = write
    transport.query = query


BANNER = """
+--------------------------------------------------------------+
|  Disconnect everything from the output terminals before this  |
|  runs. It sources small voltages and currents, and it checks  |
|  them against open-circuit expectations.                      |
+--------------------------------------------------------------+
"""


def list_addresses():
    """What each transport can see, with the flag needed to use it.

    Printing the flag matters: a plain port name shows up under both
    'serial' and 'minismu', and the address alone does not say which
    instrument is on it.
    """
    for name, cls in TRANSPORTS.items():
        if name == "demo":
            continue
        try:
            found = cls.list_available()
        except Exception as exc:
            print(f"  --transport {name:<9} unavailable: {exc}")
            continue
        print(f"  --transport {name:<9} "
              f"{', '.join(found) if found else 'nothing found'}")
        summary = getattr(cls, "scan_summary", None)
        if summary is not None:
            for line in summary():
                print(f"  {'':<22} {line}")
    print("\n  A COM port appears under both 'serial' and 'minismu' - the "
          "address\n  cannot say which instrument is on it. The Undalogic "
          "miniSMU needs\n  'minismu'; everything else on a port needs "
          "'serial'.")


def _driver_source(driver_cls):
    """The driver's own file, relative to the repository root.

    Taken from the class rather than from a name-mangling rule, because
    the two have already disagreed once: `KeysightU2722A` lives in
    `keysight_u2722a.py`, but `UndalogicMiniSMU` lives in
    `undalogic_minismu.py`, not `undalogic_mini_smu.py`. A fingerprint
    computed over the wrong file would be perfectly stable and
    perfectly meaningless.
    """
    module = sys.modules.get(driver_cls.__module__)
    path = getattr(module, "__file__", None)
    if not path:
        return None
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.relpath(os.path.abspath(path), root).replace(os.sep, "/")


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--address", default="")
    # No default. A default of "visa" meant that pointing this at a
    # COM port reported "No VISA backend could open 'COM3'" - which
    # blames the backend for a transport choice the tool made silently.
    parser.add_argument("--transport", default=None, choices=TRANSPORTS)
    parser.add_argument("--tiers", default="1,2,3")
    parser.add_argument("--out", default="checkups")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--nplc", type=float, default=None,
                        help="integration time for the Tier 3 measurements. "
                             "Defaults to the fast end of the model's range. "
                             "Run twice at different values and the "
                             "difference in 'time per reading' is what an "
                             "aperture actually costs on that instrument.")
    parser.add_argument("--trace", action="store_true",
                        help="log every command and reply with its elapsed "
                             "time, and include the trace in the report. Use "
                             "when a check hangs or times out and the result "
                             "alone does not say which command did it.")
    parser.add_argument("--sample-connected", action="store_true",
                        help="something IS attached; skip the open-circuit "
                             "checks rather than warning about them")
    args = parser.parse_args()

    if args.list:
        print("Addresses visible to each transport:\n")
        list_addresses()
        return 0

    if args.transport is None and args.address and not args.demo:
        inferred = inferred_transport(args.address)
        if inferred is not None:
            args.transport = inferred
            print(f"Address looks like a VISA resource; using "
                  f"--transport {inferred}.")
        else:
            options = " or ".join(f"--transport {t}"
                                  for t in PORT_TRANSPORTS)
            parser.error(
                f"{args.address!r} is not a VISA resource string, so the "
                f"transport has to be stated: {options}.\n"
                f"  The Undalogic miniSMU needs 'minismu' - it is driven "
                f"through its own Python library, not VISA.\n"
                f"  Run --list to see which transport finds which address.")

    if args.demo:
        args.transport = "demo"
        args.address = args.address or "demo"
        # The simulated instrument models a resistor across its
        # terminals, so it is never an open circuit. Saying so keeps a
        # demo run a clean pass, which is what makes it usable as a
        # self-test of this tool.
        args.sample_connected = True

    open_circuit = not args.sample_connected

    if not args.address:
        parser.error("--address is required (or use --demo, or --list)")

    tiers = tuple(int(t) for t in args.tiers.split(",") if t.strip())

    if args.transport != "demo" and 3 in tiers and open_circuit:
        print(BANNER)
        answer = input("Nothing connected to the output? [y/N] ").strip().lower()
        if answer != "y":
            print("Stopping. Re-run with --tiers 1,2 to skip the sourcing "
                  "checks.")
            return 1

    log = (lambda text: None) if args.quiet else print

    transport = TRANSPORTS[args.transport]()
    log(f"Connecting to {args.address} over {args.transport}...")
    try:
        transport.connect(args.address)
    except Exception as exc:
        print(f"Could not connect: {exc}")
        return 1

    trace = []
    if args.trace:
        install_trace(transport, trace)

    try:
        try:
            driver, idn = identify(transport)
        except TypeError as exc:
            # A driver refusing the transport it was handed. The
            # miniSMU does this, because it answers *IDN? over plain
            # serial and would otherwise be detected on a transport it
            # cannot drive.
            print(f"Connected and identified, but: {exc}")
            return 1
        except UnknownInstrumentError as exc:
            # Worth its own message: the instrument is alive and
            # answering, so this is a MODEL_IDS problem rather than a
            # connection one, and the reply is the thing needed to fix
            # it. Two drivers currently carry provisional MODEL_IDS.
            print(f"Connected and it replied, but no driver claims it:\n"
                  f"  {exc}\n"
                  f"Add that string's model field to the right driver's "
                  f"MODEL_IDS.")
            return 1
        driver_cls = type(driver)
        log(f"Detected: {driver_cls.DISPLAY_NAME}")
        log(f"Identity: {idn}")

        checkup = Checkup(driver, log=log, open_circuit=open_circuit,
                          nplc=args.nplc)
        checkup.run(tiers=tiers)
        results = checkup.results
        sensing_note = checkup._sensing_note
    finally:
        try:
            transport.close()
        except Exception:
            pass

    # Taken after the session, not before: a report describes the code
    # that ran, and nothing here edits the tree mid-run.
    provenance = describe(idn=idn,
                          code_paths=code_paths_for(_driver_source(driver_cls)))
    report = build_report(driver, results, args.address, sensing_note,
                          open_circuit=open_circuit, provenance=provenance)
    os.makedirs(args.out, exist_ok=True)
    stem = (f"checkup_{driver_cls.__name__}_"
            f"{time.strftime('%Y%m%d_%H%M%S')}")
    md_path = os.path.join(args.out, stem + ".md")
    json_path = os.path.join(args.out, stem + ".json")

    if trace:
        report += "\n## Command trace\n\n```\n"
        for elapsed, sent, reply in trace:
            report += f"{elapsed * 1000:8.1f} ms  {sent}\n"
            if reply:
                report += f"{'':11}  -> {reply}\n"
        report += "```\n"

    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(report)
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump({"driver": driver_cls.__name__,
                   "display_name": driver_cls.DISPLAY_NAME,
                   "identity": idn,
                   "address": args.address,
                   "transport": args.transport,
                   # Whether the open-circuit checks were meaningful.
                   # It was only in the Markdown prose before, which
                   # meant the JSON could not be read on its own - and
                   # the JSON is the half people send to someone else.
                   "open_circuit": open_circuit,
                   "tiers": list(tiers),
                   "requested_nplc": args.nplc,
                   "trace": [{"elapsed_s": e, "sent": c, "reply": r}
                             for e, c, r in trace],
                   "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   # Which code and which firmware this describes. Both
                   # were missing until 2026-08-20, and working out
                   # what had changed between two reports cost five
                   # rounds of hypotheses that a commit sha would have
                   # settled in one line.
                   **provenance,
                   "results": [r.as_dict() for r in results]},
                  handle, indent=2)

    counts = checkup.counts()
    print(f"\n{counts['pass']} passed, {counts['warn']} warned, "
          f"{counts['fail']} failed, {counts['skip']} skipped")
    print(f"Report:  {md_path}")
    print(f"JSON:    {json_path}")
    if counts["fail"]:
        print("\nFailures:")
        for result in results:
            if result.severity == "fail":
                print(f"  - {result.name}: {result.detail}")
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
