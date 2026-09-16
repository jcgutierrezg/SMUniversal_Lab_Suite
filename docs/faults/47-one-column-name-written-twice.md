---
type: fault
fault: 47
title: "One column name written twice"
---

# 47. One column name written twice

## Symptom

Every Fixed source CSV had two columns headed `compliance`. Opened with
Python's `csv.DictReader`, a row has one `compliance` key, holding
`yes`, `no` or blank. Opened with pandas, there is a `compliance` and a
`compliance.1`. Opened in Excel, both are there and look like one
setting written twice.

## Cause

`build_sample_csv` builds the header from the run's metadata keys and
then the readings' keys, as two separate lists. The Fixed source
experiment used `compliance` in both: the run's limit in the metadata,
and each sample's trip flag in the reading. Nothing checked that the
two lists were disjoint, so the name went out twice.

## Risk

The two columns hold different kinds of thing - a limit in amps or
volts, and a yes/no flag - and a reader keyed on names gets one of them
without being told the other existed. `DictReader` keeps the last
column: every script written that way reads the trip flag and loses the
limit, with no error. A script written against pandas reads the limit
under `compliance` and has to know that `.1` is the flag.

It is the same shape as a sentinel read as data
([Sentinels read as data](03-sentinels-as-data.md)): a well-formed
value in the place a different value should be.

## Detection

Read every saved file back **by column name** and ask whether any name
appears twice in the header row. A reader that indexes by position will
never notice, and neither will a test that only checks the values it
wrote.

It was found by the CSV plotter, whose reader keeps repeated names apart
as `compliance#2` and says so.

## Prevention

`build_sample_csv` raises `ColumnCollision` when a run key and a reading
key share a name, or when either shadows `record_id` or `run_timestamp`.
A save that hits it fails with a message naming the column, rather than
writing a file that reads wrong. The builder refuses rather than
renames, because a renamed column would carry a name nobody chose.

The Fixed source trip flag is now `compliance_tripped`. That is a column
layout change, so `FILE_SCHEMA` is 3; see
[the stored-file schema](../reference/schema.md#stored-file-schema).

## Status

Closed. Schema 2 Fixed source files still carry both columns; the
plotter reads them, naming the flag `compliance#2`.

## Evidence

`tests/test_snapshot_saving.py`
(`test_a_name_used_for_the_run_and_each_reading_is_refused`);
`tests/test_plotter_real_files.py` saves a file from every experiment
and fails on a repeated column name.
