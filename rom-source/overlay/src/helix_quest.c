#include "global.h"
#include <stddef.h>
#include "helix_quest.h"
#include "helix_signal.h"
#include "helix_settings.h"
#include "pokemon.h"
#include "event_data.h"
#include "field_player_avatar.h"
#include "script_menu.h"
#include "string_util.h"
#include "text.h"
#include "constants/species.h"

// Flags 020..02F are permanent unused Emerald flags, outside both reset ranges.
// Do not reinterpret this save word in a future quest version.
const u32 gHelixQuestSaveLayout[4] = {offsetof(struct SaveBlock1, flags), HELIX_QUEST_FIRST_FLAG, 2, 2};
const u16 gHelixQuestDescriptor[6] = {1, HELIX_QUEST_MAGIC, HELIX_QUEST_MAGIC_MASK, HELIX_QUEST_FIRST_FLAG, 16, 2};
EWRAM_DATA struct HelixQuestView gHelixQuestView = {0};
static EWRAM_DATA u16 sPreparedRaw = 0;
STATIC_ASSERT(offsetof(struct HelixQuestView, recipe) == 20, HelixQuestRecipeOffset);
STATIC_ASSERT(sizeof(struct HelixQuestView) >= 22 && sizeof(struct HelixQuestView) <= 24, HelixQuestViewSize);
STATIC_ASSERT(HELIX_QUEST_FIRST_FLAG >= 0x20 && HELIX_QUEST_FIRST_FLAG + 15 < 0x920, HelixQuestPermanentFlags);

