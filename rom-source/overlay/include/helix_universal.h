#ifndef GUARD_HELIX_UNIVERSAL_H
#define GUARD_HELIX_UNIVERSAL_H

#include "helix_universal_types.h"

struct BoxPokemon;

enum HelixUniversalStatus
{
    HELIX_UNIVERSAL_NONE,
    HELIX_UNIVERSAL_OK,
    HELIX_UNIVERSAL_UNSUPPORTED,
    HELIX_UNIVERSAL_UNREGISTERED,
    HELIX_UNIVERSAL_CORRUPT,
    HELIX_UNIVERSAL_FULL,
    HELIX_UNIVERSAL_COLLISION,
    HELIX_UNIVERSAL_UNKNOWN,
    HELIX_UNIVERSAL_DUPLICATE,
    HELIX_UNIVERSAL_EMPTY,
};

enum HelixUniversalOrigin
{
    HELIX_UNIVERSAL_ENCOUNTER = 1,
    HELIX_UNIVERSAL_LEGACY = 2,
};

// Observer snapshots only; never a mailbox and never written by external tools.
struct HelixUniversalView
{
    u32 status, origin, location, slot, species, count;
    u32 namespace[3], serial, seed[4];
    u8 genome[HELIX_UNIVERSAL_GENOME_BYTES];
    u32 genomeCrc;
};
extern struct HelixUniversalView gHelixUniversalView;
extern struct HelixUniversalView gHelixUniversalEncounter;
extern u32 gHelixUniversalMigrationStatus;
extern u32 gHelixUniversalMigrated;
extern const u32 gHelixUniversalSaveLayout[16];
extern const u32 gHelixUniversalDescriptor[8];

u32 HelixUniversalCrc32(const u8 *data, u32 size);
void HelixUniversalExpandGenome(const u32 seed[4], u8 genome[HELIX_UNIVERSAL_GENOME_BYTES]);
u32 HelixUniversalStoreCrc(const struct HelixUniversalStore *store);
u32 HelixUniversalValidateStore(const struct HelixUniversalStore *store);
void HelixUniversalNewGame(void);
void HelixUniversalContinue(void);
void HelixUniversalRegisterEncounter(struct BoxPokemon *mon);
u32 HelixUniversalInspect(const struct BoxPokemon *mon, struct HelixUniversalView *view);
void HelixUniversalInspectFirst(void);

// Checksum-valid copy access in pokemon.c; no generic getter's bad-egg mutation.
bool32 HelixUniversalReadBox(const struct BoxPokemon *mon, u16 *species, u8 *tag);
bool32 HelixUniversalWriteTag(struct BoxPokemon *mon, u8 tag);

#endif
