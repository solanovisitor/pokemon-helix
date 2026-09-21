#include "global.h"
#include "pokemon_birth.h"
#include <stddef.h>
#include "aurora_combat.h"
#include "aurora_adventure.h"
#include "aurora_individual.h"
#include "battle.h"
#include "event_data.h"
#include "pokemon.h"
#include "pokemon_storage_system.h"
#include "constants/ai_bridge.h"
#include "constants/moves.h"
#include "constants/pokemon.h"
#include "constants/species.h"

#if AURORA_COMBAT_ENABLED
STATIC_ASSERT(sizeof(struct AuroraCombatProfile) == 16, AuroraCombatProfileSize);
STATIC_ASSERT(sizeof(struct AuroraCombatRecord) == 32, AuroraCombatRecordSize);
STATIC_ASSERT(offsetof(struct AuroraCombatRecord, crc) == 28, AuroraCombatRecordCrc);
// Audit both Emerald and FRLG aliases: 406E is cleared by shared overworld
// resets; 4073 belongs to the shared trainer fan club. Never allocate either.
// These vars never touch legacy 104 bytes or the 40-byte binding.
#define COMBAT_VAR_IDS 0x406C, 0x406D, 0x40FD, 0x4070, 0x40FE, 0x4075, 0x4076, 0x4077, 0x4078, 0x4079, 0x407A, 0x407C, 0x407D, 0x407E, 0x407F, 0x4080
static const u16 sCombatVars[16] = {COMBAT_VAR_IDS};
const u32 gAuroraCombatSaveLayout[20] = {offsetof(struct SaveBlock1, vars), 32, 16, AURORA_COMBAT_MAGIC, COMBAT_VAR_IDS};
const u32 gAuroraCombatDescriptor[12] = {
    1, AURORA_COMBAT_VERSION, 3, sizeof(struct AuroraCombatProfile),
    SPECIES_AURORA_FAMILY_ONE, AURORA_ADVENTURE_FIRST_PERSONALITY,
    SPECIES_AURORA_FAMILY_TWO, AURORA_ADVENTURE_SECOND_PERSONALITY,
    SPECIES_AURORA_FAMILY_THREE, AURORA_ADVENTURE_THIRD_PERSONALITY,
    AURORA_COMBAT_PROFILE_VERSION, AURORA_COMBAT_BREEDING_XP,
};
const u8 gAuroraCombatIds[3][32] = {AURORA_ADVENTURE_FIRST_ID_BYTES, AURORA_ADVENTURE_SECOND_ID_BYTES, AURORA_ADVENTURE_THIRD_ID_BYTES};
const u8 gAuroraCombatProfileHashes[3][32] = {AURORA_COMBAT_PROFILE_HASH_0_BYTES, AURORA_COMBAT_PROFILE_HASH_1_BYTES, AURORA_COMBAT_PROFILE_HASH_2_BYTES};
const u8 gAuroraCombatEventIds[4][32] = {AURORA_COMBAT_ENCOUNTER_EVENT_BYTES, AURORA_COMBAT_BIRTH_EVENT_BYTES, AURORA_COMBAT_REWARD_0_BYTES, AURORA_COMBAT_REWARD_2_BYTES};
const struct AuroraCombatProfile gAuroraCombatProfiles[3] = {AURORA_COMBAT_PROFILE_0, AURORA_COMBAT_PROFILE_1, AURORA_COMBAT_PROFILE_2};
static const u8 sPredecessorPackage[32] = AURORA_COMBAT_PREDECESSOR_PACKAGE_BYTES;
static const u8 sNames[3][POKEMON_NAME_LENGTH + 1] = {_(AURORA_ADVENTURE_FIRST_NAME), _(AURORA_ADVENTURE_SECOND_NAME), _(AURORA_ADVENTURE_THIRD_NAME)};
EWRAM_DATA u16 gAuroraCombatLastResult = 0;
EWRAM_DATA u16 gAuroraCombatResolvedBattlers[4] = {0};
static EWRAM_DATA bool8 sStagingProfile = FALSE;
static EWRAM_DATA bool8 sEncounterArmed = FALSE;

static void Result(u16 result)
{
    gAuroraCombatLastResult = gSpecialVar_Result = result;
}

