"""Stable identifiers and the sample registry (review §15, B3/B4).

The acceptance criterion from §15 is worth quoting as a test plan,
because it is two separate claims and each needs its own proof:

  *Two samples with the same display name remain distinguishable.
  Renaming a sample does not silently rewrite historical results.*

The first is about minting; the second is about what a completed run
kept hold of. A registry that satisfies only the first would still
relabel finished work.
"""
import datetime
import importlib.util
import re
import sys
import threading

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core import identity
from core.identity import (
    SESSION_ID,
    TAIL_WIDTHS,
    SampleRef,
    SampleRegistry,
    format_run_id,
    new_record_id,
    new_result_id,
    new_sample_id,
    new_save_id,
    parse_object_id,
    parse_run_id,
    reading_id,
    split_reading_id,
)
from core.run_control import RunController


# ------------------------------------------------------------------
# shapes
# ------------------------------------------------------------------
def test_sample_ids_are_readable_dated_and_unique():
    ids = [new_sample_id() for _ in range(500)]
    assert len(set(ids)) == 500
    for value in ids:
        assert re.fullmatch(r"smp-\d{8}-[0-9a-f]{16}", value), value


def test_every_persistent_identifier_carries_64_random_bits(check):
    """The width is the guarantee; the registry's re-draw is a backstop.

    The tail was 8 hex characters, and the docstring claimed a
    collision "roughly every ten thousand years" at a few hundred a
    day. The birthday expectation for 300 draws from 2**32 is about
    1.0e-5 per day, which is one collision every 260 years or so -
    wrong by two orders of magnitude and wrong in the reassuring
    direction. These identifiers are the join keys of a scientific
    record meant to outlive the people who made it, and the volume is
    not 300 a day: a `rec-` is minted per run, not per sample.

    Written as a property of every minter rather than of one, because a
    minter added later that reaches for its own narrower tail is
    exactly how this comes back.
    """
    for name, mint in (("sample", new_sample_id), ("record", new_record_id),
                       ("save", new_save_id), ("result", new_result_id)):
        tail = mint().rsplit("-", 1)[-1]
        check(f"{name}: 16 hex characters", len(tail) == 16, f"{tail!r}")
        check(f"{name}: hex", re.fullmatch(r"[0-9a-f]{16}", tail), f"{tail!r}")


def test_result_ids_have_their_own_prefix():
    """A prefix per kind means a stray identifier in a log line or a CSV
    says what it is without a lookup."""
    assert new_result_id().startswith("res-")
    assert new_sample_id().startswith("smp-")


def test_the_run_id_keeps_its_readable_stem_and_gains_a_session():
    """The stem is what an operator reads, so it stays first and intact.

    `RunController` delegates here, so Wave 1's history, log lines and
    `test_run_control` all follow this format. What is appended is 64
    bits identifying the process; what is not touched is the
    experiment, the sequence number and the timestamp in front of it.
    """
    value = format_run_id("ossila_4pp", 7)
    assert re.fullmatch(r"ossila_4pp-0007-\d{8}T\d{6}-[0-9a-f]{16}", value), value
    assert value.startswith("ossila_4pp-0007-")


def test_run_controller_uses_the_shared_formatter():
    controller = RunController(name="ossila_4pp")
    with controller.begin() as run:
        assert re.fullmatch(r"ossila_4pp-0001-\d{8}T\d{6}-[0-9a-f]{16}",
                            run.run_id)
        run.token.cancel("test")


