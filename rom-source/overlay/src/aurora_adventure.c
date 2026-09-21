#include "global.h"
#include <stddef.h>
#include "aurora_adventure.h"
#include "aurora_combat.h"
#include "aurora_individual.h"
#include "battle.h"
#include "event_data.h"
#include "pokemon.h"
#include "pokemon_storage_system.h"
#include "constants/moves.h"
#include "constants/species.h"
#include "constants/ai_bridge.h"

STATIC_ASSERT(sizeof(struct AuroraAdventureRecord) == 40, AuroraAdventureSaveSize);
STATIC_ASSERT(offsetof(struct AuroraAdventureRecord, crc) == 36, AuroraAdventureCrcOffset);
STATIC_ASSERT(AURORA_ADVENTURE_FIRST_PERSONALITY != AURORA_ADVENTURE_SECOND_PERSONALITY, AuroraAdventureDistinctPersonalities);
STATIC_ASSERT(AURORA_ADVENTURE_FIRST_PERSONALITY != AURORA_INDIVIDUAL_PERSONALITY && AURORA_ADVENTURE_FIRST_PERSONALITY != AURORA_CHILD_PERSONALITY, AuroraAdventureFirstLegacyIdentity);
STATIC_ASSERT(AURORA_ADVENTURE_SECOND_PERSONALITY != AURORA_INDIVIDUAL_PERSONALITY && AURORA_ADVENTURE_SECOND_PERSONALITY != AURORA_CHILD_PERSONALITY, AuroraAdventureSecondLegacyIdentity);
STATIC_ASSERT(SPECIES_AURORA_FAMILY_TWO <= 2047, AuroraAdventureNativeSpeciesBudget);

// Source audit: these previously unused vars have no upstream read/write users.
// They do not increase SaveBlock1, change sector sizes, or use temporary vars.
#define ADVENTURE_VAR_IDS 0x404E, 0x4083, 0x408B, 0x4091, 0x409B, 0x409D, 0x40A1, 0x40A8, 0x40B8, 0x40BB, 0x40DB, 0x40DC, 0x40E5, 0x4064, 0x4065, 0x4066, 0x4067, 0x4068, 0x406A, 0x406B
static const u16 sAdventureVars[AURORA_ADVENTURE_SAVE_WORDS] = { ADVENTURE_VAR_IDS };
const u32 gAuroraAdventureSaveLayout[24] = {
    offsetof(struct SaveBlock1, vars), 40, AURORA_ADVENTURE_SAVE_WORDS, AURORA_ADVENTURE_MAGIC, ADVENTURE_VAR_IDS,
};
const u32 gAuroraAdventureDescriptor[8] = {
    AURORA_ADVENTURE_ENABLED, AURORA_ADVENTURE_VERSION, AURORA_ADVENTURE_VARIANT, 2,
    SPECIES_AURORA_FAMILY_ONE, AURORA_ADVENTURE_FIRST_PERSONALITY,
    SPECIES_AURORA_FAMILY_TWO, AURORA_ADVENTURE_SECOND_PERSONALITY,
};
const u8 gAuroraAdventureIds[4][32] = {
    AURORA_ADVENTURE_ID_BYTES, AURORA_ADVENTURE_PACKAGE_BYTES,
    AURORA_ADVENTURE_FIRST_ID_BYTES, AURORA_ADVENTURE_SECOND_ID_BYTES,
};

// Native implementation and pure validators are compiled by the host harness.
EWRAM_DATA u16 gAuroraAdventureLastResult = 0;
EWRAM_DATA u16 gAuroraAdventureRecoveryMode = 0;
static EWRAM_DATA bool8 sAdventureParticipantsMatch = FALSE;
struct AdventureParticipant
{
    u32 personality;
    u32 otId;
    u16 species;
    u16 slot;
};
static EWRAM_DATA struct AdventureParticipant sAdventureParticipants[2];
static EWRAM_DATA bool8 sAdventureBattleArmed = FALSE;
static EWRAM_DATA u32 sAdventureBattleCrc = 0;
static const u8 sAdventureNames[2][POKEMON_NAME_LENGTH + 1] = {
    _(AURORA_ADVENTURE_FIRST_NAME), _(AURORA_ADVENTURE_SECOND_NAME),
};

