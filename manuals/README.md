# Instrument manuals

**The PDFs in this folder are deliberately not committed.** They are
gitignored, so a fresh clone gets this file and nothing else.

## Why

An instrument manual runs tens of megabytes. Committing the set would
put several hundred megabytes into git history permanently — cloned by
every bench machine and by every CI job, on every push, forever, with no
way to remove it afterwards. Adding one instrument is a once-per-lifetime
event; paying for it on every clone is the wrong trade.

## So how do you get them

Copy them in by hand after cloning — USB stick, network share, whatever
is to hand. Nothing in the suite reads them; they are for a person
sitting in front of an instrument that is doing something surprising.

## What is committed instead

The parts that are actually load-bearing live in
`docs/reference/manuals/` as Markdown: the **command summary tables**
and the **per-attribute reset-default tables**.

Those two are what every driver here was written from, and as Markdown
they are greppable, diffable, and citable from a driver note. A PDF is
none of those, and it is absent on any machine that has not had the USB
stick. The reset-default tables in particular have earned their keep:
every driver written from a manual so far has had at least one setting
whose reset value had to be overridden, and the worst of them had no
command in the log to trace it to.

## What should be here

| Instrument | Document |
|---|---|
| Keithley 2401 | Model 2400 Series SourceMeter User's Manual |
| Keithley 2450 | Model 2450 Reference Manual |
| Keithley 2611A | Series 2600A System SourceMeter Reference Manual |
| Keithley 2635B | Series 2600B System SourceMeter Reference Manual |
| Keysight B2901A | B2900 Series SMU SCPI Command Reference |
| Keysight U2722A | U2722A/U2723A USB Modular SMU Programmer's Reference |
| GW Instek GSM-20H10 | GSM-20H10 Programming Manual |
| Undalogic miniSMU MS01 | `minismu_py` documentation and the MS01 spec sheet |

Filenames are not prescribed — nothing looks for them.
