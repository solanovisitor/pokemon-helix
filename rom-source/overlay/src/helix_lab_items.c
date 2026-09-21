#include "global.h"
#include <stddef.h>
#include "helix_lab_items.h"
#include "helix_signal.h"
#include "helix_region.h"
#include "helix_settings.h"
#include "helix_indicator_model.h"
#include "pokemon.h"
#include "main.h"
#include "task.h"
#include "script.h"
#include "event_data.h"
#include "field_player_avatar.h"
#include "item.h"
#include "script_menu.h"
#include "string_util.h"
#include "constants/items.h"
#include "constants/species.h"

const u32 gHelixLabItemsSaveLayout[4] = {offsetof(struct SaveBlock1, flags), 0x40, 2, 2};
const u16 gHelixLabItemsDescriptor[8] = {1, 0x7000, 0xFF00, 0x40, 16, 2, ITEM_HELIX_READER, ITEM_HELIX_MEDIUM};
EWRAM_DATA struct HelixLabItemsView gHelixLabItemsView = {0};
EWRAM_DATA u16 gHelixLabNativeLastResult = 0;
static EWRAM_DATA u16 sLabPreparedRaw = 0;
static EWRAM_DATA u16 sLabPreparedRecipe = 0;
static EWRAM_DATA struct BoxPokemon sLabPreparedMon = {0};
STATIC_ASSERT(sizeof(struct HelixLabItemsView) == 24, HelixLabItemsViewSize);
#define LAB_PAIR(en, pt) {COMPOUND_STRING(en), COMPOUND_STRING(pt)}
static const u8 *const sLabPages[][2] = {
    LAB_PAIR("MIRA: I study changing signals.\nADA needs a steady watering guide.\pTake a reader and one culture?\nThis study uses no POKE BALL.$", "MIRA: Estudo sinais que mudam.\nADA quer uma guia firme de rega.\pLevar leitor e uma cultura?\nO estudo nao usa POKE BALL.$"), // 0
    LAB_PAIR("First keep the field guide:\ncompare shelter and exposure\nwith your companion at this post.$", "Primeiro guarde o guia de campo:\ncompare abrigo e area exposta\ncom seu parceiro neste posto.$"),
    LAB_PAIR("Reader and Nanomon medium kept!\nOne fictional indicator culture.\pMeet ADA east in the village.\nThe reader stays after use.$", "Leitor e meio Nanomon guardados!\nUma cultura indicadora ficticia.\pFale com ADA a leste da vila.\nO leitor fica apos o uso.$"),
    LAB_PAIR("Make room in ITEMS and KEY ITEMS.\nNothing was given or taken.\nYou can return later.$", "Abra espaco em ITENS e ITENS CHAVE.\nNada foi dado nem retirado.\nPode voltar depois.$"),
    LAB_PAIR("ADA: I want a steady signal\nto compare my seedling water.\pMIRA wants to detect small changes.\nBoth uses matter. Which suits you?$", "ADA: Quero um sinal constante\npara comparar a agua das mudas.\pMIRA quer notar pequenas mudancas.\nOs dois usos valem. Qual prefere?$"),
    LAB_PAIR("Speak with ADA in the village.\nHer watering work explains\nwhy a steady signal can matter.$", "Fale com ADA na vila.\nO trabalho de rega explica\npor que um sinal firme importa.$"),
    LAB_PAIR("Same culture. Same medium.\nThis reader works offline.\pWe simulate three small changes.\nPredict the indicator's response.$", "Mesma cultura. Mesmo meio.\nEste leitor funciona offline.\pSimulamos tres pequenas mudancas.\nPreveja a resposta do indicador.$"),
    LAB_PAIR("Shelter selected: like the reeds\nfrom your companion's field guide.\pWhat signal do you predict?$", "Abrigo: como os juncos\ndo guia feito com seu parceiro.\pQue sinal voce espera?$"),
    LAB_PAIR("Exposure selected: like the open\nclearing in your field guide.\pWhat signal do you predict?$", "Exposicao: como a clareira\naberta no seu guia de campo.\pQue sinal voce espera?$"),
    LAB_PAIR("Cost: one Nanomon medium.\nReader and companion stay.\pA wrong prediction costs no extra.\nRun the simulated assay?$", "Custo: um meio Nanomon.\nLeitor e parceiro continuam.\pPrevisao errada nao custa mais.\nExecutar o ensaio simulado?$"),
    LAB_PAIR("Preparing the offline assay.\nB stops without using the medium.$", "Preparando o ensaio offline.\nB para sem usar o meio.$"),
    LAB_PAIR("No result. The medium stays.\nCheck your companion and kit.\pReturn when ready to try again.$", "Sem resultado. O meio continua.\nConfira seu parceiro e kit.\pVolte quando puder tentar de novo.$"),
    LAB_PAIR("Stopped. Nothing was consumed.\nYour field guide and kit stay.$", "Parou. Nada foi consumido.\nSeu guia e kit continuam.$"),
    LAB_PAIR("Bring your healthy companion,\nthe reader and one medium.\nThe saved kit is issued only once.$", "Traga seu parceiro saudavel,\no leitor e um meio.\nO kit salvo e entregue uma vez.$"),
    LAB_PAIR("Shelter: readings 10, 11, 13.\nControl 10. Middle 11. Range 3.\pThis culture: a steadier signal.\nADA keeps it as a watering guide.$", "Abrigo: leituras 10, 11, 13.\nControle 10. Meio 11. Faixa 3.\pNesta cultura: sinal mais firme.\nADA guarda como guia de rega.$"),
    LAB_PAIR("Exposure: readings 46, 50, 54.\nControl 10. Middle 50. Range 8.\pThis culture: more response.\nMIRA keeps it to notice changes.$", "Exposto: leituras 46, 50, 54.\nControle 10. Meio 50. Faixa 8.\pNesta cultura: resposta maior.\nMIRA guarda para notar mudancas.$"),
    LAB_PAIR("Your prediction matched.\nThese are fictional signal units.\pEnvironment changed the signal.\nThis did not change or test DNA.$", "Sua previsao combinou.\nSao unidades de sinal ficticias.\pO ambiente mudou o sinal.\nIsto nao muda nem testa o DNA.$"),
    LAB_PAIR("The result differs from your guess.\nKeep the comparison and learn.\pEnvironment changed the signal.\nThis did not change or test DNA.$", "O resultado difere da previsao.\nGuarde a comparacao e aprenda.\pO ambiente mudou o sinal.\nIsto nao muda nem testa o DNA.$"),
    LAB_PAIR("These lab notes cannot be read.\nNothing has been changed.$", "Nao foi possivel ler estas notas.\nNada foi alterado.$"),
    LAB_PAIR("ADA: Your sheltered assay helps\nme compare water more steadily.\pI remember your shared study.\nMIRA can still read the result.$", "ADA: Seu ensaio abrigado ajuda\na comparar a agua com firmeza.\pLembro do nosso estudo.\nMIRA ainda pode ler o resultado.$"),
    LAB_PAIR("ADA: Your exposed assay helps\nMIRA notice changing conditions.\pI use the old shelter guide.\nOur different work fits together.$", "ADA: Seu ensaio exposto ajuda\nMIRA a notar as mudancas.\pUso o guia de abrigo anterior.\nNossos trabalhos se completam.$"),
    LAB_PAIR("ADA: MIRA has a reader at the post.\nFirst compare the two waters\nwith your own companion.$", "ADA: MIRA tem um leitor no posto.\nPrimeiro compare as duas aguas\ncom seu proprio parceiro.$"),
};
static u16 LabRaw(void)
{
    const u8 *b = &gSaveBlock1Ptr->flags[HELIX_LAB_ITEMS_FIRST_FLAG / 8];
    return b[0] | (b[1] << 8);
}
static void LabWrite(u16 raw)
{
    gSaveBlock1Ptr->flags[HELIX_LAB_ITEMS_FIRST_FLAG / 8] = raw;
    gSaveBlock1Ptr->flags[HELIX_LAB_ITEMS_FIRST_FLAG / 8 + 1] = raw >> 8;
}
static u16 LabLocation(void)
{
    s16 x, y;
    if (gSaveBlock1Ptr->location.mapGroup != 75) return 0;
    GetXYCoordsOneStepInFrontOfPlayer(&x, &y);
    x -= 7; y -= 7;
    if (gSaveBlock1Ptr->location.mapNum == 2 && x == 4 && y == 5) return 1;
    if (gSaveBlock1Ptr->location.mapNum == 0 && x == 20 && y == 14) return 2;
    return 0;
}
void ClearHelixLabItemsPreview(void)
{
    gHelixLabItemsView.prepared = 0;
    gHelixLabItemsView.condition = 0;
    gHelixLabItemsView.prediction = 0;
    gHelixLabItemsView.menu = 0;
    sLabPreparedRaw = 0;
    sLabPreparedRecipe = 0;
    memset(&sLabPreparedMon, 0, sizeof(sLabPreparedMon));
}
void GetHelixLabItemsState(void)
{
    struct BoxPokemon mon;
    u16 raw = LabRaw(), condition = (raw >> 2) & 3, prediction = (raw >> 4) & 3;
    u16 species = 0;
    gHelixLabItemsView.raw = raw;
    gHelixLabItemsView.stage = raw == 0 ? 0 : 1;
    if (raw && raw != 0x7001 && raw != 0x7003
        && !((raw & 0xFF43) == 0x7043 && condition >= 1 && condition <= 2
             && prediction >= 1 && prediction <= 2))
        gHelixLabItemsView.stage = 0xFFFF;
    else if (raw & 0x40) gHelixLabItemsView.stage = 3;
    else if (raw == 0x7003) gHelixLabItemsView.stage = 2;
    gHelixLabItemsView.resident = raw && (raw & 2);
    gHelixLabItemsView.inspection = HelixSignalInspect(&mon);
    gHelixLabItemsView.recipe = 0;
    if (gHelixLabItemsView.inspection == HELIX_SIGNAL_READY
        || gHelixLabItemsView.inspection == HELIX_SIGNAL_BOXED
        || gHelixLabItemsView.inspection == HELIX_SIGNAL_FAINTED)
    {
        species = GetBoxMonData(&mon, MON_DATA_SPECIES);
        if (species == SPECIES_HELIX_FOUNDER_ONE) gHelixLabItemsView.recipe = 1;
        if (species == SPECIES_HELIX_FOUNDER_TWO) gHelixLabItemsView.recipe = 2;
    }
    if (gHelixLabItemsView.stage == 3 && gHelixLabItemsView.recipe
        && ((raw >> 7) & 1) + 1 != gHelixLabItemsView.recipe)
        gHelixLabItemsView.stage = 0xFFFF;
    gHelixLabItemsView.reader = CheckBagHasItem(ITEM_HELIX_READER, 1);
    gHelixLabItemsView.medium = CountTotalItemQuantityInBag(ITEM_HELIX_MEDIUM);
    if (gHelixLabItemsView.prepared && (raw != sLabPreparedRaw || LabLocation() != 1
        || gHelixLabItemsView.recipe != sLabPreparedRecipe
        || gHelixLabItemsView.inspection != HELIX_SIGNAL_READY
        || memcmp(&mon, &sLabPreparedMon, sizeof(mon)))) ClearHelixLabItemsPreview();
    if (gHelixLabItemsView.stage == 3)
    {
        gHelixLabItemsView.condition = condition;
        gHelixLabItemsView.prediction = prediction;
    }
    gSpecialVar_Result = gHelixLabItemsView.stage;
}
static bool32 LabReady(void)
{
    GetHelixRegionState();
    return gHelixRegionView.state == 15 && gHelixLabItemsView.reader
        && gHelixLabItemsView.medium && gHelixLabItemsView.recipe
        && gHelixLabItemsView.inspection == HELIX_SIGNAL_READY;
}
bool32 HelixLabItemsValidateRequest(u16 raw, u16 condition, u16 prediction)
{
    GetHelixLabItemsState();
    return gHelixLabItemsView.stage == 2 && raw == 0x7003
        && raw == sLabPreparedRaw && raw == gHelixLabItemsView.raw
        && condition >= 1 && condition <= 2 && prediction >= 1 && prediction <= 2
        && gHelixLabItemsView.prepared == 2 && condition == gHelixLabItemsView.condition
        && prediction == gHelixLabItemsView.prediction && LabLocation() == 1 && LabReady();
}
bool32 HelixLabItemsApplyResult(u16 raw, u16 condition, u16 prediction, u16 result)
{
    u16 next;
    if (result != condition || !HelixLabItemsValidateRequest(raw, condition, prediction)) return FALSE;
    next = 0x7043 | (condition << 2) | (prediction << 4) | ((sLabPreparedRecipe - 1) << 7);
    // Single synchronous native operation: no script/frame/save yield in between.
    // RemoveBagItem is atomic on insufficient quantity; result is receipt-only.
    if (!RemoveBagItem(ITEM_HELIX_MEDIUM, 1)) return FALSE;
    LabWrite(next);
    ClearHelixLabItemsPreview();
    GetHelixLabItemsState();
    return TRUE;
}
// 1 kit, 2 resident, 3/4 condition, 5/6 prediction. Never grants another kit.
void CommitHelixLabItemsAction(void)
{
    u16 action = gSpecialVar_0x8006;
    GetHelixLabItemsState();
    gSpecialVar_Result = 0;
    if (gHelixLabItemsView.stage == 0xFFFF) return;
    if (action == 1)
    {
        struct ItemSlot items[BAG_ITEMS_COUNT], keys[BAG_KEYITEMS_COUNT];
        if (LabLocation() != 1 || gHelixLabItemsView.stage != 0) return;
        GetHelixRegionState();
        gSpecialVar_Result = 0;
        if (gHelixRegionView.state != 15 || !CheckBagHasSpace(ITEM_HELIX_READER, 1)
            || !CheckBagHasSpace(ITEM_HELIX_MEDIUM, 1)) return;
        // Save encrypted pocket bytes, preserving encryption key and order exactly.
        memcpy(items, gSaveBlock1Ptr->bag.items, sizeof(items));
        memcpy(keys, gSaveBlock1Ptr->bag.keyItems, sizeof(keys));
        if (!AddBagItem(ITEM_HELIX_READER, 1) || !AddBagItem(ITEM_HELIX_MEDIUM, 1))
        {
            memcpy(gSaveBlock1Ptr->bag.items, items, sizeof(items));
            memcpy(gSaveBlock1Ptr->bag.keyItems, keys, sizeof(keys));
            return;
        }
        LabWrite(0x7001);
    }
    else if (action == 2)
    {
        if (LabLocation() != 2 || !gHelixLabItemsView.stage) return;
        if (gHelixLabItemsView.stage == 1) LabWrite(0x7003);
    }
    else if (action == 3 || action == 4)
    {
        ClearHelixLabItemsPreview();
        if (LabLocation() != 1 || gHelixLabItemsView.stage != 2 || !LabReady()) goto refused;
        sLabPreparedRaw = LabRaw();
        sLabPreparedRecipe = gHelixLabItemsView.recipe;
        if (HelixSignalInspect(&sLabPreparedMon) != HELIX_SIGNAL_READY) goto refused;
        gHelixLabItemsView.condition = action - 2;
        gHelixLabItemsView.prepared = 1;
    }
    else if (action == 5 || action == 6)
    {
        if (LabLocation() != 1 || gHelixLabItemsView.prepared != 1 || !LabReady()) goto refused;
        gHelixLabItemsView.prediction = action - 4;
        gHelixLabItemsView.prepared = 2;
    }
    else return;
    GetHelixLabItemsState();
    gSpecialVar_Result = 1;
    return;
refused:
    ClearHelixLabItemsPreview();
    gSpecialVar_Result = 0;
}
void BufferHelixLabItemsText(void)
{
    u16 page = gSpecialVar_0x8005, pt = gHelixSettingsView.language == 1;
    GetHelixLabItemsState();
    gHelixLabItemsView.phase = page;
    if (gHelixLabItemsView.stage == 0xFFFF) page = 18;
    else if (page == 11 && gHelixLabNativeLastResult == 2) page = 12;
    else if (page == 22) page = gHelixLabItemsView.condition == 2 ? 8 : 7;
    else if (page == 23) page = gHelixLabItemsView.stage == 3 ? 13 + gHelixLabItemsView.condition : 18;
    else if (page == 24) page = gHelixLabItemsView.stage == 3
        ? (gHelixLabItemsView.prediction == gHelixLabItemsView.condition ? 16 : 17) : 18;
    else if (page == 25) page = gHelixLabItemsView.stage == 3 ? 18 + gHelixLabItemsView.condition : 21;
    if (page >= ARRAY_COUNT(sLabPages)) page = 18;
    StringCopy(gStringVar4, sLabPages[page][pt]);
}
#define LAB_OPTION(s) {COMPOUND_STRING(s), {NULL}}
static const struct MenuAction sLabConditionEn[] = {LAB_OPTION("Sheltered"), LAB_OPTION("Exposed"), LAB_OPTION("Leave")};
static const struct MenuAction sLabConditionPt[] = {LAB_OPTION("Abrigo"), LAB_OPTION("Exposto"), LAB_OPTION("Sair")};
static const struct MenuAction sLabPredictionEn[] = {LAB_OPTION("Steadier signal"), LAB_OPTION("More response"), LAB_OPTION("Leave")};
static const struct MenuAction sLabPredictionPt[] = {LAB_OPTION("Sinal mais firme"), LAB_OPTION("Resposta maior"), LAB_OPTION("Sair")};
void ShowHelixLabItemsMenu(void)
{
    u16 menu = gSpecialVar_0x8007, pt = gHelixSettingsView.language == 1;
    GetHelixLabItemsState();
    gHelixLabItemsView.menu = menu;
    gSpecialVar_Result = 0xFF;
    DrawMultichoiceMenuInternal(0, 0, MULTI_BRINEY_ON_DEWFORD, FALSE, 0,
        menu == 2 ? (pt ? sLabPredictionPt : sLabPredictionEn) : (pt ? sLabConditionPt : sLabConditionEn), 3);
}
const u8 *HelixLabItemsItemName(u16 item)
{
    bool32 pt = gHelixSettingsView.language == 1;
    if (item == ITEM_HELIX_READER) return pt ? COMPOUND_STRING("Leitor Cultura") : COMPOUND_STRING("Culture Reader");
    if (item == ITEM_HELIX_MEDIUM) return pt ? COMPOUND_STRING("Meio Nanomon") : COMPOUND_STRING("Nanomon Medium");
    return NULL;
}
const u8 *HelixLabItemsItemDescription(u16 item)
{
    bool32 pt = gHelixSettingsView.language == 1;
    if (item == ITEM_HELIX_READER)
        return pt ? COMPOUND_STRING("Leitor reutilizavel.\nUse com MIRA no\nposto de pesquisa.")
                  : COMPOUND_STRING("Reusable reader.\nUse with MIRA at\nthe research post.");
    if (item == ITEM_HELIX_MEDIUM)
        return pt ? COMPOUND_STRING("Cultura ficticia.\nMIRA usa uma para\num ensaio no posto.")
                  : COMPOUND_STRING("Fictional culture.\nMIRA uses one for\na lab assay.");
    return NULL;
}

