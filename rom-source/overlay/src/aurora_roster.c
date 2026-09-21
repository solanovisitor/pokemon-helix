#include "global.h"
#include "pokemon_birth.h"
#include <stddef.h>
#include "aurora_individual.h"
#include "aurora_roster.h"
#include "event_data.h"
#include "pokemon.h"
#include "pokemon_storage_system.h"
#include "string_util.h"
#include "strings.h"
#include "constants/species.h"
#include "constants/moves.h"
#include "constants/ai_bridge.h"

STATIC_ASSERT(AURORA_CHILD_SIGNAL_BASE >= 0 && AURORA_CHILD_SIGNAL_BASE <= 15, AuroraRosterBaseSignalBound);
STATIC_ASSERT(AURORA_CHILD_SIGNAL_EDITED >= 0 && AURORA_CHILD_SIGNAL_EDITED <= 15, AuroraRosterEditedSignalBound);
STATIC_ASSERT(AURORA_LUMIFIN_SIGNAL >= 0 && AURORA_LUMIFIN_SIGNAL <= 15, AuroraRosterOriginalSignalBound);
STATIC_ASSERT(AURORA_CHILD_PERSONALITY != AURORA_INDIVIDUAL_PERSONALITY, AuroraRosterDistinctPersonality);
STATIC_ASSERT(AURORA_CHILD_SPECIES != AURORA_CHILD_EDITED_SPECIES, AuroraRosterDistinctPhenotypeSpecies);
STATIC_ASSERT(sizeof(struct AuroraRosterExtension) == 28, AuroraRosterExtensionSize);
STATIC_ASSERT(offsetof(struct AuroraRosterExtension, crc) == 24, AuroraRosterExtensionCrcOffset);
STATIC_ASSERT(sizeof(struct AuroraIndividualRecord) + sizeof(struct AuroraRosterExtension) == 104, AuroraRosterReservedSpace);

const u32 gAuroraRosterSaveLayout[8] = {
    offsetof(struct SaveBlock2, pokedex.filler), 76, 28, 104,
    AURORA_ROSTER_MAGIC, AURORA_ROSTER_VERSION, AURORA_ROSTER_MANIFEST_CRC, 1,
};
const u32 gAuroraRosterDescriptor[8] = {
    AURORA_CHILD_SPECIES, AURORA_CHILD_EDITED_SPECIES, AURORA_CHILD_PERSONALITY,
    AURORA_CHILD_SIGNAL_BASE, AURORA_CHILD_SIGNAL_EDITED,
    AURORA_ROSTER_SIGNAL_THRESHOLD, 3, 7,
};
EWRAM_DATA u16 gAuroraRosterLastResult = 0;
EWRAM_DATA u16 gAuroraRosterLastState = 0;
static const u8 sRosterChildNickname[POKEMON_NAME_LENGTH + 1] = _("RIPPLE");
static EWRAM_DATA bool8 sEditPreviewReady = FALSE;
static EWRAM_DATA u8 sEditPreviewKind = 0;
static EWRAM_DATA u8 sEditPreviewSlot = 0;
static EWRAM_DATA u32 sEditPreviewCrc = 0;

// A v1 save remains byte-for-byte unchanged on reads. Only a successful
// adoption, rest or confirmed edit writes the recognized extension.
static bool32 ReadRoster(struct AuroraRosterExtension *record)
{
    const u8 *bytes = gSaveBlock2Ptr->pokedex.filler;
    u32 i;
    bool32 empty = TRUE;
    if (AuroraIndividualReadState(bytes, 104) != AURORA_INDIVIDUAL_PRESENT)
        return FALSE;
    for (i = 76; i < 104; i++)
        if (bytes[i])
            empty = FALSE;
    memcpy(record, bytes + 76, sizeof(*record));
    if (empty)
    {
        record->magic = AURORA_ROSTER_MAGIC;
        record->version = AURORA_ROSTER_VERSION;
        record->manifestCrc = AURORA_ROSTER_MANIFEST_CRC;
        record->crc = AuroraIndividualCrc32((const u8 *)record, 24);
    }
    return AuroraRosterValidateExtension(record);
}

static void CommitRoster(struct AuroraRosterExtension *record)
{
    record->crc = AuroraIndividualCrc32((const u8 *)record, 24);
    memcpy(gSaveBlock2Ptr->pokedex.filler + 76, record, sizeof(*record));
}

static void RosterResult(u16 result)
{
    gAuroraRosterLastResult = result;
    gSpecialVar_Result = result;
}

u16 AuroraRosterLifeStage(u16 days)
{
    if (days < 3)
        return AURORA_ROSTER_HATCHLING;
    if (days < 7)
        return AURORA_ROSTER_JUVENILE;
    return AURORA_ROSTER_MATURE;
}

