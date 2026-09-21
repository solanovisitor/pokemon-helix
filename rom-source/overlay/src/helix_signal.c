#include "global.h"
#include "helix_signal.h"
#include "helix_genesis.h"
#include "helix_settings.h"
#include "pokemon.h"
#include "event_data.h"
#include "string_util.h"
#include "text.h"
#include "constants/ai_bridge.h"

// This field task is ordinary cooperation, not a new genome-derived ability.
// The existing signal quest owns progress. These helpers only inspect copies.
#define SIGNAL_PAIR(en, pt) {COMPOUND_STRING(en), COMPOUND_STRING(pt)}
static const u8 *const sPages[][2] = {
    SIGNAL_PAIR("IVO: You and {STR_VAR_1}\ncan help me follow a light.\pIt flashes beside the eastern pond.\nWhy would you like to investigate?$", "IVO: Você e {STR_VAR_1}\npodem me ajudar a seguir uma luz.\pEla pisca junto ao lago a leste.\nPor que você quer investigar?$"),
    SIGNAL_PAIR("IVO: Find the blue light beside\nthe eastern pond, above the sign.\pWatch its rhythm together.\nThen tell me what you discover.$", "IVO: Ache a luz azul junto\nao lago a leste, acima da placa.\pObservem o ritmo juntos.\nDepois me conte a descoberta.$"),
    SIGNAL_PAIR("IVO: The blue light is beside\nthe eastern pond, above the sign.\pBring your companion and watch\nclosely. I will listen from here.$", "IVO: A luz azul fica junto\nao lago a leste, acima da placa.\pLeve seu companheiro e observe.\nVou escutar daqui.$"),
    SIGNAL_PAIR("The blue light blinks in a rhythm.\nA low plate sits beside its base.\pIVO, south of the laboratory,\nis listening to this signal.$", "A luz azul pisca em um ritmo.\nHá uma placa baixa junto à base.\pIVO, ao sul do laboratório,\nestá escutando este sinal.$"),
    SIGNAL_PAIR("Two flashes, then a pause.\nA low plate rests beside the base.\pThe upper button is within reach.\nThe plate must stay pressed, too.$", "Duas piscadas, depois uma pausa.\nHá uma placa baixa junto à base.\pVocê alcança o botao de cima.\nA placa precisa ficar pressionada.$"),
    SIGNAL_PAIR("{STR_VAR_1} steps closer.\nIt holds down the low plate.\pThe upper button lights up!\nTap the rhythm you observed.$", "{STR_VAR_1} se aproxima.\nSeu companheiro pressiona a placa.\pO botao de cima acende!\nToque no ritmo que você observou.$"),
    SIGNAL_PAIR("One tap. The light fades again.\nYour companion releases the plate.\pThe light repeats its own rhythm.\nYou can watch and try again.$", "Um toque. A luz se apaga de novo.\nSeu companheiro solta a placa.\pA luz repete seu próprio ritmo.\nVocê pode observar e tentar de novo.$"),
    SIGNAL_PAIR("Two taps! A small panel opens.\nBeneath it, a message appears:\pWE ARE STILL HERE.\nThe light answers both of you!\pTell IVO what you found?$", "Dois toques! Um painel se abre.\nUma mensagem aparece embaixo:\pAINDA ESTAMOS AQUI.\nA luz responde a vocês dois!\pContar a IVO o que encontraram?$"),
    SIGNAL_PAIR("You remember the answering light.\nThe message stays in your notes.\pReturn to IVO, south of the lab.\nHe is waiting for your discovery.$", "Você guarda a resposta da luz.\nA mensagem fica nas suas notas.\pVolte a IVO, ao sul do laboratório.\nEle espera pela sua descoberta.$"),
    SIGNAL_PAIR("IVO: You found an answer!\nThe light carried a message.\pWE ARE STILL HERE...\nSomeone was waiting for an answer.\pI will keep your observation.\nThere may be more signals to find.$", "IVO: Você encontrou uma resposta!\nA luz guardava uma mensagem.\pAINDA ESTAMOS AQUI...\nAlguém esperava uma resposta.\pVou guardar sua observaçao.\nTalvez existam outros sinais.$"),
    SIGNAL_PAIR("IVO: I remember your curiosity.\nYour discovery is in our notes.\pOur notes are here when you return.\nKeep exploring at your own pace.$", "IVO: Lembro da sua curiosidade.\nSua descoberta está nas notas.\pNossas notas ficam aqui para você.\nExplore no seu próprio ritmo.$"),
    SIGNAL_PAIR("WE ARE STILL HERE.\nThe light keeps this message.\pTwo flashes, then a pause.\nYour discovery is still recorded.$", "AINDA ESTAMOS AQUI.\nA luz guarda esta mensagem.\pDuas piscadas, depois uma pausa.\nSua descoberta segue registrada.$"),
    SIGNAL_PAIR("Your companion's notes are unclear.\nReturn to the lab to check them.\pThe light will wait for you.$", "As notas do companheiro estao vagas.\nVolte ao laboratório para conferir.\pA luz vai esperar por vocês.$"),
    SIGNAL_PAIR("IVO: I will keep listening here.\nCome back whenever you feel ready.$", "IVO: Vou continuar escutando aqui.\nVolte quando você quiser.$"),
};
static const u8 *const sHelpMemory[2] = SIGNAL_PAIR(
    "IVO: You wanted to help our town.\nYour discovery is in our notes.\pOur notes are here when you return.\nKeep exploring at your own pace.$",
    "IVO: Você queria ajudar a vila.\nSua descoberta está nas notas.\pNossas notas ficam aqui para você.\nExplore no seu próprio ritmo.$");
