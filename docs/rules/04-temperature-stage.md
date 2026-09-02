---
type: rule
rule: 4
title: "The temperature stage is one line"
---

# 4. The temperature stage is one line

```python
from core.gui.temp_panel import build_temp_panel
PANELS = [..., build_temp_panel, ...]
```

`self.temp_ctrl` exists on every experiment already, and
`LabApp.shutdown_devices()` switches the PID off and closes the port on
the way out — the window's, not the experiment's, because one window
holds one stage. It confirms the stage stopped rather than assuming a
clean write meant it did; see
[A shutdown path that fails open](../faults/29-a-shutdown-that-fails-open.md).

Record the temperature per run in `metadata` — it belongs **with the
data**, not in a separate header. A stage temperature that lives in a
file header describes the session; one that lives on the row describes
the reading, and a run where the stage was still settling is only
visible in the second form.
