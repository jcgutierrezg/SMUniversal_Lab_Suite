"""The 487 trigger probe, run against the fake instrument.

The tool exists to count lost readings and capture what the instrument
says after each one, so the path that matters most is the one a clean
fake never takes: a reading that does not come, a reconnect, the status
words read before anything can clear them, and the session carrying on.
"""
from test_keithley487 import Fake487

from tools.bench_487_trigger import (
    DELAYS_S,
    INTEGRATIONS,
    LEVELS,
    THREADS,
    TriggerProbe,
    build_report,
    condition_key,
    trials,
)


class LosesEveryTenthReading(Fake487):
    """A reading that never comes, now and then - with a flag left
    behind so the words read afterwards have something to show."""

    reading_talks = 0       # across reconnects: one count per session

    def _read(self, timeout_s):
        if self.pending is None and self.state["T"] == "1":
            type(self).reading_talks += 1
            if type(self).reading_talks % 10 == 0:
                self.u1[4] = 1
                raise TimeoutError("no reading")
        return super()._read(timeout_s)


#: What belongs to the instrument rather than to one connection to it.
#: A reconnect reaches the same 487, latched flags and all, so each new
#: fake transport starts from the last one's.
INSTRUMENT = ("state", "u1", "u9", "level", "v_range", "v_limit",
              "autorange", "m_range", "delay", "last_reading", "converting")


def probe_with(fake_class, repeats=2):
    made = []

    def connect():
        transport = fake_class(resistance=1e6)
        if made:
            for name in INSTRUMENT:
                setattr(transport, name, getattr(made[-1], name))
        made.append(transport)
        return transport

    probe = TriggerProbe(connect, repeats=repeats, seed=7,
                         log=lambda message: None,
                         sleep=lambda seconds: None)
    probe.run()
    return probe, made


def test_every_condition_is_asked_for_and_shuffled(check):
    plan = trials(3, seed=1)
    per_cell = len(INTEGRATIONS) * len(THREADS)
    check("every cell, three times each",
          len(plan) == 3 * per_cell * (len(DELAYS_S) * len(LEVELS) + 1),
          f"{len(plan)}")
    check("the same seed, the same order", plan == trials(3, seed=1))
    check("shuffled", plan != sorted(plan, key=lambda t: str(t)))


def test_a_clean_session(check):
    probe, made = probe_with(Fake487)
    check("every trial ran", len(probe.results) == len(probe.plan))
    check("nothing lost", not probe.losses)
    check("one connection", len(made) == 1)
    check("finished", probe.stopped is None, f"{probe.stopped}")
    check("output off at the end", made[-1].state["O"] == "0")
    check("both threads ran", {r["thread"] for r in probe.results}
          == set(THREADS))


def test_a_lost_reading_is_counted_and_its_words_kept(check):
    LosesEveryTenthReading.reading_talks = 0
    probe, made = probe_with(LosesEveryTenthReading)
    check("every trial still ran", len(probe.results) == len(probe.plan),
          f"{len(probe.results)} of {len(probe.plan)}")
    check("losses were counted", len(probe.losses) >= 5,
          f"{len(probe.losses)}")
    check("a fresh connection after each",
          len(made) == len(probe.losses) + 1,
          f"{len(made)} connections, {len(probe.losses)} losses")
    first = probe.losses[0]["words_after"] if probe.losses else {}
    check("the words were read before any reset could clear them",
          first.get("U1", "").startswith("4870000100"), f"{first}")
    check("all three words", set(first) == {"U1", "U9", "U0"}, f"{first}")
    check("finished", probe.stopped is None, f"{probe.stopped}")
    check("output off at the end", made[-1].state["O"] == "0")

    summary = probe.summary()
    check("the losses add up by condition",
          sum(lost for _, lost in summary.values()) == len(probe.losses))
    report = build_report(probe, "487B07", "GPIB0::3::INSTR", {})
    check("the report lists each", report.count("Read after it:")
          == len(probe.losses))
    check("and keys them by condition",
          " / ".join(map(str, condition_key(probe.losses[0])))
          in report)
