#include "global.h"
#include "constants/helix_public_fixture.h"
#include "helix_genesis.h"
#include "helix_settings.h"
#include "pokemon.h"
#include "event_data.h"
#include "string_util.h"
#include "text.h"
#include "constants/ai_bridge.h"
#include "constants/species.h"

// Authored story copy retained; its accepted package/individual bindings are excluded.
// Inspect the current save on every page; the prepared recipe is never a party.
#define LAB_PAIR(en, pt) {COMPOUND_STRING(en), COMPOUND_STRING(pt)}
// Public synthetic placeholders do not match or admit any accepted package.
// A future public gameplay package needs its own reviewed notes and evidence.
static const u8 sNotesPackageHash[32] = HELIX_PUBLIC_NOTES_PACKAGE_HASH;
static const u8 sCoralPackageHash[32] = HELIX_PUBLIC_CORAL_PACKAGE_HASH;
static const u8 *const sNotesUnavailable[2] = LAB_PAIR(
    "These origin notes are unavailable.\nYour companion is unchanged.$",
    "As notas de origem estao ausentes.\nSeu companheiro segue igual.$");
static const u8 *const sInvalid[2] = LAB_PAIR(
    "These notes could not be read.\nYour companions are unchanged.$",
    "Nao foi possível ler as notas.\nSeus companheiros nao mudaram.$");
static const u8 *const sMissing[2] = LAB_PAIR(
    "Your companion is not in your\nparty or PC.\pIts birth is still on record.\nThis terminal cannot replace it.$",
    "Seu companheiro nao está na\nequipe nem no PC.\pSeu nascimento segue registrado.\nEste terminal nao pode recriá-lo.$");
static const u8 *const sPending[5][2] = {
    LAB_PAIR("No companion has hatched yet.\nFirst, speak to LIA at reception.$", "Seu companheiro ainda nao nasceu.\nPrimeiro, fale com LIA na recepçao.$"),
    LAB_PAIR("No companion has hatched yet.\nNext, use the north analysis bench.$", "Seu companheiro ainda nao nasceu.\nUse a bancada de análise ao norte.$"),
    LAB_PAIR("Your choice is ready to prepare.\nUse the terminal on the left wall.$", "Sua escolha está pronta.\nUse o terminal na parede esquerda.$"),
    LAB_PAIR("Your companion is not born yet.\nUse the incubator beside INA.$", "Seu companheiro ainda nao nasceu.\nUse a incubadora ao lado de INA.$"),
    LAB_PAIR("Your companion is ready to hatch!\nReturn to the incubator beside INA.$", "Seu companheiro já pode nascer!\nVolte à incubadora ao lado de INA.$"),
};
static const u8 *const sParty[2] = LAB_PAIR(
    "{STR_VAR_1}  Lv. {STR_VAR_2}\nTraveling with you.\pOpen POKéMON, then SUMMARY\nto see its moves and progress.$",
    "{STR_VAR_1}  Nv. {STR_VAR_2}\nNa sua equipe.\pAbra POKéMON e depois SUMMARY\npara ver golpes e progresso.$");
static const u8 *const sBoxed[2] = LAB_PAIR(
    "{STR_VAR_1}  Lv. {STR_VAR_2}\nResting in your PC.\pWithdraw it at the POKéMON CENTER\nto explore together again.$",
    "{STR_VAR_1}  Nv. {STR_VAR_2}\nDescansando no PC.\pRetire-o no CENTRO POKéMON\npara explorarem juntos de novo.$");