static bool32 IsRosterChild(struct BoxPokemon *mon, const struct AuroraRosterExtension *record)
{
    struct BoxPokemon copy;
    u16 species = record->phenotypeRevision ? AURORA_CHILD_EDITED_SPECIES : AURORA_CHILD_SPECIES;
    if (mon->personality != AURORA_CHILD_PERSONALITY || mon->otId != READ_OTID_FROM_SAVE)
        return FALSE;
    // Native getters mark checksum failures as Bad Eggs. Inspect a copy so
    // an unsupported/corrupt specimen is rejected without changing its bytes.
    copy = *mon;
    return GetBoxMonData(&copy, MON_DATA_SPECIES) == species
        && !GetBoxMonData(&copy, MON_DATA_IS_EGG)
        && !GetBoxMonData(&copy, MON_DATA_SANITY_IS_BAD_EGG);
}

static bool32 HasChildIdentity(struct BoxPokemon *mon)
{
    struct BoxPokemon copy;
    u16 species;
    if (mon->personality != AURORA_CHILD_PERSONALITY || mon->otId != READ_OTID_FROM_SAVE)
        return FALSE;
    copy = *mon;
    species = GetBoxMonData(&copy, MON_DATA_SPECIES);
    // A damaged matching identity also blocks issuance, even though the native
    // species getter reports it as an egg rather than its encrypted species.
    return GetBoxMonData(&copy, MON_DATA_SANITY_IS_BAD_EGG)
        || species == AURORA_CHILD_SPECIES || species == AURORA_CHILD_EDITED_SPECIES;
}

static u16 ChildState(const struct AuroraRosterExtension *record)
{
    u32 box, slot, found = 0;
    u16 state = record->flags & AURORA_ROSTER_CHILD_ISSUED
        ? AURORA_INDIVIDUAL_MISSING : AURORA_INDIVIDUAL_PARTY_ABSENT;
    gSpecialVar_0x8004 = 0xffff;
    for (slot = 0; slot < PARTY_SIZE; slot++)
    {
        struct BoxPokemon *mon = &gParties[B_TRAINER_PLAYER][slot].box;
        if (HasChildIdentity(mon))
        {
            if (!IsRosterChild(mon, record) || ++found > 1)
                return AURORA_INDIVIDUAL_PARTY_UNSUPPORTED;
            gSpecialVar_0x8004 = slot;
            state = AURORA_INDIVIDUAL_PARTY;
        }
    }
    for (box = 0; box < TOTAL_BOXES_COUNT; box++)
        for (slot = 0; slot < IN_BOX_COUNT; slot++)
        {
            struct BoxPokemon *mon = GetBoxedMonPtr(box, slot);
            if (HasChildIdentity(mon))
            {
                if (!IsRosterChild(mon, record) || ++found > 1)
                    return AURORA_INDIVIDUAL_PARTY_UNSUPPORTED;
                state = AURORA_INDIVIDUAL_BOXED;
            }
        }
    return state;
}

void GetAuroraRosterState(void)
{
    struct AuroraRosterExtension record;
    u16 state = AURORA_INDIVIDUAL_PARTY_UNSUPPORTED;
    if (gSpecialVar_0x8005 <= AURORA_ROSTER_CHILD && ReadRoster(&record))
    {
        if (gSpecialVar_0x8005 == AURORA_ROSTER_ORIGINAL)
        {
            GetAuroraIndividualPartyState();
            state = gSpecialVar_Result;
        }
        else
            state = ChildState(&record);
    }
    else
        gSpecialVar_0x8004 = 0xffff;
    gAuroraRosterLastState = state;
    RosterResult(state);
}

