"""The operational log: that a run happened, never what it measured.

Review §26. The finding is that discarding a cancelled run's readings
should not also discard the evidence that a cancellation happened. The
boundary attached to it is just as load-bearing: provisional
measurements must not appear in the operational log, because a cancelled
run's readings are the ones taken before somebody hit Stop, and a file
full of them sitting near real exports is a mistake waiting to be made.

So there are two properties here, and the second is the one worth
guarding hardest:

  1. every run ends up in the log - completed, cancelled or failed;
  2. no reading value ever does.

The second is tested by putting a value that appears nowhere else into a
run's readings and asserting it appears nowhere in the log text. That
catches a leak through any field, including one added later by somebody
who did not read this docstring - which is the only kind of guard worth
having against a rule a future edit will not remember.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.event_log import (EVENT_SCHEMA, EventLog, build_event,  # noqa: E402
                            parameter_fingerprint, sample_identity)
from core.run_control import (Outcome, RunController, ShutdownReport,  # noqa: E402
                              ShutdownStatus, TerminalStatus)
#: A confirmed shutdown, which the default completion policy requires.
CONFIRMED = ShutdownReport(ShutdownStatus.CONFIRMED)
from core import version  # noqa: E402
from core.version import app_version, build_id  # noqa: E402


class FakeSample:
    sample_id = "smp-20260808-abcd"
    label = "wafer_A"
    slug = "wafer_A"


@dataclasses.dataclass
class TypedParams:
    """Shaped like the three experiments that pass a dataclass."""
    sample: object
    voltage_V: float = 1.5
    points: int = 11


def _drive(run, rows=1):
    """The shortest legal path to a commit.

    The completion policy requires readings and a confirmed shutdown, so
    a run that merely starts and commits is *rejected* - which is the
    policy working, and is why this helper exists rather than each test
    inventing its own shortcut.
    """
    run.start()
    for n in range(rows):
        run.add_reading({"point": n})
    run.note_shutdown(CONFIRMED)
    return run.commit(f"result-{run.run_id}", lambda built: None)


def status(outcome=Outcome.COMPLETED, **kw):
    kw.setdefault("run_id", "run-1")
    kw.setdefault("stage", "sweeping")
    return TerminalStatus(outcome=outcome, **kw)


@pytest.fixture
def log(tmp_path):
    return EventLog(tmp_path / "events.jsonl")


# ------------------------------------------------------------------
# the boundary: no scientific data
# ------------------------------------------------------------------

#: A value that appears nowhere in this project but the discarded
#: readings below. Absence of it in the log file is the whole assertion,
#: so it has to be genuinely *reachable* from what the log is handed -
#: otherwise "it is not in the file" is true of any code at all.
READING_MARKER = 8675309.0000042


def test_readings_are_gone_before_the_log_ever_sees_the_run(check):
    """§26's boundary, enforced structurally rather than by good manners.

    A cancelled run calls `discard()` *before* `_record`, so the context
    handed to the sink has an empty ledger. The operational log is not
    trusted to decline writing the readings; by the time it could, they
    do not exist.

    That is the difference between a rule and a guarantee, and it is
    what makes the count meaningful: `readings_discarded` is the only
    trace, which is exactly what §26 asks for.
    """
    captured = []
    controller = RunController(name="test",
                               event_sink=lambda s, c: captured.append((s, c)))

    with controller.begin(parameters={"sample": FakeSample()}) as run:
        run.start()
        for n in range(7):
            run.add_reading({"point": n, "voltage_V": READING_MARKER})
        check("the readings really were taken", len(run.readings) == 7,
              str(len(run.readings)))
        controller.request_cancel("operator")

    check("the run reached the sink", len(captured) == 1, str(len(captured)))
    status_obj, context = captured[0]
    check("the ledger is already empty at the sink",
          list(context.readings) == [], str(context.readings))
    check("and the count survived", status_obj.readings_discarded == 7,
          str(status_obj.readings_discarded))


def test_no_reading_value_reaches_the_operational_log(check, log):
    """The serialisation half: parameters are fingerprinted, not copied.

    `parameter_fingerprint` reduces the snapshot to a hash, and
    `sample_identity` takes only the id. So a parameter set carrying a
    measurement value must leave no trace of it in the file - and this
    goes red the moment any field starts transcribing its inputs
    verbatim instead.

    Written this way after a mutation round found the first version
    useless: it defined a marker, never put it anywhere reachable, and
    then checked the file did not contain it. That assertion held
    whether or not the code was correct - the most repeated fault in
    this project's history, and it had landed in the one test guarding
    the boundary §26 exists to draw.

    The gap it does not close, recorded rather than papered over:
    `metadata` *is* transcribed verbatim, by design, because an
    experiment's operator note belongs in the log. Nothing here can stop
    a caller putting a reading in it. `experiments/base_experiment.py`
    passes `context.metadata`, which holds run parameters and notes and
    never readings - but that is a property of the caller, not of this
    module.
    """
    log.record(build_event(
        status(Outcome.CANCELLED, detail="operator", readings_discarded=7),
        experiment="vanderpauw",
        sample_id=FakeSample.sample_id,
        parameters={"sample": FakeSample(),
                    "last_voltage_V": READING_MARKER,
                    "trace": [READING_MARKER, READING_MARKER]},
        metadata={"operator_note": "probe slipped"}))

    text = log.path.read_text(encoding="utf-8")
    check("the run was recorded", "run-1" in text)
    check("but no reading value is in the file",
          str(READING_MARKER) not in text, text)
    check("the parameters left a fingerprint instead",
          bool(log.read_all()[0]["parameter_fingerprint"]),
          str(log.read_all()[0]["parameter_fingerprint"]))
    check("only the count of what was discarded",
          log.read_all()[0]["readings_discarded"] == 7)


def test_a_cancelled_run_leaves_evidence_behind(check, log):
    """The finding itself.

    Before this the only trace was a console line that vanished with the
    window. "Nothing was saved" and "somebody stopped it after two
    minutes because the probe slipped" are very different explanations
    for a missing dataset.
    """
    log.record(build_event(
        status(Outcome.CANCELLED, detail="operator", readings_discarded=3),
        experiment="hall"))
    event = log.read_all()[0]
    check("the outcome is recorded", event["outcome"] == "cancelled")
    check("with the reason", event["detail"] == "operator")
    check("and the stage it got to", event["stage"] == "sweeping")


def test_an_uncertain_shutdown_is_recorded_distinctly(check, log):
    """The outcome that means "go and look at the instrument".

    `UNCERTAIN_SHUTDOWN` is separated from ordinary failure because the
    operator response differs, and it is the single most important line
    this log will ever hold: it says the output could not be confirmed
    off. It must be greppable rather than buried in a detail string.
    """
    log.record(build_event(
        status(Outcome.UNCERTAIN_SHUTDOWN,
               shutdown=ShutdownReport(ShutdownStatus.UNCERTAIN,
                                       "no reply to output query")),
        experiment="iv_sweep"))
    event = log.read_all()[0]
    check("the outcome is its own value",
          event["outcome"] == "uncertain-shutdown")
    check("the shutdown status is its own field",
          event["shutdown_status"] == "uncertain")
    check("and the reason is kept",
          "no reply" in event["shutdown_detail"])


# ------------------------------------------------------------------
# the fields §26 asks for
# ------------------------------------------------------------------

def test_every_field_the_review_asks_for_is_present(check, log):
    log.record(build_event(
        status(Outcome.FAILED, detail="TimeoutError: instrument did not reply"),
        experiment="vanderpauw",
        sample_id=FakeSample.sample_id,
        instruments={"source": "Keithley 2611A @ GPIB0::26"},
        parameters=TypedParams(FakeSample())))
    event = log.read_all()[0]
    for key in ("timestamp", "run_id", "experiment", "sample_id",
                "instruments", "parameter_fingerprint", "outcome", "stage",
                "detail", "exception_category", "shutdown_status",
                "shutdown_detail", "app_version", "build_id", "schema"):
        check(f"{key} is present", key in event, sorted(event))
    check("the version is this build's", event["app_version"] == app_version())
    check("and the build names the commit", event["build_id"] == build_id())
    check("the schema is declared", event["schema"] == EVENT_SCHEMA)


def test_the_event_records_the_build_and_not_only_the_release(check, log,
                                                             monkeypatch):
    """`run_id` joins this log to the stored CSVs, so both ends of that
    join have to agree on which code they describe.

    `app_version` did not move between waves, so on its own it could
    not tell a cancellation logged in March from one logged in
    September. Injected rather than read from the ambient tree: an
    assertion that merely compares the field against `build_id()` would
    pass just as happily if both were empty.

    `EVENT_SCHEMA` is deliberately **not** bumped. Its own rule is that
    a new key needs no bump - a reader that does not know a key simply
    does not see it, which is why this log is JSON Lines rather than
    CSV.
    """
    monkeypatch.setattr("core.provenance.head_commit",
                        lambda root=None: ("5e7308eff34a79954ab6", False, []))
    version.reset_build_id_cache()
    try:
        log.record(build_event(status(), experiment="hall"))
        event = log.read_all()[0]
        check("the injected commit reaches the line",
              event["build_id"] == f"{app_version()}+g5e7308eff34a",
              repr(event.get("build_id")))
        check("the schema did not need a bump",
              event["schema"] == EVENT_SCHEMA)
    finally:
        version.reset_build_id_cache()


def test_a_build_that_cannot_be_determined_is_still_recorded(check, log,
                                                            monkeypatch):
    """The frozen bench machine with no git and no stamp.

    Writing nothing would be the worst outcome: a line with no
    `build_id` reads as one written by code that did not record builds.
    An explicit `unknown` says the writer tried. This is the
    data-preservation path, so it must not be swallowed either - the
    event has to be written at all.
    """
    monkeypatch.setattr("core.provenance.head_commit",
                        lambda root=None: (None, False, []))
    version.reset_build_id_cache()
    try:
        check("the write succeeded",
              log.record(build_event(status(), experiment="hall")))
        event = log.read_all()[0]
        check("the key is there", "build_id" in event, sorted(event))
        check("and it says unknown",
              event["build_id"] == f"{app_version()}+unknown",
              repr(event.get("build_id")))
    finally:
        version.reset_build_id_cache()


def test_the_exception_category_is_separated_from_the_message(check, log):
    """Because you group by category and read the message.

    "Is this the same fault as last week?" is answered by the type; the
    message is usually unique to the occasion and would make every
    failure look distinct.
    """
    log.record(build_event(
        status(Outcome.FAILED, detail="TimeoutError: no reply on GPIB0::26"),
        experiment="hall"))
    event = log.read_all()[0]
    check("the category is the exception type",
          event["exception_category"] == "TimeoutError",
          event["exception_category"])
    check("and the message is kept whole",
          "GPIB0::26" in event["detail"])


def test_a_prose_reason_is_not_mistaken_for_an_exception(check, log):
    """A cancellation reason is not a type name.

    `detail` carries an operator's reason on a cancelled run and an
    exception line on a failed one. Reading the first word blindly would
    file "Operator pressed stop" under an exception category called
    `Operator`, and any grouping by category would then be wrong.
    """
    log.record(build_event(
        status(Outcome.CANCELLED, detail="Operator pressed stop"),
        experiment="hall"))
    check("no category invented", log.read_all()[0]["exception_category"] == "",
          log.read_all()[0]["exception_category"])


# ------------------------------------------------------------------
# the parameter fingerprint, and both parameter shapes
# ------------------------------------------------------------------

def test_the_fingerprint_works_for_both_parameter_shapes(check):
    """Three experiments pass a dataclass; the IV sweep passes a dict.

    A fingerprint that only understood mappings would be empty on three
    experiments out of four - silently, so the log would look complete
    while the field that answers "were these configured the same?" was
    blank on most lines.
    """
    typed = parameter_fingerprint(TypedParams(FakeSample()))
    mapping = parameter_fingerprint(
        {"sample": FakeSample(), "voltage_V": 1.5, "points": 11})
    check("a dataclass gets a fingerprint", bool(typed), typed)
    check("a dict gets one too", bool(mapping), mapping)
    check("nothing gets an empty one", parameter_fingerprint(None) == "")


def test_the_fingerprint_changes_when_a_parameter_does(check):
    """The discriminating half.

    A constant would satisfy "is it present?" perfectly and answer no
    question at all.
    """
    one = parameter_fingerprint(TypedParams(FakeSample(), voltage_V=1.5))
    two = parameter_fingerprint(TypedParams(FakeSample(), voltage_V=1.6))
    check("different settings, different fingerprint", one != two,
          f"{one} vs {two}")
    same = parameter_fingerprint(TypedParams(FakeSample(), voltage_V=1.5))
    check("same settings, same fingerprint", one == same)


def test_key_order_does_not_change_the_fingerprint(check):
    """Otherwise two identical configurations would look different."""
    a = parameter_fingerprint({"a": 1, "b": 2})
    b = parameter_fingerprint({"b": 2, "a": 1})
    check("order-independent", a == b, f"{a} vs {b}")


def test_the_sample_is_read_from_the_snapshot(check):
    check("from a dataclass",
          sample_identity(TypedParams(FakeSample())) == FakeSample.sample_id)
    check("from a dict",
          sample_identity({"sample": FakeSample()}) == FakeSample.sample_id)
    check("and nothing when there is no sample",
          sample_identity({"points": 11}) == "")


# ------------------------------------------------------------------
# the file itself
# ------------------------------------------------------------------

def test_the_log_is_append_only(check, log):
    for n in range(3):
        log.record(build_event(status(run_id=f"run-{n}"), experiment="hall"))
    events = log.read_all()
    check("three lines, oldest first", [e["run_id"] for e in events]
          == ["run-0", "run-1", "run-2"], str(events))


def test_one_json_object_per_line(check, log):
    """The format, checked rather than assumed.

    A multi-line record would break `read_json(lines=True)` and every
    `grep` anybody ever runs against this file.
    """
    log.record(build_event(
        status(detail="a detail\nwith an embedded newline"),
        experiment="hall"))
    lines = log.path.read_text(encoding="utf-8").strip().splitlines()
    check("exactly one line", len(lines) == 1, str(lines))
    check("and it parses", json.loads(lines[0])["run_id"] == "run-1")


def test_a_malformed_line_does_not_hide_the_rest(check, log):
    """A log truncated by a power cut still has to be readable."""
    log.record(build_event(status(run_id="good-1"), experiment="hall"))
    with open(log.path, "a", encoding="utf-8") as handle:
        handle.write('{"truncated": ')          # a half-written line
    log.record(build_event(status(run_id="good-2"), experiment="hall"))
    check("both good lines survive",
          [e["run_id"] for e in log.read_all()] == ["good-1", "good-2"],
          str(log.read_all()))


def test_it_rotates_and_keeps_one_generation(check, tmp_path):
    small = EventLog(tmp_path / "events.jsonl", max_bytes=400)
    for n in range(12):
        small.record(build_event(status(run_id=f"run-{n}"), experiment="hall"))
    previous = small.path.with_suffix(small.path.suffix + ".1")
    check("the live file exists", small.path.exists())
    check("and so does one previous generation", previous.exists())
    check("the live file is the newer one",
          small.read_all()[-1]["run_id"] == "run-11")


# ------------------------------------------------------------------
# and it must never break a run
# ------------------------------------------------------------------

def test_a_log_that_cannot_be_written_does_not_raise(check, tmp_path):
    """A full disk is not a reason to fail a completed measurement.

    Same rule house rule 11 applies to the summary file: a secondary
    artefact that cannot be written must not take the primary one down.
    """
    blocked = tmp_path / "a-file"
    blocked.write_text("not a directory", encoding="utf-8")
    complaints = []
    bad = EventLog(blocked / "nested" / "events.jsonl",
                   log=complaints.append)

    ok = bad.record(build_event(status(), experiment="hall"))
    check("it reports failure rather than raising", ok is False)
    check("and tells the operator once", len(complaints) == 1, str(complaints))

    bad.record(build_event(status(), experiment="hall"))
    check("but does not repeat itself every run",
          len(complaints) == 1, str(complaints))


def test_a_sink_that_raises_does_not_fail_the_run(check):
    """The second belt, for a sink the controller did not write.

    A run that measured correctly and put its output away must not be
    reported as failed because a log file was locked.
    """
    said = []

    def exploding(status, context=None):
        raise RuntimeError("disk on fire")

    controller = RunController(name="test", log=said.append,
                               event_sink=exploding)
    with controller.begin(parameters={"sample": FakeSample()}) as run:
        _drive(run)

    check("the run still completed",
          controller.last_status.outcome is Outcome.COMPLETED,
          str(controller.last_status.outcome))
    check("and the failure was reported, not swallowed silently",
          any("RuntimeError" in line for line in said), str(said))


def test_the_controller_emits_one_event_per_run(check):
    """Wired at the choke point, so no path can skip it.

    Every terminal status goes through `_record`, which is why the sink
    hangs there rather than off each of the three `_finish_*` methods -
    a fourth one added later gets logging for free instead of being
    forgotten.
    """
    seen = []
    controller = RunController(name="test",
                               event_sink=lambda s, c: seen.append((s, c)))

    with controller.begin(parameters={"sample": FakeSample()}) as run:
        _drive(run)
    check("a completed run emits once", len(seen) == 1, str(len(seen)))

    with controller.begin(parameters={"sample": FakeSample()}) as run:
        run.start()
        controller.request_cancel("operator")
    check("a cancelled run emits too", len(seen) == 2, str(len(seen)))
    check("with the right outcome",
          seen[1][0].outcome is Outcome.CANCELLED, str(seen[1][0].outcome))
    check("and the context comes with it, so the sample can be read",
          sample_identity(seen[1][1].parameters) == FakeSample.sample_id)


def test_the_log_creates_its_directory_on_a_fresh_machine(check, tmp_path):
    """First run, before anything has ever written to per-machine state.

    Found by the same mutation as its twin in
    `tests/test_single_instance.py`: `lock_directory()` stopped creating
    what it returns in Wave 7f, so both writers have to create their own
    parent - and every other test here is handed a `tmp_path` that
    already exists, so removing that `mkdir` broke nothing.

    The failure it would cause is quiet by design. `EventLog.record`
    swallows its own errors so a broken log can never fail a
    measurement, which is right - and means a missing directory would
    show up as an event log that is simply always empty, on every fresh
    machine, with nothing said about it anywhere.
    """
    nested = tmp_path / "never" / "existed" / "before"
    check("the parent really is absent to begin with", not nested.exists())

    log = EventLog(nested / "events.jsonl")
    log.record(build_event(status(Outcome.COMPLETED),
                           experiment="vanderpauw",
                           sample_id=FakeSample.sample_id,
                           parameters={"sample": FakeSample()},
                           metadata=None))

    check("the directory was created", nested.is_dir(), str(nested))
    check("and the event actually landed", len(log.read_all()) == 1,
          str(log.read_all()))
