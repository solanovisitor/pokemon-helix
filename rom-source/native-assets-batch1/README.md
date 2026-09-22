# Native catalog batch 1

Final source selection: [`catalog-selection-v2.json`](catalog-selection-v2.json).
It binds four published designs to five existing object positions at the exact
`todeschini/helix-assets` gallery revision
`d7c825f2d15b0818d549b8367d1054cb53c23713`.

| Design | Existing placement | Native frame |
| --- | --- | --- |
| Slate Cobalt low table | HelixResearchPost `(2,5)` | 32×32 |
| Indoor potted tree | HelixResearchPost `(8,1)`, `(9,1)` | 16×32 each |
| Mineral Silver registration terminal | HelixLaboratory `(3,0)` | 32×32 |
| Mineral Silver preparation terminal | HelixLaboratory `(1,9)` | 16×32 |

Every design has only `idle`. Original reference PNG bytes remain intact;
provider PNGs remain available through pinned URLs and SHA-256 hashes. Native
PNG, 4bpp and RGB555 files are separate derivatives. No generation calls,
characters, events, interactions, collision changes or save-format changes are
introduced.

The table uses one uniform scale inside its complete 32×32 native footprint;
its original visible body was 28×32. The other designs retain their original
foreground envelopes. Registration uses alpha≥4 bounds and native opacity uses
alpha≥128; both thresholds, discarded faint-alpha counts and transforms are
recorded. Source images are never trimmed or overwritten.

The requested post backdrop repair reuses the original table's opaque peach
lower-layer tile references `0x6218` in four metatile definitions: `0x223`,
`0x298`, `0x289`, `0x28a`. This changes 66 existing background cells (62 floor,
two below plants, two below shelving), separately from the five object
positions. Furniture foregrounds, map blocks and metatile attributes remain
unchanged by that repair. Both new secondary tilesets are exclusive to the
two Helix rooms; the laboratory receives a byte-identical map/border clone.

Use a fresh isolated game checkout and output directory for conversion:

```sh
uv run --with pillow==11.3.0 python scripts/integrate-native-assets-v2.py \
  --game .local/example/game --output .local/example/conversion \
  --table-variation slate_cobalt --install
uv run --with pillow==11.3.0 python scripts/verify-native-assets-v2.py \
  --game .local/example/game --conversion .local/example/conversion
```

Omitting `--catalog` downloads only the four hash-checked published PNGs;
passing an existing pinned export enables offline conversion. Compilation and
`scripts/verify-native-assets-compiled.py` check the linked graphics and map
bindings. Source renders in this directory are previews, not emulator captures;
gameplay acceptance requires the separate exact-ROM mGBA evidence.
