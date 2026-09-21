#include "global.h"
#include "constants/helix_public_fixture.h"
#include "pokemon_birth.h"
#include <stddef.h>
#include "helix_genesis.h"
#include "aurora_combat.h"
#include "aurora_individual.h"
#include "battle.h"
#include "event_data.h"
#include "pokemon.h"
#include "pokemon_storage_system.h"
#include "string_util.h"
#include "overworld.h"
#include "constants/species.h"
#include "constants/moves.h"
#include "constants/pokemon.h"
#include "constants/heal_locations.h"
#include "constants/opponents.h"

#define HELIX_MAGIC 0x31475848
#define HELIX_VERSION 1
#define HELIX_RIVAL_OT HELIX_PUBLIC_RIVAL_OT
#define HELIX_CROSS_MAGIC 0xC048
#define HELIX_CROSS_VERSION 1
#define HELIX_CROSS_INITIALIZED 1
#define HELIX_CROSS_BORN 2
#define HELIX_CROSS_REWARDED 4
#define HELIX_CROSS_MIGRATED 8
// CORAL is retained for a later research journey. Current gameplay must not
// admit a second companion immediately after the opening. Only the host-C
// transaction harness may exercise the future admission branch explicitly.
#if defined(HELIX_CROSS_HOST_TEST) && defined(HELIX_CROSS_TEST_ENABLE_UNRELEASED)
#define HELIX_CROSS_ADMISSION_RELEASED 1
#else
#define HELIX_CROSS_ADMISSION_RELEASED 0
#endif
const u32 gHelixCrossAdmissionReleased = HELIX_CROSS_ADMISSION_RELEASED;
#ifndef HELIX_GENESIS_HAS_PREDECESSOR
#define HELIX_GENESIS_HAS_PREDECESSOR 0
#define HELIX_GENESIS_PREDECESSOR_BYTES {0}
#define HELIX_CROSS_EVENT_IDS {{0},{0},{0}}
#define HELIX_CROSS_BREEDING_XP 125
#define HELIX_CROSS_RIVAL_INITIAL_XP 125
#endif
// Emerald unused scene vars; no shared C/reset consumers. FRLG map scripts
// using aliases are not reachable in this Emerald-only compiled laboratory.
// Preserve Aurora's 104 identity bytes, 40-byte binding and 32-byte receipt.
#define HELIX_CROSS_VAR_IDS 0x4052, 0x4055, 0x4056, 0x4059, 0x405B, 0x405C, 0x405F, 0x4061, 0x4062, 0x4081
STATIC_ASSERT(sizeof(struct HelixCrossRecord) == 20, HelixCrossSize);
STATIC_ASSERT(offsetof(struct HelixCrossRecord, crc) == 16, HelixCrossCrc);
const u32 gHelixCrossSaveLayout[14] = {offsetof(struct SaveBlock1, vars), 20, 10, 16, HELIX_CROSS_VAR_IDS};
STATIC_ASSERT(sizeof(struct HelixGenesisRecord) == 52, HelixGenesisRecordSize);
STATIC_ASSERT(offsetof(struct HelixGenesisRecord, crc) == 48, HelixGenesisCrcOffset);
STATIC_ASSERT(sizeof(gSaveBlock1Ptr->filler1) == 52, HelixGenesisPaddingSize);
// This existing previously-unused dex padding has no other source consumers.
// Never grow either save block or overwrite Aurora's vars/pokedex extension.
const u32 gHelixGenesisSaveLayout[4] = {offsetof(struct SaveBlock1, filler1), 52, 48, HELIX_VERSION};
EWRAM_DATA u16 gHelixGenesisResolvedBattlers[4] = {0};

static void ReadRecord(struct HelixGenesisRecord *record)
{
    memcpy(record, gSaveBlock1Ptr->filler1, sizeof(*record));
}

