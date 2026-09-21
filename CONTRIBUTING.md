# Contributing

Start with a small, reproducible improvement. Useful first contributions include
clearer experiment explanations, synthetic failure cases, accessibility feedback
and the [open roadmap](docs/roadmap.md). Explain the player or contributor problem
in an issue before starting a broad feature or save-format change.

## Set up and check your change

Install Git and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From your fork:

```sh
git clone https://github.com/YOUR-USERNAME/pokemon-helix.git
cd pokemon-helix
uv sync --locked --python 3.12
uv run --offline --frozen python -m companion.demo
uv run --offline --frozen python -m unittest discover -s tests -v
uv run --offline --frozen python platform/rg34xx/smoke.py
```

Setup may download Python. The demo and tests use synthetic inputs and require
no API keys, emulator, personal files or retained game packages. The socket smoke
uses temporary local data and loopback networking. See [verification](docs/verification.md)
for the restricted container check.

## Keep responsibilities clear

Use Python for bounded host computation, Lua for the emulator bridge, and
C/event scripts for native game behavior. See [architecture](docs/architecture.md).
Validate lengths, identifiers, enums and current request bindings. Keep networking
and inference off the emulator's frame loop. Deterministic fixtures are the
default; live inference must be an explicit, separately bounded integration.

The public native source is a patch and overlay against a pinned upstream, as
explained in [native source setup](rom-source/README.md).
Preserve upstream history, authorship and notices. Do not copy unrelated local
development history into this repository or widen the [license](LICENSE) to
third-party game content.

Never upload ROMs, saves, savestates, credentials, real genetic files, personal
profiles, conversations or private authoring material. Reproduce problems with
synthetic inputs. Report vulnerabilities using [SECURITY.md](SECURITY.md), and
follow the [code of conduct](CODE_OF_CONDUCT.md).

## Open a pull request

Describe the problem, resulting behavior, commands you ran and remaining limits.
Use focused tests for changed behavior; do not claim the historical game suite
ran against this public export. New native gameplay claims require the exact
compiled ROM in mGBA, inspected screenshots, state assertions and ordinary
Save/Continue evidence. Record source/package/ROM identities without distributing
the ROM or real player data. Host checks alone cannot establish playability.

Keep original saves untouched, use isolated test data and release injected inputs.
Changes must preserve existing individual identities and histories. V14 remains
the accepted local default; candidate status and CORAL's blocked birth do not
change merely because a pull request passes CI.
