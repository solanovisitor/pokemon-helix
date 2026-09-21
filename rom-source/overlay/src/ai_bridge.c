#include "global.h"
#include <stddef.h>
#include "ai_bridge.h"
#include "event_data.h"
#include "helix_genesis.h"
#include "main.h"
#include "random.h"
#include "script.h"
#include "string_util.h"
#include "task.h"
#include "text.h"
#include "constants/characters.h"

STATIC_ASSERT(sizeof(struct AiBridgeMailbox) == 264, AiBridgeMailboxSize);
STATIC_ASSERT(offsetof(struct AiBridgeMailbox, response) == 24, AiBridgeResponseOffset);
STATIC_ASSERT(offsetof(struct AiBridgeMailbox, status) == 6, AiBridgeStatusOffset);

EWRAM_DATA volatile struct AiBridgeMailbox gAiBridgeMailbox = {0};
EWRAM_DATA u16 gAiBridgeLastResult = AI_BRIDGE_RESULT_NONE;
EWRAM_DATA u16 gAiBridgeConversationActive = 0;
static EWRAM_DATA u32 sExpectedEpoch = 0;
static EWRAM_DATA u32 sExpectedRequest = 0;
static EWRAM_DATA u16 sExpectedMotivation = 0;
static EWRAM_DATA u16 sExpectedQuest = 0;
static EWRAM_DATA u16 sExpectedNpc = 0;

// Debuggers and validation read these instead of assuming SaveBlock1 layout.
const u32 gAiBridgeSaveOffsets[2] =
{
    offsetof(struct SaveBlock1, vars) + 2 * (VAR_SIGNAL_QUEST_STATE - VARS_START),
    offsetof(struct SaveBlock1, vars) + 2 * (VAR_SIGNAL_MOTIVATION - VARS_START),
};

const u32 gAiBridgeLanguage = AURORA_LANGUAGE_PT_BR;

#if AURORA_LANGUAGE_PT_BR
static const u8 sLabFallback[] = _("Seu perfil e uma escolha.\nO DNA e opcional.\pOs equipamentos guardam\ncada etapa da genese.");
static const u8 sFallbackCuriosity[] = _("IVO: Sua curiosidade importa.\nA pista fica ao norte da placa.\pProcure um pequeno aparelho\ncom uma luz azul.");
static const u8 sFallbackVillage[] = _("IVO: Obrigado por ajudar a vila.\nA pista fica ao norte da placa.\pProcure um pequeno aparelho\ncom uma luz azul.");
static const u8 sFallbackDoneCuriosity[] = _("IVO: Eu lembro: queria descobrir.\nFoi assim que achamos o sinal.\pSe ele chamar de novo, vamos\ninvestigar juntos.");
static const u8 sFallbackDoneVillage[] = _("IVO: Eu lembro: queria ajudar.\nA vila tem sorte de ter voce.\pSe ele chamar de novo, vamos\nproteger este lugar juntos.");
#else
static const u8 sLabFallback[] = _("Your profile is your choice.\nDNA is optional.\pThe equipment keeps each\nstep of genesis safe.");
static const u8 sFallbackCuriosity[] = _("IVO: Your curiosity matters.\nThe clue is north of the sign.\pLook for a small device\nwith a blue light.");
static const u8 sFallbackVillage[] = _("IVO: Thanks for helping us.\nThe clue is north of the sign.\pLook for a small device\nwith a blue light.");
static const u8 sFallbackDoneCuriosity[] = _("IVO: I remember your curiosity.\nIt led us to the signal.\pIf it calls again, we can\ninvestigate together.");
static const u8 sFallbackDoneVillage[] = _("IVO: You wanted to help us.\nThis town is lucky to have you.\pIf it calls again, we can\nprotect this place together.");
#endif

static void BufferFallback(void)
{
    bool32 village = sExpectedMotivation == SIGNAL_MOTIVATION_VILLAGE;
    const u8 *text;

    if (sExpectedNpc != AI_NPC_IVO)
    {
        StringCopy(gStringVar4, sLabFallback);
        return;
    }

    if (sExpectedQuest >= SIGNAL_QUEST_REPORTED)
        text = village ? sFallbackDoneVillage : sFallbackDoneCuriosity;
    else
        text = village ? sFallbackVillage : sFallbackCuriosity;
    StringCopy(gStringVar4, text);
}

static bool32 IsSafeGlyph(u8 c)
{
    return c == CHAR_SPACE
        || (c >= 0xA1 && c <= 0xAE)
        || c == 0xB4 || c == 0xB8 || c == 0xBA || c == 0xF0
        || (c >= 0xBB && c <= 0xEE);
}

// No placeholders, extended controls, extra terminators, or arbitrary GBA
// bytes reach the text engine. Limit pages and actual rendered pixel width.
static bool32 ValidateResponse(u8 *text, u16 length)
{
    u32 i;
    u32 lineLength = 0;
    u32 linesOnPage = 1;
    u32 pages = 1;
    u8 line[31];

    if (length == 0 || length >= AI_BRIDGE_RESPONSE_CAPACITY)
        return FALSE;
    for (i = 0; i <= length; i++)
    {
        u8 c = i == length ? EOS : text[i];
        if (c == CHAR_NEWLINE || c == CHAR_PROMPT_CLEAR || i == length)
        {
            if (lineLength == 0)
                return FALSE;
            line[lineLength] = EOS;
            if (GetStringWidth(FONT_NORMAL, line, 0) > 208)
                return FALSE;
            lineLength = 0;
            if (c == CHAR_NEWLINE && ++linesOnPage > 2)
                return FALSE;
            if (c == CHAR_PROMPT_CLEAR)
            {
                if (++pages > 2)
                    return FALSE;
                linesOnPage = 1;
            }
        }
        else
        {
            if (!IsSafeGlyph(c) || lineLength >= 30)
                return FALSE;
            line[lineLength++] = c;
        }
    }
    text[length] = EOS;
    return TRUE;
}

