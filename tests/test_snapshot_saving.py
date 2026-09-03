"""What a saved file says about itself, and what saving twice means.

House rule 3, `docs/rules/03-no-auto-save.md`. The decision is
**option A, immutable snapshot**: every save writes the whole store,
so two saves overlap on purpose.

Option B - new runs only - was rejected, and the reason is worth keeping
next to the tests rather than only in the plan. `build_sample_csv` puts
the calculated results in the `#` header, and those are derived from
every run in the store. A new-runs-only file would therefore carry a
sheet resistance computed from readings the file does not contain: a
correct-looking number above a table that cannot produce it, which is
this project's signature fault rather than a formatting quibble.

What A owes in exchange is legibility, and that is what these check:

  * `save_kind` says which model it is, in the file, for a reader who
    was never told;
  * `save_id` groups the files one press produced;
  * `record_id` (Wave 7b-i) identifies a row, so a reader combining two
    overlapping snapshots de-duplicates correctly instead of guessing;
  * `schema` and `app_version` say what wrote it.

These are pure string work - so they run in the shared process. One
exception, and it earns it: the newline check has to read a file back,
because the string and the bytes on disk were exactly what disagreed. It
calls `write_atomic` unbound and writes into `tmp_path`, so it still
builds no Tk root.
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import version  # noqa: E402
from core.run_store import (  # noqa: E402
    FILE_SCHEMA,
    Run,
    build_sample_csv,
    build_sample_summary,
)
from core.version import app_version, build_id  # noqa: E402


def _header(text):
    """The `#` block as a dict of key -> value."""
    out = {}
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        body = line[1:].strip()
        if ":" in body:
            key, _, value = body.partition(":")
            out.setdefault(key.strip(), value.strip())
    return out


def _table(text):
    body = [l for l in text.splitlines() if not l.startswith("#")]
    return list(csv.DictReader(io.StringIO("\n".join(body))))


def _runs(n, points=2):
    return [Run("wafer_A", {"meas_number": i + 1},
                [{"point": p + 1, "voltage_V": 0.1 * p} for p in range(points)])
            for i in range(n)]


# ------------------------------------------------------------------
# what the file says about itself
# ------------------------------------------------------------------

def test_a_saved_file_declares_its_schema_and_the_code_that_wrote_it(check):
    """Both, and both matter for different questions.

    `schema` answers "can my reader parse this?"; `app_version` answers
    "which code computed the numbers in the header?". A file from last
    March needs the second when somebody changes a formula in April, and
    without it that question cannot be answered from the file at all.
    """
    text = build_sample_csv("wafer_A", _runs(2), "Van der Pauw")
    header = _header(text)
    check("schema is declared", header.get("schema") == str(FILE_SCHEMA),
          f"got {header.get('schema')!r}")
    check("app version is declared",
          header.get("app_version") == app_version(),
          f"got {header.get('app_version')!r}")
    check("and so is the build behind it",
          header.get("build_id") == build_id(),
          f"got {header.get('build_id')!r}")


def test_the_summary_file_declares_them_too(check):
    """The summary is a stored file like any other.

    Easy to forget, because it is written on a different path - after
    the data CSVs and outside their `try`, per house rule 11. A reader
    that trusts `schema` has to be able to trust it everywhere.
    """
    text = build_sample_summary(
        "wafer_A", "smp-1",
        [("Van der Pauw", [("Sheet resistance", "412.6", "Ω/sq", "res-1")])])
    header = _header(text)
    check("schema is declared", header.get("schema") == str(FILE_SCHEMA),
          f"got {header.get('schema')!r}")
    check("app version is declared",
          header.get("app_version") == app_version(),
          f"got {header.get('app_version')!r}")
    check("and so is the build behind it",
          header.get("build_id") == build_id(),
          f"got {header.get('build_id')!r}")


def test_the_build_is_recorded_because_the_version_does_not_move(check,
                                                                monkeypatch):
    """What `app_version` alone could not answer.

    `0.1.0` was set once and did not change across every
    behaviour-changing wave that followed, so a file written last March
    and a file written in September both claim the same application
    identity - which defeats the point of stamping a version into
    scientific output at all. The commit is what distinguishes them.

    Both writers are checked here, and against an injected build rather
    than the ambient one, so this fails if either stops reading the
    stamp or starts writing a literal.
    """
    monkeypatch.setattr("core.provenance.head_commit",
                        lambda root=None: ("5e7308eff34a79954ab6", True, []))
    version.reset_build_id_cache()
    expected = f"{app_version()}+g5e7308eff34a.dirty"
    try:
        csv_header = _header(build_sample_csv("wafer_A", _runs(1), "IV sweep"))
        summary_header = _header(build_sample_summary("wafer_A", "smp-1", []))
        check("the data CSV carries the injected build",
              csv_header.get("build_id") == expected,
              f"got {csv_header.get('build_id')!r}")
        check("so does the summary",
              summary_header.get("build_id") == expected,
              f"got {summary_header.get('build_id')!r}")
        check("and a modified tree is visible in the file",
              csv_header.get("build_id", "").endswith(".dirty"),
              f"got {csv_header.get('build_id')!r}")
    finally:
        version.reset_build_id_cache()


def test_a_build_that_cannot_be_determined_says_so(check, monkeypatch):
    """Never an empty field, and never a missing key.

    A frozen `.exe` with no stamp and no git is the case this is
    written for. An absent `build_id` would read as "written by a
    version that did not record builds"; `0.1.0+unknown` reads as
    "written by one that could not determine one". Silently omitting
    the stamp is the exact failure this field exists to remove.
    """
    monkeypatch.setattr("core.provenance.head_commit",
                        lambda root=None: (None, False, []))
    version.reset_build_id_cache()
    try:
        for name, text in (("data CSV",
                            build_sample_csv("wafer_A", _runs(1), "IV sweep")),
                           ("summary",
                            build_sample_summary("wafer_A", "smp-1", []))):
            header = _header(text)
            check(f"{name}: the key is present", "build_id" in header,
                  sorted(header))
            check(f"{name}: and says unknown",
                  header.get("build_id") == f"{app_version()}+unknown",
                  f"got {header.get('build_id')!r}")
    finally:
        version.reset_build_id_cache()


def test_the_files_are_written_with_lf_endings(check):
    """`csv.writer` defaults to `\\r\\n` whatever the platform.

    Both builders pass `lineterminator="\\n"` and both join their `#`
    blocks with `"\\n"`; this is what says so, because the two header
    keys added here were appended to a list somebody could later rewrite
    as a `writelines`.

    This is only half the claim. It inspects the string in memory, and
    the string was never the part that was wrong - see the test below.
    """
    for name, text in (("data CSV",
                        build_sample_csv("wafer_A", _runs(2), "Van der Pauw")),
                       ("summary",
                        build_sample_summary(
                            "wafer_A", "smp-1",
                            [("Hall", [("V_H", "1.2", "V", "res-1")])]))):
        check(f"{name}: no carriage returns", "\r" not in text,
              repr(text[:200]))


def test_the_bytes_on_disk_are_the_bytes_the_builder_produced(check, tmp_path):
    """The same claim, at the only place it can be checked: the file.

    The builders decided LF deliberately. `write_atomic` then opened in
    text mode with no `newline`, and Python translated every one of them
    to CRLF on Windows - so the code that produced a measurement CSV and
    the CSV on disk disagreed, and the test above passed throughout
    because it never looked at a file.

    Which end to change was a genuine decision rather than an obvious
    bug: RFC 4180 specifies CRLF for CSV. It is settled as LF, and the
    reasoning is in `LabApp.write_atomic`. The point of pinning it here
    is that it stays *decided*: a writer that quietly rewrites what it
    was handed is indefensible whichever ending wins.

    Called unbound because `write_atomic` touches no instance state, and
    building a `LabApp` would need Tk - which would move this file into
    a GUI process for no gain.
    """
    from core.base_app import LabApp

    for name, text in (("data CSV",
                        build_sample_csv("wafer_A", _runs(2), "Van der Pauw")),
                       ("summary",
                        build_sample_summary(
                            "wafer_A", "smp-1",
                            [("Hall", [("V_H", "1.2", "V", "res-1")])]))):
        target = tmp_path / f"{name.replace(' ', '_')}.csv"
        LabApp.write_atomic(None, str(target), text)
        data = target.read_bytes()

        check(f"{name}: nothing was translated on the way to disk",
              b"\r" not in data, repr(data[:200]))
        check(f"{name}: and the file is what was built",
              data == text.encode("utf-8"),
              f"{len(data)} bytes on disk, {len(text.encode('utf-8'))} built")
        check(f"{name}: the .tmp file did not survive",
              not (tmp_path / f"{target.name}.tmp").exists())


def test_the_file_says_it_is_a_snapshot(check):
    """The wording on the button matches the model.

    A reader who finds two files with overlapping rows and no
    explanation reasonably concludes something went wrong. The header
    has to say the overlap is the design.
    """
    text = build_sample_csv("wafer_A", _runs(2), "Van der Pauw")
    check("save_kind is declared",
          _header(text).get("save_kind") == "snapshot",
          f"got {_header(text).get('save_kind')!r}")


# ------------------------------------------------------------------
# saving twice
# ------------------------------------------------------------------

def test_saving_twice_writes_the_earlier_runs_again(check):
    """The behaviour under option A, pinned rather than assumed.

    This is the property a future change to option B would break, and it
    should break loudly here rather than quietly in somebody's data. The
    store is not emptied by a save, so the second file is a superset.
    """
    runs = _runs(2)
    first = build_sample_csv("wafer_A", runs, "Van der Pauw")
    runs.append(_runs(1)[0])
    second = build_sample_csv("wafer_A", runs, "Van der Pauw")

    first_ids = {r["record_id"] for r in _table(first)}
    second_ids = {r["record_id"] for r in _table(second)}
    check("the first save's runs are in the second file",
          first_ids < second_ids,
          f"{sorted(first_ids)} vs {sorted(second_ids)}")
    check("and the second holds one more",
          len(second_ids) == len(first_ids) + 1,
          f"{len(first_ids)} then {len(second_ids)}")


def test_two_overlapping_snapshots_deduplicate_on_record_id(check):
    """The reason `record_id` is on the row at all.

    This is the operation the whole wave exists to make correct:
    concatenate two saves, drop duplicates, get each measurement once.
    Done here with plain stdlib so the test does not depend on pandas,
    but it is exactly `drop_duplicates(subset="record_id")`.
    """
    runs = _runs(2)
    first = _table(build_sample_csv("wafer_A", runs, "Van der Pauw"))
    runs.append(_runs(1)[0])
    second = _table(build_sample_csv("wafer_A", runs, "Van der Pauw"))

    combined = first + second
    unique = {r["record_id"] for r in combined}
    check("rows overlap before de-duplication",
          len(combined) > len(unique), f"{len(combined)} rows")
    check("three measurements survive de-duplication",
          len(unique) == 3, f"{len(unique)}")


def test_one_press_of_save_stamps_every_file_with_the_same_id(check):
    """Three samples in the table means three files and one action.

    Without a shared id those three files look like three separate
    saves, and the question "which files did I produce just now?" has no
    answer on disk.
    """
    shared = "sav-test-0001"
    files = [build_sample_csv(name, _runs(1), "Van der Pauw", save_id=shared)
             for name in ("wafer_A", "wafer_B", "wafer_C")]
    check("every file carries the id it was given",
          {_header(f).get("save_id") for f in files} == {shared},
          str({_header(f).get("save_id") for f in files}))


def test_two_presses_of_save_are_told_apart(check):
    """The other half: a shared id is only useful if it also changes.

    A constant would satisfy the test above perfectly and be useless -
    which is the fault this project has recorded as a non-discriminating
    check often enough to look for it on purpose.
    """
    one = build_sample_csv("wafer_A", _runs(1), "Van der Pauw")
    two = build_sample_csv("wafer_A", _runs(1), "Van der Pauw")
    check("a fresh id per call",
          _header(one).get("save_id") != _header(two).get("save_id"),
          f"{_header(one).get('save_id')} vs {_header(two).get('save_id')}")


# ------------------------------------------------------------------
# and none of it may break the reader
# ------------------------------------------------------------------

def test_the_new_header_keys_do_not_disturb_the_table(check):
    """`pd.read_csv(path, comment="#")` still gives a clean frame.

    Every header line added is a line a naive reader could trip over.
    This is the property house rule 3 promises about every file the
    suite writes, re-checked because the header just grew by four lines.
    """
    text = build_sample_csv("wafer_A", _runs(2, points=3), "Van der Pauw",
                            calculated={"Rs_ohm_per_sq": "4532.36"})
    rows = _table(text)
    check("one row per reading", len(rows) == 6, f"{len(rows)}")
    check("the calculated header survived",
          _header(text).get("Rs_ohm_per_sq") == "4532.36",
          str(_header(text).get("Rs_ohm_per_sq")))
    check("no row leaked a `#` line",
          all(not r["record_id"].startswith("#") for r in rows))
