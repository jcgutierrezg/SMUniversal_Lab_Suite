"""
The per-sample summary, at the level that needs no Tk (Wave 5c-ii).

Two pure pieces are worth pinning down on their own, away from the
window: what the file *says*, and how a "not calculated" half is
rendered so it cannot be read as a sample that was only half measured.
The wiring - who calls this and when - is exercised in
`test_summary_lifecycle.py`, which needs a real app.

The format matters more than it looks. A summary that silently omits the
Hall section reads exactly like a sample nobody ran Hall on; the whole
point of the explicit "not calculated" line is that those two are
different on disk.
"""
import csv
import io

from core.run_store import build_sample_summary


def _table(text):
    """The CSV rows under the `#` preamble, as dicts."""
    body = "\n".join(line for line in text.splitlines()
                     if not line.startswith("#"))
    return list(csv.DictReader(io.StringIO(body)))


def test_a_full_summary_lists_every_quantity(check):
    text = build_sample_summary(
        "film_A", "smp-1",
        [("Van der Pauw", [("Sheet resistance", "5623.46", "\u03a9/\u25a1",
                            "res-vdp")]),
         ("Hall effect", [("Carrier type", "n-type", "", "res-hall"),
                          ("Hall mobility", "41.2", "cm\u00b2/Vs", "res-hall")])])
    rows = _table(text)

    check("three quantity rows", len(rows) == 3, len(rows))
    labels = [r["quantity"] for r in rows]
    check("sheet resistance is there", "Sheet resistance" in labels, labels)
    check("carrier type is there", "Carrier type" in labels, labels)
    check("values carried through",
          any(r["value"] == "5623.46" for r in rows), rows)
    check("units carried through",
          any(r["unit"] == "cm\u00b2/Vs" for r in rows), rows)
    check("the source result id is on each row",
          all(r["source"] for r in rows), rows)


def test_the_sample_and_its_id_are_in_the_preamble(check):
    text = build_sample_summary("film_A", "smp-1", [])
    check("sample name", "# sample: film_A" in text, text[:200])
    check("sample id", "# sample_id: smp-1" in text, text[:200])
    check("and it says it is a summary",
          "Sample summary" in text.splitlines()[0], text.splitlines()[0])


def test_a_missing_section_is_marked_not_absent(check):
    """The failure this line exists to prevent: a half-run session that
    looks complete."""
    with_hall = build_sample_summary(
        "film_A", "smp-1",
        [("Van der Pauw", [("Sheet resistance", "5623", "\u03a9/\u25a1", "r")]),
         ("Hall effect", None)])
    without_hall = build_sample_summary(
        "film_A", "smp-1",
        [("Van der Pauw", [("Sheet resistance", "5623", "\u03a9/\u25a1", "r")])])

    rows = _table(with_hall)
    hall_row = [r for r in rows if r["measurement"] == "Hall effect"]
    check("the Hall section is present", len(hall_row) == 1, rows)
    if hall_row:
        check("and says not calculated",
              hall_row[0]["quantity"] == "not calculated", hall_row[0])
    check("which is visibly different from omitting it entirely",
          with_hall != without_hall,
          "a not-calculated section must not render identically to no "
          "section at all")


def test_the_body_is_a_real_table_not_another_hash_block(check):
    """`.csv` is a promise that Excel can open it as columns. If the
    numbers were in the `#` preamble instead, that promise would be
    broken and the extension would be a lie."""
    text = build_sample_summary(
        "film_A", "smp-1",
        [("Van der Pauw", [("Sheet resistance", "5623", "\u03a9/\u25a1", "r")])])
    rows = _table(text)
    check("the value is in the table, not the comments",
          any(r["value"] == "5623" for r in rows), rows)
    check("no calculated value hides in the preamble",
          "5623" not in "\n".join(l for l in text.splitlines()
                                   if l.startswith("#")))


def test_carrier_type_has_no_unit(check):
    """The unitless quantity keeps an empty unit column rather than
    borrowing the next one's - a cosmetic slip that would misread every
    carrier type as having units."""
    text = build_sample_summary(
        "film_A", "smp-1",
        [("Hall effect", [("Carrier type", "p-type", "", "res-hall")])])
    row = _table(text)[0]
    check("value is the type", row["value"] == "p-type", row)
    check("unit is blank", row["unit"] == "", row)