// Native offline execution. The retained LAB1 host channel is not consulted.
// Ninety frames are an explicit preparation/cancellation window, not compute time.
#define HELIX_LAB_NATIVE_PREPARE_FRAMES 90
static EWRAM_DATA struct
{
    u16 raw, condition, prediction;
    u8 trainerId[4];
    u8 namespace[12];
    u8 genesis[52];
} sLabNativeContext = {0};

static bool32 NativeLabContextMatches(void)
{
    return memcmp(sLabNativeContext.trainerId, gSaveBlock2Ptr->playerTrainerId, 4) == 0
        && memcmp(sLabNativeContext.namespace, gSaveBlock3Ptr->helixUniversal.namespace, 12) == 0
        && memcmp(sLabNativeContext.genesis, gSaveBlock1Ptr->filler1, 52) == 0
        && HelixLabItemsValidateRequest(sLabNativeContext.raw,
                                       sLabNativeContext.condition,
                                       sLabNativeContext.prediction);
}

static void FinishNativeLab(u8 taskId, u16 code)
{
    gHelixLabNativeLastResult = code; // 1 applied, 2 cancelled, 3 stale, 4 model error, 5 no task.
    gSpecialVar_Result = code == 1;
    memset(&sLabNativeContext, 0, sizeof(sLabNativeContext));
    DestroyTask(taskId);
    ScriptContext_Enable();
}