#if HELIX_GENESIS_ENABLED
const u8 gHelixGenesisPackageHash[32] = HELIX_GENESIS_PACKAGE_BYTES;
const u8 gHelixGenesisIds[4][32] = HELIX_GENESIS_IDS;
const u8 gHelixGenesisProfileHashes[4][32] = HELIX_GENESIS_PROFILE_HASHES;
const struct AuroraCombatProfile gHelixGenesisProfiles[4] = HELIX_GENESIS_PROFILES;
const u32 gHelixGenesisPersonalities[4] = HELIX_GENESIS_PERSONALITIES;
static const u16 sSpecies[4] = {SPECIES_HELIX_FOUNDER_ONE, SPECIES_HELIX_FOUNDER_TWO, SPECIES_HELIX_RIVAL, SPECIES_HELIX_CHILD};
static const u8 sNames[4][POKEMON_NAME_LENGTH + 1] = HELIX_GENESIS_NAMES;
static const u8 sRivalName[PLAYER_NAME_LENGTH + 1] = _("NOA");
const u32 gHelixGenesisDescriptor[9] = {1, HELIX_VERSION, HELIX_GENESIS_RESIDENT_COUNT,
    SPECIES_HELIX_FOUNDER_ONE, SPECIES_HELIX_FOUNDER_TWO, SPECIES_HELIX_RIVAL,
    HELIX_RIVAL_OT, sizeof(struct AuroraCombatProfile), HELIX_MAGIC};
static EWRAM_DATA bool8 sStaging = FALSE;
static EWRAM_DATA bool8 sRivalArmed = FALSE;
static EWRAM_DATA bool8 sRivalStarted = FALSE;
static EWRAM_DATA u8 sRivalPendingOutcome = 0;

const u8 gHelixGenesisPredecessorHash[32] = HELIX_GENESIS_PREDECESSOR_BYTES;
const u8 gHelixCrossEventIds[3][32] = HELIX_CROSS_EVENT_IDS;
const u32 gHelixCrossDescriptor[8] = {HELIX_GENESIS_RESIDENT_COUNT > 3, HELIX_CROSS_VERSION,
    HELIX_CROSS_MAGIC, SPECIES_HELIX_CHILD, HELIX_CROSS_BREEDING_XP,
    HELIX_CROSS_RIVAL_INITIAL_XP, 20, 16};
static const u16 sCrossVars[10] = {HELIX_CROSS_VAR_IDS};

static u32 RewardExperience(u32 xp)
{
    return xp > 1000000 - HELIX_CROSS_BREEDING_XP ? 1000000 : xp + HELIX_CROSS_BREEDING_XP;
}

