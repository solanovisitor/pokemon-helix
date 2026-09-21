# Verification and limits

Public host checks and historical native evidence answer different questions.
This source kickstart does not contain a playable ROM, retained saves or the
generated packages required for the full local game.

## Reproduce public checks

After cloning:

```sh
uv sync --locked --python 3.12
uv run --offline --frozen python -m companion.demo
uv run --offline --frozen python -m unittest discover -s tests -v
uv run --offline --frozen python platform/rg34xx/smoke.py
```

The demo compares sheltered readings 10/11/13 with exposed readings 46/50/54.
To change predictions and inspect complete deterministic results, run
`uv run --offline --frozen python -m companion.demo --config examples/lab-demo.toml --json`.
The service smoke checks loopback request/result, replay, cancellation, restart
and persisted results using temporary synthetic data. Neither opens a player
save nor establishes native gameplay.

The Linux ARM64 check uses Docker:

```sh
docker build --platform linux/arm64 -f platform/rg34xx/Dockerfile \
  -t helix-lab-service:public-arm64 .
docker run --rm --platform linux/arm64 --network none --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 256m --cpus 1 \
  helix-lab-service:public-arm64
```

The container exercises the Python service, not RG34XX hardware or its emulator.
Public CI runs the checks available in this export. It does not run the complete
historical development suite, compile a complete Helix release or operate mGBA.

Publication preparation on 2026-09-21 passed 39 public unit tests (including 19 bootstrap safety checks), the local
socket smoke and the restricted Linux ARM64 container smoke on this export.
The container used Python 3.12.14 as unprivileged UID 65532. An independent clone from GitHub at `fcf101c` passed the README quickstart,
all 39 tests, socket smoke and public-file/fixture checks. Both hosted jobs
passed in [GitHub Actions run 35618923296](https://github.com/solanovisitor/pokemon-helix/actions/runs/35618923296).
These are public-export checks, separate from the historical local results below.

## Historical local evidence

On 2026-09-21, the retained V17c candidate record reported **1,070 passing
tests, 384 mGBA checkpoints, 205 distinct inspected images and 12 ordinary
Save/Continue pairs**. Its preservation audit covered 9,139 original paths.
These counts belong to the local development build and its retained evidence;
they are not results from a public fresh clone or this repository's CI.

The integrated record binds 153 files. These SHA-256 commitments identify the
immutable local records; the underlying records are not distributed here:

| Record | SHA-256 |
| --- | --- |
| Integrated V17c verification | `eaa0cd268c6444659d636b8394a0b73beb5fa576d642cc28c3df93f2b2309881` |
| Final independent supplementary review | `b3e977109496eea23e12ef56529d8c9813290e26ade4f97b9c9b271983fb3b0d` |

V14 remains accepted/default **locally**; V15c, V16b and V17c are verified
candidates. CORAL remains blocked. The historical V17c run did not prove all
model branches in mGBA, fresh opening/duel, capture/PC/evolution or arbitrary
savestate forks on that ROM. Native DNA is limited to Wingull/Pelipper with
40 lifetime records, including abandoned encounters. Offline reset returns the
host-backed language preference to English.

## Published images

Both files are unmodified emulator captures, selected individually. The title
is a historical presentation capture, not a V17c gameplay test. The laboratory
image shows V17c's sheltered assay result. Neither image establishes a runnable
public ROM or handheld playability.

| File | SHA-256 |
| --- | --- |
| [Title GIF](media/helix-title.gif) | `75a72c4812074a43c0dbff2b9873d8137b9c5762858680226124cba7b8fbbf04` |
| [Assay PNG](media/lab-assay.png) | `6a1c342fe243cca6127542643adf56fa23ce201625c3aec7ce4d333c46d82466` |

New gameplay claims require the exact compiled ROM, mGBA screenshots inspected
alongside state assertions and ordinary-save evidence. RG34XX claims additionally
require a real device, frontend, controls, saves and power/peripheral checks.
Preserve original saves and use isolated inputs for all future verification.

## Native source compilation

On 2026-09-21, the integration compiled in an isolated checkout of the exact
upstream, using Arm GNU Toolchain 14.3.Rel1 (GCC 14.3.1), GNU Make 3.81 and
Apple clang 17 on macOS ARM64. Upstream generation scripts used Python 3.9.6;
the public host suite used Python 3.12. All **174** patched/overlay source files
matched the public native manifest after the build. The complete upstream was
cloned from its public URL; no retained Helix package was installed.

The build required explicit toolchain `PATH`, reviewed art placeholders for
inactive dependency branches and the authored-teachable symbol adjustment
recorded in the manifest. Those corrections are included in the public source.

- Local output ROM SHA-256: `b1b4d6bcd54cdb775036c9dc527d37b4cb51618c30698de335661f95e61e9605`.
- Local output ELF SHA-256: `e5741024fa14cc031c193b9b3c0c21dfa5575309bbc69a8c13d9bcbb80ba346e`.

Neither binary is distributed. Both generated-package gates stayed disabled;
public fixture identities and placeholder art are not the accepted game content.
**This ROM was not run in mGBA.** Compilation is not gameplay, save compatibility,
a full public Helix release, or RG34XX proof. Follow the
[native setup and remaining package gate](../rom-source/README.md).
