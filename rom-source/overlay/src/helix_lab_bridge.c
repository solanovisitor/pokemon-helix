#include "global.h"
#include <stddef.h>
#include "helix_lab_bridge.h"
#include "helix_lab_items.h"
#include "helix_genesis.h"
#include "helix_signal.h"
#include "helix_universal.h"
#include "pokemon.h"
#include "main.h"
#include "task.h"
#include "script.h"
#include "event_data.h"

#define LAB_MAGIC 0x3142414C
#define LAB_REQUEST 1
#define LAB_RESPONSE 2
#define LAB_CANCELLED 3
#define LAB_ERROR 4
#define LAB_TIMEOUT 600
EWRAM_DATA volatile struct HelixLabMailbox gHelixLabMailbox = {0};
EWRAM_DATA u16 gHelixLabBridgeLastResult = 0;
static EWRAM_DATA struct HelixLabMailbox sExpected = {0};
static EWRAM_DATA struct BoxPokemon sCompanion = {0};
static EWRAM_DATA u32 sSequence = 0;
static EWRAM_DATA u32 sEpoch = 0;
const u32 gHelixLabBridgeDescriptor[6] = {1, sizeof(struct HelixLabMailbox), 8, 76, 84, LAB_TIMEOUT};
STATIC_ASSERT(sizeof(struct HelixLabMailbox) == 92, HelixLabMailboxSize);
STATIC_ASSERT(offsetof(struct HelixLabMailbox, result) == 84, HelixLabResultOffset);

static bool32 SameContext(void)
{
    struct BoxPokemon current;
    u8 saveKey[16];
    memcpy(saveKey, gSaveBlock2Ptr->playerTrainerId, 4);
    memcpy(saveKey + 4, gSaveBlock3Ptr->helixUniversal.namespace, 12);
    return gHelixLabMailbox.magic == LAB_MAGIC && gHelixLabMailbox.version == 1
        && memcmp((const u8 *)&gHelixLabMailbox + 8, (const u8 *)&sExpected + 8, 76) == 0
        && memcmp(saveKey, sExpected.saveKey, 16) == 0
        && HelixUniversalCrc32(gSaveBlock1Ptr->filler1, 52) == sExpected.bindingCrc
        && HelixLabItemsValidateRequest(sExpected.raw, sExpected.condition, sExpected.prediction)
        && HelixSignalInspect(&current) == HELIX_SIGNAL_READY
        && memcmp(&current, &sCompanion, sizeof(current)) == 0;
}

static void FinishLab(u8 taskId, u16 code, bool32 applied)
{
    gHelixLabBridgeLastResult = code; // 1 applied, 2 cancel, 3 stale, 4 offline, 5 timeout.
    gSpecialVar_Result = applied ? 1 : 0;
    gHelixLabMailbox.status = applied ? 0 : LAB_CANCELLED;
    DestroyTask(taskId);
    ScriptContext_Enable();
}

static void Task_HelixLabSimulation(u8 taskId)
{
    bool32 applied;
    if (JOY_NEW(B_BUTTON)) { FinishLab(taskId, 2, FALSE); return; }
    if (!SameContext()) { FinishLab(taskId, 3, FALSE); return; }
    if (gHelixLabMailbox.status == LAB_RESPONSE)
    {
        // Model v1 has exactly two admitted protocols. Untrusted host numbers
        // cannot choose an effect, price, individual, genome or arbitrary flag.
        if (gHelixLabMailbox.result != sExpected.condition
            || gHelixLabMailbox.signal != (sExpected.condition == 1 ? 11 : 50)
            || gHelixLabMailbox.span != (sExpected.condition == 1 ? 3 : 8)
            || gHelixLabMailbox.control != 10)
        { FinishLab(taskId, 3, FALSE); return; }
        applied = HelixLabItemsApplyResult(sExpected.raw, sExpected.condition,
                                         sExpected.prediction, gHelixLabMailbox.result);
        FinishLab(taskId, applied ? 1 : 3, applied);
    }
    else if (gHelixLabMailbox.status == LAB_ERROR) FinishLab(taskId, 4, FALSE);
    else if (gHelixLabMailbox.status != LAB_REQUEST) FinishLab(taskId, 3, FALSE);
    else if (++gTasks[taskId].data[0] >= LAB_TIMEOUT) FinishLab(taskId, 5, FALSE);
}

void StartHelixLabSimulation(void)
{
    u8 i;
    // Script immediately uses waitstate; even refusal resumes on the next task.
    gSpecialVar_Result = 0;
    if (FuncIsActiveTask(Task_HelixLabSimulation)) return;
    for (i = 0; i < NUM_TASKS && gTasks[i].isActive; i++);
    if (i == NUM_TASKS) return;
    CreateTask(Task_HelixLabSimulation, 8);
    memset(&sExpected, 0, sizeof(sExpected));
    sExpected.magic = LAB_MAGIC;
    sExpected.version = 1;
    if (!sEpoch) sEpoch = gMain.vblankCounter1 | 1;
    sExpected.epoch = sEpoch;
    sExpected.request = ++sSequence;
    if (!sSequence) { sExpected.request = ++sSequence; sExpected.epoch = ++sEpoch; }
    sExpected.model = 1;
    sExpected.raw = gHelixLabItemsView.raw;
    sExpected.condition = gHelixLabItemsView.condition;
    sExpected.prediction = gHelixLabItemsView.prediction;
    sExpected.recipe = gHelixLabItemsView.recipe;
    memcpy(sExpected.saveKey, gSaveBlock2Ptr->playerTrainerId, 4);
    memcpy(sExpected.saveKey + 4, gSaveBlock3Ptr->helixUniversal.namespace, 12);
    if (sExpected.recipe >= 1 && sExpected.recipe <= 2)
        memcpy(sExpected.individual, gHelixGenesisIds[sExpected.recipe - 1], 32);
    sExpected.bindingCrc = HelixUniversalCrc32(gSaveBlock1Ptr->filler1, 52);
    sExpected.contextCrc = HelixUniversalCrc32((const u8 *)&sExpected + 8, 72);
    memcpy((void *)&gHelixLabMailbox, &sExpected, sizeof(sExpected));
    gHelixLabBridgeLastResult = 0;
    if (sExpected.recipe < 1 || sExpected.recipe > 2
        || !HelixLabItemsValidateRequest(sExpected.raw, sExpected.condition, sExpected.prediction)
        || HelixSignalInspect(&sCompanion) != HELIX_SIGNAL_READY)
        gHelixLabMailbox.status = LAB_ERROR;
    else gHelixLabMailbox.status = LAB_REQUEST; // Publish last.
    gSpecialVar_Result = 99;
}