static const u8 *const sOrigins[2][2] = {
    LAB_PAIR("Ancient sample + coastal donor.\nThe sample is not a living parent.\pPaddle feet recall the coastal donor.\nThe shell recalls the ancient armor.$", "Amostra antiga + doador costeiro.\nA amostra nao é um pai vivo.\pPés de nadadeira lembram o doador.\nO casco lembra a armadura antiga.$"),
    LAB_PAIR("Ancient sample + reedland donor.\nThe sample is not a living parent.\pLong legs recall the reedland donor.\nRaised plates recall ancient armor.\pThis project used a made-up sample.\nIt says nothing about a person's DNA.$", "Amostra antiga + doador dos juncos.\nA amostra nao é um pai vivo.\pPernas longas lembram o doador.\nPlacas lembram a armadura antiga.\pO projeto usou uma amostra fictícia.\nEla nao descreve o DNA de alguém.$"),
};
static const u8 *const sTraits[2][2] = {
    LAB_PAIR("Look for the pale spiral shell\nand little paddle feet.\pThe donor has long whiskers.\nYour companion has glowing cheeks!\pInherited parts can look different\ntogether. Each companion is itself.$", "Veja a espiral clara no casco\ne os pequenos pés de nadadeira.\pO doador tem bigodes longos.\nSeu companheiro tem faces brilhantes!\pPartes herdadas podem mudar juntas.\nCada companheiro tem seu jeito.$"),
    LAB_PAIR("Look for the raised back plates\nand the split tail.\pThe donor has a tall back fin.\nYour companion has separate plates!\pInherited parts can look different\ntogether. Each companion is itself.$", "Veja as placas nas costas\ne a cauda dividida.\pO doador tem uma nadadeira alta.\nSeu companheiro tem placas separadas!\pPartes herdadas podem mudar juntas.\nCada companheiro tem seu jeito.$"),
};
static const u8 *const sNext[4][2] = {
    LAB_PAIR("No beacon discovery recorded yet.\nTalk to IVO in LITTLEROOT.\pLeave the lab, then walk south\nfrom OLDALE along ROUTE 101.$", "Nenhuma descoberta do sinal ainda.\nFale com IVO em LITTLEROOT.\pSaia do laboratório e siga ao sul\nde OLDALE pela ROUTE 101.$"),
    LAB_PAIR("IVO's investigation is waiting.\nBring your companion in your party.\pAt the eastern LITTLEROOT pond,\nwatch the beacon's pulses.\pLet your companion hold the plate.\nAnswer the signal together.$", "A investigaçao de IVO está esperando.\nLeve seu companheiro na equipe.\pNo lago a leste de LITTLEROOT,\nobserve os pulsos da luz.\pSeu companheiro segura a placa.\nRespondam ao sinal juntos.$"),
    LAB_PAIR("Discovery: the light answered!\nYour observation is recorded.\pThe message: WE ARE STILL HERE.\nNext, tell IVO in LITTLEROOT.$", "Descoberta: a luz respondeu!\nSua observaçao está registrada.\pA mensagem: AINDA ESTAMOS AQUI.\nAgora conte a IVO, em LITTLEROOT.$"),
    LAB_PAIR("Discovery: IVO heard your report.\nYour beacon notes are kept.\pYou can revisit the beacon to meet\nthe source of its reply.$", "Descoberta: IVO ouviu seu relato.\nSuas notas sobre a luz estao salvas.\pVolte à luz se quiser conhecer\nquem respondeu ao sinal.$"),
};
static const u8 *const sCrossNext[2] = LAB_PAIR(
    "Your beacon discovery is recorded.\nKeep exploring with your companion.\pCORAL is a future family project.\nIts birth is not available yet.$",
    "Sua descoberta da luz está salva.\nContinue com seu companheiro.\pCORAL é um projeto para o futuro.\nSeu nascimento ainda nao está aberto.$");
static const u8 *const sRest[2] = LAB_PAIR(
    "Let your party rest and heal?$", "Deixar sua equipe descansar e curar?$");
static const u8 *const sRested[2] = LAB_PAIR(
    "Your party feels better!\nReturn whenever you need a rest.$", "Sua equipe está melhor!\nVolte quando precisar descansar.$");

void GetHelixLabLanguage(void)
{
    gSpecialVar_Result = gHelixSettingsView.language == 1;
}

void BufferHelixLabPage(void)
{
    struct BoxPokemon mon;
    u16 state = HelixGenesisInspect(&mon);
    u16 language = gHelixSettingsView.language == 1;
    u16 page = gSpecialVar_0x8004;
    const u8 *text = sInvalid[language];
    gStringVar1[0] = EOS;
    gStringVar2[0] = EOS;
    gStringVar4[0] = EOS;
    gSpecialVar_0x8009 = 0;
    gSpecialVar_Result = state;
    if (state == HELIX_INSPECT_PENDING)
        text = sPending[HelixGenesisStage() - 1][language];
    else if (state == HELIX_INSPECT_MISSING)
        text = sMissing[language];
    else if (state == HELIX_INSPECT_PARTY || state == HELIX_INSPECT_BOXED)
    {
        u16 species = GetBoxMonData(&mon, MON_DATA_SPECIES);
        u16 recipe = species == SPECIES_HELIX_FOUNDER_ONE ? 0 : 1;
        GetBoxMonData(&mon, MON_DATA_NICKNAME, gStringVar1);
        ConvertIntToDecimalStringN(gStringVar2, GetLevelFromBoxMonExp(&mon), STR_CONV_MODE_LEFT_ALIGN, 3);
        if ((page == 1 || page == 2) && (memcmp(gHelixGenesisPackageHash, sNotesPackageHash, sizeof(sNotesPackageHash)) != 0
            && memcmp(gHelixGenesisPackageHash, sCoralPackageHash, 32) != 0))
            text = sNotesUnavailable[language];
        else if (page == 0)
        {
            text = state == HELIX_INSPECT_PARTY ? sParty[language] : sBoxed[language];
            gSpecialVar_0x8009 = species;
        }
        else if (page == 1) text = sOrigins[recipe][language];
        else if (page == 2)
        {
            text = sTraits[recipe][language];
            gSpecialVar_0x8009 = species;
        }
        else if (page == 3)
        {
            u16 quest = VarGet(VAR_SIGNAL_QUEST_STATE);
            if (quest <= SIGNAL_QUEST_REPORTED) text = sNext[quest][language];
            if (quest == SIGNAL_QUEST_REPORTED && recipe == 0) text = sCrossNext[language];
        }
        else if (page == 4) text = sRest[language];
        else if (page == 5) text = sRested[language];
    }
    StringExpandPlaceholders(gStringVar4, text);
}