// 0 absent, 1 valid, 2 occupied and incompatible. Reading never writes.
static u32 ReadCross(struct HelixCrossRecord *r)
{
    u32 i;
    bool32 empty = TRUE;
    u8 *bytes = (u8 *)r;
    for (i = 0; i < 10; i++)
    {
        u16 value = VarGet(sCrossVars[i]);
        bytes[2 * i] = value;
        bytes[2 * i + 1] = value >> 8;
        if (value) empty = FALSE;
    }
    if (empty) return 0;
    if (r->magic != HELIX_CROSS_MAGIC || r->version != HELIX_CROSS_VERSION
        || (r->flags != HELIX_CROSS_INITIALIZED
            && r->flags != (HELIX_CROSS_INITIALIZED | HELIX_CROSS_BORN | HELIX_CROSS_REWARDED)
            && r->flags != (HELIX_CROSS_INITIALIZED | HELIX_CROSS_BORN | HELIX_CROSS_REWARDED | HELIX_CROSS_MIGRATED))
        || r->crc != AuroraIndividualCrc32(bytes, 16)) return 2;
    if (r->flags & HELIX_CROSS_BORN)
    {
        if (r->nautilXpBefore > 1000000 || r->revaXpBefore != HELIX_CROSS_RIVAL_INITIAL_XP
            || r->revaXp != RewardExperience(r->revaXpBefore)) return 2;
    }
    else if (r->nautilXpBefore || r->revaXpBefore || r->revaXp != HELIX_CROSS_RIVAL_INITIAL_XP) return 2;
    return 1;
}
static void InitializeCross(struct HelixCrossRecord *r)
{
    memset(r, 0, sizeof(*r));
    r->magic = HELIX_CROSS_MAGIC;
    r->version = HELIX_CROSS_VERSION;
    r->flags = HELIX_CROSS_INITIALIZED;
    r->revaXp = HELIX_CROSS_RIVAL_INITIAL_XP;
}
static void WriteCross(struct HelixCrossRecord *r)
{
    u32 i;
    const u8 *bytes = (const u8 *)r;
    r->crc = AuroraIndividualCrc32(bytes, 16);
    for (i = 0; i < 10; i++) VarSet(sCrossVars[i], bytes[2 * i] | (bytes[2 * i + 1] << 8));
}
static bool32 Predecessor(const struct HelixGenesisRecord *r)
{
    return HELIX_GENESIS_HAS_PREDECESSOR && memcmp(r->packageHash, gHelixGenesisPredecessorHash, 32) == 0;
}
static bool32 Valid(const struct HelixGenesisRecord *r)
{
    return r->magic == HELIX_MAGIC && r->version == HELIX_VERSION
        && r->stage >= 1 && r->stage <= 6 && r->soul <= 3 && r->dnaTutorial <= 1
        && r->recipe <= 2 && r->issued <= 1 && r->duelWins <= 1
        && (r->stage < 2 || r->soul != 0)
        && (r->stage < 3 || (r->recipe != 0 && r->dnaTutorial == (r->recipe == 2)))
        && ((r->stage == 6) == (r->issued == 1))
        && (memcmp(r->packageHash, gHelixGenesisPackageHash, 32) == 0 || Predecessor(r))
        && r->crc == AuroraIndividualCrc32((const u8 *)r, 48);
}
static bool32 Current(struct HelixGenesisRecord *r)
{
    struct HelixCrossRecord cross;
    u32 state;
    ReadRecord(r);
    if (!Valid(r)) return FALSE;
    if (HELIX_GENESIS_RESIDENT_COUNT < 4) return TRUE;
    state = ReadCross(&cross);
    if (state == 2 || (Predecessor(r) && state != 0)) return FALSE;
    return state != 1 || !(cross.flags & HELIX_CROSS_BORN) || (r->issued && r->recipe == 1);
}
static void WriteRecord(struct HelixGenesisRecord *r)
{
    r->crc = AuroraIndividualCrc32((const u8 *)r, 48);
    memcpy(gSaveBlock1Ptr->filler1, r, sizeof(*r));
}
static void Result(u16 result) { gSpecialVar_Result = result; }

bool32 HelixGenesisCanContinue(void)
{
    struct HelixGenesisRecord r;
    ReadRecord(&r);
    // An empty extension is a legacy save. Unknown nonzero bytes fail closed.
    // No record is erased to repair a different or damaged package.
    {
        u32 i;
        const u8 *bytes = (const u8 *)&r;
        for (i = 0; i < sizeof(r); i++) if (bytes[i]) return Current(&r);
    }
    if (HELIX_GENESIS_RESIDENT_COUNT > 3) { struct HelixCrossRecord cross; return ReadCross(&cross) == 0; }
    return TRUE;
}

void HelixGenesisNewGame(void)
{
    struct HelixGenesisRecord r = {0};
    r.magic = HELIX_MAGIC;
    r.version = HELIX_VERSION;
    r.stage = 1;
    memcpy(r.packageHash, gHelixGenesisPackageHash, 32);
    WriteRecord(&r);
    if (HELIX_GENESIS_RESIDENT_COUNT > 3) { struct HelixCrossRecord cross; InitializeCross(&cross); WriteCross(&cross); }
    // Replace only the new-game tutorial. Continue never executes this function.
    // No starter is issued and no Ivo/Lumifin record is fabricated.
    VarSet(VAR_LITTLEROOT_INTRO_STATE, 7);
    VarSet(VAR_LITTLEROOT_TOWN_STATE, 4);
    VarSet(VAR_LITTLEROOT_RIVAL_STATE, 4);
    VarSet(VAR_LITTLEROOT_HOUSES_STATE_MAY, 2);
    VarSet(VAR_LITTLEROOT_HOUSES_STATE_BRENDAN, 2);
    VarSet(VAR_BIRCH_LAB_STATE, 5);
    VarSet(VAR_ROUTE101_STATE, 3);
    VarSet(VAR_OLDALE_RIVAL_STATE, 2);
    FlagSet(FLAG_RESCUED_BIRCH);
    FlagSet(FLAG_ADVENTURE_STARTED);
    FlagSet(FLAG_HIDE_ROUTE_101_BIRCH_STARTERS_BAG);
    FlagSet(FLAG_HIDE_ROUTE_101_BIRCH);
    FlagSet(FLAG_HIDE_ROUTE_101_ZIGZAGOON);
    FlagSet(FLAG_HIDE_ROUTE_101_BIRCH_ZIGZAGOON_BATTLE);
    FlagSet(FLAG_HIDE_ROUTE_103_RIVAL);
    FlagSet(FLAG_HIDE_OLDALE_TOWN_RIVAL);
    FlagSet(FLAG_HIDE_LITTLEROOT_TOWN_BRENDANS_HOUSE_TRUCK);
    FlagSet(FLAG_HIDE_LITTLEROOT_TOWN_MAYS_HOUSE_TRUCK);
    FlagClear(FLAG_HIDE_MAP_NAME_POPUP);
    SetLastHealLocationWarp(HEAL_LOCATION_OLDALE_TOWN);
}

