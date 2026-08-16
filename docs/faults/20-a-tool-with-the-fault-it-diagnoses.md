---
type: fault
fault: 20
title: "A diagnostic tool with the fault it diagnoses"
found_by: "writing the tools"
---

# 20. A diagnostic tool with the fault it diagnoses

*Found by writing the tools.*

`tools/scpi_console.py` decided which lines produce a reply by looking
for `?`. TSP has no query punctuation — a 2600B answers when the script
calls `print()` and stays silent otherwise — so every `print(...)` was
sent as a write. The instrument still generates the reply, so it sits in
the output buffer and **the next real query reads the previous line's
answer**: every result after it off by one, silently, each looking
plausible.

The console had therefore never been usable against the TSP instruments,
and the fault was found only because a TSP probe script was written for
the first time.

**Tools that produce evidence need the same scrutiny as the code they
produce evidence about.** The same lesson arrived independently as
[Output state assumed across a source-function change](14-output-across-function-change.md), where the checkup rather than the
experiments carried the fault.
