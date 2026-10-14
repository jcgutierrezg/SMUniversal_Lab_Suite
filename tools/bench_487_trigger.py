"""
Which Keithley 487 readings are lost, and after what.

On 2026-10-14 two checkup runs lost a reading - the talk that should
have carried it timed out - at the same step: the first point of the
software sweep. Every other reading in three runs came back, the same
sequence included. Two losses in thirty-one talks cannot say whether
what matters is the time since the source command, re-sending a level
the source already holds, the sweep's worker thread, or the integration
period. This asks, a few hundred times, with each varied on its own.

    uv run tools/bench_487_trigger.py --address GPIB0::3::INSTR

**Nothing connected to the output.** It sources 0 V and 0.1 V into an
open circuit, on the 50 V range with the 25 uA limit, and switches the
output off at the end and on any error or Ctrl-C.

What one trial is
-----------------
Exactly what a sweep point does, through the driver:
`set_voltage_level()`, a wait, then `measure()` - which sends `T1X`,
takes the talk that triggers and carries the reading, and sends `T3X`.
The talk is given a short timeout, so a lost reading costs about a
second rather than three.

The conditions, crossed:

  W           the instrument's own trigger delay, 0 or 10 ms - the
              checkup leaves 10 ms in force, and every lost reading so
              far was taken with it
  delay       0, 10, 50 or 100 ms between the level and the reading
  level       changed (alternating 0 and 0.1 V) or re-sent unchanged
  thread      the main thread, or a worker thread like the sweep's
  integration fast (S0) or line cycle (S1)

plus a control with no level command at all. The trials are shuffled,
with the seed recorded, so a slow drift over the session cannot pass
for a condition.

After a lost reading
--------------------
The link is out of step and the transport refuses to read again, as it
must. So the tool closes it, connects afresh, and reads `U1`, `U9` and
`U0` **before** anything else - the driver's reset would read and set
aside exactly the flags that say what happened. Then it resets,
reconfigures, and carries on.

It does not interpret. The report counts losses per condition and lists
each with the words read after it; what they mean is decided afterwards.
"""
import argparse
import datetime
import json
import os
import random
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smuniversal_lab_suite.core.provenance import (  # noqa: E402
    as_markdown_lines,
    code_paths_for,
    describe,
)
from smuniversal_lab_suite.core.ranges import RangePlan  # noqa: E402
from smuniversal_lab_suite.core.transports.base import (  # noqa: E402
    TransportDesynchronised,
)
from smuniversal_lab_suite.drivers.keithley_487 import (
    Keithley487,  # noqa: E402
)
from tools.smu_checkup import (  # noqa: E402
    TRANSPORTS,
    _driver_source,
    inferred_transport,
    install_trace,
    trace_times,
)

#: The two levels, in volts. Small, into nothing.
LOW_V, HIGH_V = 0.0, 0.1

#: The current limit and the measurement range the checkup used when it
#: lost its readings: 25 uA, which puts the ammeter on 200 uA.
LIMIT_A = 25e-6

DELAYS_S = (0.0, 0.010, 0.050, 0.100)
LEVELS = ("changed", "same")

#: The instrument's own trigger delay (`W`), in seconds. The checkup
#: leaves 10 ms in force through every reading it lost, because its
#: tier 2 checks `set_source_delay(0.01)` and nothing clears it; the
#: first run of this probe had none, and lost nothing in 720.
TRIGGER_DELAYS_S = (0.0, 0.010)
THREADS = ("main", "worker")
INTEGRATIONS = (("fast", 0.1), ("line", 1.0))

#: Per condition. 4 x 2 x 2 x 2 x 2 cells and the controls at 12 each
#: is about 860 readings - three to four minutes if nothing is lost.
REPEATS = 12

#: The timeout on the talk that carries a reading. Ordinary readings
#: take 50 to 80 ms here.
TALK_TIMEOUT_S = 1.0


def trials(repeats, seed):
    """Every trial, shuffled. Each is a dict naming its condition."""
    plan = []
    for trigger_delay in TRIGGER_DELAYS_S:
        w = round(trigger_delay * 1000)
        for integration, _ in INTEGRATIONS:
            for thread in THREADS:
                for delay in DELAYS_S:
                    for level in LEVELS:
                        plan += [{"trigger_delay_ms": w,
                                  "integration": integration,
                                  "thread": thread,
                                  "delay_ms": round(delay * 1000),
                                  "level": level}] * repeats
                plan += [{"trigger_delay_ms": w, "integration": integration,
                          "thread": thread, "delay_ms": None,
                          "level": "none"}] * repeats
    # Trial order, not a secret: a seeded generator is the point.
    random.Random(seed).shuffle(plan)  # noqa: S311
    return [dict(trial) for trial in plan]


def condition_key(trial):
    delay = "-" if trial["delay_ms"] is None else f"{trial['delay_ms']} ms"
    return (f"W {trial['trigger_delay_ms']} ms", trial["integration"],
            trial["thread"], trial["level"], delay)


