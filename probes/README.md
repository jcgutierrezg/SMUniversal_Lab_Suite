# Console scripts

Scratch scripts for `tools/scpi_console.py --script`. Untracked and
gitignored: they are working material for one question at one bench,
not part of the suite.

```powershell
uv run python tools/scpi_console.py --address <addr> --script probes/thing.txt
```

**Anything a script establishes belongs in the instrument's note**, not
here. A script that produced a finding has done its job and can be
deleted; a folder of old ones is a place to go looking for an answer
that was never written down.

This folder exists so those scripts do not sit in the repository root,
where they made every checkup report say `dirty: True` — and a
provenance flag that is always set says nothing. See `.gitignore`.
