"""The Markdown report a checkup writes.
"""
import time

from smuniversal_lab_suite.core.provenance import as_markdown_lines


def build_report(driver, results, address="", sensing_note=None,
                 open_circuit=True, provenance=None, stopped_early=False):
    """Render the results as Markdown."""
    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for result in results:
        counts[result.severity] += 1

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    verdict = "FAIL" if counts["fail"] else (
        "PASS WITH WARNINGS" if counts["warn"] else "PASS")

    lines = [
        f"# Instrument checkup - {type(driver).DISPLAY_NAME}",
        "",
        f"- **Result:** {verdict}",
        f"- **When:** {stamp}",
        f"- **Address:** {address or 'not recorded'}",
        f"- **Driver:** `{type(driver).__name__}`",
        *as_markdown_lines(provenance or {}),
        f"- **Checks:** {counts['pass']} passed, {counts['warn']} warned, "
        f"{counts['fail']} failed, {counts['skip']} skipped",
        "",
        "> This checkup assumes **nothing is connected to the output**. "
        "The measurement checks expect open-circuit behaviour, so a "
        "connected sample will produce warnings that are not faults."
        if open_circuit else
        "> This checkup was told **something is connected** to the "
        "output. The open-circuit measurement checks were skipped, "
        "because the expected reading is unknown. Everything else ran "
        "normally.",
        "",
    ]
    if sensing_note:
        lines += [f"> {sensing_note}", ""]
    # Deliberately the built-in sum, not math.fsum: this counts
    # results, and fsum would return a float where an integer count is
    # meant. The 3.12 float-summation change that moved the maths
    # modules does not touch integer summation.
    if stopped_early:
        lines += [
            "> **This checkup did not finish.** The link to the instrument "
            "went out of step, so the run stopped there rather than record "
            "readings that would answer the previous command. Everything "
            "listed below was taken before that point and is sound; "
            "everything the instrument was never asked is simply absent. "
            "Reconnect the instrument and run it again.", ""]

    if counts["fail"]:
        lines += ["## Failures", ""]
        for result in results:
            if result.severity == "fail":
                lines.append(f"- **{result.name}** - {result.detail}")
        lines.append("")
    if counts["warn"]:
        lines += ["## Warnings", ""]
        for result in results:
            if result.severity == "warn":
                lines.append(f"- **{result.name}** - {result.detail}")
        lines.append("")

    titles = {1: "Tier 1 - identity and declarations",
              2: "Tier 2 - configuration syntax (output off)",
              3: "Tier 3 - live measurement"}
    for tier in (1, 2, 3):
        rows = [r for r in results if r.tier == tier]
        if not rows:
            continue
        lines += [f"## {titles[tier]}", "",
                  "| Check | Result | Detail |", "|---|---|---|"]
        for result in rows:
            detail = (result.detail or "").replace("|", "\\|")
            lines.append(f"| {result.name} | {result.severity} | {detail} |")
        lines.append("")

    return "\n".join(lines)
