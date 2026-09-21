#include "global.h"
#include "constants/helix_public_fixture.h"
#include "pokemon_birth.h"
#include <stddef.h>
#include "aurora_individual.h"
#include "helix_genesis.h"
#include "constants/ai_bridge.h"
#include "event_data.h"
#include "main.h"
#include "menu.h"
#include "random.h"
#include "script.h"
#include "script_menu.h"
#include "sprite.h"
#include "task.h"
#include "window.h"
#include "bg.h"
#include "battle.h"
#include "pokemon.h"
#include "pokemon_storage_system.h"
#include "constants/moves.h"
#include "constants/species.h"

STATIC_ASSERT(sizeof(struct AuroraIndividualMailbox) == 2164, AuroraIndividualMailboxSize);
STATIC_ASSERT(offsetof(struct AuroraIndividualMailbox, payload) == 84, AuroraIndividualPayloadOffset);
STATIC_ASSERT(sizeof(struct AuroraIndividualRecord) == AURORA_INDIVIDUAL_SAVE_SIZE, AuroraIndividualRecordSize);
STATIC_ASSERT(offsetof(struct AuroraIndividualRecord, recordCrc) == 72, AuroraIndividualRecordCrcOffset);
STATIC_ASSERT(sizeof(gSaveBlock2Ptr->pokedex.filler) == 104, AuroraIndividualReservedSpace);

#include "data/aurora_individual_art.h"

// Public synthetic identity; the original authorial artwork is reused unchanged.
static const u8 sIndividualId[12] = HELIX_PUBLIC_INDIVIDUAL_ID;
static const u8 sIndividualGenome[16] = HELIX_PUBLIC_INDIVIDUAL_GENOME;
static const u8 sIndividualArtHash[32] = HELIX_PUBLIC_INDIVIDUAL_ART_HASH;
#define INDIVIDUAL_ART_CRC HELIX_PUBLIC_INDIVIDUAL_ART_CRC

// Pure bounded validators are compiled directly by the host regression test.
u32 AuroraIndividualCrc32(const u8 *data, u32 size)
{
    u32 crc = 0xffffffff;
    u32 i, bit;
    for (i = 0; i < size; i++)
    {
        crc ^= data[i];
        for (bit = 0; bit < 8; bit++)
            crc = (crc >> 1) ^ (0xedb88320 & (0 - (crc & 1)));
    }
    return crc ^ 0xffffffff;
}

bool32 AuroraIndividualValidatePayload(const u8 *data, u16 size, u32 crc)
{
    u32 i;
    if (size != AURORA_INDIVIDUAL_PAYLOAD_SIZE || crc != INDIVIDUAL_ART_CRC)
        return FALSE;
    if (AuroraIndividualCrc32(data, size) != crc)
        return FALSE;
    // Each RGB555 entry must have its unused high bit clear.
    for (i = 2049; i < AURORA_INDIVIDUAL_PAYLOAD_SIZE; i += 2)
        if (data[i] & 0x80)
            return FALSE;
    // This milestone admits one authored individual only. Exact comparison
    // binds SHA metadata without trusting a remote hash or CRC collisions.
    return memcmp(data, sAuroraIndividualArt, size) == 0;
}

bool32 AuroraIndividualValidateRecord(const struct AuroraIndividualRecord *record)
{
    return record->magic == AURORA_INDIVIDUAL_MAGIC
        && record->version == AURORA_INDIVIDUAL_VERSION
        && (record->flags == AURORA_INDIVIDUAL_PRESENT || record->flags == AURORA_INDIVIDUAL_ISSUED)
        && memcmp(record->individualId, sIndividualId, sizeof(sIndividualId)) == 0
        && memcmp(record->genome, sIndividualGenome, sizeof(sIndividualGenome)) == 0
        && memcmp(record->artHash, sIndividualArtHash, sizeof(sIndividualArtHash)) == 0
        && record->payloadCrc == INDIVIDUAL_ART_CRC
        && record->recordCrc == AuroraIndividualCrc32((const u8 *)record, 72);
}

