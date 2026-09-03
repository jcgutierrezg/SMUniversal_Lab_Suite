"""Regenerate the golden reference files under `tests/golden/`.

Run this **only** when a method's version has been deliberately bumped
in `core.calculation.METHODS`, and read what changed before committing:
the whole point of the golden files is that they do not move on their
own. Regenerating them to make a red test go green throws away the
guard §28 asks for.

    uv run python tools/make_goldens.py

The cases themselves live in `tests/golden_cases.py` so that the values
being asserted and the inputs producing them are never edited in the
same place at the same time.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Both, and in this order: `core` is imported from the project root,
# `golden_cases` by bare name from the tests directory - which is how
# pytest sees it, and how `stage_blocking_smu` is already imported. One
# spelling in both places means the module cannot be found by the tool
# and missed by the suite.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from golden_cases import CASES, evaluate  # noqa: E402

from core.calculation import version_of  # noqa: E402


def main():
    out_dir = ROOT / "tests" / "golden"
    out_dir.mkdir(exist_ok=True)
    for method, spec in sorted(CASES.items()):
        payload = {
            "method": method,
            "version": version_of(method),
            "tolerance": spec["tolerance"],
            "cases": [
                {"name": case["name"], "args": case["args"],
                 "expect": evaluate(method, case["args"])}
                for case in spec["cases"]
            ],
        }
        path = out_dir / f"{method}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        print(f"  wrote {path.relative_to(ROOT)} "
              f"({len(payload['cases'])} cases, v{payload['version']})")


if __name__ == "__main__":
    main()