static bool32 AdventureContentValid(void)
{
    u32 i, n;
    if (!AURORA_ADVENTURE_ENABLED || AURORA_ADVENTURE_VARIANT < 1 || AURORA_ADVENTURE_VARIANT > 2)
        return FALSE;
    for (i = 0; i < 4; i++)
    {
        bool32 nonzero = FALSE;
        for (n = 0; n < 32; n++)
            if (gAuroraAdventureIds[i][n])
                nonzero = TRUE;
        if (!nonzero)
            return FALSE;
    }
    return memcmp(gAuroraAdventureIds[2], gAuroraAdventureIds[3], 32) != 0;
}

bool32 AuroraAdventureValidateRecord(const struct AuroraAdventureRecord *record)
{
    return AdventureContentValid()
        && record->magic == AURORA_ADVENTURE_MAGIC
        && record->versionFlags == ((AURORA_ADVENTURE_VERSION << 8) | AURORA_ADVENTURE_ISSUED)
        && (memcmp(record->packageHash, gAuroraAdventureIds[1], 32) == 0
#if AURORA_COMBAT_ENABLED
            || AuroraCombatAcceptPredecessor(record->packageHash)
#endif
        )
        && record->crc == AuroraIndividualCrc32((const u8 *)record, 36);
}

static u16 ReadAdventure(struct AuroraAdventureRecord *record)
{
    u32 i;
    bool32 empty = TRUE;
    u8 *bytes = (u8 *)record;
    for (i = 0; i < AURORA_ADVENTURE_SAVE_WORDS; i++)
    {
        u16 word = VarGet(sAdventureVars[i]);
        bytes[i * 2] = word;
        bytes[i * 2 + 1] = word >> 8;
        if (word)
            empty = FALSE;
    }
    // Even a disabled build refuses saves from a package. It cannot safely
    // render that package's two native appearance indices as its own art.
    if (empty)
        return AURORA_ADVENTURE_ENABLED ? AURORA_ADVENTURE_UNBOUND : AURORA_ADVENTURE_DISABLED;
    return AuroraAdventureValidateRecord(record) ? AURORA_ADVENTURE_BOUND : AURORA_ADVENTURE_INVALID;
}

bool32 AuroraAdventureCanContinue(void)
{
    struct AuroraAdventureRecord record;
    return ReadAdventure(&record) != AURORA_ADVENTURE_INVALID
#if AURORA_COMBAT_ENABLED
        && AuroraCombatCanContinue()
#endif
        ;
}

static void AdventureResult(u16 result)
{
    gAuroraAdventureLastResult = result;
    gSpecialVar_Result = result;
}

void GetAuroraAdventureState(void)
{
    struct AuroraAdventureRecord record;
    AdventureResult(ReadAdventure(&record));
}

// Return -1 for unrelated, 0/1 for a genuine mapped identity, 2 for any
// suspicious map/personality collision. All native getters inspect copies.
static s32 AdventureIdentity(const struct BoxPokemon *mon)
{
    struct BoxPokemon copy = *mon;
    u32 i;
    u16 species = GetBoxMonData(&copy, MON_DATA_SPECIES);
    for (i = 0; i < 2; i++)
    {
        u32 expectedSpecies = gAuroraAdventureDescriptor[4 + i * 2];
        u32 personality = gAuroraAdventureDescriptor[5 + i * 2];
        if (species == expectedSpecies || mon->personality == personality)
        {
            if (species != expectedSpecies || mon->personality != personality || mon->otId != READ_OTID_FROM_SAVE
                || GetBoxMonData(&copy, MON_DATA_IS_EGG) || GetBoxMonData(&copy, MON_DATA_SANITY_IS_BAD_EGG))
                return 2;
            return i;
        }
    }
    return -1;
}