bool32 AuroraRosterValidateExtension(const struct AuroraRosterExtension *record)
{
    u32 i;
    if (record->magic != AURORA_ROSTER_MAGIC
        || record->version != AURORA_ROSTER_VERSION
        || (record->flags & ~AURORA_ROSTER_CHILD_ISSUED)
        || record->phenotypeRevision > 1 || record->genotypeRevision > 1
        || record->genotypeRevision > record->phenotypeRevision
        || record->manifestCrc != AURORA_ROSTER_MANIFEST_CRC
        || record->crc != AuroraIndividualCrc32((const u8 *)record, 24))
        return FALSE;
    // Unissued children have no age or edit history.
    if (!(record->flags & AURORA_ROSTER_CHILD_ISSUED)
        && (record->childDays || record->phenotypeRevision || record->genotypeRevision))
        return FALSE;
    for (i = 0; i < sizeof(record->reserved); i++)
        if (record->reserved[i])
            return FALSE;
    return TRUE;
}

u16 AuroraIndividualReadState(const u8 *bytes, u32 size)
{
    struct AuroraIndividualRecord record;
    struct AuroraRosterExtension extension;
    u32 i;
    bool32 tailPresent = FALSE;
    if (size != 104)
        return AURORA_INDIVIDUAL_UNSUPPORTED;
    memcpy(&record, bytes, sizeof(record));
    for (i = sizeof(record); i < size; i++)
        if (bytes[i] != 0)
            tailPresent = TRUE;
    if (tailPresent)
    {
        memcpy(&extension, bytes + sizeof(record), sizeof(extension));
        if (!AuroraRosterValidateExtension(&extension))
            return AURORA_INDIVIDUAL_UNSUPPORTED;
    }
    if (AuroraIndividualValidateRecord(&record))
        return AURORA_INDIVIDUAL_PRESENT;
    if (tailPresent)
        return AURORA_INDIVIDUAL_UNSUPPORTED;
    for (i = 0; i < sizeof(record); i++)
        if (bytes[i] != 0)
            return AURORA_INDIVIDUAL_UNSUPPORTED;
    return AURORA_INDIVIDUAL_EMPTY;
}


// ROM integration begins here.
EWRAM_DATA volatile struct AuroraIndividualMailbox gAuroraIndividualMailbox = {0};
EWRAM_DATA u16 gAuroraIndividualLastResult = AI_BRIDGE_RESULT_NONE;
EWRAM_DATA u16 gAuroraIndividualViewerOpen = FALSE;
EWRAM_DATA u16 gAuroraIndividualPartyState = AURORA_INDIVIDUAL_PARTY_ABSENT;
static EWRAM_DATA u32 sEpoch = 0;
static EWRAM_DATA u32 sRequest = 0;
static EWRAM_DATA u8 ALIGNED(4) sReceivedArt[AURORA_INDIVIDUAL_PAYLOAD_SIZE] = {0};
static EWRAM_DATA bool8 sReceivedArtValid = FALSE;

const u32 gAuroraIndividualSaveLayout[3] =
{
    offsetof(struct SaveBlock2, pokedex.filler),
    AURORA_INDIVIDUAL_SAVE_SIZE,
    sizeof(gSaveBlock2Ptr->pokedex.filler),
};

const u32 gAuroraInvestigationSaveOffset = offsetof(struct SaveBlock1, vars)
    + (VAR_AURORA_INVESTIGATION - VARS_START) * sizeof(u16);

// Read-only native-layout metadata for emulator assertions. Native secure
// substruct order is personality % 24; each word is XORed with personality/OT.
const u32 gAuroraCompanionLayout[20] =
{
    SPECIES_LUMIFIN, AURORA_INDIVIDUAL_PERSONALITY,
    sizeof(struct Pokemon), sizeof(struct BoxPokemon),
    offsetof(struct BoxPokemon, personality), offsetof(struct BoxPokemon, otId),
    offsetof(struct BoxPokemon, secure), NUM_SUBSTRUCT_BYTES,
    0, 4, // Species: low 11 bits; experience: low 21 bits (bitfields).
    0, 8, // Four 11-bit moves in u16s; four 7-bit PP values in u8s.
    offsetof(struct Pokemon, level), offsetof(struct Pokemon, hp), offsetof(struct Pokemon, maxHP),
    offsetof(struct PokemonStorage, boxes), TOTAL_BOXES_COUNT, IN_BOX_COUNT,
    offsetof(struct SaveBlock2, playerTrainerId),
    offsetof(struct BoxPokemon, checksum),
};

