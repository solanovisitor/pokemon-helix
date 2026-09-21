#include "global.h"
#include <stddef.h>
#include "helix_region.h"
#include "helix_signal.h"
#include "helix_genesis.h"
#include "helix_settings.h"
#include "pokemon.h"
#include "event_data.h"
#include "string_util.h"
#include "text.h"
#include "constants/ai_bridge.h"
#include "constants/species.h"

// One previously unclaimed Emerald variable. All old identity/XP/quest records
// remain in place. Unknown nonzero values fail closed and are never rewritten.
#define FIELD_MAGIC 0x5200
#define FIELD_INVALID 0xFFFF
const u32 gHelixRegionSaveLayout[4] = {offsetof(struct SaveBlock1, vars), VAR_HELIX_FIELD_RESEARCH, 2, 1};
// Additive, explicitly recognized states; the original research low bits stay.
const u16 gHelixUtilityDescriptor[5] = {1, 0x521F, 0x523F, 0x525F, 6};
// Version 1 keeps the six-field utility view prefix; care is u16 at offset 12.
const u16 gHelixCareDescriptor[7] = {1, 0x527F, 0x529F, 0x52BF, 0x52DF, 8, 9};
EWRAM_DATA struct HelixRegionView gHelixRegionView = {0};

#define FIELD_PAIR(en, pt) {COMPOUND_STRING(en), COMPOUND_STRING(pt)}
static const u8 *const sFieldPages[][2] = {
    FIELD_PAIR("A field village lies nearby.\nIts trail has a small research post.\pWalk there with me?$", "Há uma vila de campo aqui perto.\nA trilha leva a um posto de pesquisa.\pVamos caminhar até lá?$"),
    FIELD_PAIR("The path leads back to OLDALE.\nWalk back with me?$", "O caminho volta para OLDALE.\nVamos caminhar de volta?$"),
    FIELD_PAIR("IVO kept your first discovery.\nNow, where does water stay still?\pCompare the trail's sheltered pool\nand its windy clearing together.\pStart these field notes?$", "IVO guardou sua primeira descoberta.\nAgora, onde a água fica parada?\pComparem o lago abrigado da trilha\ne a clareira com vento.\pComeçar estas notas de campo?$"),
    FIELD_PAIR("Find both markers on the trail:\nthe sheltered pool and windy clearing.\pUse the same tray at each place.\nThen compare your notes here.$", "Ache os dois marcos na trilha:\no lago abrigado e a clareira.\pUsem a mesma bandeja nos dois.\nDepois comparem as notas aqui.$"),
    FIELD_PAIR("Tall reeds shelter this pool.\nTry the water tray together?$", "Juncos altos abrigam este lago.\nTestar a bandeja de água juntos?$"),
    FIELD_PAIR("Wind crosses this open clearing.\nTry the water tray together?$", "O vento cruza esta clareira.\nTestar a bandeja de água juntos?$"),
    FIELD_PAIR("{STR_VAR_1} steps closer.\nYou both watch the water.$", "{STR_VAR_1} se aproxima.\nVocês observam a água juntos.$"),
    FIELD_PAIR("Behind the reeds, the water is still.\nThe tray stays in place.\pRecord the sheltered reading?$", "Atrás dos juncos, a água fica parada.\nA bandeja continua no lugar.\pAnotar a leitura do abrigo?$"),
    FIELD_PAIR("Gusts ripple the water here.\nYour companion keeps the tray steady.\pRecord the exposed reading?$", "As rajadas fazem ondas na água.\nSeu companheiro firma a bandeja.\pAnotar a leitura da clareira?$"),
    FIELD_PAIR("Observation saved in your notes.\nYou can leave and return later.$", "Observaçao salva nas suas notas.\nVocê pode sair e voltar depois.$"),
    FIELD_PAIR("Same tray. Same companion.\nOnly the surroundings changed.\pWas the sheltered water calmer?$", "Mesma bandeja. Mesmo companheiro.\nSó o ambiente mudou.\pA água abrigada ficou mais calma?$"),
    FIELD_PAIR("Check both notes: gusts made ripples;\nthe reeds kept the water still.\pYou can compare again whenever\nyou are ready.$", "Confira as notas: rajadas fazem ondas;\nos juncos deixam a água parada.\pVocê pode comparar de novo\nquando quiser.$"),
    FIELD_PAIR("Yes! Shelter changed the reading.\nYour companion's DNA did not change.\pKeep this finding in a field guide?$", "Isso! O abrigo mudou a leitura.\nO DNA do companheiro nao mudou.\pGuardar isto no guia de campo?$"),
    FIELD_PAIR("Field guide: shelter keeps water calm.\nChoose a sheltered spot to study it.\pYour companion kept the tray steady.\nYou learned how to work together.\pRead this guide here whenever needed.\nUse it in your next field study.$", "Guia: o abrigo deixa a água calma.\nEscolha um abrigo para estudá-la.\pSeu companheiro firmou a bandeja.\nVocês aprenderam a trabalhar juntos.\pLeia o guia aqui quando precisar.\nUse-o no próximo estudo de campo.$"),
    FIELD_PAIR("Take your time. Your saved notes stay.\nReturn whenever you are ready.$", "Tudo bem. Suas notas salvas ficam.\nVolte quando quiser.$"),
    FIELD_PAIR("Bring your first companion to help.\nYour family is unchanged.$", "Traga seu primeiro companheiro.\nSua família continua igual.$"),
    FIELD_PAIR("We study places with our companions.\nA small finding can help a village.\pThe post is north, along the trail.\nTake time to learn from yours.$", "Estudamos lugares com companheiros.\nUma descoberta pode ajudar a vila.\pO posto fica ao norte, pela trilha.\nObserve o seu com calma.$"),
    FIELD_PAIR("FIELD VILLAGE - research trail north.\nOLDALE - speak to the southern guide.$", "VILA DE CAMPO - trilha ao norte.\nOLDALE - fale com o guia ao sul.$"),
    FIELD_PAIR("First, finish IVO's light research\nin LITTLEROOT and tell him the result.\pYour earlier notes will stay.\nThen begin this new field study.$", "Primeiro, conclua a pesquisa de IVO\nem LITTLEROOT e conte o resultado.\pSuas notas antigas continuam salvas.\nDepois comece este estudo de campo.$"),
    FIELD_PAIR("These field notes cannot be read.\nNothing has been changed.$", "Nao foi possível ler estas notas.\nNada foi alterado.$"),
    FIELD_PAIR("Meet the researcher inside the post.\nFirst, choose a question together.$", "Fale com a pessoa no posto.\nPrimeiro, escolham uma pergunta.$"),
    FIELD_PAIR("This observation is already saved.\nCompare both readings at the post.$", "Esta observaçao já está salva.\nCompare as duas leituras no posto.$"),
    FIELD_PAIR("Your field question is recorded.\nVisit both markers on the trail.\pThe pool is sheltered by reeds.\nThe clearing is open to the wind.$", "Sua pergunta de campo está salva.\nVisite os dois marcos na trilha.\pJuncos abrigam o lago.\nA clareira fica exposta ao vento.$"),
    FIELD_PAIR("Gusts tip my seedling water tray.\nYour shelter guide could help!\pHelp me choose a sheltered place\nfor our village's watering bench?$", "O vento vira a água das minhas mudas.\nSeu guia de abrigo pode ajudar!\pVamos escolher um lugar abrigado\npara a bancada de rega da vila?$"),
    FIELD_PAIR("The wind tips my seedling water tray.\nFirst, keep a shelter guide at the post.\pBring that finding back to our village.\nWe can put it to work together.$", "O vento vira a água das minhas mudas.\nPrimeiro, guarde o guia no posto.\pTraga essa descoberta para a vila.\nVamos usá-la juntos.$"),
    FIELD_PAIR("Try the two marked spots in the village:\nthe house wall and the leafy hedge.\pBoth shelter water from the wind.\nChoose one with your companion.\pYou may move the same bench later.\nNothing is lost while you are away.$", "Teste os dois marcos da vila:\na parede da casa e a cerca viva.\pOs dois protegem a água do vento.\nEscolha um com seu companheiro.\pPode mover a mesma bancada depois.\nNada se perde quando você sai.$"),
    FIELD_PAIR("The house wall blocks the gusts.\nTest this work spot together?$", "A parede da casa barra as rajadas.\nTestar este lugar juntos?$"),
    FIELD_PAIR("The leafy hedge breaks the wind.\nTest this work spot together?$", "A cerca viva reduz o vento.\nTestar este lugar juntos?$"),
    FIELD_PAIR("{STR_VAR_1} steadies the tray.\nThe sheltered water stays calm.$", "{STR_VAR_1} firma a bandeja.\nA água abrigada fica calma.$"),
    FIELD_PAIR("The tray is steady in this shelter.\nSet up the watering bench here?$", "A bandeja fica firme neste abrigo.\nMontar a bancada de rega aqui?$"),
    FIELD_PAIR("This shelter works for the tray, too.\nMove our existing bench here?$", "Este abrigo também serve à bandeja.\nMover nossa bancada para cá?$"),
    FIELD_PAIR("The watering bench is by the wall!\nI can tend the seedlings here.\pYour guide and companion helped.\nYou can review the other spot later.$", "A bancada fica junto à parede!\nPosso cuidar das mudas aqui.\pSeu guia e companheiro ajudaram.\nPode rever o outro lugar depois.$"),
    FIELD_PAIR("The watering bench is by the hedge!\nI can tend the seedlings here.\pYour guide and companion helped.\nYou can review the other spot later.$", "A bancada fica junto à cerca viva!\nPosso cuidar das mudas aqui.\pSeu guia e companheiro ajudaram.\nPode rever o outro lugar depois.$"),
    FIELD_PAIR("No change. Our notes and bench stay.\nReturn whenever you want to help.$", "Nada mudou. Notas e bancada ficam.\nVolte quando quiser ajudar.$"),
    FIELD_PAIR("Our watering bench is already here.\nThe shelter keeps the tray steady.\pThe same bench serves the village.\nTry the other marker to move it.$", "Nossa bancada de rega já fica aqui.\nO abrigo mantém a bandeja firme.\pA mesma bancada serve à vila.\nUse o outro marco para movê-la.$"),
    FIELD_PAIR("Our seedlings have a sheltered bench!\nThank you and your companion.\pVisit either marker to review the spot.\nWe will keep using the same bench.$", "As mudas têm uma bancada abrigada!\nObrigado a você e ao seu companheiro.\pReveja o lugar em qualquer marco.\nVamos usar a mesma bancada.$"),
    FIELD_PAIR("Talk to the villager by the house.\nThey need a sheltered watering bench.$", "Fale com o morador perto da casa.\nEle precisa de uma bancada abrigada.$"),
    FIELD_PAIR("Our bench is ready for the seedlings.\nWill you help with their first watering?\pYou and your companion can help.\nAccept this small task?$", "A bancada está pronta para as mudas.\nVamos fazer a primeira rega?\pVocê e seu companheiro podem ajudar.\nAceitar esta tarefa?$"),
    FIELD_PAIR("Go to our installed bench.\nYour companion can steady the tray.\pYou can leave and return later.\nWe will wait until you are ready.$", "Vá até a bancada que montamos.\nSeu companheiro pode firmar a bandeja.\pPode sair e voltar depois.\nEsperaremos até você querer.$"),
    FIELD_PAIR("{STR_VAR_1} steadies the tray.\nThe water is ready for the seedlings.$", "{STR_VAR_1} firma a bandeja.\nA água está pronta para as mudas.$"),
    FIELD_PAIR("The tray is ready and steady.\nWater the seedlings together now?$", "A bandeja está pronta e firme.\nRegar as mudas juntos agora?$"),
    FIELD_PAIR("You water the seedlings together!\nYour companion keeps the tray steady.\pOur first watering is complete.\nThe villager will remember your help.$", "Vocês regam as mudas juntos!\nSeu companheiro firma a bandeja.\pNossa primeira rega está concluída.\nO morador vai lembrar da ajuda.$"),
    FIELD_PAIR("No watering yet. The bench stays.\nReturn whenever you want to help.$", "Ainda nao regamos. A bancada fica.\nVolte quando quiser ajudar.$"),
    FIELD_PAIR("You watered these seedlings together.\nYour companion kept the tray steady.\pThe first watering is already complete.\nThe other marker can move this bench.$", "Vocês regaram estas mudas juntos.\nSeu companheiro firmou a bandeja.\pA primeira rega já está concluída.\nO outro marco pode mover a bancada.$"),
    FIELD_PAIR("Thank you for watering our seedlings!\nI remember your companion's help.\pWe still use the same sheltered bench.\nYou can review it whenever you like.$", "Obrigado por regar nossas mudas!\nLembro da ajuda do seu companheiro.\pUsamos a mesma bancada abrigada.\nPode revê-la quando quiser.$"),
    FIELD_PAIR("This is our sheltered watering bench.\nPrepare the tray with your companion?$", "Esta é nossa bancada de rega abrigada.\nPreparar a bandeja juntos?$"),
    FIELD_PAIR("Our watering bench is already here.\nTalk to the villager about watering.\pThe other marker can move this bench.$", "Nossa bancada de rega já fica aqui.\nFale com o morador para ajudar na rega.\pO outro marco pode mover a bancada.$"),
};
static const u8 *const sCareNautil[2] = FIELD_PAIR(
    "{STR_VAR_1} steadies the tray.\nIts inherited paddle feet give support.\pYou prepare water for the seedlings.\nEverything is ready for your choice.$",
    "{STR_VAR_1} firma a bandeja.\nOs pés de nadadeira herdados ajudam.\pVocê prepara a água para as mudas.\nTudo está pronto para sua escolha.$");