# ------------------------------------------------------------------
# two processes, one second
# ------------------------------------------------------------------
def test_two_sessions_in_the_same_second_do_not_collide(check):
    """The fault, reproduced: same experiment, same first run, same second.

    The sequence number restarts at 1 when the process does, and the
    timestamp that was supposed to disambiguate it has one-second
    resolution. So a restart inside one second - or a second bench
    machine started alongside the first - produced the identical first
    run identifier. `run_id` is the join key between a stored
    measurement row and the operational event log, so that collision
    joins one machine's readings to another machine's cancellation.

    Both sessions are pinned to the same `when` deliberately: without
    the session part these assertions are not merely unproven, they are
    false.
    """
    moment = datetime.datetime(2026, 9, 2, 14, 30, 12)
    first = format_run_id("ossila_4pp", 1, when=moment,
                          session="1111111111111111")
    second = format_run_id("ossila_4pp", 1, when=moment,
                           session="2222222222222222")
    check("they differ", first != second, f"{first} / {second}")
    check("and only in the session",
          first.rsplit("-", 1)[0] == second.rsplit("-", 1)[0],
          f"{first} / {second}")
    check("the readable stem survives",
          first.startswith("ossila_4pp-0001-20260902T143012-"), first)


def _second_session():
    """A second, independent copy of the module - a second launch.

    Loaded under a name of its own rather than with
    `importlib.reload`, on purpose. A reload rebinds the names every
    other test in this process already imported, including the
    `SampleRef` dataclass whose `__eq__` compares `__class__` - so it
    would leave a trap for tests that have nothing to do with sessions.

    It has to be in `sys.modules` while it executes, because
    `@dataclass` resolves annotations through the defining module, and
    it is taken out again afterwards.
    """
    name = "core.identity__second_session"
    spec = importlib.util.spec_from_file_location(name, identity.__file__)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def test_a_second_launch_draws_a_different_session(check):
    """Two processes, simulated the only way one process can.

    A fresh import draws a new `SESSION_ID`, which is exactly what a
    second application launch does. This is what makes the test above a
    statement about restarts rather than about two hand-written
    constants.
    """
    other = _second_session()
    moment = datetime.datetime(2026, 9, 2, 14, 30, 12)
    check("the session moved", other.SESSION_ID != SESSION_ID,
          other.SESSION_ID)
    check("64 bits of it", re.fullmatch(r"[0-9a-f]{16}", other.SESSION_ID),
          other.SESSION_ID)
    check("so the first run of each launch differs",
          format_run_id("ossila_4pp", 1, when=moment)
          != other.format_run_id("ossila_4pp", 1, when=moment))


def test_one_session_still_relies_on_the_counter(check):
    """Within a process the session is constant, so uniqueness is the
    counter's job and always was. Stated as a test because it is the
    half of the guarantee the session does *not* provide."""
    moment = datetime.datetime(2026, 9, 2, 14, 30, 12)
    ids = [format_run_id("hall", n, when=moment) for n in range(1, 51)]
    check("all distinct", len(set(ids)) == 50)
    check("all one session", len({i.rsplit("-", 1)[-1] for i in ids}) == 1)


# ------------------------------------------------------------------
# reading old identifiers back
# ------------------------------------------------------------------
def test_old_narrow_identifiers_still_parse(check):
    """Stored CSVs carry 8-character tails, and they are the record.

    A reader that only accepted what it writes would be a reader that
    cannot open last year's data - a worse failure than the collision
    the widening fixes, because it is certain rather than unlikely.
    """
    for old, kind in (("smp-20260808-a3f19c2b", "smp"),
                      ("rec-20260808-9b2c4d61", "rec"),
                      ("sav-20260808-1c4e77b2", "sav"),
                      ("res-20260808-5e1d7f04", "res")):
        parsed = parse_object_id(old)
        check(f"{old} parses", parsed is not None, repr(parsed))
        check(f"{old} is a {kind}", parsed and parsed.kind == kind)
        check(f"{old} keeps its date", parsed and parsed.date == "20260808")


def test_new_wide_identifiers_parse_too(check):
    for mint in (new_sample_id, new_record_id, new_save_id, new_result_id):
        value = mint()
        parsed = parse_object_id(value)
        check(f"{value} parses", parsed is not None, repr(parsed))
        check("the tail is the wide one", parsed and len(parsed.tail) == 16)