static u16 ReadIndividualState(void)
{
    return AuroraIndividualReadState(gSaveBlock2Ptr->pokedex.filler, sizeof(gSaveBlock2Ptr->pokedex.filler));
}

void GetAuroraIndividualState(void)
{
    gSpecialVar_Result = ReadIndividualState();
}

static void CommitAuthoredIndividual(u16 flags)
{
    struct AuroraIndividualRecord record = {0};
    record.magic = AURORA_INDIVIDUAL_MAGIC;
    record.version = AURORA_INDIVIDUAL_VERSION;
    record.flags = flags;
    memcpy(record.individualId, sIndividualId, sizeof(sIndividualId));
    memcpy(record.genome, sIndividualGenome, sizeof(sIndividualGenome));
    memcpy(record.artHash, sIndividualArtHash, sizeof(sIndividualArtHash));
    record.payloadCrc = INDIVIDUAL_ART_CRC;
    record.recordCrc = AuroraIndividualCrc32((const u8 *)&record, 72);
    memcpy(gSaveBlock2Ptr->pokedex.filler, &record, sizeof(record));
}

static bool32 IsAuthoredCompanion(struct BoxPokemon *mon)
{
    struct BoxPokemon copy;
    if (mon->personality != AURORA_INDIVIDUAL_PERSONALITY || mon->otId != READ_OTID_FROM_SAVE)
        return FALSE;
    // Native getters can mark invalid checksums as Bad Eggs. Identity reads
    // must not mutate a damaged candidate while rejecting it.
    copy = *mon;
    return GetBoxMonData(&copy, MON_DATA_SPECIES) == SPECIES_LUMIFIN
        && !GetBoxMonData(&copy, MON_DATA_IS_EGG)
        && !GetBoxMonData(&copy, MON_DATA_SANITY_IS_BAD_EGG);
}

static u16 ReadCompanionPartyState(void)
{
    u32 slot, box;
    u16 state = ReadIndividualState();
    struct AuroraIndividualRecord record;
    gSpecialVar_0x8004 = 0xffff;
    if (state == AURORA_INDIVIDUAL_UNSUPPORTED)
        return AURORA_INDIVIDUAL_PARTY_UNSUPPORTED;
    if (state == AURORA_INDIVIDUAL_EMPTY)
        return AURORA_INDIVIDUAL_PARTY_ABSENT;
    for (slot = 0; slot < PARTY_SIZE; slot++)
    {
        if (IsAuthoredCompanion(&gParties[B_TRAINER_PLAYER][slot].box))
        {
            gSpecialVar_0x8004 = slot;
            return AURORA_INDIVIDUAL_PARTY;
        }
    }
    for (box = 0; box < TOTAL_BOXES_COUNT; box++)
        for (slot = 0; slot < IN_BOX_COUNT; slot++)
            if (IsAuthoredCompanion(GetBoxedMonPtr(box, slot)))
                return AURORA_INDIVIDUAL_BOXED;
    memcpy(&record, gSaveBlock2Ptr->pokedex.filler, sizeof(record));
    return record.flags & AURORA_INDIVIDUAL_FLAG_ISSUED
        ? AURORA_INDIVIDUAL_MISSING : AURORA_INDIVIDUAL_PARTY_ABSENT;
}

void GetAuroraIndividualPartyState(void)
{
    gAuroraIndividualPartyState = ReadCompanionPartyState();
    gSpecialVar_Result = gAuroraIndividualPartyState;
}

