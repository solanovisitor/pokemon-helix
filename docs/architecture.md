# Architecture

The game keeps ordinary gameplay and saved decisions native. A bounded host
service can calculate an experiment; the ROM remains responsible for deciding
whether that result applies and whether an item is consumed.

```text
GBA C / event scripts ← bounded mailbox → desktop mGBA Lua
                                              ↕ loopback
                                      Python lab service
                                              ↓
                               deterministic assay + local journal
```

The public demo calls the assay directly. It does not start an emulator, load a
save, create a Pokémon or replay an accepted individual's history.

## Repository boundaries

| Location | Responsibility |
| --- | --- |
| `genetics/` | Pure synthetic indicator calculation |
| `companion/` | Runnable demo and bounded local lab service |
| `bridge/` | Desktop mGBA Lua transport for a matching native mailbox |
| `rom-source/` | Helix patch/overlay and exact upstream identity |
| `platform/rg34xx/` | Service smoke and platform preparation; not a complete device port |
| `tests/` | Synthetic checks runnable from this public repository |

The [native export](../rom-source/README.md) does not supply the generated founder
and adventure packages used by the recorded local build. A successful upstream
bootstrap is source reconstruction, not proof of a playable or save-compatible
Helix release.

## The indicator model

`helix-indicator-hill-v1` describes one fictional culture's response to a stimulus:

```text
signal(s) = round_half_up(10 + 80 × s² / (500² + s²)), 0 ≤ s ≤ 1000
```

Integer arithmetic makes results deterministic. Sheltered probes at 0, 50 and
100 give 10, 11 and 13 (center 11, range 3). Exposed probes at 450, 500 and 550
give 46, 50 and 54 (center 50, range 8). These are controlled probe conditions,
not independent biological replicates. Parameters are fictional and uncalibrated;
the model does not read Pokémon DNA or demonstrate heredity, real biology or
genotype-by-environment interaction. Prediction affects interpretation, not physics.

Requests bind the condition and prediction to bounded identifiers, quest revision
and a state commitment. Verification recalculates the result against the current
expected binding. Unsupported fields and malformed values are refused. Hashes
check integrity and context; they do not authenticate ownership.

The service handles computation outside the emulator's frame loop, journals
complete results, bounds work and supports replay/cancellation. A host journal
entry is not a native Save acknowledgment. The native side must recheck context,
items and admitted results before applying an effect. The current transport is
loopback-only and provides no shared-world authority.

## Platform limits

The usual libretro mGBA frontend lacks the desktop Lua bridge used here. An
RG34XX adapter needs explicit mailbox bounds, scheduling, cancellation, controls
and normal-save proof on physical hardware. Linux ARM64 container checks cover
the Python service only. Offline reset currently returns the host-backed language
preference to English; offline language persistence is unfinished.