def test_the_recogniser_is_built_from_the_widths_it_claims(check):
    """So widening the tail again cannot leave the reader behind.

    That is the shape of mistake that makes a file unreadable by the
    code that wrote it, and it is invisible until somebody opens an old
    file - which is exactly when nobody is in a position to fix it.
    """
    for width in TAIL_WIDTHS:
        value = f"smp-20260808-{'a' * width}"
        check(f"width {width} accepted", parse_object_id(value) is not None,
              value)


def test_the_recogniser_refuses_what_is_not_an_identifier(check):
    """A "yes" to anything is not a check. Widths between the two
    supported ones are refused rather than truncated to a prefix."""
    for text in ("", "smp-20260808-a3f19c2", "smp-20260808-a3f19c2b7",
                 "xyz-20260808-a3f19c2b", "smp-2026080-a3f19c2b",
                 "smp-20260808-A3F19C2B", "not an id"):
        check(f"{text!r} refused", parse_object_id(text) is None,
              repr(parse_object_id(text)))


def test_old_run_ids_still_parse_and_say_they_have_no_session(check):
    """`None`, not `""`.

    "This identifier predates sessions" is a fact about a stored file.
    It must not read as "this run recorded a blank session", which
    would be a fact about a bug.
    """
    parsed = parse_run_id("ossila_4pp-0007-20260808T143012")
    check("it parses", parsed is not None, repr(parsed))
    check("the name survives", parsed and parsed.name == "ossila_4pp")
    check("the sequence is a number", parsed and parsed.sequence == 7)
    check("the moment survives", parsed and parsed.when == "20260808T143012")
    check("and the session is absent, not blank",
          parsed and parsed.session is None, repr(parsed))


def test_new_run_ids_round_trip(check):
    value = format_run_id("vanderpauw", 12, session="0123456789abcdef")
    parsed = parse_run_id(value)
    check("it parses", parsed is not None, repr(parsed))
    check("name", parsed and parsed.name == "vanderpauw")
    check("sequence", parsed and parsed.sequence == 12)
    check("session", parsed and parsed.session == "0123456789abcdef")
    check("hyphenated experiment names survive",
          parse_run_id(format_run_id("iv-sweep", 3)).name == "iv-sweep")


def test_parse_run_id_refuses_anything_else(check):
    for text in ("", "ossila_4pp", "ossila_4pp-7-20260808T143012",
                 "ossila_4pp-0007-20260808", "not a run id"):
        check(f"{text!r} refused", parse_run_id(text) is None,
              repr(parse_run_id(text)))


# ------------------------------------------------------------------
# reading ids
# ------------------------------------------------------------------
def test_reading_ids_are_derived_and_reversible():
    """A reading has no identity apart from its run and its position, so
    the identifier is derived rather than random - which means Wave 4
    can walk a provenance chain backwards from a stored row without a
    second index."""
    run = format_run_id("hall", 3)
    assert reading_id(run, 0) == f"{run}#0001"
    assert reading_id(run, 41) == f"{run}#0042"
    assert split_reading_id(reading_id(run, 41)) == (run, 41)


def test_split_reading_id_rejects_anything_else():
    assert split_reading_id("not-a-reading-id") is None
    assert split_reading_id("") is None


@given(st.integers(min_value=0, max_value=99999))
@settings(max_examples=200, deadline=None)
def test_reading_id_round_trips(index):
    run = "vanderpauw-0012-20260808T101112"
    assert split_reading_id(reading_id(run, index)) == (run, index)


# ------------------------------------------------------------------
# SampleRef
# ------------------------------------------------------------------
def test_sample_ref_is_frozen():
    ref = SampleRef("smp-20260808-aaaaaaaa", "ITO 3")
    # `FrozenInstanceError` subclasses `AttributeError`, so this is the
    # narrowest class that does not pin the test to dataclasses. A bare
    # `Exception` would also pass against a `SampleRef` that had no
    # `label` at all.
    with pytest.raises(AttributeError):
        ref.label = "something else"


