# Verification and limits

Public host checks and historical native evidence answer different questions.
This source kickstart does not contain a playable ROM, retained saves or the
generated packages required for the full local game.

## Reproduce public checks

After cloning:

```sh
uv sync --locked --python 3.12 --extra generation
uv run --offline --frozen python -m companion.demo
uv run --offline --frozen python -m unittest discover -s tests -v
uv run --offline --frozen python platform/rg34xx/smoke.py
uv run --offline --frozen python scripts/smoke-agent-tools.py
```

The demo compares sheltered readings 10/11/13 with exposed readings 46/50/54.
To change predictions and inspect complete deterministic results, run
`uv run --offline --frozen python -m companion.demo --config examples/lab-demo.toml --json`.
The service smoke checks loopback request/result, replay, cancellation, restart
and persisted results using temporary synthetic data. Neither opens a player
save nor establishes native gameplay.

The extended suite needs a C compiler (`clang` or `cc`). Agent fixtures use
temporary synthetic identities and explicitly disable tracing. The generation
extra exercises the actual Deep Agents SDK with an offline model and tool.

## V18 public export checks

On 2026-09-21 this export passed **247 tests**, with no skips, using its own
locked Python 3.12 environment. This includes eight C model/preferences tests,
the original 39 public tests and 200 agent/producer/genetics tests. The agent
smoke denied network access and verified persistent dialogue replay, a draft
quest and cached visual asset conversion. All three authoring CLIs passed
fixture/replay checks without provider calls. The original terminal demo and
loopback service smoke also passed.

A clean local clone of `79d7713` independently passed all 247 tests, the demo,
both host smokes and file/fixture checks. A real `uv run langgraph dev` process
started from that clone's root, served a fixture dialogue and replayed it through
the HTTP API, with tracing disabled and no paid calls. The owned server stopped
after the check. Invoking the CLI from an unrelated directory cannot import this
unpackaged project; use the documented repository-root command.

Both Linux ARM64 Docker checks passed: the service remains dependency-free,
and the C indicator model matched Python and independent numeric vectors at
`-O0`/`-O2` with undefined-behavior checks. Reproduce the additional model lane:

```sh
docker build --platform linux/arm64 -f platform/rg34xx/Dockerfile.indicator \
  -t helix-indicator:public-arm64 .
docker run --rm --platform linux/arm64 --network none --read-only \
  --tmpfs /tmp:rw,exec,nosuid,size=64m --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 512m --cpus 1 \
  helix-indicator:public-arm64
```

The initial model container run could compile but could not execute its temporary
test binaries. Explicit `exec` on that isolated tmpfs corrected the configuration;
the service lane retains `noexec`. Neither lane proves ARM7 execution or hardware
behavior on RG34XX. Native preference tests use a host struct stub and do not
establish ordinary-save layout compatibility by themselves.

## Original service container lane

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

The later V18b local candidate recorded **1,158 tests, 408 mGBA checkpoints,
201 distinct inspected screenshots and 18 ordinary Save/Continue pairs**. It
adds native offline assay calculation and saved EN/PT language. Its final
verification commitment is
`bf6eaade8732183bff68e672099cef059667d4a450a229cf054488e33c44bc69`.
This evidence belongs to the retained local ROM, not the sanitized public ROM.
V18b is also unaccepted; V14 remains default and CORAL remains blocked.

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

## Initial native source compilation

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

## V18 public native compilation

The updated overlay compiled in a new isolated checkout with the same pinned
upstream and Arm GNU Toolchain 14.3.Rel1. All **179** manifest source results
matched after compilation; the bootstrap also verified an unchanged second
invocation before building. Only 13 native files changed from the previous
public bundle. Public IDs, existing art, disabled-package aliases and both
package gates remain unchanged.

- Native manifest SHA-256: `e5b16967ff48d952d53cf0d06f8f8483141a5eb282a8f97569f6541916aa1814`.
- Local output ROM SHA-256: `3ea15eed18855b0aa763f7f0fd4fca85a98b20bf50f5a47055f388c4e5efcfd6`.
- Local output ELF SHA-256: `590defcbb8637995b42be77e640a405d751441bf9b8a6d3ac48f0a5e11671064`.

**The public V18 ROM has not run in mGBA or on physical RG34XX.** These binaries
are not distributed. A public gameplay package, its own save namespace and
exact-ROM play evidence remain required. The local candidate's measured assay
wait was about six seconds: the native counter counts task iterations, not
hardware frames. No device performance claim follows from the host model tests.