class TriggerProbe:
    """One session. `connect()` returns a connected transport, and is
    called again after every lost reading."""

    def __init__(self, connect, repeats=REPEATS, seed=None, trace=None,
                 log=print, sleep=time.sleep):
        self.connect = connect
        self.seed = seed if seed is not None else int(time.time())
        self.plan = trials(repeats, self.seed)
        self.trace = trace
        self.log = log
        self.sleep = sleep
        self.results = []
        self.losses = []
        self.driver = None
        self.integration = None
        self.trigger_delay = None
        self.level = LOW_V
        self.stopped = None

    # ---- the instrument --------------------------------------------
    def _open(self):
        transport = self.connect()
        if self.trace is not None:
            install_trace(transport, self.trace)
        self.driver = Keithley487(transport)
        return transport

    def _configure(self):
        driver = self.driver
        driver.reset()
        driver.set_source_function("voltage")
        driver.apply_ranges(RangePlan.for_sourcing(
            "voltage", source_range=HIGH_V, measure_range=LIMIT_A),
            log=lambda message: None)
        driver.set_current_limit(LIMIT_A)
        driver.set_voltage_level(LOW_V)
        self.level = LOW_V
        self.integration = None
        self.trigger_delay = None
        driver.output_on()

    def _words_after_a_loss(self):
        """Reconnect and read the status words before anything else."""
        try:
            self.driver.transport.close()
        except Exception:
            pass
        transport = self._open()
        words = {}
        for which in (1, 9, 0):
            try:
                words[f"U{which}"] = str(transport.query(
                    f"U{which}X", timeout_s=3.0)).strip()
            except TransportDesynchronised as exc:
                # The fresh link is out of step too: the session is over.
                # What was read is kept on the exception for the report.
                words[f"U{which}"] = f"!! {type(exc).__name__}: {exc}"
                exc.words_after = words
                raise
            except Exception as exc:
                words[f"U{which}"] = f"!! {type(exc).__name__}: {exc}"
                break
        return words

    # ---- one trial -------------------------------------------------
    def _set_integration(self, name):
        if name != self.integration:
            self.driver.set_nplc(dict(INTEGRATIONS)[name])
            self.integration = name

    def _body(self, trial, outcome):
        driver = self.driver
        try:
            if trial["level"] != "none":
                if trial["level"] == "changed":
                    self.level = HIGH_V if self.level == LOW_V else LOW_V
                driver.set_voltage_level(self.level)
                if trial["delay_ms"]:
                    self.sleep(trial["delay_ms"] / 1000)
            started = time.perf_counter()
            _, amps = driver.measure(timeout_s=TALK_TIMEOUT_S)
            outcome["talk_ms"] = round(
                (time.perf_counter() - started) * 1000, 1)
            outcome["amps"] = amps
        except Exception as exc:
            outcome["error"] = exc

    def _set_trigger_delay(self, milliseconds):
        # Through the driver, as the checkup sets it: `set_source_delay`
        # is the instrument's W command.
        if milliseconds != self.trigger_delay:
            self.driver.set_source_delay(milliseconds / 1000)
            self.trigger_delay = milliseconds

    def run_trial(self, index, trial):
        self._set_trigger_delay(trial["trigger_delay_ms"])
        self._set_integration(trial["integration"])
        outcome = {}
        if trial["thread"] == "worker":
            worker = threading.Thread(target=self._body,
                                      args=(trial, outcome))
            worker.start()
            worker.join()
        else:
            self._body(trial, outcome)

        row = {**trial, "index": index, "level_v": self.level,
               "talk_ms": outcome.get("talk_ms"),
               "amps": outcome.get("amps"), "lost": False}
        error = outcome.get("error")
        if error is None:
            self.results.append(row)
            return
        if not isinstance(error, TransportDesynchronised):
            raise error
        row["lost"] = True
        row["error"] = f"{type(error).__name__}: {error}"
        self.results.append(row)
        try:
            words = self._words_after_a_loss()
        except TransportDesynchronised as exc:
            self.losses.append({**row, "words_after":
                                getattr(exc, "words_after", {})})
            raise
        self.losses.append({**row, "words_after": words})
        self.log(f"  lost #{len(self.losses)} at trial {index}: "
                 f"{condition_key(trial)} - {words}")
        self._configure()

    # ---- the session -----------------------------------------------
    def run(self):
        self._open()
        try:
            self._configure()
            for index, trial in enumerate(self.plan):
                self.run_trial(index, trial)
                if index % 50 == 49:
                    self.log(f"  {index + 1} of {len(self.plan)}, "
                             f"{len(self.losses)} lost")
        except KeyboardInterrupt:
            self.stopped = "interrupted by Ctrl-C"
        except Exception as exc:
            self.stopped = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                self.driver.safe_output_off()
            finally:
                try:
                    self.driver.transport.close()
                except Exception:
                    pass
        return self.results

    # ---- what came back --------------------------------------------
    def summary(self):
        """{condition: (trials, lost)}, in a stable order."""
        counts = {}
        for row in self.results:
            key = condition_key(row)
            total, lost = counts.get(key, (0, 0))
            counts[key] = (total + 1, lost + int(row["lost"]))
        return dict(sorted(counts.items(), key=lambda kv: kv[0]))


