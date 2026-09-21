# Native integration source

This is Helix C/event/map source and selected original-art build inputs. It is
not a ROM, an accepted release or a playable public package. Source comes from
the local V17c integration, with accepted individual bindings replaced by
deterministic public fixtures. V14 remains the accepted local default.

## Reconstruct source

From the public repository root, after the README's Python setup:

```sh
uv run --offline --frozen python scripts/check-public-native-fixtures.py
uv run --offline --frozen python scripts/bootstrap-game.py
```

Bootstrap clones the complete RHH `pokeemerald-expansion` history, checks out
`36f5cf6271c382d4dc161ba040dd1dd3bc8b2a7f`, verifies the bundle, applies the
text patch and copies the explicit overlay. It never resets or cleans an
existing checkout. A second invocation verifies the applied files. Use a new
`--destination` for an updated overlay. A fresh clone requires network access
and space for the upstream history.

Install the pinned upstream's
[build prerequisites](https://github.com/rh-hideout/pokeemerald-expansion/blob/36f5cf6271c382d4dc161ba040dd1dd3bc8b2a7f/INSTALL.md)
before an experimental compilation. With an ARM embedded GCC toolchain:

```sh
PATH="$ARM_TOOLCHAIN/bin:$PATH" make -C game -j4 TOOLCHAIN="$ARM_TOOLCHAIN" DINFO=1
```

Set `ARM_TOOLCHAIN` to the toolchain installation root as described by upstream;
no developer-specific toolchain is included. The historical development test
suite and private build scripts are not part of this public export. Public
host tests do not need the native checkout.

## Packages and identity

`HELIX_GENESIS_ENABLED` and `AURORA_ADVENTURE_ENABLED` stay disabled. The
accepted founder/adventure packages, stores, expression profiles and saves are
absent. Compilation cannot reproduce the V14/V17c opening or prove their save
compatibility. Never import an accepted or personal save into this integration.
No native gameplay or handheld playability is claimed for this export.

The upstream graphics dependency scanner also sees inactive package branches.
Five absent package sprite sets therefore contain byte-identical copies of
the reviewed Lumifin sprite/palette as **build placeholders**. The manifest
records every alias, and the fixture checker verifies them. These are not the
accepted founders, rival or child artwork and must not be used to imply a
complete gameplay package. No accepted package is opened to supply them.

Embedded legacy individual/package constants use the separate namespace
`pokemon-helix/public-source-fixture/v1`. The generated header and checker bind
synthetic IDs/genomes, placeholder profiles and reused original artwork without
claiming that the new genomes generated that art. `--write` regenerates only
that fixture header; it does not create or admit a game package. CORAL remains
blocked. New public gameplay needs its own complete package, save namespace,
compiled-ROM mGBA screenshots, state assertions and ordinary Save/Continue proof.

`manifest.json` enumerates every patch result and overlay file with SHA-256,
including converted title/frame bytes needed by native `INCBIN`. These are
build inputs. ROM/ELF outputs, saves, root assets, prompts, private canon,
credentials and retained development evidence are excluded.

The [license boundary](../docs/licensing.md) excludes this integration from MIT.
RHH/pret history, contributors and existing notices remain intact; see
[attribution](../docs/attribution.md) and [public update workflow](../docs/publication.md).
