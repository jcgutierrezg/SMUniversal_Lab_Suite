"""
Is the missing reply LATE, or is it GONE?

    uv run python tools/probes/20h10_late_reply.py --address <addr>

Run this only when `20h10_burst_then_one_query.txt` has died on its
query with a 30 s budget. If that script completed, the reply is merely
slow and this probe has nothing to add.

WHY THIS CANNOT BE DONE AT THE CONSOLE
--------------------------------------
`Transport.query()` latches on any failed exchange and every later call
raises, which is correct for a measurement and fatal for this question:
after the timeout there is exactly one thing worth doing, and that is
to keep reading. So this probe talks to pyvisa directly.

**It therefore has no desync protection at all.** Nothing it prints is a
measurement, and no value read after the first timeout may be believed
as an answer to the question that asked for it. That is the point - the
probe exists to find out whether such a value appears.

WHAT IT DECIDES
---------------
Three outcomes, and they point at three different fixes:

  the reply arrives on a later read attempt
      The instrument answered and the first read gave up too early.
      The backend's timeout is the fault; a longer budget at this one
      position is a real fix.

  no reply, and a following *IDN? returns the ERROR QUEUE text
      The reply existed and the stream is one behind - the desync this
      project has documented since 2026-08-24, caught in the act rather
      than inferred from timing. The latch is right and the fix is to
      stop asking here.

  no reply, and *IDN? returns the identity
      The instrument never answered and the link stayed in step. The
      query was simply not serviced at that moment, and no budget and
      no retry will help. Do not ask at this position.

Run it several times. The fault is intermittent; a clean pass means the
burst did not trip it that time, not that it cannot.
"""
import argparse
import sys
import time

BURST = [
    "*CLS", "*RST", "SYST:CLE", "SYST:BEEP:STAT 1", "OUTP:ENAB 0",
    "SYST:LFR:AUTO 1", "SOUR:CLE:AUTO 0", "ROUT:TERM FRON",
    "TRAC:FEED:CONT NEV", "FORM:ELEM VOLT,CURR",
    'SENS:FUNC:CONC ON', 'SENS:FUNC:ON "VOLT","CURR"', "SOUR:FUNC VOLT",
    "SOUR:CLE:AUTO 0", "SOUR:VOLT:RANG:AUTO OFF",
    "SOUR:VOLT:RANG 8.000000e-01", "SENS:CURR:DC:RANG:AUTO OFF",
    "SENS:CURR:DC:RANG 1.000000e-01", "SENS:VOLT:DC:RANG:AUTO ON",
    "SENS:CURR:DC:PROT:LEV 1.000000e-01", "SYST:RSEN 0",
    "SENS:CURR:DC:NPLC 1.0000", "SENS:VOLT:DC:NPLC 1.0000",
    "OUTP:SMOD NORM", "SOUR:VOLT:PROT 20 V",
]
QUERY = "SYST:ERR:ALL?"


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--attempts", type=int, default=30,
                        help="1 s read attempts after the write (default 30)")
    args = parser.parse_args()

    import pyvisa
    # Same order the suite uses: vendor VISA if one is installed, then
    # pyvisa-py. Which one answers is itself a finding - the note
    # attributes this fault to libusb-win32, and that attribution is
    # only as current as the last time anyone checked.
    resource = None
    for spec in ("", "@py"):
        try:
            rm = pyvisa.ResourceManager(spec) if spec \
                else pyvisa.ResourceManager()
            resource = rm.open_resource(args.address)
            print(f"backend: {spec or '(vendor default)'}")
            break
        except Exception as exc:
            print(f"backend {spec or '(vendor default)'}: {exc}")
    if resource is None:
        print("No backend could open that address.")
        return 1

    resource.timeout = 3000
    print(f"sending {len(BURST)} writes with no read between them...")
    for command in BURST:
        resource.write(command)

    print(f"writing {QUERY} and then reading, 1 s at a time\n")
    resource.timeout = 1000
    resource.write(QUERY)
    started = time.perf_counter()

    reply = None
    for attempt in range(1, args.attempts + 1):
        try:
            reply = resource.read()
        except Exception as exc:
            print(f"  attempt {attempt:>2}  "
                  f"{time.perf_counter() - started:5.2f} s  "
                  f"{type(exc).__name__}")
            continue
        print(f"  attempt {attempt:>2}  "
              f"{time.perf_counter() - started:5.2f} s  -> {reply.strip()!r}")
        break

    if reply is not None:
        if attempt == 1:
            print("\nThe reply arrived first time. The burst did not trip "
                  "the fault on this run - repeat it.")
        else:
            print(f"\nLATE, not gone: the reply needed {attempt} attempts "
                  f"({time.perf_counter() - started:.2f} s). The read gave "
                  f"up too early.")
        resource.close()
        return 0

    # Nothing came back. Ask a question whose answer is unmistakable, and
    # see which question the instrument answers.
    print(f"\nno reply in {args.attempts} attempts. Asking *IDN? - if the "
          f"identity comes back, the link is in step and the reply to "
          f"{QUERY} was never sent. If the ERROR QUEUE comes back "
          f"instead, it existed and the stream is one behind.")
    resource.timeout = 3000
    try:
        resource.write("*IDN?")
        answer = resource.read().strip()
    except Exception as exc:
        print(f"  *IDN? also failed: {type(exc).__name__}: {exc}")
        print("  The link is not answering at all. Power-cycle before "
              "reading anything else into this.")
        resource.close()
        return 1

    print(f"  *IDN? -> {answer!r}")
    if "GSM" in answer.upper() or "INSTEK" in answer.upper():
        print("\nIN STEP. The instrument did not answer the error queue at "
              "that moment and there is nothing to wait for. Do not ask "
              "at this position.")
    else:
        print("\nONE BEHIND. That is the error-queue reply arriving late, "
              "which is the desync mechanism caught in the act. The latch "
              "is right; the fix is not to ask here.")
    resource.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
