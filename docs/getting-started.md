# Getting started

[Documentation](README.md) · [Features](features.md) · [Contributing](../CONTRIBUTING.md)

Run a small, deterministic version of Helix's laboratory experiment. This
terminal demo calculates a fictional indicator culture's response to two
conditions. It does not launch the game or require a ROM, emulator, API key
or player save.

## Install and run

Install [Git](https://git-scm.com/downloads) and
[uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```sh
git clone https://github.com/solanovisitor/pokemon-helix.git
cd pokemon-helix
uv sync --locked --python 3.12
uv run --offline --frozen python -m companion.demo
```

Initial setup may download Python 3.12. After setup, the demo runs offline
with no third-party Python dependencies.

## Read the result

The demo prints three controlled readings for each condition:

| Condition | Readings | Center | Range |
| --- | --- | --- | --- |
| Sheltered | 10, 11, 13 | 11 | 3 |
| Exposed | 46, 50, 54 | 50 | 8 |

The exposed condition has a higher center and wider range. These are fixed
probe conditions, not random samples. Running the same inputs again gives
the same result.

## Make a prediction

Open [examples/lab-demo.toml](../examples/lab-demo.toml). Each prediction can be
`stable` or `sensitive`. Try changing `sheltered` to `"sensitive"`, then run:

```sh
uv run --offline --frozen python -m companion.demo --config examples/lab-demo.toml --json
```

The readings and observation stay the same. In the structured output,
`prediction_match` is now `false` for the sheltered condition: your prediction
did not match the observed response. The model is fictional and uncalibrated;
it does not read or edit Pokémon DNA.

## Choose your next step

- [Understand the model and service](architecture.md#the-indicator-model).
- [Run tests and service checks](verification.md#reproduce-public-checks).
- [Work on native game source](../rom-source/README.md). Source reconstruction
  does not supply a playable public Helix release.
- [Make a contribution](../CONTRIBUTING.md).