u16 HelixGenesisSoul(void) { struct HelixGenesisRecord r; return Current(&r) ? r.soul : 0; }
u16 HelixGenesisStage(void) { struct HelixGenesisRecord r; return Current(&r) ? r.stage : 0; }
void GetHelixGenesisState(void)
{
    struct HelixGenesisRecord r;
    if (!Current(&r)) { Result(0); gSpecialVar_0x8005 = 0; return; }
    gSpecialVar_0x8005 = r.soul;
    gSpecialVar_0x8006 = r.recipe;
    gSpecialVar_0x8007 = r.duelWins;
    gSpecialVar_0x8008 = r.dnaTutorial;
    VarSet(VAR_TEMP_0, r.stage == 1 && !(r.memories & 1) ? 1 : 0);
    Result(r.stage);
}
void MarkHelixGenesisWelcome(void)
{
    struct HelixGenesisRecord r;
    if (Current(&r)) { r.memories |= 1; WriteRecord(&r); }
}
void SetHelixGenesisSoul(void)
{
    struct HelixGenesisRecord r;
    if (!Current(&r) || gSpecialVar_0x8004 < 1 || gSpecialVar_0x8004 > 3) { Result(0); return; }
    r.soul = gSpecialVar_0x8004;
    if (r.stage == 1) r.stage = 2;
    r.memories |= 2;
    WriteRecord(&r);
    Result(1);
}
void SetHelixGenesisDnaTutorial(void)
{
    struct HelixGenesisRecord r;
    if (!Current(&r) || gSpecialVar_0x8004 > 1) { Result(0); return; }
    // Viewing the tutorial later cannot rewrite an accepted contribution.
    if (r.stage >= 3) { Result(1); return; }
    r.dnaTutorial = gSpecialVar_0x8004;
    WriteRecord(&r);
    Result(1);
}
void SelectHelixGenesisRecipe(void)
{
    struct HelixGenesisRecord r;
    if (!Current(&r) || r.stage < 2 || r.stage > 3 || gSpecialVar_0x8004 < 1 || gSpecialVar_0x8004 > 2) { Result(0); return; }
    r.recipe = gSpecialVar_0x8004;
    r.dnaTutorial = r.recipe == 2;
    r.stage = 3;
    r.memories |= 4;
    WriteRecord(&r);
    Result(1);
}
void PrepareHelixGenesis(void)
{
    struct HelixGenesisRecord r;
    if (!Current(&r) || r.stage != 3) { Result(0); return; }
    r.stage = 4;
    r.memories |= 8;
    WriteRecord(&r);
    Result(1);
}
void IncubateHelixGenesis(void)
{
    struct HelixGenesisRecord r;
    if (!Current(&r) || r.stage != 4) { Result(0); return; }
    r.stage = 5;
    r.memories |= 16;
    WriteRecord(&r);
    Result(1);
}