static const u8 *const sCareFerro[2] = FIELD_PAIR(
    "{STR_VAR_1} steadies the tray.\nIts inherited long legs give support.\pYou prepare water for the seedlings.\nEverything is ready for your choice.$",
    "{STR_VAR_1} firma a bandeja.\nAs pernas longas herdadas ajudam.\pVocê prepara a água para as mudas.\nTudo está pronto para sua escolha.$");
static const u8 *const sUtilityNautil[2] = FIELD_PAIR(
    "{STR_VAR_1} steadies the tray.\nIts inherited paddle feet give support.\pTogether, you test the sheltered spot.\nThe water stays still for the seedlings.$",
    "{STR_VAR_1} firma a bandeja.\nOs pés de nadadeira herdados ajudam.\pJuntos, vocês testam este abrigo.\nA água das mudas fica parada.$");
static const u8 *const sUtilityFerro[2] = FIELD_PAIR(
    "{STR_VAR_1} steadies the tray.\nIts inherited long legs give support.\pTogether, you test the sheltered spot.\nThe water stays still for the seedlings.$",
    "{STR_VAR_1} firma a bandeja.\nAs pernas longas herdadas ajudam.\pJuntos, vocês testam este abrigo.\nA água das mudas fica parada.$");
static const u8 *const sFieldNautil[2] = FIELD_PAIR(
    "{STR_VAR_1} steps closer.\nIts paddle feet help steady the tray.\pYou both watch the water.\nIts familiar inherited feet help.$",
    "{STR_VAR_1} se aproxima.\nOs pés de nadadeira firmam a bandeja.\pVocês observam a água juntos.\nOs mesmos pés herdados ajudam.$");
