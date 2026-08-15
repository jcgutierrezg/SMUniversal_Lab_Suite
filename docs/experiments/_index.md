---
type: index
title: "Experiments"
---

# Experiments

One note per folder under `experiments/`: where the measurement came
from, what it computes, how a cancelled run behaves, and what the saved
CSV holds.

An instrument is never a new experiment - that is what the driver layer
is for. The test for whether something earns a folder here is whether it
produces a different *derived quantity*; a different sweep shape is a
feature of an existing experiment, and a different box is a driver.

> **Stub.** Content arrives in a later patch; see [[migration-status]].