static bool32 ScanAdventure(u16 locations[2])
{
    u32 area, box, slot;
    locations[0] = locations[1] = 0;
    for (area = 0; area < 2; area++)
        for (box = 0; box < (area ? TOTAL_BOXES_COUNT : 1); box++)
            for (slot = 0; slot < (area ? IN_BOX_COUNT : PARTY_SIZE); slot++)
            {
                const struct BoxPokemon *mon = area ? GetBoxedMonPtr(box, slot) : &gParties[B_TRAINER_PLAYER][slot].box;
                s32 identity = AdventureIdentity(mon);
                if (identity == 2 || (identity >= 0 && locations[identity]))
                    return FALSE;
                if (identity >= 0)
                    locations[identity] = area ? 2 : 1;
            }
    return TRUE;
}

void AdoptAuroraAdventureFamily(void)
{
#if AURORA_COMBAT_ENABLED
    AdoptAuroraCombatParent();
#else
    struct AuroraAdventureRecord record;
    struct Pokemon staged[2];
    u16 locations[2], slots[2];
    u32 i, vacancies = 0;
    u16 state = ReadAdventure(&record);
    sAdventureBattleArmed = FALSE;
    if ((state != AURORA_ADVENTURE_BOUND && state != AURORA_ADVENTURE_UNBOUND)
        || !AdventureContentValid() || VarGet(VAR_SIGNAL_QUEST_STATE) != SIGNAL_QUEST_REPORTED
        || AuroraIndividualReadState(gSaveBlock2Ptr->pokedex.filler, 104) != AURORA_INDIVIDUAL_PRESENT
        || !ScanAdventure(locations))
    {
        AdventureResult(AURORA_INDIVIDUAL_PARTY_UNSUPPORTED);
        return;
    }
    if (state == AURORA_ADVENTURE_BOUND)
    {
        AdventureResult(locations[0] && locations[1] ? AURORA_INDIVIDUAL_PARTY : AURORA_INDIVIDUAL_MISSING);
        return;
    }
    // An unbound save containing either reserved appearance is unsupported.
    // Do not invent ownership or erase a conflicting registry to issue again.
    if (locations[0] || locations[1])
    {
        AdventureResult(AURORA_INDIVIDUAL_PARTY_UNSUPPORTED);
        return;
    }
    for (i = 0; i < PARTY_SIZE; i++)
    {
        struct BoxPokemon copy = gParties[B_TRAINER_PLAYER][i].box;
        u16 species = GetBoxMonData(&copy, MON_DATA_SPECIES);
        if (GetBoxMonData(&copy, MON_DATA_SANITY_IS_BAD_EGG))
        {
            AdventureResult(AURORA_INDIVIDUAL_PARTY_UNSUPPORTED);
            return;
        }
        if (species == SPECIES_NONE && vacancies < 2)
            slots[vacancies++] = i;
    }
    if (vacancies < 2)
    {
        AdventureResult(AURORA_INDIVIDUAL_RESULT_PARTY_FULL);
        return;
    }
    memset(&record, 0, sizeof(record));
    record.magic = AURORA_ADVENTURE_MAGIC;
    record.versionFlags = (AURORA_ADVENTURE_VERSION << 8) | AURORA_ADVENTURE_ISSUED;
    memcpy(record.packageHash, gAuroraAdventureIds[1], 32);
    record.crc = AuroraIndividualCrc32((const u8 *)&record, 36);
    for (i = 0; i < 2; i++)
    {
        CreateMonWithIVs(&staged[i], gAuroraAdventureDescriptor[4 + i * 2], 5,
            gAuroraAdventureDescriptor[5 + i * 2], OTID_STRUCT_PLAYER_ID, 15);
        SetMonData(&staged[i], MON_DATA_NICKNAME, sAdventureNames[i]);
        SetMonMoveSlot(&staged[i], MOVE_WATER_GUN, 0);
        SetMonMoveSlot(&staged[i], MOVE_TACKLE, 1);
        SetMonMoveSlot(&staged[i], MOVE_TAIL_WHIP, 2);
        SetMonMoveSlot(&staged[i], MOVE_SUPERSONIC, 3);
    }
    // No yielding/network/save calls occur during this synchronous transaction.
    // Reset before ordinary Save restores the old complete save, never half.
    for (i = 0; i < 2; i++)
        gParties[B_TRAINER_PLAYER][slots[i]] = staged[i];
    for (i = 0; i < AURORA_ADVENTURE_SAVE_WORDS; i++)
    {
        const u8 *bytes = (const u8 *)&record;
        VarSet(sAdventureVars[i], bytes[i * 2] | (bytes[i * 2 + 1] << 8));
    }
    CalculatePlayerPartyCount();
    FlagSet(FLAG_SYS_POKEMON_GET);
    AdventureResult(AURORA_INDIVIDUAL_PARTY);
#endif
}