#define QUEST_PAIR(en, pt) {COMPOUND_STRING(en), COMPOUND_STRING(pt)}
// Authored copy of fixture revision 1. Third lines start a native second page.
static const u8 *const sQuestPages[][2] = {
    QUEST_PAIR("Guide: This arrow points away.\nI want a route people can read.\pWill you check it with me?$", "Guia: Esta seta aponta errado.\nQuero uma rota facil de ler.\pQuer investigar comigo?$"), // offer
    QUEST_PAIR("Guide: You can come back later.\nThe trail stays open.$", "Guia: Pode voltar depois.\nA trilha continua aberta.$"), // declined
    QUEST_PAIR("Check the sign and the post map.\nPick either place to start.$", "Veja a placa e o mapa do posto.\nComece por onde preferir.$"), // accepted
    QUEST_PAIR("Clue: Scratches circle the ring.\nThey do not prove who moved it.$", "Pista: Riscos cercam o anel.\nNao provam quem moveu a seta.$"), // clue_scratches
    QUEST_PAIR("Guide: I saw it face the post.\nA report, not proof of why.$", "Guia: Eu a vi mirar o posto.\nE um relato, nao prova a causa.$"), // clue_guide
    QUEST_PAIR("Map: The post is up the trail.\nSketch: The arrow has a ring.\pResearcher: I use it for wind.$", "Mapa: O posto fica pela trilha.\nDesenho: A seta tem um anel.\pPesquisador: Ela mede o vento.$"), // clue_reference
    QUEST_PAIR("Guess: The ring may be loose.\nA test could check that.$", "Ideia: O anel pode estar solto.\nUm teste pode conferir isso.$"), // hypothesis_joint
    QUEST_PAIR("Guess: Someone moved the arrow.\nThe marks cannot prove who.$", "Ideia: Alguem moveu a seta.\nOs riscos nao provam quem foi.$"), // hypothesis_moved
    QUEST_PAIR("NAUTIL braces with paddle feet.\nThe base stays still.\pWatch the upper arrow to test.$", "NAUTIL usa os pes de nadadeira.\nA base fica parada.\pObserve a seta para testar.$"), // nautil_prepare
    QUEST_PAIR("The base is still; arrow turns.\nFact: Loose ring lets it turn.\pWho moved it before is unknown.$", "Base parada; a seta gira.\nFato: Anel solto deixa girar.\pNao sabemos quem moveu antes.$"), // nautil_test
    QUEST_PAIR("FERRO braces the upper arm.\nLong legs hold it still.\pRelease and watch to test.$", "FERRO apoia o braco da seta.\nAs pernas longas o firmam.\pSolte e observe para testar.$"), // ferro_prepare
    QUEST_PAIR("On release, the arrow turns.\nFact: Loose ring lets it turn.\pWho moved it before is unknown.$", "Ao soltar, a seta volta a girar.\nFato: Anel solto deixa girar.\pNao sabemos quem moveu antes.$"), // ferro_test
    QUEST_PAIR("Your companion must be here\nand well to work on this sign.\pYou can keep exploring.$", "Seu parceiro precisa estar aqui\ne bem para mexer nesta placa.\pVoce pode seguir explorando.$"), // unavailable
    QUEST_PAIR("Check the sign and the post map.\nBoth help set up a fair test.$", "Veja a placa e o mapa do posto.\nOs dois ajudam a fazer o teste.$"), // need_clues
    QUEST_PAIR("Stopped. Your notes stay intact.\nNo fix was made.$", "Parou. Suas notas continuam.\nNenhum conserto foi feito.$"), // cancelled
    QUEST_PAIR("Notes kept. Return to the sign.\nBring your companion to test.$", "Notas mantidas. Volte a placa.\nTraga seu parceiro para testar.$"), // resume
    QUEST_PAIR("One clear sign or two cues?\nBoth keep the trail open.\pRead each plan before choosing.$", "Uma placa clara ou duas pistas?\nAs duas deixam a trilha aberta.\pLeia os planos antes de decidir.$"), // choose_solution
    QUEST_PAIR("Fix arrow: one clear direction.\nThis sign cannot sample wind.$", "Fixar seta: uma direcao clara.\nEsta placa deixa de medir vento.$"), // solution_lock
    QUEST_PAIR("Low route marker; free arrow.\nKeep wind readings, but read\ptwo cues instead of one.$", "Marco baixo; seta fica livre.\nMede vento, mas pede que leia\pdois sinais em vez de um.$"), // solution_split
    QUEST_PAIR("Result: Arrow faces the post.\nGuide: One clear route sign.\pResearcher: No wind sample here.$", "Resultado: Seta mira o posto.\nGuia: Uma placa de rota clara.\pPesquisador: Sem medir vento.$"), // result_lock
    QUEST_PAIR("Result: Low marker points ahead.\nResearcher: Wind arrow is free.\pGuide: Read the low marker.$", "Resultado: Marco mostra a rota.\nPesquisador: Seta gira livre.\pGuia: Leia o marco baixo.$"), // result_split
    QUEST_PAIR("Kept: One fixed route arrow.\nNo wind sample at this sign.$", "Guardado: Uma seta fixa de rota.\nSem medir vento nesta placa.$"), // hook_lock
    QUEST_PAIR("Kept: Route marker and wind arm.\nTwo cues share this place.$", "Guardado: Marco e seta de vento.\nDois sinais no mesmo lugar.$"), // hook_split

    QUEST_PAIR("These notes cannot be read.\nNothing has been changed.$", "Nao foi possivel ler as notas.\nNada foi alterado.$"), // 23 invalid
    QUEST_PAIR("Notes: No clue recorded yet.$", "Notas: Nenhuma pista anotada.$"), // 24 notes fallback
    QUEST_PAIR("The guide can explain this task.\nThe path stays open.$", "O guia explica esta tarefa.\nO caminho continua aberto.$"), // 25 not started
    QUEST_PAIR("Test the ring with your companion\nbefore choosing a change.$", "Teste o anel com seu parceiro\nantes de escolher uma mudanca.$"), // 26 need test
};
static const u8 *const sNotesHeader[2] = QUEST_PAIR("NOTES - THE SIGN AND THE WIND$", "NOTAS - A SETA E O VENTO$");
static const u8 *const sNotesScratches[2] = QUEST_PAIR("Clue: Scratches circle the ring.\nThey do not prove who moved it.$", "Pista: Riscos cercam o anel.\nNao provam quem moveu a seta.$");
static const u8 *const sNotesReference[2] = QUEST_PAIR("Reference: The post is north.\nThe arrow has a ring.$", "Referencia: O posto fica a norte.\nA seta tem um anel.$");
static const u8 *const sNotesGuide[2] = QUEST_PAIR("Report: Guide saw it face north.\nThe cause is still unknown.$", "Relato: Guia a viu mirar o norte.\nA causa ainda e desconhecida.$");
static const u8 *const sNotesGround[2] = QUEST_PAIR("Test kept: NAUTIL held the base.\nThe upper arrow still turned.$", "Teste: NAUTIL segurou a base.\nA seta de cima ainda girou.$");
static const u8 *const sNotesRaised[2] = QUEST_PAIR("Test kept: FERRO held the arm.\nOn release, the arrow turned.$", "Teste: FERRO segurou o braco.\nAo soltar, a seta voltou a girar.$");
static const u8 *const sNotesFact[2] = QUEST_PAIR("Fact: Loose ring lets it turn.\nThe earlier cause is unknown.$", "Fato: Anel solto deixa girar.\nA causa anterior e desconhecida.$");