static u32 FindEmptyPartySlot(void)
{
    u32 slot, candidate = PARTY_SIZE;
    for (slot = 0; slot < PARTY_SIZE; slot++)
    {
        struct BoxPokemon copy = gParties[B_TRAINER_PLAYER][slot].box;
        u16 species = GetBoxMonData(&copy, MON_DATA_SPECIES);
        // Party counting after creation uses native getters on live data.
        // Do not create anything when it would mutate a corrupt party entry.
        if (GetBoxMonData(&copy, MON_DATA_SANITY_IS_BAD_EGG))
            return PARTY_SIZE;
        if (candidate == PARTY_SIZE && species == SPECIES_NONE)
            candidate = slot;
    }
    return candidate;
}

static void CreateAuthoredCompanion(u32 slot, bool32 newBirth)
{
    struct Pokemon mon;
    // Balance is authored independently of the inherited virtual genome.
    CreateMonWithIVs(&mon, SPECIES_LUMIFIN, 5, AURORA_INDIVIDUAL_PERSONALITY, OTID_STRUCT_PLAYER_ID, 15);
    SetMonMoveSlot(&mon, MOVE_WATER_GUN, 0);
    SetMonMoveSlot(&mon, MOVE_TACKLE, 1);
    SetMonMoveSlot(&mon, MOVE_TAIL_WHIP, 2);
    SetMonMoveSlot(&mon, MOVE_SUPERSONIC, 3);
    if (newBirth) RecordMonBirthDate(&mon);
    // Commit native mon and registry synchronously, before yielding to artwork.
    gParties[B_TRAINER_PLAYER][slot] = mon;
    CalculatePlayerPartyCount();
    FlagSet(FLAG_SYS_POKEMON_GET);
    CommitAuthoredIndividual(AURORA_INDIVIDUAL_ISSUED);
    gAuroraIndividualPartyState = AURORA_INDIVIDUAL_PARTY;
}

void JoinAuroraIndividualParty(void)
{
    u32 slot;
    if (!HelixGenesisCanContinue())
    {
        gSpecialVar_Result = AI_BRIDGE_RESULT_INVALID;
        return;
    }
    GetAuroraIndividualPartyState();
    if (VarGet(VAR_SIGNAL_QUEST_STATE) != SIGNAL_QUEST_REPORTED || ReadIndividualState() != AURORA_INDIVIDUAL_PRESENT)
    {
        gSpecialVar_Result = AI_BRIDGE_RESULT_INVALID;
        return;
    }
    if (gAuroraIndividualPartyState == AURORA_INDIVIDUAL_PARTY || gAuroraIndividualPartyState == AURORA_INDIVIDUAL_BOXED)
    {
        // A legacy record with an existing native individual adopts it once.
        CommitAuthoredIndividual(AURORA_INDIVIDUAL_ISSUED);
        return;
    }
    if (gAuroraIndividualPartyState != AURORA_INDIVIDUAL_PARTY_ABSENT)
        return;
    // An old specimen-only record is not permission to add a second early
    // companion to a Helix journey. Existing owned individuals remain intact.
    if (HelixGenesisStage() != 0)
    {
        gSpecialVar_Result = AI_BRIDGE_RESULT_INVALID;
        return;
    }
    slot = FindEmptyPartySlot();
    if (slot == PARTY_SIZE)
    {
        gSpecialVar_Result = AURORA_INDIVIDUAL_RESULT_PARTY_FULL;
        return;
    }
    CreateAuthoredCompanion(slot, FALSE);
    gSpecialVar_0x8004 = slot;
    gSpecialVar_Result = AURORA_INDIVIDUAL_PARTY;
}

void GetAuroraIndividualBattleReady(void)
{
    u32 slot;
    GetAuroraIndividualPartyState();
    gSpecialVar_Result = FALSE;
    if (gAuroraIndividualPartyState != AURORA_INDIVIDUAL_PARTY)
        return;
    for (slot = 0; slot < PARTY_SIZE; slot++)
    {
        struct Pokemon *mon = &gParties[B_TRAINER_PLAYER][slot];
        if (GetMonData(mon, MON_DATA_SPECIES) != SPECIES_NONE && !GetMonData(mon, MON_DATA_IS_EGG) && GetMonData(mon, MON_DATA_HP))
        {
            gSpecialVar_Result = IsAuthoredCompanion(&mon->box);
            return;
        }
    }
}

