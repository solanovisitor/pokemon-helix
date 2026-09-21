#include "global.h"
#include <stddef.h>
#include "helix_expansion.h"
#include "helix_signal.h"
#include "helix_settings.h"
#include "pokemon.h"
#include "event_data.h"
#include "field_player_avatar.h"
#include "script_menu.h"
#include "string_util.h"
#include "constants/species.h"

// Emerald permanent unused flags, outside temporary/daily reset ranges.
// V1 receipt is append-only and independent of the older sign/care quests.
const u32 gHelixExpansionSaveLayout[4] = {offsetof(struct SaveBlock1, flags), 0x30, 2, 2};
const u16 gHelixExpansionDescriptor[6] = {1, 0x6000, 0xFFC0, 0x30, 16, 2};
EWRAM_DATA struct HelixExpansionView gHelixExpansionView = {0};
static EWRAM_DATA u16 sExpansionPreparedRaw = 0;
STATIC_ASSERT(offsetof(struct HelixExpansionView, recipe) == 18, HelixExpansionRecipeOffset);
#define EXP_PAIR(en, pt) {COMPOUND_STRING(en), COMPOUND_STRING(pt)}
static const u8 *const sExpansionPages[][2] = {
    EXP_PAIR("Guide: The Quiet Garden is east.\nWalk there with me?$", "Guia: O Jardim da Vazante e ali.\nQuer ir comigo?$"),
    EXP_PAIR("Guide: Return to Shelter Trail?$", "Guia: Voltar a Trilha Abrigo?$"),
    EXP_PAIR("LIA: Leaves reach my seedlings.\nTOM needs a clear water edge.\pWill you help us choose a screen?$", "LIA: Folhas chegam as mudas.\nTOM precisa ver a beira da agua.\pAjuda a escolher onde por tela?$"),
    EXP_PAIR("LIA: Come back when you wish.\nThe whole garden stays open.$", "LIA: Volte quando quiser.\nO jardim inteiro fica aberto.$"),
    EXP_PAIR("Check the sheltered bed west,\nthen the channel mouth east.\pEither order is fine.$", "Veja o canteiro abrigado a oeste\ne a entrada do canal a leste.\pPode comecar por qualquer um.$"),
    EXP_PAIR("Clue: Wet leaves line this bed.\nWind or water brought them?\pThe marks alone cannot tell.$", "Pista: Folhas molhadas na borda.\nVieram pelo vento ou pela agua?\pAs marcas nao dizem a causa.$"),
    EXP_PAIR("Clue: A shallow channel leads\nfrom this mouth to the bed.\pThat does not prove it flows now.$", "Pista: Um canal raso liga esta\nentrada ao canteiro.\pNao prova que a agua corre agora.$"),
    EXP_PAIR("TOM: I watch leaves drift here.\nA screen at the bed hides them.\pAt the mouth, it narrows access.$", "TOM: Observo folhas boiando aqui.\nTela no canteiro cobre a vista.\pNa entrada, estreita o acesso.$"),
    EXP_PAIR("NAUTIL braces the low tray\nwith its paddle feet.\pFloat one fallen leaf to test?$", "NAUTIL firma a bandeja baixa\ncom seus pes de nadadeira.\pSoltar uma folha para testar?$"),
    EXP_PAIR("FERRO supports the raised tray\nwith its long legs.\pLower one fallen leaf to test?$", "FERRO apoia a bandeja alta\ncom suas pernas longas.\pBaixar uma folha para testar?$"),
    EXP_PAIR("The leaf follows the water\nfrom the mouth to the bed.\pFact: The channel carries leaves.$", "A folha acompanha a agua\nda entrada ate o canteiro.\pFato: O canal carrega folhas.$"),
    EXP_PAIR("Bed screen: easy access stays.\nLeaves stop before the seedlings.\pTOM loses this clear water view.$", "Tela no canteiro: acesso livre.\nFolhas param antes das mudas.\pTOM perde a vista da agua aqui.$"),
    EXP_PAIR("Mouth screen: clear bed view.\nLeaves stop at the channel mouth.\pVisitors must walk around it.$", "Tela na entrada: vista livre.\nFolhas param na boca do canal.\pVisitantes precisam contorna-la.$"),
    EXP_PAIR("Kept: Screen beside the bed.\nLIA: The access stays simple.\pTOM: I cannot watch leaves here.$", "Guardado: Tela junto ao canteiro.\nLIA: O acesso continua simples.\pTOM: Nao vejo folhas aqui.$"),
    EXP_PAIR("Kept: Screen at the mouth.\nTOM: The bed stays in view.\pLIA: We walk around the screen.$", "Guardado: Tela na entrada.\nTOM: A vista continua livre.\pLIA: Contornamos a tela.$"),
    EXP_PAIR("Stopped. Your notes stay.\nNo screen has been placed.$", "Parou. Suas notas continuam.\nNenhuma tela foi colocada.$"),
    EXP_PAIR("Your companion must be here\nand well for this test.\pYou can keep exploring.$", "Seu parceiro precisa estar aqui\ne bem para fazer o teste.\pVoce pode seguir explorando.$"),
    EXP_PAIR("Read both water-edge clues.\nThen meet at the test board.$", "Veja as duas pistas na beira.\nDepois volte ao quadro de teste.$"),
    EXP_PAIR("Test the channel together\nbefore placing a screen.$", "Testem o canal juntos\nantes de colocar uma tela.$"),
    EXP_PAIR("These notes cannot be read.\nNothing has been changed.$", "Nao foi possivel ler as notas.\nNada foi alterado.$"),
    EXP_PAIR("LIA can explain the problem.\nYou may explore at any time.$", "LIA explica o problema.\nVoce pode explorar quando quiser.$"),
    EXP_PAIR("Notes kept: both clues read.\nBring your companion to the board.$", "Notas: As duas pistas foram lidas.\nTraga seu parceiro ao quadro.$"),
};
static u16 ExpansionRaw(void)
{
    const u8 *b = &gSaveBlock1Ptr->flags[6];
    return b[0] | (b[1] << 8);
}
static u16 ExpansionLocation(void)
{
    s16 x, y;
    if (gSaveBlock1Ptr->location.mapGroup != 75 || gSaveBlock1Ptr->location.mapNum != 3) return 0;
    GetXYCoordsOneStepInFrontOfPlayer(&x, &y);
    x -= 7; y -= 7;
    if (x == 7 && y == 14) return 1; // LIA
    if (x == 5 && y == 11) return 2; // bed clue
    if (x == 15 && y == 5) return 3; // mouth clue
    if (x == 10 && y == 10) return 4; // test board
    if (x == 15 && y == 8) return 5; // TOM
    return 0;
}
void ClearHelixExpansionPreview(void)
{
    gHelixExpansionView.prepared = 0;
    gHelixExpansionView.menu = 0;
    sExpansionPreparedRaw = 0;
}
void GetHelixExpansionState(void)
{
    struct BoxPokemon copy;
    u16 raw = ExpansionRaw(), species = 0;
    gHelixExpansionView.raw = raw;
    gHelixExpansionView.clues = raw & 3;
    gHelixExpansionView.method = (raw >> 2) & 3;
    gHelixExpansionView.resolution = (raw >> 4) & 3;
    gHelixExpansionView.stage = raw ? 1 : 0;
    if (raw && ((raw & 0xFFC0) != 0x6000
        || gHelixExpansionView.method == 3 || gHelixExpansionView.resolution == 3
        || (gHelixExpansionView.method && gHelixExpansionView.clues != 3)
        || (gHelixExpansionView.resolution && !gHelixExpansionView.method)))
        gHelixExpansionView.stage = 0xFFFF;
    else if (gHelixExpansionView.resolution) gHelixExpansionView.stage = 3;
    else if (gHelixExpansionView.method) gHelixExpansionView.stage = 2;
    gHelixExpansionView.inspection = HelixSignalInspect(&copy);
    gHelixExpansionView.recipe = 0;
    if (gHelixExpansionView.inspection == HELIX_SIGNAL_READY
        || gHelixExpansionView.inspection == HELIX_SIGNAL_BOXED
        || gHelixExpansionView.inspection == HELIX_SIGNAL_FAINTED)
    {
        species = GetBoxMonData(&copy, MON_DATA_SPECIES);
        if (species == SPECIES_HELIX_FOUNDER_ONE) gHelixExpansionView.recipe = 1;
        else if (species == SPECIES_HELIX_FOUNDER_TWO) gHelixExpansionView.recipe = 2;
        else gHelixExpansionView.inspection = HELIX_SIGNAL_INVALID;
    }
    if (gHelixExpansionView.method && gHelixExpansionView.recipe
        && gHelixExpansionView.method != gHelixExpansionView.recipe)
        gHelixExpansionView.stage = 0xFFFF;
    if (gHelixExpansionView.prepared && (ExpansionLocation() != 4
        || gHelixExpansionView.stage != 1 || raw != sExpansionPreparedRaw
        || gHelixExpansionView.prepared != gHelixExpansionView.recipe
        || gHelixExpansionView.inspection != HELIX_SIGNAL_READY)) ClearHelixExpansionPreview();
    gSpecialVar_0x8008 = gHelixExpansionView.clues;
    gSpecialVar_0x8009 = species;
    gSpecialVar_0x800A = gHelixExpansionView.inspection;
    gSpecialVar_Result = gHelixExpansionView.stage;
}
void GetHelixExpansionLayout(void)
{
    GetHelixExpansionState();
    gSpecialVar_Result = gHelixExpansionView.stage == 3 ? gHelixExpansionView.resolution : 0;
}
// Action 1 accept; 2/3 clues; 4 prepare; 5 observe; 6 bed; 7 mouth.
void CommitHelixExpansionAction(void)
{
    u16 action = gSpecialVar_0x8006, location = ExpansionLocation(), next;
    GetHelixExpansionState();
    gSpecialVar_Result = 0;
    next = gHelixExpansionView.raw;
    if (gHelixExpansionView.stage == 0xFFFF) goto refused;
    if (action == 1)
    {
        if (location != 1) goto refused;
        if (!next) next = 0x6000;
    }
    else if (action == 2 || action == 3)
    {
        if (location != action) goto refused;
        if (gHelixExpansionView.stage == 1) next |= 1 << (action - 2);
    }
    else if (action >= 4 && action <= 7)
    {
        if (location != 4 || !gHelixExpansionView.stage) goto refused;
        if (action >= 6 && gHelixExpansionView.resolution == action - 5)
        { ClearHelixExpansionPreview(); gSpecialVar_Result = 2; return; }
        if (gHelixExpansionView.inspection != HELIX_SIGNAL_READY || !gHelixExpansionView.recipe) goto refused;
        if (action <= 5)
        {
            if (gHelixExpansionView.stage != 1 || gHelixExpansionView.clues != 3) goto refused;
            if (action == 4)
            {
                sExpansionPreparedRaw = next;
                gHelixExpansionView.prepared = gHelixExpansionView.recipe;
                gSpecialVar_Result = 1;
                return;
            }
            if (gHelixExpansionView.prepared != gHelixExpansionView.recipe || sExpansionPreparedRaw != next) goto refused;
            next |= gHelixExpansionView.recipe << 2;
        }
        else
        {
            if (gHelixExpansionView.stage != 2) goto refused;
            next |= (action - 5) << 4;
        }
    }
    else goto refused;
    ClearHelixExpansionPreview();
    if (next == gHelixExpansionView.raw) { gSpecialVar_Result = 2; return; }
    gSaveBlock1Ptr->flags[6] = next;
    gSaveBlock1Ptr->flags[7] = next >> 8;
    GetHelixExpansionState();
    gSpecialVar_Result = 1;
    return;
refused:
    ClearHelixExpansionPreview();
}
static void ExpansionAppend(const u8 *text)
{
    StringAppend(gStringVar4, COMPOUND_STRING("\p"));
    StringAppend(gStringVar4, text);
}
// 22 notes; 23 preparation; 24 retained result; all other pages table above.
void BufferHelixExpansionText(void)
{
    u16 page = gSpecialVar_0x8005, pt = gHelixSettingsView.language == 1;
    GetHelixExpansionState();
    gHelixExpansionView.phase = page;
    if (gHelixExpansionView.stage == 0xFFFF) page = 19;
    if (page == 22)
    {
        ClearHelixExpansionPreview();
        StringCopy(gStringVar4, COMPOUND_STRING("QUIET GARDEN$"));
        if (!gHelixExpansionView.stage) { ExpansionAppend(sExpansionPages[20][pt]); return; }
        if (gHelixExpansionView.clues & 1) ExpansionAppend(sExpansionPages[5][pt]);
        if (gHelixExpansionView.clues & 2) ExpansionAppend(sExpansionPages[6][pt]);
        if (gHelixExpansionView.method) ExpansionAppend(sExpansionPages[10][pt]);
        if (gHelixExpansionView.resolution) ExpansionAppend(sExpansionPages[12 + gHelixExpansionView.resolution][pt]);
        else if (gHelixExpansionView.method)
        { ExpansionAppend(sExpansionPages[11][pt]); ExpansionAppend(sExpansionPages[12][pt]); }
        else ExpansionAppend(sExpansionPages[gHelixExpansionView.clues == 3 ? 21 : 17][pt]);
        return;
    }
    if (page == 23) page = gHelixExpansionView.prepared ? 7 + gHelixExpansionView.recipe : 16;
    if (page == 24) page = gHelixExpansionView.resolution ? 12 + gHelixExpansionView.resolution : 18;
    if (page == 10 && !gHelixExpansionView.method) page = 18;
    if (page >= ARRAY_COUNT(sExpansionPages)) page = 19;
    StringCopy(gStringVar4, sExpansionPages[page][pt]);
}
#define EXP_OPTION(s) {COMPOUND_STRING(s), {NULL}}
static const struct MenuAction sExpansionBoardEn[] = {EXP_OPTION("Test together"), EXP_OPTION("Place screen"), EXP_OPTION("Notes"), EXP_OPTION("Leave")};
static const struct MenuAction sExpansionBoardPt[] = {EXP_OPTION("Testar juntos"), EXP_OPTION("Colocar tela"), EXP_OPTION("Notas"), EXP_OPTION("Sair")};
static const struct MenuAction sExpansionTestEn[] = {EXP_OPTION("Float the leaf"), EXP_OPTION("Stop")};
static const struct MenuAction sExpansionTestPt[] = {EXP_OPTION("Soltar a folha"), EXP_OPTION("Parar")};
static const struct MenuAction sExpansionRaisedEn[] = {EXP_OPTION("Lower the leaf"), EXP_OPTION("Stop")};
static const struct MenuAction sExpansionRaisedPt[] = {EXP_OPTION("Baixar a folha"), EXP_OPTION("Parar")};
static const struct MenuAction sExpansionChoiceEn[] = {EXP_OPTION("Beside the bed"), EXP_OPTION("At the mouth"), EXP_OPTION("Leave")};
static const struct MenuAction sExpansionChoicePt[] = {EXP_OPTION("Junto ao canteiro"), EXP_OPTION("Na entrada"), EXP_OPTION("Sair")};
void ShowHelixExpansionMenu(void)
{
    u16 menu = gSpecialVar_0x8007, pt = gHelixSettingsView.language == 1, count = 4;
    const struct MenuAction *options = pt ? sExpansionBoardPt : sExpansionBoardEn;
    GetHelixExpansionState();
    gHelixExpansionView.menu = menu;
    if (menu == 2)
    {
        count = 2;
        options = gHelixExpansionView.recipe == 2 ? (pt ? sExpansionRaisedPt : sExpansionRaisedEn) : (pt ? sExpansionTestPt : sExpansionTestEn);
    }
    else if (menu == 3) { count = 3; options = pt ? sExpansionChoicePt : sExpansionChoiceEn; }
    else if (menu != 1) { count = 1; options += 3; }
    gSpecialVar_Result = 0xFF;
    DrawMultichoiceMenuInternal(0, 0, MULTI_BRINEY_ON_DEWFORD, FALSE, 0, options, count);
}
