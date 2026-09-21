#ifndef GUARD_HELIX_GENESIS_H
#define GUARD_HELIX_GENESIS_H
#include "constants/helix_genesis_content.h"
#include "aurora_combat.h"
#ifndef HELIX_GENESIS_RESIDENT_COUNT
#define HELIX_GENESIS_RESIDENT_COUNT 3
#endif
struct Pokemon;
struct BoxPokemon;
struct BattlePokemon;
enum {
    HELIX_INSPECT_INVALID,
    HELIX_INSPECT_PENDING,
    HELIX_INSPECT_PARTY,
    HELIX_INSPECT_BOXED,
    HELIX_INSPECT_MISSING,
};
u16 HelixGenesisInspect(struct BoxPokemon *out);
u16 HelixGenesisInspectResident(u16 resident, struct BoxPokemon *out);
struct HelixCrossRecord {
    u16 magic;
    u8 version, flags;
    u32 nautilXpBefore, revaXpBefore, revaXp, crc;
};
extern const u32 gHelixCrossSaveLayout[14];
extern const u32 gHelixCrossDescriptor[8];
extern const u32 gHelixCrossAdmissionReleased;
extern const u8 gHelixCrossEventIds[3][32];
extern const u8 gHelixGenesisPredecessorHash[32];
void GetHelixCrossState(void);
void AdmitHelixCross(void);
u32 HelixGenesisRivalExperience(void);
void GetHelixLabLanguage(void);
void BufferHelixLabPage(void);
struct HelixGenesisRecord {
    u32 magic;
    u8 version, stage, soul, dnaTutorial;
    u8 recipe, issued, duelWins, lastOutcome;
    u16 attempts, memories;
    u8 packageHash[32];
    u32 crc;
};
extern const u32 gHelixGenesisSaveLayout[4];
extern const u32 gHelixGenesisDescriptor[9];
extern const u32 gHelixGenesisPersonalities[4];
extern const u8 gHelixGenesisIds[4][32];
extern const u8 gHelixGenesisPackageHash[32];
extern const u8 gHelixGenesisProfileHashes[4][32];
extern const struct AuroraCombatProfile gHelixGenesisProfiles[4];
extern u16 gHelixGenesisResolvedBattlers[4];
bool32 HelixGenesisCanContinue(void);
void HelixGenesisNewGame(void);
u16 HelixGenesisSoul(void);
u16 HelixGenesisStage(void);
u8 HelixGenesisBaseStat(const struct Pokemon *mon, u32 stat, u8 fallback);
void HelixGenesisApplyBattleTypes(const struct Pokemon *mon, struct BattlePokemon *battle);
void GetHelixGenesisState(void);
void SetHelixGenesisSoul(void);
void SetHelixGenesisDnaTutorial(void);
void SelectHelixGenesisRecipe(void);
void PrepareHelixGenesis(void);
void IncubateHelixGenesis(void);
void AdmitHelixGenesis(void);
void BufferHelixGenesis(void);
void MarkHelixGenesisWelcome(void);
void PrepareHelixRival(void);
void HelixCaptureRivalOutcome(void);
void FinishHelixRival(void);
bool32 HelixCreateTrainerParty(struct Pokemon *party, u16 trainer);
#endif