void AdoptAuroraRosterChild(void)
{
    struct AuroraRosterExtension record;
    struct Pokemon mon;
    u32 slot, candidate;
    u16 state;
    if (VarGet(VAR_SIGNAL_QUEST_STATE) != SIGNAL_QUEST_REPORTED || !ReadRoster(&record))
    {
        RosterResult(AURORA_ROSTER_RESULT_INVALID);
        return;
    }
    state = ChildState(&record);
    if (state != AURORA_INDIVIDUAL_PARTY_ABSENT)
    {
        // Recover recognized native specimens without ever duplicating them.
        // A previous issuance remains permanent even after release or trade.
        if ((state == AURORA_INDIVIDUAL_PARTY || state == AURORA_INDIVIDUAL_BOXED)
            && !(record.flags & AURORA_ROSTER_CHILD_ISSUED))
        {
            record.flags |= AURORA_ROSTER_CHILD_ISSUED;
            CommitRoster(&record);
        }
        gAuroraRosterLastState = state;
        RosterResult(state);
        return;
    }
    if (AuroraRosterLifeStage(record.originalDays) != AURORA_ROSTER_MATURE)
    {
        RosterResult(AURORA_ROSTER_RESULT_TOO_YOUNG);
        return;
    }
    slot = PARTY_SIZE;
    for (candidate = 0; candidate < PARTY_SIZE; candidate++)
    {
        struct BoxPokemon copy = gParties[B_TRAINER_PLAYER][candidate].box;
        u16 species = GetBoxMonData(&copy, MON_DATA_SPECIES);
        // CalculatePlayerPartyCount below uses live native getters. Refuse
        // before creating anything if it could modify a damaged party entry.
        if (GetBoxMonData(&copy, MON_DATA_SANITY_IS_BAD_EGG))
        {
            RosterResult(AURORA_ROSTER_RESULT_INVALID);
            return;
        }
        if (slot == PARTY_SIZE && species == SPECIES_NONE)
            slot = candidate;
    }
    if (slot == PARTY_SIZE)
    {
        RosterResult(AURORA_INDIVIDUAL_RESULT_PARTY_FULL);
        return;
    }
    CreateMonWithIVs(&mon, AURORA_CHILD_SPECIES, 5, AURORA_CHILD_PERSONALITY, OTID_STRUCT_PLAYER_ID, 15);
    SetMonData(&mon, MON_DATA_NICKNAME, sRosterChildNickname);
    SetMonMoveSlot(&mon, MOVE_WATER_GUN, 0);
    SetMonMoveSlot(&mon, MOVE_TACKLE, 1);
    SetMonMoveSlot(&mon, MOVE_TAIL_WHIP, 2);
    SetMonMoveSlot(&mon, MOVE_SUPERSONIC, 3);
    RecordMonBirthDate(&mon);
    gParties[B_TRAINER_PLAYER][slot] = mon;
    CalculatePlayerPartyCount();
    FlagSet(FLAG_SYS_POKEMON_GET);
    record.flags |= AURORA_ROSTER_CHILD_ISSUED;
    CommitRoster(&record);
    gSpecialVar_0x8004 = slot;
    gAuroraRosterLastState = AURORA_INDIVIDUAL_PARTY;
    RosterResult(AURORA_INDIVIDUAL_PARTY);
}

void GetAuroraRosterAge(void)
{
    struct AuroraRosterExtension record;
    u16 days;
    gSpecialVar_0x8007 = 0;
    gSpecialVar_0x8008 = FALSE;
    gSpecialVar_0x8009 = 0;
    gSpecialVar_0x800A = 0;
    if (gSpecialVar_0x8005 > AURORA_ROSTER_CHILD || !ReadRoster(&record)
        || (gSpecialVar_0x8005 == AURORA_ROSTER_CHILD && !(record.flags & AURORA_ROSTER_CHILD_ISSUED)))
    {
        RosterResult(AURORA_ROSTER_RESULT_INVALID);
        return;
    }
    days = gSpecialVar_0x8005 == AURORA_ROSTER_ORIGINAL ? record.originalDays : record.childDays;
    gSpecialVar_0x8007 = days;
    gSpecialVar_0x8008 = AuroraRosterLifeStage(days) == AURORA_ROSTER_MATURE;
    if (gSpecialVar_0x8005 == AURORA_ROSTER_CHILD)
    {
        gSpecialVar_0x8009 = record.phenotypeRevision;
        gSpecialVar_0x800A = record.genotypeRevision;
    }
    RosterResult(AuroraRosterLifeStage(days));
}

void RestAuroraRoster(void)
{
    struct AuroraRosterExtension record;
    if (!ReadRoster(&record))
    {
        RosterResult(AURORA_ROSTER_RESULT_INVALID);
        return;
    }
    if (record.originalDays != 0xffff)
        record.originalDays++;
    if ((record.flags & AURORA_ROSTER_CHILD_ISSUED) && record.childDays != 0xffff)
        record.childDays++;
    CommitRoster(&record);
    sEditPreviewReady = FALSE;
    RosterResult(AURORA_ROSTER_RESULT_UPDATED);
}

void CancelAuroraRosterEdit(void)
{
    sEditPreviewReady = FALSE;
    RosterResult(0);
}

