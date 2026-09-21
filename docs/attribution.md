# Attribution and media provenance

Pokémon Helix is an independent fan project, unaffiliated with Nintendo,
Creatures or Game Freak. **Game Freak developed Pokémon Emerald.** Existing
Pokémon content, characters and trademarks remain with their respective owners.
Helix's original host simulation and tooling are separately scoped in
[LICENSE-SCOPE.md](../LICENSE-SCOPE.md); no game-wide MIT license is claimed.

## Engine

Based on **RHH (Rom Hacking Hideout)'s pokeemerald-expansion**, itself based on
**pret's pokeemerald**. Exact upstream:
`36f5cf6271c382d4dc161ba040dd1dd3bc8b2a7f`.

The [upstream README](https://github.com/rh-hideout/pokeemerald-expansion/blob/36f5cf6271c382d4dc161ba040dd1dd3bc8b2a7f/README.md)
requests RHH credit and preservation of Git history. The source bootstrap clones
that history and retains [all contributor credits](https://github.com/rh-hideout/pokeemerald-expansion/blob/36f5cf6271c382d4dc161ba040dd1dd3bc8b2a7f/CREDITS.md).
No root LICENSE exists at this revision. Individual tool notices, including
`tools/gbagfx/LICENSE` (MIT) and `tools/gbafix/COPYING` (GPLv3), remain in that
checkout; those notices do not license the entire game. The native manifest
records the complete discovered license-path inventory.

## Original visual work

The Helix direction combines an indigo laboratory, teal DNA holograms and warm
equipment lights. Selected native build inputs are reused byte-for-byte from
the project's original generated art and deterministic GBA conversions. This
publication generates no new artwork and publishes no prompts, provider
responses, personal profiles or accepted individual packages.

- The approved laboratory-title source was generated in September 2026 through
  OpenRouter with requested model `openai/gpt-image-2.5-sunburst`; the provider
  did not return a model identifier. Source-image SHA-256:
  `19edb72dc21213c84954a655bb2ca53546ce65f638f2e8f9a9e1caf04cdbaa5e`.
- Title rotation/breathing frames were subsequently generated with the built-in
  image tool using that scene as a reference, then converted to native palettes
  and immutable frame bytes. Native playback makes no inference calls.
- The earlier Aurora coast, Lumifin/family sprite inputs and signal-beacon art
  were generated for this project and converted to GBA formats. Their presence
  preserves source dependencies, not accepted individual identities. Public
  fixture bindings are separate and do not establish save compatibility.
- Tile-map layouts and authored event scripts are Helix integration work;
  their referenced Emerald tiles, fonts, sprites and other game content retain
  upstream ownership. Native artwork and screenshots are excluded from MIT.

## Published captures

Both images below are unchanged emulator captures, supplied specifically for
this public presentation. The first is historical title presentation, not V17c
gameplay. The second is the V17c indicator assay, not a public-clone play test.

| File | SHA-256 |
| --- | --- |
| [Animated title](media/helix-title.gif) | `75a72c4812074a43c0dbff2b9873d8137b9c5762858680226124cba7b8fbbf04` |
| [Laboratory result](media/lab-assay.png) | `6a1c342fe243cca6127542643adf56fa23ce201625c3aec7ce4d333c46d82466` |

The [native manifest](../rom-source/manifest.json) binds every exported native
asset by SHA-256. The project does not assert exclusive ownership of generated
images or grant rights in the Pokémon content visible within them.
