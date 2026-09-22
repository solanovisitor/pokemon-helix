# Pokémon Helix documentation

Start with the game experience, run an experiment, or choose a part of the
project to work on. The public repository contains source and host tools;
the game shown in development captures is not yet a playable public release.

## Explore the game

- [Features](features.md) — companions, fieldwork and laboratory experiments.
- [Roadmap](roadmap.md) — implemented work, candidate features and next contributions.
- [Verification](verification.md) — what has been tested and the limits of that evidence.
- [First native catalog batch](native-assets-batch1.md) — four static designs, scoped map bindings and exact build evidence.

## Run your first experiment

[Getting started](getting-started.md) walks through installation, expected
results and changing a prediction. The demo runs in a terminal with synthetic
inputs and no emulator or API key.

## Work on the project

| I want to… | Start here |
| --- | --- |
| Make a first contribution | [Contribution guide](../CONTRIBUTING.md) |
| Understand the Python, Lua and C components | [Architecture](architecture.md) |
| Reconstruct the pinned Emerald source with Helix changes | [Native source setup](../rom-source/README.md) |
| Work on desktop emulator communication | [Lua bridge](../bridge/README.md) |
| Run tests and the service smoke | [Public verification commands](verification.md#reproduce-public-checks) |
| Run deterministic NPC/Pokémon producers and visual asset tools | [Agent tools](agent-tools.md) |
| Understand the proposed quest coordinator | [Quest contract](quest-agents.md) |
| Continue implementation with another agent | [Development handoff](continue-development.md) |
| Help bring Helix to RG34XX | [Platform limits](architecture.md#platform-limits) and [roadmap](roadmap.md#useful-next-contributions) |

## Project reference

[Attribution and media](attribution.md) · [Licensing](licensing.md) ·
[Security](../SECURITY.md) · [Code of conduct](../CODE_OF_CONDUCT.md) ·
[Maintainer publication workflow](publication.md)