static bool32 RequestStillMatches(void)
{
    return gAiBridgeMailbox.magic == AI_BRIDGE_MAGIC
        && gAiBridgeMailbox.version == AI_BRIDGE_VERSION
        && gAiBridgeMailbox.epoch == sExpectedEpoch
        && gAiBridgeMailbox.request == sExpectedRequest
        && gAiBridgeMailbox.npc == sExpectedNpc
        && gAiBridgeMailbox.motivation == sExpectedMotivation
        && gAiBridgeMailbox.quest == sExpectedQuest
        && (sExpectedNpc != AI_NPC_IVO
            || (VarGet(VAR_SIGNAL_MOTIVATION) == sExpectedMotivation
                && VarGet(VAR_SIGNAL_QUEST_STATE) == sExpectedQuest));
}

static void FinishRequest(u8 taskId, u16 result)
{
    if (result != AI_BRIDGE_RESULT_RECEIVED)
        BufferFallback();
    gAiBridgeLastResult = result;
    gSpecialVar_Result = result;
    gAiBridgeMailbox.status = result == AI_BRIDGE_RESULT_RECEIVED ? AI_BRIDGE_IDLE : AI_BRIDGE_CANCELLED;
    if (result == AI_BRIDGE_RESULT_CANCELLED)
        gAiBridgeConversationActive = 0;
    DestroyTask(taskId);
    ScriptContext_Enable();
}

static void Task_WaitForDialogue(u8 taskId)
{
    u32 i;
    u16 length;
    u8 response[AI_BRIDGE_RESPONSE_CAPACITY];

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
    if (gAiBridgeMailbox.status == AI_BRIDGE_RESPONSE)
    {
        length = gAiBridgeMailbox.responseLength;
        if (length == 0 || length >= AI_BRIDGE_RESPONSE_CAPACITY)
        {
            FinishRequest(taskId, AI_BRIDGE_RESULT_INVALID);
            return;
        }
        for (i = 0; i < length; i++)
            response[i] = gAiBridgeMailbox.response[i];
        if (!ValidateResponse(response, length))
        {
            FinishRequest(taskId, AI_BRIDGE_RESULT_INVALID);
            return;
        }
        StringCopy(gStringVar4, response);
        FinishRequest(taskId, AI_BRIDGE_RESULT_RECEIVED);
    }
    else if (gAiBridgeMailbox.status == AI_BRIDGE_ERROR)
        FinishRequest(taskId, AI_BRIDGE_RESULT_OFFLINE);
    else if (gAiBridgeMailbox.status != AI_BRIDGE_REQUEST)
        FinishRequest(taskId, AI_BRIDGE_RESULT_INVALID);
    else if (++gTasks[taskId].data[0] >= AI_BRIDGE_TIMEOUT_FRAMES)
        FinishRequest(taskId, AI_BRIDGE_RESULT_TIMEOUT);
}

// Script calls this special, then waitstate. A frame task suspends only the
// event script; audio, rendering, inputs and the emulator bridge keep running.
static void RequestDialogue(u16 npc, u16 motivation, u16 quest)
{
    if (sExpectedEpoch == 0)
        sExpectedEpoch = (gMain.vblankCounter1 ^ gRngValue.a) | 1;
    if (++sExpectedRequest == 0)
    {
        sExpectedEpoch++;
        sExpectedRequest = 1;
    }
    sExpectedNpc = npc;
    sExpectedMotivation = motivation;
    sExpectedQuest = quest;
    gAiBridgeConversationActive = 1;
    gAiBridgeLastResult = AI_BRIDGE_RESULT_NONE;
    gAiBridgeMailbox.status = AI_BRIDGE_IDLE;
    gAiBridgeMailbox.magic = AI_BRIDGE_MAGIC;
    gAiBridgeMailbox.version = AI_BRIDGE_VERSION;
    gAiBridgeMailbox.epoch = sExpectedEpoch;
    gAiBridgeMailbox.request = sExpectedRequest;
    gAiBridgeMailbox.npc = sExpectedNpc;
    gAiBridgeMailbox.motivation = sExpectedMotivation;
    gAiBridgeMailbox.quest = sExpectedQuest;
    gAiBridgeMailbox.responseLength = 0;
    gAiBridgeMailbox.response[0] = EOS;
    CreateTask(Task_WaitForDialogue, 8);
    gAiBridgeMailbox.status = AI_BRIDGE_REQUEST;
}

void RequestIvoDialogue(void)
{
    RequestDialogue(AI_NPC_IVO, VarGet(VAR_SIGNAL_MOTIVATION), VarGet(VAR_SIGNAL_QUEST_STATE));
}

void RequestLabDialogue(void)
{
    u16 npc = gSpecialVar_0x8004;
    u16 soul = HelixGenesisSoul();
    u16 stage = HelixGenesisStage();
    if (npc < AI_NPC_RECEPTION || npc > AI_NPC_NURSERY)
        npc = AI_NPC_RECEPTION;
    // These compatibility fields are coarse hints, never proof of admission.
    RequestDialogue(npc, soul == 1 ? 1 : 2, stage > 3 ? 3 : stage);
}

void EndAiDialogue(void)
{
    gAiBridgeConversationActive = 0;
}