static bool32 HealthyNative(const struct Pokemon *mon)
{
    struct BoxPokemon copy = mon->box;
    return GetBoxMonData(&copy, MON_DATA_SPECIES) != SPECIES_NONE
        && !GetBoxMonData(&copy, MON_DATA_SANITY_IS_BAD_EGG)
        && !GetBoxMonData(&copy, MON_DATA_IS_EGG) && mon->hp;
}

static void SetRecoveryMode(bool32 recovery)
{
    gAuroraAdventureRecoveryMode = recovery;
    gSpecialVar_0x8007 = recovery;
}

void GetAuroraAdventurePartnerReady(void)
{
    struct AuroraAdventureRecord record;
    u16 locations[2];
    u32 slot;
    bool32 recovery;
    SetRecoveryMode(FALSE);
    AdventureResult(FALSE);
    if (ReadAdventure(&record) != AURORA_ADVENTURE_BOUND || !ScanAdventure(locations))
        return;
    // Only a genuinely missing permanent issuance permits the field-note
    // fallback. Boxed or fainted owned companions retain their ordinary gates.
    recovery = !locations[0] || !locations[1];
    SetRecoveryMode(recovery);
    for (slot = 0; slot < PARTY_SIZE; slot++)
        if (HealthyNative(&gParties[B_TRAINER_PLAYER][slot])
            && (recovery || AdventureIdentity(&gParties[B_TRAINER_PLAYER][slot].box) >= 0))
        {
            AdventureResult(TRUE);
            return;
        }
}

void GetAuroraAdventureBattleReady(void)
{
    struct AuroraAdventureRecord record;
    u16 locations[2];
    u32 slot, usable = 0, mask = 0;
    bool32 recovery;
    sAdventureBattleArmed = FALSE;
    sAdventureParticipantsMatch = FALSE;
    SetRecoveryMode(FALSE);
    AdventureResult(FALSE);
    if (ReadAdventure(&record) != AURORA_ADVENTURE_BOUND || !ScanAdventure(locations))
        return;
    recovery = !locations[0] || !locations[1];
    SetRecoveryMode(recovery);
    for (slot = 0; slot < PARTY_SIZE && usable < 2; slot++)
    {
        struct BoxPokemon copy = gParties[B_TRAINER_PLAYER][slot].box;
        u16 species = GetBoxMonData(&copy, MON_DATA_SPECIES);
        s32 identity;
        if (GetBoxMonData(&copy, MON_DATA_SANITY_IS_BAD_EGG))
            return;
        if (species == SPECIES_NONE || GetBoxMonData(&copy, MON_DATA_IS_EGG) || !gParties[B_TRAINER_PLAYER][slot].hp)
            continue;
        identity = AdventureIdentity(&copy);
        if (!recovery && (identity < 0 || identity > 1))
            return;
        if (identity >= 0 && identity <= 1)
            mask |= 1 << identity;
        sAdventureParticipants[usable].personality = copy.personality;
        sAdventureParticipants[usable].otId = copy.otId;
        sAdventureParticipants[usable].species = species;
        sAdventureParticipants[usable].slot = slot;
        usable++;
    }
    if (usable == 2 && (recovery || mask == 3))
    {
        sAdventureBattleArmed = TRUE;
        sAdventureBattleCrc = record.crc;
        AdventureResult(TRUE);
    }
}