static u16 QuestRaw(void)
{
    const u8 *bytes = &gSaveBlock1Ptr->flags[HELIX_QUEST_FIRST_FLAG / 8];
    return bytes[0] | (bytes[1] << 8);
}

static void DecodeQuest(u16 raw)
{
    gHelixQuestView.raw = raw;
    gHelixQuestView.stage = 0;
    gHelixQuestView.clues = 0;
    gHelixQuestView.hypothesis = 0;
    gHelixQuestView.method = 0;
    gHelixQuestView.resolution = 0;
    if (raw == 0) return;
    gHelixQuestView.clues = raw & 7;
    gHelixQuestView.hypothesis = (raw >> 3) & 3;
    gHelixQuestView.method = (raw >> 5) & 3;
    gHelixQuestView.resolution = (raw >> 7) & 3;
    if ((raw & HELIX_QUEST_MAGIC_MASK) != HELIX_QUEST_MAGIC
        || gHelixQuestView.hypothesis > 2 || gHelixQuestView.method > 2
        || gHelixQuestView.resolution > 2
        || (gHelixQuestView.method && (gHelixQuestView.clues & 3) != 3)
        || (gHelixQuestView.resolution && !gHelixQuestView.method))
        gHelixQuestView.stage = HELIX_QUEST_INVALID;
    else gHelixQuestView.stage = gHelixQuestView.resolution ? 3 : gHelixQuestView.method ? 2 : 1;
}

// The shared sign script is also used at (18,23); never redirect that sign.
static u16 QuestLocation(void)
{
    s16 x, y;
    if (gSaveBlock1Ptr->location.mapGroup != 75) return 0;
    GetXYCoordsOneStepInFrontOfPlayer(&x, &y);
    if (gSaveBlock1Ptr->location.mapNum == 0)
    {
        if (x == 14 + 7 && y == 24 + 7) return 1;
        if (x == 18 + 7 && y == 3 + 7) return 3;
    }
    if (gSaveBlock1Ptr->location.mapNum == 2 && x == 6 + 7 && y == 3 + 7) return 2;
    return 0;
}

void GetHelixQuestLocation(void)
{
    gSpecialVar_Result = QuestLocation();
}

void ClearHelixQuestPreview(void)
{
    gHelixQuestView.prepared = 0;
    gHelixQuestView.menu = 0;
    sPreparedRaw = 0;
}

void GetHelixQuestState(void)
{
    struct BoxPokemon copy;
    u16 species = 0;
    DecodeQuest(QuestRaw());
    gHelixQuestView.inspection = HelixSignalInspect(&copy);
    gHelixQuestView.recipe = 0;
    if (gHelixQuestView.inspection == HELIX_SIGNAL_READY
        || gHelixQuestView.inspection == HELIX_SIGNAL_BOXED
        || gHelixQuestView.inspection == HELIX_SIGNAL_FAINTED)
    {
        species = GetBoxMonData(&copy, MON_DATA_SPECIES);
        if (species == SPECIES_HELIX_FOUNDER_ONE) gHelixQuestView.recipe = 1;
        else if (species == SPECIES_HELIX_FOUNDER_TWO) gHelixQuestView.recipe = 2;
        else gHelixQuestView.inspection = HELIX_SIGNAL_INVALID;
    }
    if (gHelixQuestView.method && gHelixQuestView.recipe
        && gHelixQuestView.method != gHelixQuestView.recipe)
        gHelixQuestView.stage = HELIX_QUEST_INVALID;
    if (gHelixQuestView.prepared && (gHelixQuestView.stage != 1
        || gHelixQuestView.raw != sPreparedRaw || QuestLocation() != 3
        || gHelixQuestView.inspection != HELIX_SIGNAL_READY
        || gHelixQuestView.prepared != gHelixQuestView.recipe))
        ClearHelixQuestPreview();
    gSpecialVar_0x8009 = species;
    gSpecialVar_0x8008 = gHelixQuestView.clues;
    gSpecialVar_0x800A = gHelixQuestView.inspection;
    gSpecialVar_Result = gHelixQuestView.stage;
}