void GetAuroraIndividualBattleWon(void)
{
    GetAuroraIndividualPartyState();
    // BattleResults survives return to the field. The quest requires this
    // individual to lead; the first player species records actual participation.
    gSpecialVar_Result = gAuroraIndividualPartyState == AURORA_INDIVIDUAL_PARTY
        && gBattleOutcome == B_OUTCOME_WON
        && gBattleResults.playerMon1Species == SPECIES_LUMIFIN;
}

static bool32 RequestStillMatches(void)
{
    u32 i;
    if (gAuroraIndividualMailbox.magic != AURORA_INDIVIDUAL_MAGIC
        || gAuroraIndividualMailbox.version != AURORA_INDIVIDUAL_VERSION
        || gAuroraIndividualMailbox.epoch != sEpoch
        || gAuroraIndividualMailbox.request != sRequest
        || gAuroraIndividualMailbox.operation != AURORA_INDIVIDUAL_OPERATION_HATCH
        || VarGet(VAR_SIGNAL_QUEST_STATE) != SIGNAL_QUEST_REPORTED
        || ReadIndividualState() != AURORA_INDIVIDUAL_PRESENT)
        return FALSE;
    for (i = 0; i < sizeof(sIndividualId); i++)
        if (gAuroraIndividualMailbox.individualId[i] != sIndividualId[i])
            return FALSE;
    for (i = 0; i < sizeof(sIndividualGenome); i++)
        if (gAuroraIndividualMailbox.genome[i] != sIndividualGenome[i])
            return FALSE;
    for (i = 0; i < sizeof(sIndividualArtHash); i++)
        if (gAuroraIndividualMailbox.artHash[i] != sIndividualArtHash[i])
            return FALSE;
    return TRUE;
}

static void FinishRequest(u8 taskId, u16 result)
{
    gAuroraIndividualLastResult = result;
    gSpecialVar_Result = result;
    gAuroraIndividualMailbox.status = result == AI_BRIDGE_RESULT_RECEIVED ? AI_BRIDGE_IDLE : AI_BRIDGE_CANCELLED;
    DestroyTask(taskId);
    ScriptContext_Enable();
}

static void Task_WaitForIndividual(u8 taskId)
{
    u32 i;
    if (gTasks[taskId].data[1])
    {
        FinishRequest(taskId, AI_BRIDGE_RESULT_INVALID);
        return;
    }
    if (JOY_NEW(B_BUTTON))
    {
        FinishRequest(taskId, AI_BRIDGE_RESULT_CANCELLED);
        return;
    }
    if (!RequestStillMatches())
    {
        FinishRequest(taskId, AI_BRIDGE_RESULT_INVALID);
        return;
    }
    if (gAuroraIndividualMailbox.status == AI_BRIDGE_RESPONSE)
    {
        // Bound before copying. Complete payload is staged before validation.
        if (gAuroraIndividualMailbox.payloadLength != AURORA_INDIVIDUAL_PAYLOAD_SIZE)
        {
            FinishRequest(taskId, AI_BRIDGE_RESULT_INVALID);
            return;
        }
        for (i = 0; i < AURORA_INDIVIDUAL_PAYLOAD_SIZE; i++)
            sReceivedArt[i] = gAuroraIndividualMailbox.payload[i];
        if (!AuroraIndividualValidatePayload(sReceivedArt, gAuroraIndividualMailbox.payloadLength, gAuroraIndividualMailbox.payloadCrc))
        {
            FinishRequest(taskId, AI_BRIDGE_RESULT_INVALID);
            return;
        }
        sReceivedArtValid = TRUE;
        FinishRequest(taskId, AI_BRIDGE_RESULT_RECEIVED);
    }
    else if (gAuroraIndividualMailbox.status == AI_BRIDGE_ERROR)
        FinishRequest(taskId, AI_BRIDGE_RESULT_OFFLINE);
    else if (gAuroraIndividualMailbox.status != AI_BRIDGE_REQUEST)
        FinishRequest(taskId, AI_BRIDGE_RESULT_INVALID);
    else if (++gTasks[taskId].data[0] >= AI_BRIDGE_TIMEOUT_FRAMES)
        FinishRequest(taskId, AI_BRIDGE_RESULT_TIMEOUT);
}

