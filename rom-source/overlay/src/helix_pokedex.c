#include "global.h"
#include "constants/helix_public_fixture.h"
#include "helix_pokedex.h"
#include "helix_genesis.h"
#include "helix_settings.h"
#include "bg.h"
#include "gpu_regs.h"
#include "graphics.h"
#include "decompress.h"
#include "window.h"
#include "pokedex_common.h"
#include "main.h"
#include "menu.h"
#include "menu_helpers.h"
#include "overworld.h"
#include "palette.h"
#include "pokedex.h"
#include "pokemon.h"
#include "pokemon_birth.h"
#include "scanline_effect.h"
#include "sound.h"
#include "sprite.h"
#include "string_util.h"
#include "task.h"
#include "text.h"
#include "trainer_pokemon_sprites.h"
#include "window.h"
#include "constants/rgb.h"
#include "constants/characters.h"
#include "constants/songs.h"
#include "constants/species.h"

// Synthetic public metadata; accepted IDs, genomes, traits and profiles are excluded.
// These disabled fixture tables do not describe the retained authorial artwork.
const u8 gHelixPokedexPackageHash[32] = HELIX_PUBLIC_NOTES_PACKAGE_HASH;
static const u8 sCoralPackageHash[32] = HELIX_PUBLIC_CORAL_PACKAGE_HASH;
const u8 gHelixPokedexGenome[3][96] = HELIX_PUBLIC_DEX_GENOMES;
const u8 gHelixPokedexChanges[3][24] = HELIX_PUBLIC_DEX_CHANGES;
static const u8 sIndividualIds[3][32] = HELIX_PUBLIC_DEX_IDS;
static const u8 sProfileHashes[3][32] = HELIX_PUBLIC_DEX_PROFILE_HASHES;
static const u8 sTraitScores[3][16] = HELIX_PUBLIC_DEX_TRAIT_SCORES;

#define DEX_PAIR(en, pt) {COMPOUND_STRING(en), COMPOUND_STRING(pt)}
static const u8 *const sTabs[HELIX_DEX_PAGE_COUNT][2] = {
    DEX_PAIR("INFO", "INFO"), DEX_PAIR("TRAITS", "TRAÇOS"),
    DEX_PAIR("ORIGIN", "ORIGEM"), DEX_PAIR("DNA", "DNA"),
};
static const u8 *const sTraitNames[16][2] = {
    DEX_PAIR("Size", "Tamanho"), DEX_PAIR("Length", "Alongado"),
    DEX_PAIR("Limbs", "Membros"), DEX_PAIR("Armor", "Proteçao"),
    DEX_PAIR("Pigment", "Pigmento"), DEX_PAIR("Contrast", "Contraste"),
    DEX_PAIR("Patterns", "Padroes"), DEX_PAIR("Glow", "Brilho"),
    DEX_PAIR("Aquatic", "Aquático"), DEX_PAIR("Cold", "Frio"),
    DEX_PAIR("Nocturnal", "Noturno"), DEX_PAIR("Camouflage", "Camuflagem"),
    DEX_PAIR("Curiosity", "Curiosidade"), DEX_PAIR("Social", "Sociável"),
    DEX_PAIR("Territory", "Território"), DEX_PAIR("Signal", "Sinal"),
};
static const u8 *const sLocation[2][2] = {
    DEX_PAIR("In your party", "Na sua equipe"),
    DEX_PAIR("Resting in your PC", "Descansando no PC"),
};
static const u8 *const sOriginDonor[3][2] = {
    DEX_PAIR("Coastal donor", "Doador costeiro"),
    DEX_PAIR("Reedland donor", "Doador dos juncos"),
    DEX_PAIR("REVA", "REVA"),
};
static const u8 *const sOriginCue[3][2] = {
    DEX_PAIR("Paddle feet", "Pés de nadadeira"),
    DEX_PAIR("Long legs", "Pernas longas"),
    DEX_PAIR("Spiral + split tail", "Espiral + cauda"),
};
static const u8 *const sTypes[3][2] = {
    DEX_PAIR("WATER / PSYCHIC", "ÁGUA / PSÍQUICO"),
    DEX_PAIR("WATER / ICE", "ÁGUA / GELO"),
    DEX_PAIR("WATER / PSYCHIC", "ÁGUA / PSÍQUICO"),
};
static const u8 *const sDnaHelp[6][2] = {
    DEX_PAIR("Two copies, 96 sites each.", "Duas cópias de 96 locais."),
    DEX_PAIR("8 pairs of 12 sites.", "8 pares de 12 locais."),
    DEX_PAIR("0-F are 16 fictional variants.", "0-F sao 16 variantes fictícias."),
    DEX_PAIR("Gold dot: recorded change.", "Ponto: mudança registrada."),
    DEX_PAIR("Codes do not predict powers", "Os códigos nao preveem poderes"),
    DEX_PAIR("or looks. A: back to copies.", "nem aparencia. A: voltar às cópias."),
};
static const u8 *const sMissing[2] = DEX_PAIR("Your companion is not in your party\nor PC. Its birth is still recorded.\nThis view cannot replace it.", "Seu companheiro nao está na equipe\nnem no PC. Seu nascimento foi salvo.\nEsta tela nao pode recriá-lo.");
static const u8 *const sUnavailable[2] = DEX_PAIR("These notes are unavailable.\nYour companion is unchanged.", "Estas notas estao indisponíveis.\nSeu companheiro segue igual.");
static const u8 *const sPending[2] = DEX_PAIR("No companion has hatched yet.\nVisit INA in the laboratory.", "Seu companheiro ainda nao nasceu.\nVisite INA no laboratório.");
static const u8 *const sInvalid[2] = DEX_PAIR("The companion record could not\nbe read. Nothing was changed.", "Nao foi possível ler o registro.\nNada foi alterado.");

