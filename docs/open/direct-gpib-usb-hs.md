---
type: state
title: "Direct NI GPIB-USB-HS"
---

# Direct NI GPIB-USB-HS

**Windows communication and the full Tier 1/2/3 checkup are bench-proven on a
Keysight B2901A; only robustness/stress follow-up remains open.** On 2026-08-18
a genuine `3923:709b`, revision `0x0101`, opened through WinUSB + bundled
libusb and drove a B2901A at GPIB address 9 through the suite's normal
transport/driver path. The first attempt exposed one required compatibility
step described below.

## Why it exists

Occasionally a bench machine needs a genuine NI GPIB-USB-HS but must not carry
NI-VISA or NI-488.2. `NIUSBGPIBTransport` wraps `ni-gpib-usb-hs==0.1.0` behind
the same `Transport` contract the drivers already use. It is deliberately
optional and explicit:

- normal `uv sync` does not install the third-party GPIB driver; use
  `uv sync --extra direct-gpib`;
- the connection panel still starts on **VISA** and never falls back to direct
  USB control;
- `tools/smu_checkup.py` still infers `visa` from a GPIB resource unless
  `--transport gpib-hs` is written explicitly;
- USB probing happens only after that transport is selected (or explicitly
  listed by the checkup tool); it does not scan GPIB addresses;
- drivers and experiments are unchanged.

The upstream package is GPL-2.0-only. Local bench use does not copy any of its
implementation into this repository, but redistribution/bundling of the
optional dependency needs to respect that license.

## Windows prerequisite

The adapter must be accessible through libusb. Bind the genuine GPIB-USB-HS
USB device (`3923:709b`) to the Windows **WinUSB** driver, for example with
Zadig. That replaces the driver association for this adapter on that Windows
installation; a machine that later needs NI's driver will have to restore that
association. `libusb-package`, already a normal suite dependency, supplies the
libusb DLL used by the direct transport.

Upstream 0.1.0 advertises macOS and Linux, not Windows. On the Windows bench its
constructor opened the adapter successfully, but the first GPIB command returned
`NO_BUS`. A bare UNL (`0x3f`) failed the same way, excluding the SMU address and
SCPI layer. Sending the NI USB `IBSIC` operation (`0f 00 00 00 04 00 00 00`)
pulsed IFC; immediately afterwards UNL succeeded and the B2901A answered
`*IDN?`. `NIUSBGPIBTransport` therefore performs that IFC pulse after every
controller construction, including timeout-recovery reopen. See
`docs/faults/27-direct-gpib-hs-missing-ifc.md`. With that fix in place,
`smu_checkup` Tiers 1, 2 and 3 all passed on the B2901A. This note remains under
`docs/open/` only for the narrower robustness/stress questions below.

## Software validation gate

The direct path is optional hardware, but its software tests are not optional. Before
merging a change to this transport, follow the repository test rules rather than
running one giant pytest process:

1. On the unmodified checkout, run `uv run python run_tests.py --all` and record
   the passing test count. The baseline must be green.
2. Apply the change and run the same command again. Quote both counts in the
   review/commit notes; a new test changes the count, an unrelated disappearance
   needs explaining.
3. Capture `git status --porcelain` before and after the test command and require
   the same output. Tests may create temporary/generated files internally, but they
   must restore the tree before returning.
4. Mutate each new guarantee one at a time and run the repository runner again:
   make direct GPIB the default, move its package into normal dependencies, remove
   the timeout restoration, change the device-clear command, break the shared GPIB
   ownership key, and make normal VISA refresh probe the direct adapter. Each
   mutation must make at least one test fail. Revert the mutation before the next
   round.
5. Do not use sleeps to make a transport test pass. The direct transport tests are
   synchronous; any future threaded test must wait on an observable event/fact and
   drain queued work explicitly, following `tests/README.md`.

`tests/test_ni_gpib_usb_hs_transport.py` covers byte-level transport behaviour and
recovery. `tests/test_direct_gpib_optional.py` separately guards the opt-in policy
and dependency boundary. Keeping those questions separate makes a failure say
whether the adapter contract broke or the application accidentally started using
it by default.

## Bench commissioning result

The staged checkup was completed with the B2901A output terminals safe for the
bench procedure:

```powershell
uv sync --extra direct-gpib
uv run tools/smu_checkup.py --transport gpib-hs --address GPIB0::9::INSTR --tiers 1 --trace
uv run tools/smu_checkup.py --transport gpib-hs --address GPIB0::9::INSTR --tiers 1,2 --trace
uv run tools/smu_checkup.py --transport gpib-hs --address GPIB0::9::INSTR --tiers 1,2,3 --trace
```

All three tiers passed. Tier 1 therefore proves the suite's normal termination,
EOI, query and driver-identification path end to end; Tier 2 proves the
non-sourcing configuration/error-check path; Tier 3 proves the checkup's
controlled sourcing path through the direct transport. Basic Windows
commissioning is complete for this adapter/B2901A combination.

The remaining items below are deliberately narrower fault-injection or stress
coverage and are not blockers for using the commissioned path within its stated
scope.

## Questions the bench must answer

1. **Answered for one bench:** WinUSB + bundled libusb enumerated and opened the
   genuine `3923:709b` adapter successfully.
2. **Answered end to end:** after the required IFC pulse, the suite's Tier 1
   checkup identified the B2901A normally at address 9, proving the direct
   transport's `\n` termination + EOI path through the registered driver. Tiers
   2 and 3 also passed.
3. **Basic reads answered; stress case still open:** the full checkup completed
   without read-framing errors. A deliberately large sweep reply has not yet
   been used to probe the upstream synchronous read limit/truncation boundary.
4. Does a deliberately induced timeout recover: reopen the adapter, pulse IFC,
   send Selected Device Clear, and leave the *next* query aligned with its own
   reply? A failed recovery must leave the transport disconnected.
5. Is repeated connect/disconnect clean, including after a failed connection?
6. Does the same `GPIB0::<addr>::INSTR` lock out a simultaneous VISA/direct
   claimant through the shared ownership key?

Upstream 0.1.0 also has hard scope limits: primary addressing only; no serial
poll, SRQ, parallel poll, secondary addressing, or multi-controller sharing.
If a driver later depends on one of those capabilities, this transport must
refuse that use rather than emulate it invisibly.

When the Windows bench check is complete, move durable facts into the relevant
reference pages, record any actual failures under `docs/faults/`, and remove
this state note only when no validation is still owed.