// Zero means a pre-v2 save. Nonzero unrecognized data is never cleared.
static u32 ReadCombat(struct AuroraCombatRecord *record)
{
    u32 i;
    bool32 empty = TRUE;
    u8 *bytes = (u8 *)record;
    for (i = 0; i < 16; i++)
    {
        u16 word = VarGet(sCombatVars[i]);
        bytes[i * 2] = word;
        bytes[i * 2 + 1] = word >> 8;
        if (word) empty = FALSE;
    }
    if (empty) return 0;
    if (record->magic != AURORA_COMBAT_MAGIC || record->version != AURORA_COMBAT_VERSION
        || record->profileVersion != AURORA_COMBAT_PROFILE_VERSION
        || record->flags & ~63 || !(record->flags & AURORA_COMBAT_PARENT)
        || ((record->flags & AURORA_COMBAT_REWARDED) && !(record->flags & AURORA_COMBAT_BORN))
        || record->crc != AuroraIndividualCrc32(bytes, 28))
        return 2;
    return 1;
}

static void WriteCombat(struct AuroraCombatRecord *record)
{
    u32 i;
    const u8 *bytes = (const u8 *)record;
    record->crc = AuroraIndividualCrc32(bytes, 28);
    for (i = 0; i < 16; i++)
        VarSet(sCombatVars[i], bytes[i * 2] | (bytes[i * 2 + 1] << 8));
}

bool32 AuroraCombatAcceptPredecessor(const u8 *hash)
{
    struct AuroraCombatRecord record;
    return ReadCombat(&record) == 0 && memcmp(hash, sPredecessorPackage, 32) == 0;
}

bool32 AuroraCombatCanContinue(void)
{
    struct AuroraCombatRecord record;
    return ReadCombat(&record) != 2;
}

// Full individual ID is selected only after every immutable native field agrees.
// Player OT is installed before wild creation and remains identical on capture.
static s32 ResolveIdentity(const struct BoxPokemon *mon)
{
    struct BoxPokemon copy = *mon;
    u16 species = GetBoxMonData(&copy, MON_DATA_SPECIES);
    u32 i;
    for (i = 0; i < 3; i++)
        if (species == gAuroraCombatDescriptor[4 + 2 * i] || mon->personality == gAuroraCombatDescriptor[5 + 2 * i])
        {
            if (species != gAuroraCombatDescriptor[4 + 2 * i] || mon->personality != gAuroraCombatDescriptor[5 + 2 * i]
                || mon->otId != READ_OTID_FROM_SAVE || GetBoxMonData(&copy, MON_DATA_IS_EGG)
                || GetBoxMonData(&copy, MON_DATA_SANITY_IS_BAD_EGG))
                return -2;
            return i;
        }
    return -1;
}

static s32 ActiveIdentity(const struct Pokemon *mon)
{
    struct AuroraCombatRecord record;
    if (!sStagingProfile && ReadCombat(&record) != 1) return -1;
    return ResolveIdentity(&mon->box);
}

u8 AuroraCombatBaseStat(const struct Pokemon *mon, u32 stat, u8 fallback)
{
    s32 identity = ActiveIdentity(mon);
    return identity >= 0 && stat < 6 ? gAuroraCombatProfiles[identity].baseStats[stat] : fallback;
}

void AuroraCombatApplyBattleTypes(const struct Pokemon *mon, struct BattlePokemon *battle)
{
    s32 identity = ActiveIdentity(mon);
    u32 battler;
    for (battler = 0; battler < 4; battler++)
        if (battle == &gBattleMons[battler]) gAuroraCombatResolvedBattlers[battler] = identity >= 0 ? identity + 1 : 0;
    if (identity >= 0)
    {
        battle->types[0] = gAuroraCombatProfiles[identity].types[0];
        battle->types[1] = gAuroraCombatProfiles[identity].types[1];
    }
}

static bool32 Scan(u16 locations[3], u16 partySlots[3])
{
    u32 area, box, slot;
    memset(locations, 0, 3 * sizeof(u16));
    for (area = 0; area < 2; area++)
        for (box = 0; box < (area ? TOTAL_BOXES_COUNT : 1); box++)
            for (slot = 0; slot < (area ? IN_BOX_COUNT : PARTY_SIZE); slot++)
            {
                const struct BoxPokemon *mon = area ? GetBoxedMonPtr(box, slot) : &gParties[B_TRAINER_PLAYER][slot].box;
                s32 id = ResolveIdentity(mon);
                if (id == -2 || (id >= 0 && locations[id])) return FALSE;
                if (id >= 0)
                {
                    locations[id] = area ? 2 : 1;
                    if (!area) partySlots[id] = slot;
                }
            }
    return TRUE;
}