// Reuse Emerald's exact native detail frame, glyph palette and rounded tabs.
static const struct BgTemplate sBgs[] = {
    {.bg = 1, .charBaseIndex = 0, .mapBaseIndex = 13, .screenSize = 0, .paletteMode = 0, .priority = 1, .baseTile = 0},
    {.bg = 2, .charBaseIndex = 2, .mapBaseIndex = 14, .screenSize = 0, .paletteMode = 0, .priority = 0, .baseTile = 0},
    {.bg = 3, .charBaseIndex = 0, .mapBaseIndex = 15, .screenSize = 0, .paletteMode = 0, .priority = 2, .baseTile = 0},
};
static const struct WindowTemplate sWindows[] = {
    {.bg = 2, .tilemapLeft = 0, .tilemapTop = 0, .width = 30, .height = 20,
     .paletteNum = 0, .baseBlock = 1}, DUMMY_WIN_TEMPLATE,
};
static const u8 sTextColors[3] = {0, 15, 3};
static const u8 sMutedColors[3] = {0, 15, 3};
static const u8 sAlleleColors[3] = {1, 15, 3};
EWRAM_DATA struct HelixPokedexView gHelixPokedexView = {0};
static EWRAM_DATA struct Pokemon sMon = {0};
static EWRAM_DATA u16 sTilemap[3][32 * 32] = {0};
static EWRAM_DATA u16 sPortrait = 0;
static EWRAM_DATA bool8 sExitToSpecies = FALSE;
static EWRAM_DATA u8 sLanguage = 0;
static EWRAM_DATA bool8 sSelectChild = FALSE;

