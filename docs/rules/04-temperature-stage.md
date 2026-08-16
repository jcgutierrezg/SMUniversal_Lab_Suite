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
`Experiment.shutdown_devices()` turns the PID off and closes the port.

Record the temperature per run in `metadata` — it belongs **with the
data**, not in a separate header. A stage temperature that lives in a
file header describes the session; one that lives on the row describes
the reading, and a run where the stage was still settling is only
visible in the second form.