void CommitHelixQuestAction(void)
{
    u16 action = gSpecialVar_0x8006;
    u16 location = QuestLocation();
    u16 next, bit = 0;
    GetHelixQuestState();
    gSpecialVar_Result = 0;
    if (gHelixQuestView.stage == HELIX_QUEST_INVALID) goto refused;
    next = gHelixQuestView.raw;
    if (action == HELIX_QUEST_ACCEPT)
    {
        if (location != 1) goto refused;
        if (!next) next = HELIX_QUEST_MAGIC;
    }
    else if (action >= HELIX_QUEST_SCRATCHES && action <= HELIX_QUEST_GUIDE_REPORT)
    {
        if (action == HELIX_QUEST_SCRATCHES) { if (location != 3) goto refused; bit = 1; }
        if (action == HELIX_QUEST_REFERENCE) { if (location != 2) goto refused; bit = 2; }
        if (action == HELIX_QUEST_GUIDE_REPORT) { if (location != 1) goto refused; bit = 4; }
        if (gHelixQuestView.stage == 1 || gHelixQuestView.stage == 2) next |= bit;
        // Exploration before acceptance, or completed replay, records no new past.
    }
    else if (action == HELIX_QUEST_HYPOTHESIS_JOINT || action == HELIX_QUEST_HYPOTHESIS_MOVED)
    {
        if (location != 1 || gHelixQuestView.stage != 1) goto refused;
        next = (next & ~0x18) | ((action - HELIX_QUEST_HYPOTHESIS_JOINT + 1) << 3);
    }
    else if (action >= HELIX_QUEST_PREPARE && action <= HELIX_QUEST_SPLIT)
    {
        if (location != 3 || !gHelixQuestView.stage) goto refused;
        if (action >= HELIX_QUEST_LOCK && gHelixQuestView.resolution == action - HELIX_QUEST_LOCK + 1)
        { ClearHelixQuestPreview(); gSpecialVar_Result = 2; return; }
        if (gHelixQuestView.stage == 3 || gHelixQuestView.inspection != HELIX_SIGNAL_READY
            || !gHelixQuestView.recipe) goto refused;
        if (action == HELIX_QUEST_PREPARE || action == HELIX_QUEST_OBSERVE)
        {
            if (gHelixQuestView.stage != 1 || (gHelixQuestView.clues & 3) != 3) goto refused;
            if (action == HELIX_QUEST_PREPARE)
            {
                sPreparedRaw = next;
                gHelixQuestView.prepared = gHelixQuestView.recipe;
                gSpecialVar_Result = 1;
                return;
            }
            if (gHelixQuestView.prepared != gHelixQuestView.recipe || sPreparedRaw != next) goto refused;
            next |= gHelixQuestView.recipe << 5;
        }
        else
        {
            if (gHelixQuestView.stage != 2) goto refused;
            next |= (action - HELIX_QUEST_LOCK + 1) << 7;
        }
    }
    else goto refused;
    ClearHelixQuestPreview();
    if (next == gHelixQuestView.raw) { gSpecialVar_Result = 2; return; }
    // No other field is written. Ordinary Save commits this word with the game.
    gSaveBlock1Ptr->flags[HELIX_QUEST_FIRST_FLAG / 8] = next;
    gSaveBlock1Ptr->flags[HELIX_QUEST_FIRST_FLAG / 8 + 1] = next >> 8;
    GetHelixQuestState();
    gSpecialVar_Result = 1;
    return;
refused:
    ClearHelixQuestPreview();
    gSpecialVar_Result = 0;
}

