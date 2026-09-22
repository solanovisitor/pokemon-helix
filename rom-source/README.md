# Native integration source

This is Helix C/event/map source and selected original-art build inputs. It is
not a ROM, an accepted release or a playable public package. Source comes from
the local V18b integration, with accepted individual bindings replaced by
deterministic public fixtures. V14 remains the accepted local default.

The V18b source adds an offline indicator calculation and ordinary-save language
preferences. This public variant still needs its own complete package and mGBA
verification before any claim of playable delivery.

The first native catalog batch replaces four static designs at five existing
positions: the Research Post slate-cobalt table and its two potted trees, plus the laboratory
registration desk and preparation bench. The isolated secondary tilesets retain
the original map cells, collisions, scripts and NPC placements. Published source
images remain unchanged; conversion hashes are in
[public-conversion-v2.json](native-assets-batch1/public-conversion-v2.json).
The post's reviewed lower tile layer gives the table, plants and open floor a
continuous native peach floor; all collision and behavior attributes stay exact.
The public source retains its V18 fixture boundary. Its exact ROM was separately
tested in two synthetic empty-room fixtures for these props; see the
[runtime scope and captures](../docs/native-assets-batch1.md). That result does
not establish public campaign access or accepted-save compatibility.

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

The committed patch and overlay already include the catalog batch. Maintainers
can reproduce the conversion against the preceding public source at commit
`5d0e7d8b580bf164708aa7d4f324b33656a06086`, using a fresh isolated checkout.
The exact catalog revision is
`d7c825f2d15b0818d549b8367d1054cb53c23713`, config `gallery` of
[`todeschini/helix-assets`](https://huggingface.co/datasets/todeschini/helix-assets).
The converter downloads only the four pinned PNGs and verifies their hashes.
To work without network access, add `--catalog <export>` pointing to that
revision's local `images/` directory parent.

```sh
mkdir -p .local/catalog-replay/base
git archive 5d0e7d8b580bf164708aa7d4f324b33656a06086 rom-source \
  | tar -x -C .local/catalog-replay/base
uv run --offline --frozen python scripts/bootstrap-game.py \
  --bundle .local/catalog-replay/base/rom-source \
  --destination .local/catalog-replay/game
uv run --offline --with pillow==11.3.0 python scripts/integrate-native-assets-v2.py \
  --game .local/catalog-replay/game \
  --output .local/catalog-replay/conversion --table-variation slate_cobalt --install
uv run --offline --frozen python scripts/export-native-assets-bundle-v2.py \
  --game .local/catalog-replay/game --conversion .local/catalog-replay/conversion
```

The converter rejects an already integrated checkout. The exporter verifies
every declared derived file and refuses unrelated edits to public source. It
does not import packages or saves, invoke inference, or produce a ROM.
The four replacements contain no decorative DNA or real logos.

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
absent. Compilation cannot reproduce the V14/V18b opening or prove their save
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