static s32 Vacancy(void)
{
    u32 i;
    for (i = 0; i < PARTY_SIZE; i++)
    {
        struct BoxPokemon copy = gParties[B_TRAINER_PLAYER][i].box;
        if (GetBoxMonData(&copy, MON_DATA_SPECIES) == SPECIES_NONE && !GetBoxMonData(&copy, MON_DATA_SANITY_IS_BAD_EGG)) return i;
    }
    return -1;
}

static void CreateIndividual(struct Pokemon *mon, u32 id)
{
    u32 move;
    sStagingProfile = TRUE;
    CreateMonWithIVs(mon, gAuroraCombatDescriptor[4 + id * 2], 5,
        gAuroraCombatDescriptor[5 + id * 2], OTID_STRUCT_PRESET(READ_OTID_FROM_SAVE), 15);
    SetMonData(mon, MON_DATA_NICKNAME, sNames[id]);
    for (move = 0; move < 4; move++) SetMonMoveSlot(mon, gAuroraCombatProfiles[id].moves[move], move);
    CalculateMonStats(mon);
    sStagingProfile = FALSE;
}

// Explicit append-only migration: old issue bits and all XP/levels/moves survive.
// A historical child is already born; migration cannot pay its parents again.
static bool32 Migrate(void)
{
    struct AuroraCombatRecord record;
    u16 locations[3], slots[3];
    u32 slot;
    if (ReadCombat(&record) != 0 || !AuroraAdventureIsPredecessor() || !Scan(locations, slots) || locations[2]) return FALSE;
    memset(&record, 0, sizeof(record));
    record.magic = AURORA_COMBAT_MAGIC;
    record.version = AURORA_COMBAT_VERSION;
    record.profileVersion = AURORA_COMBAT_PROFILE_VERSION;
    record.flags = AURORA_COMBAT_PARENT | AURORA_COMBAT_BORN | AURORA_COMBAT_REWARDED | AURORA_COMBAT_MIGRATED;
    WriteCombat(&record);
    AuroraAdventureWriteCurrentBinding();
    for (slot = 0; slot < PARTY_SIZE; slot++)
        if (ResolveIdentity(&gParties[B_TRAINER_PLAYER][slot].box) >= 0) CalculateMonStats(&gParties[B_TRAINER_PLAYER][slot]);
    // PC stats are transient and recomputed by ordinary withdrawal. No boxed XP,
    // native data, legacy records, known moves or held items need replacement.
    return TRUE;
}

void GetAuroraCombatState(void)
{
    struct AuroraCombatRecord record;
    u32 state = ReadCombat(&record);
    if (state == 0 && AuroraAdventureIsPredecessor()) { Result(16); return; }
    Result(state == 2 ? 255 : state == 0 ? 0 : record.flags);
}

void AdoptAuroraCombatParent(void)
{
    struct AuroraCombatRecord record;
    struct Pokemon staged;
    u16 locations[3], slots[3];
    s32 vacancy;
    if (Migrate()) { Result(1); return; }
    if (ReadCombat(&record) == 1) { Result(1); return; }
    GetAuroraAdventureState();
    if (gSpecialVar_Result != AURORA_ADVENTURE_UNBOUND || ReadCombat(&record) != 0
        || VarGet(VAR_SIGNAL_QUEST_STATE) != SIGNAL_QUEST_REPORTED
        || AuroraIndividualReadState(gSaveBlock2Ptr->pokedex.filler, 104) != AURORA_INDIVIDUAL_PRESENT
        || !Scan(locations, slots) || locations[0] || locations[1] || locations[2]) { Result(4); return; }
    vacancy = Vacancy();
    if (vacancy < 0) { Result(7); return; }
    CreateIndividual(&staged, 0);
    memset(&record, 0, sizeof(record));
    record.magic = AURORA_COMBAT_MAGIC;
    record.version = AURORA_COMBAT_VERSION;
    record.profileVersion = AURORA_COMBAT_PROFILE_VERSION;
    record.flags = AURORA_COMBAT_PARENT;
    gParties[B_TRAINER_PLAYER][vacancy] = staged;
    AuroraAdventureWriteCurrentBinding();
    WriteCombat(&record);
    CalculatePlayerPartyCount();
    FlagSet(FLAG_SYS_POKEMON_GET);
    Result(1);
}