static void AppendQuestNote(const u8 *text)
{
    StringAppend(gStringVar4, COMPOUND_STRING("\p"));
    StringAppend(gStringVar4, text);
}

static void BufferQuestNotes(u16 language)
{
    StringCopy(gStringVar4, sNotesHeader[language]);
    if (!gHelixQuestView.stage)
    { AppendQuestNote(sQuestPages[HELIX_QUEST_PAGE_NOT_STARTED][language]); return; }
    if (gHelixQuestView.clues & 1) AppendQuestNote(sNotesScratches[language]);
    if (gHelixQuestView.clues & 2) AppendQuestNote(sNotesReference[language]);
    if (gHelixQuestView.clues & 4) AppendQuestNote(sNotesGuide[language]);
    if (gHelixQuestView.hypothesis) AppendQuestNote(sQuestPages[5 + gHelixQuestView.hypothesis][language]);
    if (gHelixQuestView.method)
    {
        AppendQuestNote(gHelixQuestView.method == 1 ? sNotesGround[language] : sNotesRaised[language]);
        AppendQuestNote(sNotesFact[language]);
    }
    if (gHelixQuestView.resolution)
        AppendQuestNote(sQuestPages[18 + gHelixQuestView.resolution][language]);
    else if (gHelixQuestView.method)
    {
        AppendQuestNote(sQuestPages[HELIX_QUEST_PAGE_CHOOSE][language]);
        AppendQuestNote(sQuestPages[HELIX_QUEST_PAGE_LOCK_PLAN][language]);
        AppendQuestNote(sQuestPages[HELIX_QUEST_PAGE_SPLIT_PLAN][language]);
    }
    else AppendQuestNote(sQuestPages[(gHelixQuestView.clues & 3) == 3 ? HELIX_QUEST_PAGE_RESUME : HELIX_QUEST_PAGE_NEED_CLUES][language]);
}

void BufferHelixQuestText(void)
{
    u16 page = gSpecialVar_0x8005;
    u16 language = gHelixSettingsView.language == 1;
    GetHelixQuestState();
    gHelixQuestView.phase = page;
    if (gHelixQuestView.stage == HELIX_QUEST_INVALID) page = HELIX_QUEST_PAGE_INVALID;
    if (page == HELIX_QUEST_PAGE_NOTES)
    {
        ClearHelixQuestPreview();
        BufferQuestNotes(language);
        return;
    }
    if (page == HELIX_QUEST_PAGE_PREPARE || page == HELIX_QUEST_PAGE_NAUTIL_PREPARE || page == HELIX_QUEST_PAGE_FERRO_PREPARE)
        page = gHelixQuestView.prepared ? (gHelixQuestView.recipe == 2 ? HELIX_QUEST_PAGE_FERRO_PREPARE : HELIX_QUEST_PAGE_NAUTIL_PREPARE) : HELIX_QUEST_PAGE_UNAVAILABLE;
    if (page == HELIX_QUEST_PAGE_TEST || page == HELIX_QUEST_PAGE_NAUTIL_TEST || page == HELIX_QUEST_PAGE_FERRO_TEST)
        page = gHelixQuestView.method ? (gHelixQuestView.method == 2 ? HELIX_QUEST_PAGE_FERRO_TEST : HELIX_QUEST_PAGE_NAUTIL_TEST) : HELIX_QUEST_PAGE_NEED_TEST;
    if (page == HELIX_QUEST_PAGE_RESULT || page == HELIX_QUEST_PAGE_LOCK_RESULT || page == HELIX_QUEST_PAGE_SPLIT_RESULT)
        page = gHelixQuestView.resolution ? 18 + gHelixQuestView.resolution : HELIX_QUEST_PAGE_NEED_TEST;
    if (page >= ARRAY_COUNT(sQuestPages)) page = HELIX_QUEST_PAGE_INVALID;
    StringCopy(gStringVar4, sQuestPages[page][language]);
}

