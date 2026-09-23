---
type: rule
rule: 4
title: "The temperature stage is one line"
---

# 4. The temperature stage is one line

```python
class MyExperiment(Experiment):
    USES_TEMP_STAGE = True
```

That is the whole of it. `LabApp` builds the stage itself — the reading
as a strip in the top row, the controls in a window behind the Stage
button — because one window holds one stage, and two tabs each building
their own would be two `TemperatureController`s on one COM port.

The split follows the use: the stage is *watched* continuously and *set*
twice a session, so the watching half is always on screen and the
commanding half is not. Closing that window changes nothing about the
stage - the connection, the PID and the polling are the controller's,
not the widgets'.

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