static s32 Resolve(const struct BoxPokemon *mon)
{
    struct BoxPokemon copy = *mon;
    u16 species = GetBoxMonData(&copy, MON_DATA_SPECIES);
    u32 i;
    for (i = 0; i < HELIX_GENESIS_RESIDENT_COUNT; i++)
        if (species == sSpecies[i] || mon->personality == gHelixGenesisPersonalities[i])
        {
            if (species != sSpecies[i] || mon->personality != gHelixGenesisPersonalities[i]
                || mon->otId != (i == 2 ? HELIX_RIVAL_OT : READ_OTID_FROM_SAVE)
                || GetBoxMonData(&copy, MON_DATA_IS_EGG) || GetBoxMonData(&copy, MON_DATA_SANITY_IS_BAD_EGG)) return -2;
            return i;
        }
    return -1;
}
static s32 Active(const struct Pokemon *mon)
{
    struct HelixGenesisRecord r;
    s32 id = Resolve(&mon->box);
    if (id < 0) return id;
    if (!sStaging && (!Current(&r) || (id < 2 && (!r.issued || id + 1 != r.recipe)))) return -1;
    if (!sStaging && id == 3)
    {
        struct HelixCrossRecord cross;
        if (ReadCross(&cross) != 1 || !(cross.flags & HELIX_CROSS_BORN)) return -1;
    }
    return id;
}
u16 HelixGenesisInspectResident(u16 resident, struct BoxPokemon *out)
{
    struct HelixGenesisRecord r;
    struct HelixCrossRecord cross;
    struct BoxPokemon found = {0};
    u32 area, box, slot, counts[4] = {0};
    u16 location = HELIX_INSPECT_MISSING;
    bool32 childBorn;
    memset(out, 0, sizeof(*out));
    if (!Current(&r) || resident >= HELIX_GENESIS_RESIDENT_COUNT || resident == 2)
        return HELIX_INSPECT_INVALID;
    childBorn = HELIX_GENESIS_RESIDENT_COUNT > 3 && ReadCross(&cross) == 1 && (cross.flags & HELIX_CROSS_BORN);
    for (area = 0; area < 2; area++)
        for (box = 0; box < (area ? TOTAL_BOXES_COUNT : 1); box++)
            for (slot = 0; slot < (area ? IN_BOX_COUNT : PARTY_SIZE); slot++)
            {
                const struct BoxPokemon *mon = area ? GetBoxedMonPtr(box, slot) : &gParties[B_TRAINER_PLAYER][slot].box;
                s32 id = Resolve(mon);
                if (id == -1) continue;
                if (id < 0 || id == 2 || ++counts[id] > 1
                    || (id < 2 && (!r.issued || id + 1 != r.recipe))
                    || (id == 3 && !childBorn)) return HELIX_INSPECT_INVALID;
                if (id == resident) { found = *mon; location = area ? HELIX_INSPECT_BOXED : HELIX_INSPECT_PARTY; }
            }
    if ((resident < 2 && (!r.issued || resident + 1 != r.recipe)) || (resident == 3 && !childBorn))
        return HELIX_INSPECT_PENDING;
    if (counts[resident]) *out = found;
    return location;
}
u16 HelixGenesisInspect(struct BoxPokemon *out)
{
    struct HelixGenesisRecord r;
    if (!Current(&r)) { memset(out, 0, sizeof(*out)); return HELIX_INSPECT_INVALID; }
    return HelixGenesisInspectResident(r.recipe == 2 ? 1 : 0, out);
}
u8 HelixGenesisBaseStat(const struct Pokemon *mon, u32 stat, u8 fallback)
{
    s32 id = Active(mon);
    return id >= 0 && stat < 6 ? gHelixGenesisProfiles[id].baseStats[stat] : fallback;
}
void HelixGenesisApplyBattleTypes(const struct Pokemon *mon, struct BattlePokemon *battle)
{
    s32 id = Active(mon);
    u32 i;
    for (i = 0; i < 4; i++)
        if (battle == &gBattleMons[i]) gHelixGenesisResolvedBattlers[i] = id >= 0 ? id + 1 : 0;
    if (id >= 0) { battle->types[0] = gHelixGenesisProfiles[id].types[0]; battle->types[1] = gHelixGenesisProfiles[id].types[1]; }
}
static void CreateIndividual(struct Pokemon *mon, u32 id)
{
    u32 move;
    sStaging = TRUE;
    CreateMonWithIVs(mon, sSpecies[id], 5, gHelixGenesisPersonalities[id],
        OTID_STRUCT_PRESET(id == 2 ? HELIX_RIVAL_OT : READ_OTID_FROM_SAVE), 15);
    SetMonData(mon, MON_DATA_NICKNAME, sNames[id]);
    if (id == 2)
    {
        // Match ordinary trainer creation: this introductory duel has no gimmick.
        // CreateMon defaults alone otherwise allow the AI to Dynamax or Tera.
        u32 data = BLOCK_AI_DYNAMAX;
        SetMonData(mon, MON_DATA_OT_NAME, sRivalName);
        SetMonData(mon, MON_DATA_DYNAMAX_LEVEL, &data);
        data = TYPE_MYSTERY;
        SetMonData(mon, MON_DATA_TERA_TYPE, &data);
    }
    for (move = 0; move < 4; move++) SetMonMoveSlot(mon, gHelixGenesisProfiles[id].moves[move], move);
    if (id == 2)
    {
        u32 experience = HelixGenesisRivalExperience();
        SetMonData(mon, MON_DATA_EXP, &experience);
    }
    CalculateMonStats(mon);
    sStaging = FALSE;
}
void AdmitHelixGenesis(void)
{
    struct HelixGenesisRecord r;
    struct Pokemon staged;
    u32 area, box, slot;
    s32 vacancy = -1;
    if (!Current(&r)) { Result(4); return; }
    if (r.issued) { Result(2); return; }
    if (r.stage != 5) { Result(4); return; }
    // Check every reserved identity/appearance before creating anything. Issued
    // identities remain consumed if boxed, traded, released, or otherwise absent.
    for (area = 0; area < 2; area++)
        for (box = 0; box < (area ? TOTAL_BOXES_COUNT : 1); box++)
            for (slot = 0; slot < (area ? IN_BOX_COUNT : PARTY_SIZE); slot++)
            {
                const struct BoxPokemon *mon = area ? GetBoxedMonPtr(box, slot) : &gParties[B_TRAINER_PLAYER][slot].box;
                struct BoxPokemon copy = *mon;
                if (Resolve(mon) != -1) { Result(4); return; }
                if (!area && vacancy < 0 && GetBoxMonData(&copy, MON_DATA_SPECIES) == SPECIES_NONE && !GetBoxMonData(&copy, MON_DATA_SANITY_IS_BAD_EGG)) vacancy = slot;
            }
    if (vacancy < 0) { Result(7); return; }
    CreateIndividual(&staged, r.recipe - 1);
    RecordMonBirthDate(&staged);
    r.stage = 6;
    r.issued = 1;
    r.memories |= 32;
    // This is founder reconstruction, not reproduction: no living parent and
    // no breeding XP or reward. Party and receipt commit synchronously.
    gParties[B_TRAINER_PLAYER][vacancy] = staged;
    WriteRecord(&r);
    CalculatePlayerPartyCount();
    FlagSet(FLAG_SYS_POKEMON_GET);
    FlagSet(FLAG_SYS_POKEDEX_GET);
    FlagSet(FLAG_SYS_B_DASH);
    Result(1);
}
u32 HelixGenesisRivalExperience(void)
{
    struct HelixCrossRecord cross;
    return HELIX_GENESIS_RESIDENT_COUNT > 3 && ReadCross(&cross) == 1 ? cross.revaXp : HELIX_CROSS_RIVAL_INITIAL_XP;
}
// Status: 0 invalid, 1 ready/success, 2 already born, 3 other founder,
// 4 no founder yet, 5 boxed parent, 6 needs healing, 7 full party, 8 missing,
// 9 later journey not released. Existing completed births are never revoked.
static u16 CrossReady(s32 *parentSlot, s32 *vacancy)
{
    struct HelixGenesisRecord r;
    struct HelixCrossRecord cross;
    struct BoxPokemon founder;
    u32 state, i;
    u16 location;
    if (HELIX_GENESIS_RESIDENT_COUNT < 4 || !Current(&r)) return 0;
    state = ReadCross(&cross);
    if (state == 1 && (cross.flags & HELIX_CROSS_BORN)) return 2;
    if (!HELIX_CROSS_ADMISSION_RELEASED) return 9;
    if (!r.issued) return 4;
    if (r.recipe != 1) return 3;
    location = HelixGenesisInspectResident(0, &founder);
    if (location == HELIX_INSPECT_INVALID) return 0;
    if (location == HELIX_INSPECT_BOXED) return 5;
    if (location != HELIX_INSPECT_PARTY) return 8;
    *parentSlot = *vacancy = -1;
    for (i = 0; i < PARTY_SIZE; i++)
    {
        struct Pokemon copy = gParties[B_TRAINER_PLAYER][i];
        if (Resolve(&copy.box) == 0)
        {
            if (!GetMonData(&copy, MON_DATA_HP)) return 6;
            if (GetMonData(&copy, MON_DATA_EXP) > 1000000) return 0;
            *parentSlot = i;
        }
        if (*vacancy < 0 && GetMonData(&copy, MON_DATA_SPECIES) == SPECIES_NONE
            && !GetMonData(&copy, MON_DATA_SANITY_IS_BAD_EGG)) *vacancy = i;
    }
    return *vacancy < 0 ? 7 : 1;
}
void GetHelixCrossState(void)
{
    s32 parent, vacancy;
    Result(CrossReady(&parent, &vacancy));
}
void AdmitHelixCross(void)
{
    struct HelixGenesisRecord r;
    struct HelixCrossRecord cross;
    struct Pokemon child, parent;
    s32 parentSlot, vacancy;
    u32 experience;
    u16 ready = CrossReady(&parentSlot, &vacancy);
    if (ready != 1) { Result(ready); return; }
    if (!Current(&r)) { Result(0); return; }
    if (ReadCross(&cross) == 0) InitializeCross(&cross);
    parent = gParties[B_TRAINER_PLAYER][parentSlot];
    cross.nautilXpBefore = GetMonData(&parent, MON_DATA_EXP);
    cross.revaXpBefore = cross.revaXp;
    experience = RewardExperience(cross.nautilXpBefore);
    SetMonData(&parent, MON_DATA_EXP, &experience);
    CalculateMonStats(&parent);
    cross.revaXp = RewardExperience(cross.revaXpBefore);
    CreateIndividual(&child, 3);
    RecordMonBirthDate(&child);
    cross.flags |= HELIX_CROSS_BORN | HELIX_CROSS_REWARDED;
    if (Predecessor(&r)) cross.flags |= HELIX_CROSS_MIGRATED;
    memcpy(r.packageHash, gHelixGenesisPackageHash, 32);
    // No callbacks/yields inside this transaction. Ordinary Save commits the
    // child, both rewards and receipt together. Cancellation never enters here.
    gParties[B_TRAINER_PLAYER][parentSlot] = parent;
    gParties[B_TRAINER_PLAYER][vacancy] = child;
    WriteRecord(&r);
    WriteCross(&cross);
    CalculatePlayerPartyCount();
    Result(1);
}
void BufferHelixGenesis(void)
{
    struct HelixGenesisRecord r;
    if (!Current(&r) || !r.recipe) { Result(0); return; }
    StringCopy(gStringVar1, sNames[r.recipe - 1]);
    gSpecialVar_0x8009 = sSpecies[r.recipe - 1];
    Result(1);
}
static bool32 HealthyParty(void)
{
    u32 i;
    for (i = 0; i < PARTY_SIZE; i++)
        if (GetMonData(&gParties[B_TRAINER_PLAYER][i], MON_DATA_HP) && !GetMonData(&gParties[B_TRAINER_PLAYER][i], MON_DATA_IS_EGG)) return TRUE;
    return FALSE;
}
void PrepareHelixRival(void)
{
    struct HelixGenesisRecord r;
    sRivalArmed = FALSE;
    sRivalStarted = FALSE;
    sRivalPendingOutcome = 0;
    if (!Current(&r) || !r.issued || r.duelWins || !HealthyParty()) { Result(0); return; }
    if (r.attempts < 65535) r.attempts++;
    WriteRecord(&r);
    sRivalArmed = TRUE;
    Result(1);
}
bool32 HelixCreateTrainerParty(struct Pokemon *party, u16 trainer)
{
    if (!sRivalArmed || trainer != TRAINER_HELIX_NOA) return FALSE;
    memset(party, 0, PARTY_SIZE * sizeof(*party));
    CreateIndividual(&party[0], 2);
    sRivalStarted = TRUE;
    return TRUE;
}
void HelixCaptureRivalOutcome(void)
{
    // The engine clears enemy parties before returning to the event script.
    // Authenticate the finished battle while the accepted opponent still exists.
    if (sRivalArmed && sRivalStarted && (gBattleTypeFlags & BATTLE_TYPE_TRAINER)
        && Resolve(&gParties[B_TRAINER_OPPONENT_A][0].box) == 2
        && ((gBattleOutcome >= B_OUTCOME_WON && gBattleOutcome <= B_OUTCOME_DREW)
            || gBattleOutcome == B_OUTCOME_FORFEITED))
    {
        // Run is exposed by the engine; a concession is a retryable defeat.
        sRivalPendingOutcome = gBattleOutcome == B_OUTCOME_FORFEITED ? B_OUTCOME_LOST : gBattleOutcome;
        sRivalStarted = FALSE;
    }
}
void FinishHelixRival(void)
{
    struct HelixGenesisRecord r;
    u8 outcome = sRivalArmed ? sRivalPendingOutcome : 0;
    sRivalArmed = FALSE;
    sRivalStarted = FALSE;
    sRivalPendingOutcome = 0;
    if (!outcome || !Current(&r)) { Result(0); return; }
    r.lastOutcome = outcome;
    if (outcome == B_OUTCOME_WON) r.duelWins = 1;
    WriteRecord(&r);
    Result(r.duelWins);
}
#else
const u32 gHelixGenesisDescriptor[9] = {0};
const u8 gHelixGenesisPredecessorHash[32] = {0};
const u8 gHelixCrossEventIds[3][32] = {{0}};
const u32 gHelixCrossDescriptor[8] = {0};
const u32 gHelixGenesisPersonalities[4] = {0};
const u8 gHelixGenesisPackageHash[32] = {0};
const u8 gHelixGenesisIds[4][32] = {0};
const u8 gHelixGenesisProfileHashes[4][32] = {0};
const struct AuroraCombatProfile gHelixGenesisProfiles[4] = {0};
bool32 HelixGenesisCanContinue(void) { struct HelixGenesisRecord r; u32 i; ReadRecord(&r); for (i = 0; i < sizeof(r); i++) if (((u8 *)&r)[i]) return FALSE; return TRUE; }
void HelixGenesisNewGame(void) {}
u16 HelixGenesisSoul(void) { return 0; }
u16 HelixGenesisStage(void) { return 0; }
u8 HelixGenesisBaseStat(const struct Pokemon *mon, u32 stat, u8 fallback) { return fallback; }
void HelixGenesisApplyBattleTypes(const struct Pokemon *mon, struct BattlePokemon *battle) {}
void GetHelixGenesisState(void) { gSpecialVar_Result = 0; }
void SetHelixGenesisSoul(void) {}
void SetHelixGenesisDnaTutorial(void) {}
void SelectHelixGenesisRecipe(void) {}
void PrepareHelixGenesis(void) {}
void IncubateHelixGenesis(void) {}
void AdmitHelixGenesis(void) {}
void BufferHelixGenesis(void) {}
void GetHelixCrossState(void) { gSpecialVar_Result = 0; }
void AdmitHelixCross(void) { gSpecialVar_Result = 0; }
u32 HelixGenesisRivalExperience(void) { return 0; }
u16 HelixGenesisInspectResident(u16 resident, struct BoxPokemon *out) { memset(out, 0, sizeof(*out)); return HELIX_INSPECT_INVALID; }
void MarkHelixGenesisWelcome(void) {}
void PrepareHelixRival(void) { gSpecialVar_Result = 0; }
void HelixCaptureRivalOutcome(void) {}
void FinishHelixRival(void) {}
bool32 HelixCreateTrainerParty(struct Pokemon *party, u16 trainer) { return FALSE; }
u16 HelixGenesisInspect(struct BoxPokemon *out) { memset(out, 0, sizeof(*out)); return HELIX_INSPECT_INVALID; }
#endif