// The two consecutive nibbles are adjacent loci, NOT the two inherited copies.
u8 HelixPokedexAllele(u16 recipe, u16 copy, u16 locus)
{
    u16 index;
    if (recipe >= 3 || copy >= 2 || locus >= 96) return 0xFF;
    index = copy * 96 + locus;
    return (gHelixPokedexGenome[recipe][index / 2] >> ((index & 1) * 4)) & 15;
}
bool32 HelixPokedexChanged(u16 recipe, u16 copy, u16 locus)
{
    u16 index;
    if (recipe >= 3 || copy >= 2 || locus >= 96) return FALSE;
    index = copy * 96 + locus;
    return (gHelixPokedexChanges[recipe][index / 8] >> (index & 7)) & 1;
}
static bool32 HasCompanion(void)
{
    return gHelixPokedexView.inspection == HELIX_INSPECT_PARTY
        || gHelixPokedexView.inspection == HELIX_INSPECT_BOXED;
}
static void ReadCompanion(void)
{
    struct BoxPokemon box;
    u32 i;
    u16 species;
    memset(&sMon, 0, sizeof(sMon));
    gHelixPokedexView.inspection = sSelectChild ? HelixGenesisInspectResident(3, &box) : HelixGenesisInspect(&box);
    gHelixPokedexView.metadataReady = FALSE;
    gHelixPokedexView.recipe = 0xFFFF;
    if (!HasCompanion()) return;
    // All getters and stat reconstruction operate on copies. In-party HP/stats
    // remain exactly those of the saved mon; boxed stats use native conversion.
    if (gHelixPokedexView.inspection == HELIX_INSPECT_BOXED)
        BoxMonToMon(&box, &sMon);
    else
        for (i = 0; i < PARTY_SIZE; i++)
            if (memcmp(&box, &gParties[B_TRAINER_PLAYER][i].box, sizeof(box)) == 0)
            {
                sMon = gParties[B_TRAINER_PLAYER][i];
                break;
            }
    species = GetMonData(&sMon, MON_DATA_SPECIES);
    if (species == SPECIES_HELIX_FOUNDER_ONE) gHelixPokedexView.recipe = 0;
    else if (species == SPECIES_HELIX_FOUNDER_TWO) gHelixPokedexView.recipe = 1;
    else if (species == SPECIES_HELIX_CHILD) gHelixPokedexView.recipe = 2;
    else return;
    i = gHelixPokedexView.recipe;
    gHelixPokedexView.metadataReady = (memcmp(gHelixGenesisPackageHash, gHelixPokedexPackageHash, 32) == 0
        || memcmp(gHelixGenesisPackageHash, sCoralPackageHash, 32) == 0)
        && memcmp(gHelixGenesisIds[i == 2 ? 3 : i], sIndividualIds[i], 32) == 0
        && memcmp(gHelixGenesisProfileHashes[i == 2 ? 3 : i], sProfileHashes[i], 32) == 0;
}
static void Text(u8 x, u8 y, const u8 *text)
{
    AddTextPrinterParameterized3(0, FONT_NORMAL, x, y, sTextColors, TEXT_SKIP_DRAW, text);
}
static void Muted(u8 x, u8 y, const u8 *text)
{
    AddTextPrinterParameterized3(0, FONT_SMALL, x, y, sMutedColors, TEXT_SKIP_DRAW, text);
}
static void Number(u8 x, u8 y, u32 number, u8 digits)
{
    u8 buffer[12];
    ConvertIntToDecimalStringN(buffer, number, STR_CONV_MODE_LEFT_ALIGN, digits);
    Text(x, y, buffer);
}
static const u8 *Local(const u8 *en, const u8 *pt)
{
    return sLanguage ? pt : en;
}
static void DrawCurrent(void)
{
    u8 name[POKEMON_NAME_LENGTH + 1];
    u8 hp[16], *end;
    GetMonData(&sMon, MON_DATA_NICKNAME, name);
    Text(96, 25, name);
    if (gHelixPokedexView.metadataReady) Text(96, 41, sTypes[gHelixPokedexView.recipe][sLanguage]);
    Text(96, 57, Local(COMPOUND_STRING("Lv."), COMPOUND_STRING("Nv.")));
    Number(119, 57, GetMonData(&sMon, MON_DATA_LEVEL), 3);
    Muted(155, 59, gHelixPokedexView.inspection == HELIX_INSPECT_BOXED
        ? COMPOUND_STRING("PC") : Local(COMPOUND_STRING("PARTY"), COMPOUND_STRING("EQUIPE")));
    Text(96, 73, COMPOUND_STRING("XP")); Number(118, 73, GetMonData(&sMon, MON_DATA_EXP), 7);
    Text(16, 97, COMPOUND_STRING("HP"));
    end = ConvertIntToDecimalStringN(hp, GetMonData(&sMon, MON_DATA_HP), STR_CONV_MODE_LEFT_ALIGN, 3);
    end = StringCopy(end, COMPOUND_STRING("/"));
    ConvertIntToDecimalStringN(end, GetMonData(&sMon, MON_DATA_MAX_HP), STR_CONV_MODE_LEFT_ALIGN, 3);
    Text(48, 97, hp);
    Text(134, 97, COMPOUND_STRING("ATK")); Number(180, 97, GetMonData(&sMon, MON_DATA_ATK), 3);
    Text(16, 113, COMPOUND_STRING("DEF")); Number(62, 113, GetMonData(&sMon, MON_DATA_DEF), 3);
    Text(134, 113, COMPOUND_STRING("SpA")); Number(180, 113, GetMonData(&sMon, MON_DATA_SPATK), 3);
    Text(16, 129, COMPOUND_STRING("SpD")); Number(62, 129, GetMonData(&sMon, MON_DATA_SPDEF), 3);
    Text(134, 129, COMPOUND_STRING("SPE")); Number(180, 129, GetMonData(&sMon, MON_DATA_SPEED), 3);
}
static void DrawTraits(void)
{
    u16 i, trait;
    for (i = 0; i < 8; i++)
    {
        u8 x = 16 + (i / 4) * 108;
        u8 y = 25 + (i % 4) * 16;
        trait = gHelixPokedexView.section * 8 + i;
        Text(x, y, sTraitNames[trait][sLanguage]);
        Number(x + 80, y, sTraitScores[gHelixPokedexView.recipe][trait], 3);
    }
    Text(16, 97, Local(COMPOUND_STRING("Recorded traits"), COMPOUND_STRING("Traços registrados")));
    Number(185, 97, gHelixPokedexView.section + 1, 1); Text(195, 97, COMPOUND_STRING("/2"));
    Text(16, 113, Local(COMPOUND_STRING("50 = typical in this fictional family."), COMPOUND_STRING("50 = típico nesta família fictícia.")));
    Text(16, 129, Local(COMPOUND_STRING("UP/DOWN: more traits"), COMPOUND_STRING("CIMA/BAIXO: mais traços")));
}
static void DrawOrigin(void)
{
    u16 recipe = gHelixPokedexView.recipe;
    struct PokemonBirthDate birth;
    u8 text[40], *next;
    Text(96, 25, recipe == 2 ? COMPOUND_STRING("NAUTIL") : Local(COMPOUND_STRING("Ancient sample"), COMPOUND_STRING("Amostra antiga")));
    Text(96, 41, sOriginDonor[recipe][sLanguage]);
    Text(96, 57, sOriginCue[recipe][sLanguage]);
    if (PokemonBirthDateToCalendar(GetMonData(&sMon, MON_DATA_DATE_OF_BIRTH), &birth))
    {
        next = StringCopy(text, Local(COMPOUND_STRING("Born "), COMPOUND_STRING("Nasc. ")));
        next = ConvertIntToDecimalStringN(next, birth.year, STR_CONV_MODE_LEADING_ZEROS, 4);
        *next++ = CHAR_HYPHEN;
        next = ConvertIntToDecimalStringN(next, birth.month, STR_CONV_MODE_LEADING_ZEROS, 2);
        *next++ = CHAR_HYPHEN;
        ConvertIntToDecimalStringN(next, birth.day, STR_CONV_MODE_LEADING_ZEROS, 2);
        Text(96, 73, text);
    }
    else Text(96, 73, Local(COMPOUND_STRING("DoB: unknown"), COMPOUND_STRING("Nasc.: sem registro")));
    Text(16, 97, recipe == 2 ? Local(COMPOUND_STRING("Two living parents, a new companion."), COMPOUND_STRING("Dois pais vivos, um novo companheiro."))
        : Local(COMPOUND_STRING("Ancient material is not a living parent."), COMPOUND_STRING("Amostra antiga nao é um pai vivo.")));
    if (recipe == 2)
    {
        Text(16, 113, Local(COMPOUND_STRING("Low shell, long legs and side gills."), COMPOUND_STRING("Casco baixo, pernas e guelras.")));
        Text(16, 129, Local(COMPOUND_STRING("Inherited traits, its own appearance."), COMPOUND_STRING("Traços herdados, aparencia própria.")));
    }
    else if (recipe == 1)
    {
        Text(16, 113, Local(COMPOUND_STRING("Also used a made-up sample."), COMPOUND_STRING("Usou também uma amostra fictícia.")));
        Text(16, 129, Local(COMPOUND_STRING("No personal DNA."), COMPOUND_STRING("Sem DNA pessoal.")));
    }
    else
    {
        Text(16, 113, Local(COMPOUND_STRING("Ancient shell, little paddle feet."), COMPOUND_STRING("Casco antigo, pés de nadadeira.")));
        Text(16, 129, Local(COMPOUND_STRING("A companion with its own traits."), COMPOUND_STRING("Um companheiro com seu jeito.")));
    }
}
static void DrawDna(void)
{
    u16 copy, i, locus;
    if (gHelixPokedexView.help)
    {
        for (i = 0; i < 6; i++) Text(16, i < 3 ? 25 + i * 20 : 97 + (i - 3) * 16, sDnaHelp[i][sLanguage]);
        return;
    }
    Text(16, 25, Local(COMPOUND_STRING("PAIR"), COMPOUND_STRING("PAR")));
    Number(50, 25, gHelixPokedexView.section + 1, 1); Text(60, 25, COMPOUND_STRING("/8"));
    Text(117, 25, Local(COMPOUND_STRING("Sites"), COMPOUND_STRING("Locais")));
    Number(157, 25, gHelixPokedexView.section * 12 + 1, 2); Text(174, 25, COMPOUND_STRING("-"));
    Number(185, 25, gHelixPokedexView.section * 12 + 12, 2);
    Muted(gHelixPokedexView.recipe == 2 ? 8 : 16, 46, gHelixPokedexView.recipe == 2 ? COMPOUND_STRING("NAUTIL") : Local(COMPOUND_STRING("Anc."), COMPOUND_STRING("Ant.")));
    Muted(16, 68, gHelixPokedexView.recipe == 2 ? COMPOUND_STRING("REVA") : Local(COMPOUND_STRING("Donor"), COMPOUND_STRING("Doador")));
    for (copy = 0; copy < 2; copy++)
    {
        u8 y = 44 + copy * 22;
        FillWindowPixelRect(0, copy ? 12 : 7, 49, y + 8, 170, 1);
        for (i = 0; i < 12; i++)
        {
            u8 allele, text[2], x = 50 + i * 14;
            locus = gHelixPokedexView.section * 12 + i;
            allele = HelixPokedexAllele(gHelixPokedexView.recipe, copy, locus);
            text[0] = allele < 10 ? CHAR_0 + allele : CHAR_A + allele - 10;
            text[1] = EOS;
            FillWindowPixelRect(0, 1, x, y, 12, 17);
            AddTextPrinterParameterized3(0, FONT_NORMAL, x + 3, y, sAlleleColors, TEXT_SKIP_DRAW, text);
            if (HelixPokedexChanged(gHelixPokedexView.recipe, copy, locus))
                FillWindowPixelRect(0, 14, x + 4, y + 15, 3, 2);
        }
    }
    Text(16, 97, gHelixPokedexView.recipe == 2 ? Local(COMPOUND_STRING("One inherited copy from each parent."), COMPOUND_STRING("Uma cópia herdada de cada pai.")) : Local(COMPOUND_STRING("Ancient sample / living donor"), COMPOUND_STRING("Amostra antiga / doador vivo")));
    Text(16, 113, Local(COMPOUND_STRING("Fictional variants: 0-F"), COMPOUND_STRING("Variantes fictícias: 0-F")));
    Text(16, 129, Local(COMPOUND_STRING("UP/DOWN: pair   A: guide"), COMPOUND_STRING("CIMA/BAIXO: par   A: guia")));
}
static void Draw(void)
{
    u16 i, j;
    FillWindowPixelBuffer(0, PIXEL_FILL(0));
    // Keep the exact native outer moulding. Species height/weight rules and
    // its footprint recess are not individual data fields on these pages.
    if (gHelixPokedexView.page == HELIX_DEX_TRAITS || gHelixPokedexView.page == HELIX_DEX_DNA)
        FillWindowPixelRect(0, 2, 16, 24, 204, 64);
    else
        FillWindowPixelRect(0, 1, 96, 56, 124, 28);
    // Native rounded selector caps with their original highlight palettes.
    // Only replace the baked AREA/CRY/SIZE/CANCEL label interiors.
    for (i = 0; i < HELIX_DEX_PAGE_COUNT; i++)
    {
        u16 palette = (i == gHelixPokedexView.page ? 2 : 4) << 12;
        u16 x = i * 7 + 1;
        sTilemap[0][x] = palette | 0x20;
        sTilemap[0][x + 32] = palette | 0x30;
        for (j = 1; j < 6; j++)
        {
            sTilemap[0][x + j] = palette | 0x21;
            sTilemap[0][x + j + 32] = palette | 0x31;
        }
        sTilemap[0][x + 6] = palette | 0x420;
        sTilemap[0][x + 38] = palette | 0x430;
        Muted(8 + i * 56 + (56 - GetStringWidth(FONT_SMALL, sTabs[i][sLanguage], 0)) / 2, 1, sTabs[i][sLanguage]);
    }
    if (sPortrait != SPRITE_NONE) gSprites[sPortrait].invisible = !HasCompanion()
        || (gHelixPokedexView.page != HELIX_DEX_CURRENT && gHelixPokedexView.page != HELIX_DEX_ORIGIN);
    if (!HasCompanion())
    {
        const u8 *message = sInvalid[sLanguage];
        if (gHelixPokedexView.inspection == HELIX_INSPECT_MISSING) message = sMissing[sLanguage];
        else if (gHelixPokedexView.inspection == HELIX_INSPECT_PENDING) message = sSelectChild
            ? Local(COMPOUND_STRING("CORAL is a future family project.\nIts birth is not available yet."), COMPOUND_STRING("CORAL é um projeto para o futuro.\nSeu nascimento ainda nao está aberto.")) : sPending[sLanguage];
        Text(16, 97, message);
    }
    else if (gHelixPokedexView.page == HELIX_DEX_CURRENT) DrawCurrent();
    else if (!gHelixPokedexView.metadataReady) Text(16, 97, sUnavailable[sLanguage]);
    else if (gHelixPokedexView.page == HELIX_DEX_TRAITS) DrawTraits();
    else if (gHelixPokedexView.page == HELIX_DEX_ORIGIN) DrawOrigin();
    else DrawDna();
    Muted(16, 146, Local(COMPOUND_STRING("L/R: pages START: partner B: back"), COMPOUND_STRING("L/R: pág. START: trocar B: voltar")));
    PutWindowTilemap(0);
    CopyWindowToVram(0, COPYWIN_FULL);
    CopyBgTilemapBufferToVram(1);
}
static void MainCB(void)
{
    RunTasks(); AnimateSprites(); BuildOamBuffer(); UpdatePaletteFade();
}
static void VBlankCB(void)
{
    LoadOam(); ProcessSpriteCopyRequests(); TransferPlttBuffer();
}
static void Task_Exit(u8 taskId)
{
    if (gPaletteFade.active) return;
    if (sPortrait != SPRITE_NONE) FreeAndDestroyMonPicSprite(sPortrait);
    sPortrait = SPRITE_NONE;
    FreeAllWindowBuffers();
    UnsetBgTilemapBuffer(1); UnsetBgTilemapBuffer(2); UnsetBgTilemapBuffer(3);
    gHelixPokedexView.open = FALSE;
    DestroyTask(taskId);
    SetMainCallback2(sExitToSpecies ? CB2_OpenPokedex : CB2_ReturnToFieldWithOpenMenu);
}
static void Task_Input(u8 taskId)
{
    bool32 redraw = FALSE;
    if (gPaletteFade.active) return;
    // Honor physical shoulder presses before L=A's synthetic confirm bit.
    if (JOY_NEW(L_BUTTON | DPAD_LEFT))
    {
        gHelixPokedexView.page = (gHelixPokedexView.page + HELIX_DEX_PAGE_COUNT - 1) % HELIX_DEX_PAGE_COUNT;
        gHelixPokedexView.section = gHelixPokedexView.help = 0;
        redraw = TRUE;
    }
    else if (JOY_NEW(R_BUTTON | DPAD_RIGHT))
    {
        gHelixPokedexView.page = (gHelixPokedexView.page + 1) % HELIX_DEX_PAGE_COUNT;
        gHelixPokedexView.section = gHelixPokedexView.help = 0;
        redraw = TRUE;
    }
    else if (JOY_NEW(B_BUTTON | SELECT_BUTTON))
    {
        sExitToSpecies = GetNationalPokedexCount(FLAG_GET_SEEN) != 0;
        BeginNormalPaletteFade(PALETTES_ALL, 0, 0, 16, RGB_BLACK);
        gTasks[taskId].func = Task_Exit;
        return;
    }
    else if (JOY_NEW(START_BUTTON))
    {
        sSelectChild ^= 1;
        ReadCompanion();
        gHelixPokedexView.section = gHelixPokedexView.help = 0;
        if (sPortrait != SPRITE_NONE) FreeAndDestroyMonPicSprite(sPortrait);
        sPortrait = SPRITE_NONE;
        if (HasCompanion())
        {
            sPortrait = CreateMonPicSprite(GetMonData(&sMon, MON_DATA_SPECIES), IsMonShiny(&sMon),
                sMon.box.personality, TRUE, MON_PAGE_X, MON_PAGE_Y, 0, TAG_NONE);
            if (sPortrait >= MAX_SPRITES) sPortrait = SPRITE_NONE;
            else gSprites[sPortrait].oam.priority = 0;
        }
        redraw = TRUE;
    }
    else if (gHelixPokedexView.page == HELIX_DEX_DNA && JOY_NEW(A_BUTTON))
    {
        gHelixPokedexView.help ^= 1;
        redraw = TRUE;
    }
    else if ((gHelixPokedexView.page == HELIX_DEX_DNA || gHelixPokedexView.page == HELIX_DEX_TRAITS)
        && !gHelixPokedexView.help && JOY_NEW(DPAD_UP | DPAD_DOWN))
    {
        u16 count = gHelixPokedexView.page == HELIX_DEX_DNA ? 8 : 2;
        gHelixPokedexView.section = (gHelixPokedexView.section + (JOY_NEW(DPAD_DOWN) ? 1 : count - 1)) % count;
        redraw = TRUE;
    }
    if (redraw)
    {
        gHelixPokedexView.reserved = 0;
        PlaySE(SE_SELECT);
        Draw();
    }
}
void CB2_OpenHelixPokedex(void)
{
    switch (gMain.state)
    {
    case 0:
        SetVBlankHBlankCallbacksToNull();
        ResetVramOamAndBgCntRegs();
        ResetBgsAndClearDma3BusyFlags(0);
        InitBgsFromTemplates(0, sBgs, ARRAY_COUNT(sBgs));
        ResetAllBgsCoordinates();
        memset(sTilemap, 0, sizeof(sTilemap));
        SetBgTilemapBuffer(1, sTilemap[0]);
        SetBgTilemapBuffer(2, sTilemap[1]);
        SetBgTilemapBuffer(3, sTilemap[2]);
        if (!InitWindows(sWindows))
        {
            SetMainCallback2(CB2_ReturnToFieldWithOpenMenu);
            return;
        }
        DeactivateAllTextPrinters();
        ResetPaletteFade(); ScanlineEffect_Stop(); ResetTasks(); ResetSpriteData(); FreeAllSpritePalettes();
        memset(&gHelixPokedexView, 0, sizeof(gHelixPokedexView));
        sLanguage = gHelixSettingsView.language == 1;
        sPortrait = SPRITE_NONE;
        sExitToSpecies = FALSE;
        sSelectChild = FALSE;
        ReadCompanion();
        gMain.state++;
        break;
    case 1:
        DecompressAndLoadBgGfxUsingHeap(3, gPokedexMenu_Gfx, 0x2000, 0, 0);
        CopyToBgTilemapBuffer(3, gPokedexInfoScreen_Tilemap, 0, 0);
        CopyToBgTilemapBuffer(1, gPokedexScreenSelectBarMain_Tilemap, 0, 0);
        // Exact Emerald Hoenn palette, independent of the list screen's freed
        // view. Preserve transparent entry 0 as the native loader does.
        LoadPalette(gPokedexBgHoenn_Pal + 1, 1, sizeof(u16) * (6 * 16 - 1));
        if (HasCompanion())
        {
            sPortrait = CreateMonPicSprite(GetMonData(&sMon, MON_DATA_SPECIES), IsMonShiny(&sMon),
                sMon.box.personality, TRUE, MON_PAGE_X, MON_PAGE_Y, 0, TAG_NONE);
            if (sPortrait >= MAX_SPRITES) sPortrait = SPRITE_NONE;
            else gSprites[sPortrait].oam.priority = 0;
        }
        Draw();
        CopyBgTilemapBufferToVram(1);
        CopyBgTilemapBufferToVram(2);
        CopyBgTilemapBufferToVram(3);
        SetGpuReg(REG_OFFSET_BLDCNT, 0); SetGpuReg(REG_OFFSET_BLDALPHA, 0); SetGpuReg(REG_OFFSET_BLDY, 0);
        SetGpuReg(REG_OFFSET_DISPCNT, DISPCNT_OBJ_ON | DISPCNT_OBJ_1D_MAP);
        ShowBg(1); ShowBg(2); ShowBg(3);
        CreateTask(Task_Input, 0);
        BeginNormalPaletteFade(PALETTES_ALL, 0, 16, 0, RGB_BLACK);
        gHelixPokedexView.open = TRUE;
        SetVBlankCallback(VBlankCB);
        SetMainCallback2(MainCB);
        break;
    }
}