void PreviewAuroraRosterEdit(void)
{
    struct AuroraRosterExtension record;
    u16 kind = gSpecialVar_0x8006;
    sEditPreviewReady = FALSE;
    if (gSpecialVar_0x8005 != AURORA_ROSTER_CHILD || !ReadRoster(&record)
        || !(record.flags & AURORA_ROSTER_CHILD_ISSUED)
        || (kind != AURORA_ROSTER_EDIT_SOMATIC && kind != AURORA_ROSTER_EDIT_GERMLINE)
        || ChildState(&record) != AURORA_INDIVIDUAL_PARTY)
    {
        RosterResult(AURORA_ROSTER_RESULT_INVALID);
        return;
    }
    if ((kind == AURORA_ROSTER_EDIT_SOMATIC && record.phenotypeRevision)
        || (kind == AURORA_ROSTER_EDIT_GERMLINE && record.genotypeRevision))
    {
        RosterResult(AURORA_ROSTER_RESULT_UNAVAILABLE);
        return;
    }
    sEditPreviewReady = TRUE;
    sEditPreviewKind = kind;
    sEditPreviewSlot = gSpecialVar_0x8004;
    sEditPreviewCrc = record.crc;
    gSpecialVar_0x8007 = AURORA_CHILD_SIGNAL_EDITED;
    gSpecialVar_0x8009 = 1;
    gSpecialVar_0x800A = kind == AURORA_ROSTER_EDIT_GERMLINE ? 1 : record.genotypeRevision;
    RosterResult(AURORA_ROSTER_RESULT_PREVIEW);
}

void CommitAuroraRosterEdit(void)
{
    struct AuroraRosterExtension record;
    u16 species = AURORA_CHILD_EDITED_SPECIES;
    bool32 ready = sEditPreviewReady;
    sEditPreviewReady = FALSE;
    if (!ready || gSpecialVar_0x8005 != AURORA_ROSTER_CHILD
        || gSpecialVar_0x8006 != sEditPreviewKind || !ReadRoster(&record)
        || record.crc != sEditPreviewCrc
        || ChildState(&record) != AURORA_INDIVIDUAL_PARTY
        || gSpecialVar_0x8004 != sEditPreviewSlot)
    {
        RosterResult(AURORA_ROSTER_RESULT_INVALID);
        return;
    }
    // Curated variants share all battle stats, growth and moves. Native setter
    // updates the encrypted species and checksum; XP, HP, moves, identity and
    // nickname remain unchanged. No recalculation grants HP or changes levels.
    SetMonData(&gParties[B_TRAINER_PLAYER][sEditPreviewSlot], MON_DATA_SPECIES, &species);
    record.phenotypeRevision = 1;
    if (sEditPreviewKind == AURORA_ROSTER_EDIT_GERMLINE)
        record.genotypeRevision = 1;
    CommitRoster(&record);
    RosterResult(AURORA_ROSTER_RESULT_EDITED);
}

void GetAuroraRosterSignal(void)
{
    struct AuroraRosterExtension record;
    u16 signal = 0;
    GetAuroraRosterState();
    if (gAuroraRosterLastState == AURORA_INDIVIDUAL_PARTY && ReadRoster(&record)
        && AuroraRosterLifeStage(gSpecialVar_0x8005 == AURORA_ROSTER_CHILD ? record.childDays : record.originalDays) == AURORA_ROSTER_MATURE
        && GetMonData(&gParties[B_TRAINER_PLAYER][gSpecialVar_0x8004], MON_DATA_HP))
    {
        if (gSpecialVar_0x8005 == AURORA_ROSTER_CHILD)
            signal = record.phenotypeRevision ? AURORA_CHILD_SIGNAL_EDITED : AURORA_CHILD_SIGNAL_BASE;
        else
            signal = AURORA_LUMIFIN_SIGNAL;
    }
    gSpecialVar_0x8007 = signal;
    RosterResult(signal >= AURORA_ROSTER_SIGNAL_THRESHOLD);
}

// Display-only helpers below are excluded from the native host harness.
static const u8 sRosterHatchling[] = _("HATCHLING");
static const u8 sRosterJuvenile[] = _("JUVENILE");
static const u8 sRosterMature[] = _("MATURE");

void BufferAuroraRosterInfo(void)
{
    struct AuroraRosterExtension record;
    u16 species;
    GetAuroraRosterAge();
    if (gSpecialVar_Result == AURORA_ROSTER_RESULT_INVALID || !ReadRoster(&record))
        return;
    species = gSpecialVar_0x8005 == AURORA_ROSTER_ORIGINAL ? SPECIES_LUMIFIN
        : record.phenotypeRevision ? AURORA_CHILD_EDITED_SPECIES : AURORA_CHILD_SPECIES;
    StringCopy(gStringVar1, gSpecialVar_0x8005 == AURORA_ROSTER_CHILD ? sRosterChildNickname : GetSpeciesName(species));
    ConvertIntToDecimalStringN(gStringVar2, gSpecialVar_0x8007, STR_CONV_MODE_LEFT_ALIGN, 5);
    StringCopy(gStringVar3, gSpecialVar_Result == AURORA_ROSTER_HATCHLING ? sRosterHatchling
        : gSpecialVar_Result == AURORA_ROSTER_JUVENILE ? sRosterJuvenile : sRosterMature);
}