static const u8 *const sBoxed[2] = SIGNAL_PAIR(
    "Your companion is resting in the PC.\nWithdraw it to work together here.\pThe light will wait for you.$",
    "Seu companheiro descansa no PC.\nRetire-o para agirem juntos aqui.\pA luz vai esperar por vocês.$");
static const u8 *const sFainted[2] = SIGNAL_PAIR(
    "Your companion needs a rest.\nVisit INA or a POKéMON CENTER.\pReturn together after it has healed.\nThe light will wait for you.$",
    "Seu companheiro precisa descansar.\nVisite INA ou um CENTRO POKéMON.\pVoltem juntos depois da cura.\nA luz vai esperar por vocês.$");
static const u8 *const sMissing[2] = SIGNAL_PAIR(
    "Your first companion is not in\nyour party or PC.\pIts birth is still on record.\nThe light cannot replace it.$",
    "Seu primeiro companheiro nao está\nna sua equipe nem no PC.\pSeu nascimento segue registrado.\nA luz nao pode recriá-lo.$");
static const u8 *const sPending[2] = SIGNAL_PAIR(
    "First, help your companion hatch\nat the HELIX laboratory.\pThen you can investigate together.$",
    "Primeiro, ajude seu companheiro\na nascer no laboratório HELIX.\pDepois vocês podem investigar juntos.$");

u16 HelixSignalInspect(struct BoxPokemon *out)
{
    u16 state = HelixGenesisInspect(out);
    u32 slot;
    if (state == HELIX_INSPECT_BOXED) return HELIX_SIGNAL_BOXED;
    if (state == HELIX_INSPECT_MISSING) return HELIX_SIGNAL_MISSING;
    if (state == HELIX_INSPECT_PENDING) return HELIX_SIGNAL_PENDING;
    if (state != HELIX_INSPECT_PARTY) return HELIX_SIGNAL_INVALID;
    // Inspection already verified recipe, OT, checksum and global uniqueness.
    // Match that exact inspected individual, not any healthy party member.
    for (slot = 0; slot < PARTY_SIZE; slot++)
    {
        struct Pokemon copy = gParties[B_TRAINER_PLAYER][slot];
        if (memcmp(&copy.box, out, sizeof(*out)) == 0)
            return GetMonData(&copy, MON_DATA_HP) ? HELIX_SIGNAL_READY : HELIX_SIGNAL_FAINTED;
    }
    memset(out, 0, sizeof(*out));
    return HELIX_SIGNAL_INVALID;
}

void GetHelixSignalRoute(void)
{
    u16 stage = HelixGenesisStage();
    // Empty legacy records retain the original scripts. Damaged nonzero records
    // must not fall through to the less restrictive historical signal route.
    // A pending Helix save at an unusual location still needs its own founder.
    gSpecialVar_Result = !HelixGenesisCanContinue() || (stage > 0 && stage < 6) ? 2 : stage == 6;
}

void GetHelixSignalReady(void)
{
    struct BoxPokemon mon;
    u16 state = HelixSignalInspect(&mon);
    gSpecialVar_Result = state;
    gSpecialVar_0x8009 = 0;
    if (state == HELIX_SIGNAL_READY || state == HELIX_SIGNAL_BOXED || state == HELIX_SIGNAL_FAINTED)
        gSpecialVar_0x8009 = GetBoxMonData(&mon, MON_DATA_SPECIES);
}

void BufferHelixSignalPage(void)
{
    struct BoxPokemon mon;
    u16 state = HelixSignalInspect(&mon);
    u16 page = gSpecialVar_0x8004;
    u16 language = gHelixSettingsView.language == 1;
    const u8 *text = sPages[12][language];
    gStringVar1[0] = EOS;
    gStringVar4[0] = EOS;
    gSpecialVar_0x8009 = 0;
    gSpecialVar_Result = state;
    if (state == HELIX_SIGNAL_READY || state == HELIX_SIGNAL_BOXED || state == HELIX_SIGNAL_FAINTED)
    {
        GetBoxMonData(&mon, MON_DATA_NICKNAME, gStringVar1);
        gSpecialVar_0x8009 = GetBoxMonData(&mon, MON_DATA_SPECIES);
    }
    if (page < ARRAY_COUNT(sPages)) text = sPages[page][language];
    if (page == 10 && VarGet(VAR_SIGNAL_MOTIVATION) == SIGNAL_MOTIVATION_VILLAGE)
        text = sHelpMemory[language];
    if (page == 12 || (page == 0 && !gSpecialVar_0x8009))
    {
        if (state == HELIX_SIGNAL_BOXED) text = sBoxed[language];
        else if (state == HELIX_SIGNAL_FAINTED) text = sFainted[language];
        else if (state == HELIX_SIGNAL_MISSING) text = sMissing[language];
        else if (state == HELIX_SIGNAL_PENDING) text = sPending[language];
        else text = sPages[12][language];
    }
    StringExpandPlaceholders(gStringVar4, text);
}
