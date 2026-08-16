---
type: fault
fault: 14
title: "Output state assumed across a source-function change"
found_by: "running the drivers"
---

# 14. Output state assumed across a source-function change

*Found by running the drivers.*

The 2400 family drops the output when the source function changes. With
auto output-off disabled — which these drivers do, so a sweep holds its
level — `:READ?` then **blocks forever with no error, looking exactly
like a dead instrument.**

Call `output_on()` *after* `set_source_function()`. Documented on
`BaseSMU.set_source_function` for every driver.

Worth noting where it was found: the experiments always got this right;
`tools/smu_checkup.py` did not. See [A diagnostic tool with the fault it diagnoses](20-a-tool-with-the-fault-it-diagnoses.md).

Deviation 48. See [Keithley 2401](../instruments/keithley-2401.md).