static const u8 *const sFieldFerro[2] = FIELD_PAIR(
    "{STR_VAR_1} steps closer.\nIts long legs help steady the tray.\pYou both watch the water.\nIts familiar inherited legs help.$",
    "{STR_VAR_1} se aproxima.\nAs pernas longas firmam a bandeja.\pVocês observam a água juntos.\nAs mesmas pernas herdadas ajudam.$");
static const u8 *const sFieldBoxed[2] = FIELD_PAIR("Your companion is resting in the PC.\nWithdraw it to study together.$", "Seu companheiro descansa no PC.\nRetire-o para estudarem juntos.$");
static const u8 *const sFieldFainted[2] = FIELD_PAIR("Your companion needs care first.\nRest at the lab or POKéMON CENTER.$", "Seu companheiro precisa de cuidados.\nDescanse no lab ou CENTRO POKéMON.$");
static const u8 *const sFieldMissing[2] = FIELD_PAIR("Your companion could not be found.\nThe record stays; no copy is created.$", "Seu companheiro nao foi encontrado.\nO registro fica; nao criamos cópias.$");

static u16 FieldState(void)
{
    u16 raw = VarGet(VAR_HELIX_FIELD_RESEARCH);
    switch (raw)
    {
    case 0: return 0;
    case FIELD_MAGIC | 1:
    case FIELD_MAGIC | 3:
    case FIELD_MAGIC | 5:
    case FIELD_MAGIC | 7:
    case FIELD_MAGIC | 15:
    case 0x521F:
    case 0x523F:
    case 0x525F:
    case 0x527F:
    case 0x529F:
    case 0x52BF:
    case 0x52DF: return raw & 15;
    default: return FIELD_INVALID;
    }
}
void GetHelixRegionState(void)
{
    gHelixRegionView.raw = VarGet(VAR_HELIX_FIELD_RESEARCH);
    gHelixRegionView.state = FieldState();
    switch (gHelixRegionView.raw)
    {
    case 0x521F: gHelixRegionView.utility = 1; break;
    case 0x523F:
    case 0x527F:
    case 0x52BF: gHelixRegionView.utility = 2; break;
    case 0x525F:
    case 0x529F:
    case 0x52DF: gHelixRegionView.utility = 3; break;
    default: gHelixRegionView.utility = gHelixRegionView.state == FIELD_INVALID ? FIELD_INVALID : 0; break;
    }
    switch (gHelixRegionView.raw)
    {
    case 0x527F:
    case 0x529F: gHelixRegionView.care = 1; break;
    case 0x52BF:
    case 0x52DF: gHelixRegionView.care = 2; break;
    default: gHelixRegionView.care = gHelixRegionView.state == FIELD_INVALID ? FIELD_INVALID : 0; break;
    }
    gSpecialVar_Result = gHelixRegionView.state;
}
void GetHelixUtilityState(void)
{
    GetHelixRegionState();
    gSpecialVar_Result = gHelixRegionView.utility;
}
void GetHelixCareState(void)
{
    GetHelixRegionState();
    gSpecialVar_Result = gHelixRegionView.care;
}
static u16 InstalledWord(u16 utility, u16 care)
{
    // Opaque allowlisted words, not flags: moving the bench retains its care.
    static const u16 words[3][2] = {{0x523F, 0x525F}, {0x527F, 0x529F}, {0x52BF, 0x52DF}};
    if (utility < 2 || utility > 3 || care > 2) return FIELD_INVALID;
    return words[care][utility - 2];
}
void CheckHelixRegionCompanion(void)
{
    struct BoxPokemon mon;
    u16 ready = HelixSignalInspect(&mon);
    GetHelixRegionState();
    gHelixRegionView.inspection = ready;
    gHelixRegionView.recipe = 0;
    gSpecialVar_0x8009 = 0;
    if (ready == HELIX_SIGNAL_READY || ready == HELIX_SIGNAL_BOXED || ready == HELIX_SIGNAL_FAINTED)
    {
        u16 species = GetBoxMonData(&mon, MON_DATA_SPECIES);
        gSpecialVar_0x8009 = species;
        gHelixRegionView.recipe = species == SPECIES_HELIX_FOUNDER_TWO ? 2 : 1;
    }
    if (gHelixRegionView.state == FIELD_INVALID) ready = 7;
    else if (VarGet(VAR_SIGNAL_QUEST_STATE) != SIGNAL_QUEST_REPORTED) ready = 6;
    gSpecialVar_Result = ready;
}
void CommitHelixRegionAction(void)
{
    u16 state, next, action = gSpecialVar_0x8006;
    CheckHelixRegionCompanion();
    if (gSpecialVar_Result != HELIX_SIGNAL_READY) { gSpecialVar_Result = 0; return; }
    state = FieldState();
    if (action >= 5 && action <= 9)
    {
        u16 utility = gHelixRegionView.utility;
        u16 care = gHelixRegionView.care;
        if (state != 15 || (action != 5 && utility == 0)) { gSpecialVar_Result = 0; return; }
        if (action >= 8)
        {
            if (utility < 2 || (action == 9 && care == 0)) { gSpecialVar_Result = 0; return; }
            if ((action == 8 && care != 0) || (action == 9 && care == 2))
            { gSpecialVar_Result = 2; return; }
            next = InstalledWord(utility, action == 8 ? 1 : 2);
        }
        else next = action == 5 ? 0x521F : InstalledWord(action == 6 ? 2 : 3, care);
        if ((action == 5 && utility != 0) || VarGet(VAR_HELIX_FIELD_RESEARCH) == next)
        { gSpecialVar_Result = 2; return; }
        VarSet(VAR_HELIX_FIELD_RESEARCH, next);
        GetHelixRegionState();
        gSpecialVar_Result = 1;
        return;
    }
    next = state;
    switch (action)
    {
    case 1: if (state == 0) next = 1; break;
    case 2: if (state & 1) next |= 2; break;
    case 3: if (state & 1) next |= 4; break;
    case 4: if (state == 7) next = 15; break;
    default: gSpecialVar_Result = 0; return;
    }
    if (next == state) { gSpecialVar_Result = state == 15 || (state && action == 1) || (state & (action == 2 ? 2 : action == 3 ? 4 : 0)) ? 2 : 0; return; }
    VarSet(VAR_HELIX_FIELD_RESEARCH, FIELD_MAGIC | next);
    GetHelixRegionState();
    gSpecialVar_Result = 1;
}
void BufferHelixRegionText(void)
{
    struct BoxPokemon mon;
    u16 page = gSpecialVar_0x8005;
    u16 language = gHelixSettingsView.language == 1;
    u16 ready;
    const u8 *text;
    CheckHelixRegionCompanion();
    ready = gSpecialVar_Result;
    gHelixRegionView.phase = page;
    text = sFieldPages[page < ARRAY_COUNT(sFieldPages) ? page : 19][language];
    gStringVar1[0] = EOS;
    if (HelixSignalInspect(&mon) == HELIX_SIGNAL_READY)
        GetBoxMonData(&mon, MON_DATA_NICKNAME, gStringVar1);
    if (page == 6) text = gHelixRegionView.recipe == 2 ? sFieldFerro[language] : sFieldNautil[language];
    if (page == 28) text = gHelixRegionView.recipe == 2 ? sUtilityFerro[language] : sUtilityNautil[language];
    if (page == 39) text = gHelixRegionView.recipe == 2 ? sCareFerro[language] : sCareNautil[language];
    if (page == 15)
    {
        if (ready == 7) text = sFieldPages[19][language];
        else if (ready == 6) text = sFieldPages[18][language];
        else if (ready == HELIX_SIGNAL_BOXED) text = sFieldBoxed[language];
        else if (ready == HELIX_SIGNAL_FAINTED) text = sFieldFainted[language];
        else if (ready == HELIX_SIGNAL_MISSING) text = sFieldMissing[language];
    }
    StringExpandPlaceholders(gStringVar4, text);
}