def build_report(probe, idn, address, provenance):
    rows = probe.summary()
    taken = len(probe.results)
    lost = len(probe.losses)
    lines = [
        "# Keithley 487 - which readings are lost",
        "",
        f"- **When:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Address:** {address}",
        f"- **Identity:** {idn}",
        *as_markdown_lines(provenance or {}),
        f"- **Seed:** {probe.seed} (trial order)",
        f"- **Readings:** {taken} asked for, {lost} lost "
        f"({(lost / taken * 100) if taken else 0:.1f}%)",
        f"- **Talk timeout:** {TALK_TIMEOUT_S:g} s",
        "",
    ]
    if probe.stopped:
        lines += [f"> **Did not finish:** {probe.stopped}. Everything "
                  f"below was taken before that.", ""]
    lines += ["## By condition", "",
              "| Trigger delay | Integration | Thread | Level | Delay "
              "| Readings | Lost |",
              "|---|---|---|---|---|---|---|"]
    for (w, integration, thread, level, delay), (total, gone) in \
            rows.items():
        mark = f"**{gone}**" if gone else "0"
        lines.append(f"| {w} | {integration} | {thread} | {level} | "
                     f"{delay} | {total} | {mark} |")
    lines += ["", "## Each lost reading", ""]
    if not probe.losses:
        lines.append("None.")
    for number, loss in enumerate(probe.losses, 1):
        words = ", ".join(f"`{k}` = `{v}`"
                          for k, v in loss["words_after"].items())
        lines += [f"{number}. trial {loss['index']}: "
                  f"{' / '.join(map(str, condition_key(loss)))}, "
                  f"level {loss['level_v']:g} V. Read after it: {words}"]
    timings = [r["talk_ms"] for r in probe.results if r["talk_ms"]]
    if timings:
        timings.sort()
        lines += ["", "## Reading times", "",
                  "Each is `measure()` whole - `T1X`, the talk, `T3X`.",
                  "",
                  f"Fastest {timings[0]:g} ms, median "
                  f"{timings[len(timings) // 2]:g} ms, slowest "
                  f"{timings[-1]:g} ms, over {len(timings)} readings that "
                  f"came back."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--address", required=True)
    parser.add_argument("--transport", default=None, choices=TRANSPORTS)
    parser.add_argument("--out", default="checkups")
    parser.add_argument("--repeats", type=int, default=REPEATS,
                        help=f"readings per condition (default {REPEATS})")
    parser.add_argument("--seed", type=int, default=None,
                        help="trial order; recorded in the report")
    args = parser.parse_args()

    transport_name = args.transport or inferred_transport(args.address)
    if transport_name is None:
        parser.error(f"{args.address!r} is not a VISA resource string, so "
                     f"--transport has to be given.")

    def connect():
        transport = TRANSPORTS[transport_name]()
        transport.connect(args.address)
        return transport

    print("Nothing may be connected to the 487's output: it sources 0.1 V "
          "into an open circuit.")
    if input("Is the output unconnected? [y/N] ").strip().lower() != "y":
        return 1

    trace = []
    probe = TriggerProbe(connect, repeats=args.repeats, seed=args.seed,
                         trace=trace)
    print(f"{len(probe.plan)} readings, seed {probe.seed}.")
    probe.run()
    idn = "not read"
    try:
        idn = next(r for _, s, r in trace if s.startswith("U2X"))
    except StopIteration:
        pass
    provenance = describe(idn=idn, code_paths=code_paths_for(
        _driver_source(Keithley487), fleet="smu"))

    stem = f"trigger_probe_Keithley487_{time.strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(args.out, exist_ok=True)
    md_path = os.path.join(args.out, stem + ".md")
    json_path = os.path.join(args.out, stem + ".json")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(build_report(probe, idn, args.address, provenance))
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump({
            "when": datetime.datetime.now().isoformat(timespec="seconds"),
            "address": args.address, "identity": idn,
            "provenance": provenance, "seed": probe.seed,
            "stopped": probe.stopped,
            "summary": [{"condition": list(k), "readings": t, "lost": g}
                        for k, (t, g) in probe.summary().items()],
            "losses": probe.losses, "results": probe.results,
            "trace": [{"at_s": at, "ms": round(e * 1000, 1), "sent": s,
                       "reply": r}
                      for (e, s, r), at in zip(trace, trace_times(trace))],
        }, handle, indent=2, default=repr)
    print(f"\n{len(probe.losses)} of {len(probe.results)} readings lost.")
    print(f"Wrote {md_path}\n      {json_path}")
    print("Bring both back, whole.")
    return 0 if not probe.stopped else 1


if __name__ == "__main__":
    sys.exit(main())