static bool32 MatchesParticipant(const struct Pokemon *mon, u32 index)
{
    const struct AdventureParticipant *participant = &sAdventureParticipants[index];
    struct BoxPokemon copy = mon->box;
    return copy.personality == participant->personality && copy.otId == participant->otId
        && GetBoxMonData(&copy, MON_DATA_SPECIES) == participant->species
        && !GetBoxMonData(&copy, MON_DATA_IS_EGG) && !GetBoxMonData(&copy, MON_DATA_SANITY_IS_BAD_EGG);
}

// Called by the real battle engine before its battler data is torn down. A
// species result alone cannot prove which same-species native mon participated.
void AuroraAdventureObserveBattleEnd(const struct Pokemon *first, const struct Pokemon *second)
{
    sAdventureParticipantsMatch = sAdventureBattleArmed
        && ((MatchesParticipant(first, 0) && MatchesParticipant(second, 1))
            || (MatchesParticipant(first, 1) && MatchesParticipant(second, 0)));
}

void GetAuroraAdventureBattleWon(void)
{
    struct AuroraAdventureRecord record;
    u16 locations[2];
    bool32 armed = sAdventureBattleArmed;
    bool32 recovery = gAuroraAdventureRecoveryMode;
    sAdventureBattleArmed = FALSE;
    AdventureResult(armed && sAdventureParticipantsMatch
        && ReadAdventure(&record) == AURORA_ADVENTURE_BOUND
        && record.crc == sAdventureBattleCrc && ScanAdventure(locations)
        && (recovery ? (!locations[0] || !locations[1]) : (locations[0] == 1 && locations[1] == 1))
        && MatchesParticipant(&gParties[B_TRAINER_PLAYER][sAdventureParticipants[0].slot], 0)
        && MatchesParticipant(&gParties[B_TRAINER_PLAYER][sAdventureParticipants[1].slot], 1)
        && gBattleOutcome == B_OUTCOME_WON && (gBattleTypeFlags & BATTLE_TYPE_DOUBLE)
        && ((gBattleResults.playerMon1Species == sAdventureParticipants[0].species
            && gBattleResults.playerMon2Species == sAdventureParticipants[1].species)
        || (gBattleResults.playerMon1Species == sAdventureParticipants[1].species
            && gBattleResults.playerMon2Species == sAdventureParticipants[0].species)));
    sAdventureParticipantsMatch = FALSE;
}

// Only the explicit v2 migration/adoption path calls this synchronous binding commit.
void AuroraAdventureWriteCurrentBinding(void)
{
    struct AuroraAdventureRecord record;
    u32 i;
    const u8 *bytes = (const u8 *)&record;
    memset(&record, 0, sizeof(record));
    record.magic = AURORA_ADVENTURE_MAGIC;
    record.versionFlags = (AURORA_ADVENTURE_VERSION << 8) | AURORA_ADVENTURE_ISSUED;
    memcpy(record.packageHash, gAuroraAdventureIds[1], 32);
    record.crc = AuroraIndividualCrc32(bytes, 36);
    for (i = 0; i < AURORA_ADVENTURE_SAVE_WORDS; i++)
        VarSet(sAdventureVars[i], bytes[i * 2] | (bytes[i * 2 + 1] << 8));
}

bool32 AuroraAdventureIsPredecessor(void)
{
    struct AuroraAdventureRecord record;
    return ReadAdventure(&record) == AURORA_ADVENTURE_BOUND
        && memcmp(record.packageHash, gAuroraAdventureIds[1], 32) != 0;
}
