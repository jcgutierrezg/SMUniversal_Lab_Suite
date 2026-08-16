---
type: bench
title: "Running a checkup"
---

# Running a checkup

Before trusting an instrument — a new one, one that has been moved, one
whose data looks odd, or one that [[checkup-owed]] lists.

```powershell
uv run tools/smu_checkup.py --address <address> --trace
```

**Nothing connected to the outputs.** It prompts to confirm before it
sources anything. Three minutes, and it writes a report you can keep and
compare against the next one.

## Why it exists, and why the test suite is not a substitute

The software has a large automated test suite, and it passes. It cannot
tell you whether an instrument agrees with what the driver believes
about it — that is a different question, and it is where **half the
faults this project has found** came from.

They are all the same shape: an instrument disagreeing with a reasonable
assumption, rather than code disagreeing with itself. A command accepted
and ignored. A setting that only applies before something is armed. A
compliance clamped to a range nobody had widened yet. **None of them
raised an error**, and none of them were reachable without an instrument
attached.

## What "checked" means, and when it stops being true

A driver is only *commissioned* while the code that was checked is the
code that is running. Change the driver and the checkup's answers were
about software that no longer exists.

That is derived automatically — [[checkup-owed]] compares each
instrument's last checkup date against the repository's own history — so
it is never a matter of anyone remembering. If a bench page carries the
warning **"This driver has changed since it was last checked against the
instrument"**, that is what it means: the measurement may well be fine,
and nobody has confirmed it.

## After a checkup

Tell the repository it happened. In `docs/instruments/<instrument>.md`:

```yaml
last_bench: 2026-08-16
bench_notes: "checkup all tiers, zero failures"
```

then rebuild:

```powershell
uv run python tools/build_docs.py
```

The chooser table and the owed list both update themselves. If the
checkup found something, it belongs in that instrument's note under
**Bench findings** — every entry there was once a surprise, and the
notes are the reason the next surprise is a smaller one.
