"""Every traced exchange says when it began, not only how long it took.

Two Keithley 487 checkups on 2026-10-14 lost a reading at a step whose
commands matched a passing run's exactly, with bus timings within 3 ms.
What could still differ was the time between commands, and a trace of
durations cannot show that. Each entry now carries its start, and is
still the `(elapsed, sent, reply)` three-tuple every reader unpacks.
"""
import json
import sys

from test_keithley487 import Fake487

from tools.smu_checkup import TraceEntry, install_trace, trace_times


def test_an_entry_is_still_a_three_tuple(check):
    entry = TraceEntry(0.005, "O1X", "", 12.5)
    elapsed, sent, reply = entry
    check("unpacks as before", (elapsed, sent, reply) == (0.005, "O1X", ""))
    check("and carries its start", entry.at == 12.5)


def test_each_exchange_records_when_it_began(check):
    transport = Fake487()
    trace = []
    install_trace(transport, trace)
    transport.write("O0X")
    transport.query("U1X")
    transport.read()
    times = trace_times(trace)
    check("three entries", len(trace) == 3, f"{trace}")
    check("from zero", times[0] == 0.0, f"{times}")
    check("in order", times == sorted(times), f"{times}")
    check("every kind of call", all(getattr(e, "at", None) is not None
                                    for e in trace))


def test_an_entry_without_a_start_reads_as_none(check):
    """A list built by hand, as the older tests do, still renders."""
    check("none", trace_times([(0.001, "X", "")]) == [None])


def test_the_checkup_json_carries_them(check, tmp_path, monkeypatch):
    import tools.smu_checkup as cli

    monkeypatch.setattr(sys, "argv", [
        "smu_checkup", "--demo", "--quiet", "--trace", "--out",
        str(tmp_path)])
    cli.main()
    written = list(tmp_path.glob("*.json"))
    check("one report", len(written) == 1, f"{written}")
    trace = json.loads(written[0].read_text(encoding="utf-8"))["trace"]
    check("every entry has a start", trace and all(
        "at_s" in e for e in trace))
    starts = [e["at_s"] for e in trace if e["at_s"] is not None]
    check("from zero, in order", starts and starts[0] == 0.0
          and starts == sorted(starts))
    md = written[0].with_suffix(".md").read_text(encoding="utf-8")
    check("and the Markdown shows them", "s from the first" in md)