// Upstream CreateTask returns 0 on exhaustion (also a valid task ID).
// Check capacity before calling it; scripts skip waitstate on synchronous error.
static u8 CreateIndividualTask(TaskFunc function)
{
    u32 i;
    gSpecialVar_Result = AI_BRIDGE_RESULT_NONE;
    for (i = 0; i < NUM_TASKS; i++)
        if (!gTasks[i].isActive)
            return CreateTask(function, 8);
    gAuroraIndividualLastResult = AI_BRIDGE_RESULT_INVALID;
    gSpecialVar_Result = AI_BRIDGE_RESULT_INVALID;
    return TASK_NONE;
}

void HatchAuroraIndividual(void)
{
    u32 i;
    u32 slot;
    u8 taskId;
    // Legacy Aurora saves keep their original birth. Helix observations never
    // issue an unrelated companion, including through a stale script entry.
    if (!HelixGenesisCanContinue() || HelixGenesisStage() != 0)
    {
        gSpecialVar_Result = AI_BRIDGE_RESULT_INVALID;
        gAuroraIndividualLastResult = AI_BRIDGE_RESULT_INVALID;
        return;
    }
    slot = FindEmptyPartySlot();
    if (slot == PARTY_SIZE)
    {
        gSpecialVar_Result = AURORA_INDIVIDUAL_RESULT_PARTY_FULL;
        gAuroraIndividualLastResult = AURORA_INDIVIDUAL_RESULT_PARTY_FULL;
        return;
    }
    taskId = CreateIndividualTask(Task_WaitForIndividual);
    if (taskId == TASK_NONE)
        return;
    if (VarGet(VAR_SIGNAL_QUEST_STATE) != SIGNAL_QUEST_REPORTED || ReadIndividualState() != AURORA_INDIVIDUAL_EMPTY)
    {
        gTasks[taskId].data[1] = TRUE;
        return;
    }
    // The explicit script confirmation authors the sole game effect. Network
    // results cannot create, replace or erase this already-chosen identity.
    CreateAuthoredCompanion(slot, TRUE);
    sReceivedArtValid = FALSE;
    if (sEpoch == 0)
        sEpoch = (gMain.vblankCounter1 ^ gRngValue.a) | 1;
    if (++sRequest == 0)
    {
        sEpoch++;
        sRequest = 1;
    }
    gAuroraIndividualLastResult = AI_BRIDGE_RESULT_NONE;
    gAuroraIndividualMailbox.status = AI_BRIDGE_IDLE;
    gAuroraIndividualMailbox.magic = AURORA_INDIVIDUAL_MAGIC;
    gAuroraIndividualMailbox.version = AURORA_INDIVIDUAL_VERSION;
    gAuroraIndividualMailbox.epoch = sEpoch;
    gAuroraIndividualMailbox.request = sRequest;
    gAuroraIndividualMailbox.operation = AURORA_INDIVIDUAL_OPERATION_HATCH;
    gAuroraIndividualMailbox.payloadLength = 0;
    for (i = 0; i < sizeof(sIndividualId); i++)
        gAuroraIndividualMailbox.individualId[i] = sIndividualId[i];
    for (i = 0; i < sizeof(sIndividualGenome); i++)
        gAuroraIndividualMailbox.genome[i] = sIndividualGenome[i];
    for (i = 0; i < sizeof(sIndividualArtHash); i++)
        gAuroraIndividualMailbox.artHash[i] = sIndividualArtHash[i];
    gAuroraIndividualMailbox.payloadCrc = INDIVIDUAL_ART_CRC;
    gAuroraIndividualMailbox.status = AI_BRIDGE_REQUEST;
}

