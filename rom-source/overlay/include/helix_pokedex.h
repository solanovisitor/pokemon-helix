#ifndef GUARD_HELIX_POKEDEX_H
#define GUARD_HELIX_POKEDEX_H

// Read-only inspection exports. UI state is session-only, never save data.
enum {
    HELIX_DEX_CURRENT,
    HELIX_DEX_TRAITS,
    HELIX_DEX_ORIGIN,
    HELIX_DEX_DNA,
    HELIX_DEX_PAGE_COUNT,
};
struct HelixPokedexView {
    u16 open, page, section, help;
    u16 inspection, metadataReady, recipe, reserved;
};
extern struct HelixPokedexView gHelixPokedexView;
extern const u8 gHelixPokedexPackageHash[32];
extern const u8 gHelixPokedexGenome[3][96];
extern const u8 gHelixPokedexChanges[3][24];
u8 HelixPokedexAllele(u16 recipe, u16 copy, u16 locus);
bool32 HelixPokedexChanged(u16 recipe, u16 copy, u16 locus);
void CB2_OpenHelixPokedex(void);

#endif