// Standard Emerald menus, native B cancellation, no additional task/heap owner.
#define QUEST_OPTION(s) {COMPOUND_STRING(s), {NULL}}
static const struct MenuAction sGuideEn[] = {QUEST_OPTION("Travel"), QUEST_OPTION("Arrow quest"), QUEST_OPTION("Notes"), QUEST_OPTION("Leave")};
static const struct MenuAction sGuidePt[] = {QUEST_OPTION("Viajar"), QUEST_OPTION("Tarefa da seta"), QUEST_OPTION("Notas"), QUEST_OPTION("Sair")};
static const struct MenuAction sPostEn[] = {QUEST_OPTION("Field research"), QUEST_OPTION("Arrow reference"), QUEST_OPTION("Notes"), QUEST_OPTION("Leave")};
static const struct MenuAction sPostPt[] = {QUEST_OPTION("Pesquisa de campo"), QUEST_OPTION("Referencia da seta"), QUEST_OPTION("Notas"), QUEST_OPTION("Sair")};
static const struct MenuAction sSignEn[] = {QUEST_OPTION("Directions"), QUEST_OPTION("Inspect ring"), QUEST_OPTION("Test together"), QUEST_OPTION("Choose solution"), QUEST_OPTION("Notes"), QUEST_OPTION("Leave")};
static const struct MenuAction sSignPt[] = {QUEST_OPTION("Direcoes"), QUEST_OPTION("Ver anel"), QUEST_OPTION("Testar juntos"), QUEST_OPTION("Escolher solucao"), QUEST_OPTION("Notas"), QUEST_OPTION("Sair")};
static const struct MenuAction sTestEn[] = {QUEST_OPTION("Observe arrow"), QUEST_OPTION("Stop")};
static const struct MenuAction sTestPt[] = {QUEST_OPTION("Observar seta"), QUEST_OPTION("Parar")};
static const struct MenuAction sReleaseEn[] = {QUEST_OPTION("Release and watch"), QUEST_OPTION("Stop")};
static const struct MenuAction sReleasePt[] = {QUEST_OPTION("Soltar e observar"), QUEST_OPTION("Parar")};
static const struct MenuAction sHypothesisEn[] = {QUEST_OPTION("Loose ring"), QUEST_OPTION("Someone moved it"), QUEST_OPTION("Keep my idea")};
static const struct MenuAction sHypothesisPt[] = {QUEST_OPTION("Anel solto"), QUEST_OPTION("Alguem moveu"), QUEST_OPTION("Manter minha ideia")};
static const struct MenuAction sSolutionEn[] = {QUEST_OPTION("Fix arrow"), QUEST_OPTION("Add low marker"), QUEST_OPTION("Leave")};
static const struct MenuAction sSolutionPt[] = {QUEST_OPTION("Fixar seta"), QUEST_OPTION("Por marco baixo"), QUEST_OPTION("Sair")};

void ShowHelixQuestMenu(void)
{
    u16 menu = gSpecialVar_0x8007;
    bool32 pt = gHelixSettingsView.language == 1;
    const struct MenuAction *actions = pt ? sGuidePt : sGuideEn;
    u16 count = 4;
    GetHelixQuestState();
    gHelixQuestView.menu = menu;
    switch (menu)
    {
    case HELIX_QUEST_MENU_GUIDE: break;
    case HELIX_QUEST_MENU_POST: actions = pt ? sPostPt : sPostEn; break;
    case HELIX_QUEST_MENU_SIGN: actions = pt ? sSignPt : sSignEn; count = 6; break;
    case HELIX_QUEST_MENU_TEST:
        actions = gHelixQuestView.recipe == 2 ? (pt ? sReleasePt : sReleaseEn) : (pt ? sTestPt : sTestEn);
        count = 2; break;
    case HELIX_QUEST_MENU_HYPOTHESIS: actions = pt ? sHypothesisPt : sHypothesisEn; count = 3; break;
    case HELIX_QUEST_MENU_SOLUTION: actions = pt ? sSolutionPt : sSolutionEn; count = 3; break;
    default: actions = pt ? &sGuidePt[3] : &sGuideEn[3]; count = 1; break;
    }
    gSpecialVar_Result = 0xFF;
    DrawMultichoiceMenuInternal(0, 0, MULTI_BRINEY_ON_DEWFORD, FALSE, 0, actions, count);
}
