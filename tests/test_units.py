"""Unit-parsing round-trip: dropdown labels must survive the trip back
to floats, since a mis-parsed label would silently source the wrong
current."""
from core.limits import format_amps, format_volts
from experiments.vanderpauw.experiment import _parse_si

CURRENTS = [1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0, 1.5]
VOLTAGES = [0.02, 0.2, 2.0, 20.0, 200.0]

def _collect_roundtrip():
    bad = []
    for a in CURRENTS:
        label = format_amps(a)
        back = _parse_si(label)
        if abs(back - a) > abs(a) * 1e-9:
            bad.append((a, label, back))
    for v in VOLTAGES:
        label = format_volts(v)
        back = _parse_si(label)
        if abs(back - v) > abs(v) * 1e-9:
            bad.append((v, label, back))
    return bad

if __name__ == "__main__":
    bad = _collect_roundtrip()
    for a in CURRENTS:
        print(f"  {a:<10g} -> {format_amps(a):>10}  -> {_parse_si(format_amps(a)):g}")
    for v in VOLTAGES:
        print(f"  {v:<10g} -> {format_volts(v):>10}  -> {_parse_si(format_volts(v)):g}")
    print("\nFAILURES:", bad if bad else "none")


# --- Wave 0a: these used to return a list of failures that only the
# --- __main__ block inspected. Under pytest a returned value is
# --- ignored, so without these wrappers all of them would pass
# --- unconditionally. The collectors above are unchanged.

def test_roundtrip():
    bad = _collect_roundtrip()
    assert not bad, f"{len(bad)} failure(s): {bad[:5]}"