@pytest.mark.parametrize("label, slug", [
    ("ITO 3", "ITO_3"),
    ("batch/7", "batch7"),
    ("  spaced  out  ", "spaced__out"),
    ("", "sample"),
    ("!!!", "sample"),
])
def test_slug_is_filename_safe(label, slug):
    """The slug is what reaches a filename. `current_sample_name()`
    produces the same shape today; keeping it on the ref means the file
    and the run's own record cannot disagree about which sample it is."""
    assert SampleRef("smp-x", label).slug == slug


# ------------------------------------------------------------------
# the registry - §15 acceptance criteria
# ------------------------------------------------------------------
def test_same_label_returns_the_same_sample():
    """The common case must need no ceremony: measure a sample, measure
    it again, same sample."""
    registry = SampleRegistry()
    first = registry.ref("ITO 3")
    second = registry.ref("ITO 3")
    assert first.sample_id == second.sample_id
    assert len(registry) == 1


def test_two_samples_may_share_a_label_and_stay_distinguishable():
    """§15, first half. Two pieces from one batch, same name on the box."""
    registry = SampleRegistry()
    first = registry.new("ITO 3")
    second = registry.new("ITO 3")
    assert first.sample_id != second.sample_id
    assert first.label == second.label == "ITO 3"
    assert len(registry) == 2
    # the newer one is what the label now points at
    assert registry.ref("ITO 3").sample_id == second.sample_id
    # and the older one is still reachable by its own identifier
    assert registry.get(first.sample_id) == first


def test_renaming_does_not_rewrite_a_captured_ref():
    """§15, second half - the one that matters scientifically.

    A run holds the ref it captured. Renaming the sample afterwards must
    change what future runs are called, not what this one records.
    """
    registry = SampleRegistry()
    ref_at_run_time = registry.ref("ITO 3")

    updated = registry.rename(ref_at_run_time.sample_id, "ITO 3 (remeasured)")

    assert updated.sample_id == ref_at_run_time.sample_id   # id never moves
    assert updated.label == "ITO 3 (remeasured)"
    assert ref_at_run_time.label == "ITO 3"                 # history intact
    assert registry.ref("ITO 3 (remeasured)").sample_id == updated.sample_id


def test_renaming_onto_an_existing_label_does_not_steal_it():
    registry = SampleRegistry()
    a = registry.ref("A")
    b = registry.ref("B")
    registry.rename(a.sample_id, "B")
    # 'B' now points at A's id, which is what was asked for, but B's own
    # sample still exists under its own identifier
    assert registry.ref("B").sample_id == a.sample_id
    assert registry.get(b.sample_id).sample_id == b.sample_id


def test_renaming_an_unknown_id_raises():
    with pytest.raises(KeyError):
        SampleRegistry().rename("smp-nope", "X")


def test_blank_label_gets_a_usable_default():
    registry = SampleRegistry()
    assert registry.new("").label == "sample"
    assert registry.new("   ").label == "sample"


def test_registry_survives_contention():
    """What this proves, and what it deliberately does not.

    It proves: concurrent use raises nothing, and no two samples share
    an identifier.

    It does **not** prove that `ref()` mints atomically. Under CPython's
    GIL the check-then-act window is a few bytecodes wide; a
    barrier-synchronised attempt with 24 threads never split a sample,
    with the racy spelling or the correct one. Per the project rule
    about fixes for faults that cannot be reproduced on demand, the
    honest statement is that the lock placement in `SampleRegistry.ref`
    is correct by construction rather than by evidence, and that it
    starts to matter on a free-threaded 3.14 build. Do not strengthen
    this test's docstring without first producing a failure.
    """
    registry = SampleRegistry()
    errors = []

    def hammer(n):
        try:
            for i in range(50):
                registry.ref(f"sample-{i % 5}")
                registry.new(f"fresh-{n}-{i}")
        except Exception as exc:            # pragma: no cover - a failure
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(registry) == 5 + 8 * 50
    assert len({r.sample_id for r in registry.all()}) == len(registry)