void PrepareAuroraCombatEncounter(void)
{
    struct AuroraCombatRecord record;
    u16 locations[3], slots[3];
    sEncounterArmed = FALSE;
    if (ReadCombat(&record) != 1 || !Scan(locations, slots) || locations[2]
        || (record.flags & AURORA_COMBAT_CAPTURED)) { Result(0); return; }
    record.flags |= AURORA_COMBAT_ENCOUNTER;
    if (record.attempts < 65535) record.attempts++;
    WriteCombat(&record);
    CreateIndividual(&gParties[B_TRAINER_OPPONENT_A][0], 2);
    sEncounterArmed = TRUE;
    Result(1);
}

void FinishAuroraCombatEncounter(void)
{
    struct AuroraCombatRecord record;
    u16 locations[3], slots[3];
    bool32 armed = sEncounterArmed;
    sEncounterArmed = FALSE;
    if (!armed || ReadCombat(&record) != 1 || !Scan(locations, slots)) { Result(0); return; }
    record.lastOutcome = gBattleOutcome;
    if (gBattleOutcome == B_OUTCOME_CAUGHT && locations[2]) record.flags |= AURORA_COMBAT_CAPTURED;
    WriteCombat(&record);
    Result((record.flags & AURORA_COMBAT_CAPTURED) ? 1 : 0);
}

void CompleteAuroraCombatBirth(void)
{
    struct AuroraCombatRecord record;
    struct Pokemon parents[2], child;
    u16 locations[3], slots[3];
    u32 i;
    s32 vacancy;
    if (ReadCombat(&record) != 1) { Result(0); return; }
    if (record.flags & AURORA_COMBAT_BORN) { Result(2); return; }
    if (!(record.flags & AURORA_COMBAT_CAPTURED) || !Scan(locations, slots)
        || locations[0] != 1 || locations[2] != 1 || locations[1]) { Result(3); return; }
    vacancy = Vacancy();
    if (vacancy < 0) { Result(7); return; }
    CreateIndividual(&child, 1);
    RecordMonBirthDate(&child);
    parents[0] = gParties[B_TRAINER_PLAYER][slots[0]];
    parents[1] = gParties[B_TRAINER_PLAYER][slots[2]];
    for (i = 0; i < 2; i++)
    {
        u32 xp = GetMonData(&parents[i], MON_DATA_EXP);
        record.xpBefore[i] = xp;
        xp = xp >= 1000000 - AURORA_COMBAT_BREEDING_XP ? 1000000 : xp + AURORA_COMBAT_BREEDING_XP;
        record.xpAfter[i] = xp;
        SetMonData(&parents[i], MON_DATA_EXP, &xp);
        CalculateMonStats(&parents[i]);
    }
    record.flags |= AURORA_COMBAT_BORN | AURORA_COMBAT_REWARDED;
    // All prerequisites validated; commit child, both parent progress records and
    // event consumption without yielding. Ordinary save persists one transaction.
    gParties[B_TRAINER_PLAYER][slots[0]] = parents[0];
    gParties[B_TRAINER_PLAYER][slots[2]] = parents[1];
    gParties[B_TRAINER_PLAYER][vacancy] = child;
    WriteCombat(&record);
    CalculatePlayerPartyCount();
    Result(1);
}
#else
u8 AuroraCombatBaseStat(const struct Pokemon *mon, u32 stat, u8 fallback) { return fallback; }
void AuroraCombatApplyBattleTypes(const struct Pokemon *mon, struct BattlePokemon *battle) {}
void AdoptAuroraCombatParent(void) { gSpecialVar_Result = 0; }
void GetAuroraCombatState(void) { gSpecialVar_Result = 0; }
void PrepareAuroraCombatEncounter(void) { gSpecialVar_Result = 0; }
void FinishAuroraCombatEncounter(void) { gSpecialVar_Result = 0; }
void CompleteAuroraCombatBirth(void) { gSpecialVar_Result = 0; }
#endif
