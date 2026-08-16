---
type: rule
rule: 6
title: "Operator input goes through `core.validation`"
---

# 6. Operator input goes through `core.validation`

`int(float(text))` accepted `2.5` as 2 at five call sites, so a decimal
in an integer box produced **a different experiment from the one
requested, silently.**

```python
from core.validation import whole_number, positive_number, si_level

reversals = whole_number(self.reversals_var.get(), "Reversals",
                         minimum=1, even_above_one=True,
                         reason="so that each polarity is measured the "
                                "same number of times.")
```

`ValidationError` subclasses `ValueError`, so the existing
`except ValueError` around form reading already shows these in a dialog.
It also carries `.field`, so a panel can highlight the offending box.

**This is for operator input only.** The `int(float(...))` calls in
drivers parse SCPI error codes, where truncation is the intended
reading. Do not route those through this module.
