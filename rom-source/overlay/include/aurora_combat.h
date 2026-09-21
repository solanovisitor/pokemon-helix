#ifndef GUARD_AURORA_COMBAT_H
#define GUARD_AURORA_COMBAT_H
#include "constants/aurora_adventure_content.h"
struct Pokemon;
struct BattlePokemon;
struct BoxPokemon;
#define AURORA_COMBAT_MAGIC 0xC071
#define AURORA_COMBAT_VERSION 2
#define AURORA_COMBAT_PARENT 1
#define AURORA_COMBAT_CAPTURED 2
#define AURORA_COMBAT_BORN 4
#define AURORA_COMBAT_REWARDED 8
#define AURORA_COMBAT_MIGRATED 16
#define AURORA_COMBAT_ENCOUNTER 32
struct AuroraCombatProfile {
    u8 baseStats[6];
    u8 types[2];
    u16 moves[4];
};
struct AuroraCombatRecord {
    u16 magic, version, flags, attempts;
    u32 xpBefore[2], xpAfter[2];
    u16 lastOutcome, profileVersion;
    u32 crc;
};
extern const u32 gAuroraCombatSaveLayout[20];
extern const u32 gAuroraCombatDescriptor[12];
extern const u8 gAuroraCombatIds[3][32];
extern const struct AuroraCombatProfile gAuroraCombatProfiles[3];
extern const u8 gAuroraCombatProfileHashes[3][32];
extern const u8 gAuroraCombatEventIds[4][32];
extern u16 gAuroraCombatLastResult;
extern u16 gAuroraCombatResolvedBattlers[4];
bool32 AuroraCombatAcceptPredecessor(const u8 *hash);
bool32 AuroraCombatCanContinue(void);
u8 AuroraCombatBaseStat(const struct Pokemon *mon, u32 stat, u8 fallback);
void AuroraCombatApplyBattleTypes(const struct Pokemon *mon, struct BattlePokemon *battle);
void AdoptAuroraCombatParent(void);
void GetAuroraCombatState(void);
void PrepareAuroraCombatEncounter(void);
void FinishAuroraCombatEncounter(void);
void CompleteAuroraCombatBirth(void);
#endif
