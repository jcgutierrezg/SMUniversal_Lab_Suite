"""`scpi_console` must know which lines produce a reply.

SCPI marks queries with `?`. TSP marks them not at all: a TSP
instrument answers when the script calls `print()` and stays silent
otherwise. The console classified on `?` alone, so every `print(...)`
was sent as a write.

The consequence is worse than a missing answer. The instrument still
generates the reply, so it sits in the output buffer and the next real
query reads the *previous* line's answer - every result after it off by
one, silently, and each one looking entirely plausible. This project's
recurring failure mode, this time in the tool used to diagnose it.

Found while writing tools/probes/2635b_reading_time.txt, which is
nothing but `print()` lines and would have returned no timings at all.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from scpi_console import looks_like_query


def test_scpi_queries_are_recognised(check):
    for line in (":SYST:ERR?", "*IDN?", ":SENS:CURR:PROT:TRIP?"):
        check(f"{line} is a query", looks_like_query(line))


def test_tsp_prints_are_recognised(check):
    """The bug. Every one of these generates a response message."""
    for line in ("print(smua.measure.iv())",
                 "print(errorqueue.next())",
                 "printbuffer(1, 5, smua.nvbuffer1)",
                 "printnumber(smua.measure.v())",
                 'print("label", timer.measure.t())'):
        check(f"{line[:34]} is a query", looks_like_query(line),
              "sent as a write, its reply would desynchronise the bus")


def test_tsp_writes_are_not_mistaken_for_queries(check):
    """The other direction matters too: reading after a line that says
    nothing blocks until the VISA timeout and looks like a dead
    instrument."""
    for line in ("reset()", "errorqueue.clear()",
                 "smua.source.output = smua.OUTPUT_ON",
                 "smua.measure.nplc = 1.0",
                 "format.asciiprecision = 16"):
        check(f"{line[:34]} is a write", not looks_like_query(line))


def test_a_print_at_the_end_of_a_compound_line_still_counts(check):
    """The timing probe puts a whole loop on one line and prints at the
    end - the shape TSP encourages, and the one a naive check misses."""
    line = ("timer.reset() for i = 1, 20 do smua.measure.iv() end "
            'print("1 baseline", timer.measure.t())')
    check("compound line with a trailing print", looks_like_query(line))


def test_a_word_ending_in_print_is_not_a_query(check):
    """`sprint(` or a variable named `footprint` must not trip it, or
    the console starts waiting for replies that never come."""
    check("footprint(", not looks_like_query("footprint(3)"))
    check("blueprint(", not looks_like_query("x = blueprint(1)"))


# --- probe scripts must not desynchronise the bus -------------------

PROBES = sorted((Path(__file__).resolve().parent.parent
                 / "tools" / "probes").glob("*.txt"))

def test_no_probe_prints_inside_a_loop(check):
    """The fault the console fix was for, reintroduced one level up.

    `for i = 1, 20 do print(1) end` generates twenty response messages
    where the reader takes one. The nineteen left behind desynchronise
    everything after, silently and plausibly - which is exactly what
    happened to sections 7 and 8 of the 2635B timing probe, and was
    only noticed because section 8 returned a number that could not
    have been a measurement.

    A print at the end of a loop line is fine, and is the shape these
    probes use: run the loop, then print once.
    """
    if not PROBES:
        pytest.skip("no probe scripts yet")

    for probe in PROBES:
        for number, line in enumerate(
                probe.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            body = stripped.split(" do ", 1)[-1] if " do " in stripped else ""
            inner = body.split(" end", 1)[0] if " end" in body else ""
            check(f"{probe.name}:{number} prints outside its loop",
                  "print(" not in inner,
                  f"{stripped[:90]}\n  a print inside the loop sends one "
                  f"reply per iteration; the reader takes one and every "
                  f"reply after it is off by one")
