"""Stable identifiers and the sample registry (review §15, B3/B4).

The acceptance criterion from §15 is worth quoting as a test plan,
because it is two separate claims and each needs its own proof:

  *Two samples with the same display name remain distinguishable.
  Renaming a sample does not silently rewrite historical results.*

The first is about minting; the second is about what a completed run
kept hold of. A registry that satisfies only the first would still
relabel finished work.
"""
import re
import threading

import pytest
from hypothesis import given, settings, strategies as st

from core.identity import (SampleRef, SampleRegistry, format_run_id,
                           new_result_id, new_sample_id, reading_id,
                           split_reading_id)
from core.run_control import RunController


# ------------------------------------------------------------------
# shapes
# ------------------------------------------------------------------
def test_sample_ids_are_readable_dated_and_unique():
    ids = [new_sample_id() for _ in range(500)]
    assert len(set(ids)) == 500
    for value in ids:
        assert re.fullmatch(r"smp-\d{8}-[0-9a-f]{8}", value), value


def test_result_ids_have_their_own_prefix():
    """A prefix per kind means a stray identifier in a log line or a CSV
    says what it is without a lookup."""
    assert new_result_id().startswith("res-")
    assert new_sample_id().startswith("smp-")


def test_run_id_format_is_unchanged_from_wave_1():
    """`RunController` now delegates here. If the format moved, Wave 1's
    history, log lines and `test_run_control` all shift with it."""
    value = format_run_id("ossila_4pp", 7)
    assert re.fullmatch(r"ossila_4pp-0007-\d{8}T\d{6}", value), value


def test_run_controller_uses_the_shared_formatter():
    controller = RunController(name="ossila_4pp")
    with controller.begin() as run:
        assert re.fullmatch(r"ossila_4pp-0001-\d{8}T\d{6}", run.run_id)
        run.token.cancel("test")


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
    with pytest.raises(Exception):
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
