#ifndef GUARD_AURORA_ADVENTURE_H
#define GUARD_AURORA_ADVENTURE_H

#include "constants/aurora_adventure_content.h"

#define AURORA_ADVENTURE_MAGIC 0xAD71
#define AURORA_ADVENTURE_VERSION 1
#define AURORA_ADVENTURE_DISABLED 0
#define AURORA_ADVENTURE_BOUND 1
#define AURORA_ADVENTURE_INVALID 2
#define AURORA_ADVENTURE_UNBOUND 3
#define AURORA_ADVENTURE_SAVE_WORDS 20
#define AURORA_ADVENTURE_ISSUED 3

// Forty bytes in audited unused event vars. The 104 legacy bytes are untouched.
// Both issuance bits become permanent in the same synchronous family commit.
struct AuroraAdventureRecord
{
    u16 magic;
    u16 versionFlags;
    u8 packageHash[32];
    u32 crc;
};

extern const u32 gAuroraAdventureSaveLayout[24];
extern const u32 gAuroraAdventureDescriptor[8];
extern const u8 gAuroraAdventureIds[4][32];
extern u16 gAuroraAdventureLastResult;
extern u16 gAuroraAdventureRecoveryMode;
struct Pokemon;
void AuroraAdventureObserveBattleEnd(const struct Pokemon *first, const struct Pokemon *second);
bool32 AuroraAdventureValidateRecord(const struct AuroraAdventureRecord *record);
bool32 AuroraAdventureCanContinue(void);
void GetAuroraAdventureState(void);
bool32 AuroraAdventureIsPredecessor(void);
void AuroraAdventureWriteCurrentBinding(void);
void AdoptAuroraAdventureFamily(void);
void GetAuroraAdventurePartnerReady(void);
void GetAuroraAdventureBattleReady(void);
void GetAuroraAdventureBattleWon(void);

#endif