static void Task_HelixLabNativeSimulation(u8 taskId)
{
    struct HelixIndicatorAssayResult result;
    // Cancellation wins even on the final preparation frame.
    if (JOY_NEW(B_BUTTON)) { FinishNativeLab(taskId, 2); return; }
    if (!NativeLabContextMatches()) { FinishNativeLab(taskId, 3); return; }
    if (++gTasks[taskId].data[0] < HELIX_LAB_NATIVE_PREPARE_FRAMES) return;
    if (!HelixIndicatorAssay(sLabNativeContext.condition, sLabNativeContext.prediction, &result)
        || result.result != sLabNativeContext.condition
        || result.signal != (result.result == 1 ? 11 : 50)
        || result.span != (result.result == 1 ? 3 : 8) || result.control != 10)
    { FinishNativeLab(taskId, 4); return; }
    // Pure bounded integer evaluation above performs no yielding, networking or RNG.
    // Consumption and the unchanged v17 receipt still share one synchronous handler.
    if (!NativeLabContextMatches()
        || !HelixLabItemsApplyResult(sLabNativeContext.raw, sLabNativeContext.condition,
                                    sLabNativeContext.prediction, result.result))
    { FinishNativeLab(taskId, 3); return; }
    FinishNativeLab(taskId, 1);
}

