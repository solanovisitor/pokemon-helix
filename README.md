# Pokémon Helix

<img src="docs/media/helix-title.gif" width="480" alt="Pokémon Helix title: a glowing DNA helix in a blue laboratory beneath an aurora">

[Features](docs/features.md) · [Getting started](#getting-started) · [Documentation](docs/README.md) · [Contributing](CONTRIBUTING.md)

**Pokémon Helix** is an experimental Pokémon Emerald fan game about field
research, lasting companions and the pursuit of extraordinary lineages.
Learn the nature of the world, earn the trust of its people, and become a
breeder whose knowledge matters.

The aim is to make Pokémon rare and meaningful: companions with histories,
practical roles and a place in the world. Observation, care and experiments
should shape your progress alongside battles. Breeding is a long-term goal
still in development.

**Public availability:** this repository provides native source and a runnable
laboratory simulation. A playable public Helix release is not available yet.

## Features

Local development builds include:

- **Companions with continuity.** A laboratory opening, persistent first
  companions and records for individual Pokémon.
- **Research in the field.** Investigations and village work, including shared
  watering that the game remembers.
- **Hands-on experiments.** A candidate laboratory lesson with MIRA and ADA:
  predict a culture's response, measure it and revisit the saved result.

<img src="docs/media/lab-assay.png" width="320" alt="Laboratory result showing sheltered readings of 10, 11 and 13, with a range of 3">

*Emulator captures from local development: historical title presentation above;
candidate laboratory lesson here. [Explore the features and their status](docs/features.md).*

## Getting started

Try the deterministic laboratory simulation in your terminal. It compares
sheltered and exposed conditions using synthetic data; no emulator, API key
or player save is needed.

Install [Git](https://git-scm.com/downloads) and
[uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```sh
git clone https://github.com/solanovisitor/pokemon-helix.git
cd pokemon-helix
uv sync --locked --python 3.12
uv run --offline --frozen python -m companion.demo
```

[Understand the results and change a prediction](docs/getting-started.md),
or [set up the native source](rom-source/README.md).

## Documentation and contributions

The [documentation](docs/README.md) covers the game, architecture, source setup
and verification. To help, start with clearer laboratory lessons, synthetic
test cases or the [public game-build work](docs/roadmap.md#useful-next-contributions).
See [Contributing](CONTRIBUTING.md) for setup and pull requests.

## Credits

Built on [RHH's pokeemerald-expansion](https://rh-hideout.github.io/pokeemerald-expansion/)
and [pret's pokeemerald](https://github.com/pret/pokeemerald). Unaffiliated with
Nintendo, Creatures or Game Freak. [Credits and media provenance](docs/attribution.md)
· [Licensing](docs/licensing.md).