#define INDIVIDUAL_SPRITE_TAG 0xA701
static const struct OamData sIndividualOam =
{
    .shape = SPRITE_SHAPE(64x64),
    .size = SPRITE_SIZE(64x64),
    .priority = 0,
};
static const struct SpriteTemplate sIndividualSpriteTemplate =
{
    .tileTag = INDIVIDUAL_SPRITE_TAG,
    .paletteTag = INDIVIDUAL_SPRITE_TAG,
    .oam = &sIndividualOam,
    .anims = gDummySpriteAnimTable,
    .images = NULL,
    .affineAnims = gDummySpriteAffineAnimTable,
    .callback = SpriteCallbackDummy,
};

static void Task_ShowIndividual(u8 taskId)
{
    struct Task *task = &gTasks[taskId];
    if (task->data[0] == 0)
    {
        const u8 *art = sReceivedArtValid ? sReceivedArt : sAuroraIndividualArt;
        struct SpriteSheet sheet = {art, 2048, INDIVIDUAL_SPRITE_TAG};
        struct SpritePalette palette = {(const u16 *)(art + 2048), INDIVIDUAL_SPRITE_TAG};
        struct WindowTemplate window = CreateWindowTemplate(0, 11, 1, 8, 8, 15, 100);
        if (ReadIndividualState() == AURORA_INDIVIDUAL_PRESENT)
            LoadSpriteSheet(&sheet);
        if (ReadIndividualState() != AURORA_INDIVIDUAL_PRESENT
            || GetSpriteTileStartByTag(INDIVIDUAL_SPRITE_TAG) == TAG_NONE
            || LoadSpritePalette(&palette) == 0xFF)
        {
            FreeSpriteTilesByTag(INDIVIDUAL_SPRITE_TAG);
            FreeSpritePaletteByTag(INDIVIDUAL_SPRITE_TAG);
            gAuroraIndividualLastResult = AI_BRIDGE_RESULT_INVALID;
            DestroyTask(taskId);
            ScriptContext_Enable();
            return;
        }
        task->data[1] = CreateSprite(&sIndividualSpriteTemplate, 120, 40, 0);
        if (task->data[1] == MAX_SPRITES)
        {
            FreeSpriteTilesByTag(INDIVIDUAL_SPRITE_TAG);
            FreeSpritePaletteByTag(INDIVIDUAL_SPRITE_TAG);
            gAuroraIndividualLastResult = AI_BRIDGE_RESULT_INVALID;
            DestroyTask(taskId);
            ScriptContext_Enable();
            return;
        }
        task->data[2] = AddWindow(&window);
        if (task->data[2] == WINDOW_NONE)
        {
            DestroySprite(&gSprites[task->data[1]]);
            FreeSpriteTilesByTag(INDIVIDUAL_SPRITE_TAG);
            FreeSpritePaletteByTag(INDIVIDUAL_SPRITE_TAG);
            gAuroraIndividualLastResult = AI_BRIDGE_RESULT_INVALID;
            DestroyTask(taskId);
            ScriptContext_Enable();
            return;
        }
        PutWindowTilemap(task->data[2]);
        SetStandardWindowBorderStyle(task->data[2], TRUE);
        ScheduleBgCopyTilemapToVram(0);
        gAuroraIndividualViewerOpen = TRUE;
        task->data[0] = 1;
    }
    else if (task->data[3] < 8)
        task->data[3]++;
    else if (JOY_NEW(A_BUTTON | B_BUTTON))
    {
        DestroySprite(&gSprites[task->data[1]]);
        FreeSpriteTilesByTag(INDIVIDUAL_SPRITE_TAG);
        FreeSpritePaletteByTag(INDIVIDUAL_SPRITE_TAG);
        ClearToTransparentAndRemoveWindow(task->data[2]);
        gAuroraIndividualViewerOpen = FALSE;
        DestroyTask(taskId);
        ScriptContext_Enable();
    }
}

void ShowAuroraIndividual(void)
{
    if (gSpecialVar_0x8004 == 1)
        gAuroraIndividualLastResult = AURORA_INDIVIDUAL_RESULT_CACHED;
    CreateIndividualTask(Task_ShowIndividual);
}