void StartHelixLabNativeSimulation(void)
{
    u8 taskId;
    gSpecialVar_Result = 0;
    if (FuncIsActiveTask(Task_HelixLabNativeSimulation)) return;
    gHelixLabNativeLastResult = 3;
    if (!HelixLabItemsValidateRequest(gHelixLabItemsView.raw,
                                     gHelixLabItemsView.condition,
                                     gHelixLabItemsView.prediction))
    { gSpecialVar_Result = 0; return; }
    for (taskId = 0; taskId < NUM_TASKS && gTasks[taskId].isActive; taskId++);
    if (taskId == NUM_TASKS)
    { gHelixLabNativeLastResult = 5; gSpecialVar_Result = 0; return; }
    sLabNativeContext.raw = gHelixLabItemsView.raw;
    sLabNativeContext.condition = gHelixLabItemsView.condition;
    sLabNativeContext.prediction = gHelixLabItemsView.prediction;
    memcpy(sLabNativeContext.trainerId, gSaveBlock2Ptr->playerTrainerId, 4);
    memcpy(sLabNativeContext.namespace, gSaveBlock3Ptr->helixUniversal.namespace, 12);
    memcpy(sLabNativeContext.genesis, gSaveBlock1Ptr->filler1, 52);
    gHelixLabNativeLastResult = 0;
    CreateTask(Task_HelixLabNativeSimulation, 8);
    gSpecialVar_Result = 99; // Event script may now waitstate; refusal never waits.
}
