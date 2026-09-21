#include "global.h"
#include "aurora_title.h"
#include "bg.h"
#include "berry_fix_program.h"
#include "clear_save_data_menu.h"
#include "event_data.h"
#include "gpu_regs.h"
#include "main.h"
#include "main_menu.h"
#include "menu.h"
#include "palette.h"
#include "reset_rtc_screen.h"
#include "scanline_effect.h"
#include "sound.h"
#include "sprite.h"
#include "task.h"
#include "text.h"
#include "trig.h"
#include "window.h"
#include "m4a.h"
#include "constants/rgb.h"
#include "constants/songs.h"

// The model-composed Helix title is converted once; no native logo or panel
// covers its art. BG2's 8bpp tiles end below 0xA000. Maps live at 0xB000/B800;
// text uses charblock 3, so its 495 4bpp tiles fit below 0x10000.
#include "data/helix_generated_title.h"
const u32 gHelixGeneratedTitleDescriptor[] = {1, 240, 160, 601, 38464, 2048, 512, 15};
const u8 gHelixGeneratedTitleSourceHash[] = HELIX_GENERATED_TITLE_SOURCE_BYTES;
const u32 gHelixGeneratedTitleTiles[] = INCBIN_U32("graphics/helix_generated_title/night.8bpp");
const u16 gHelixGeneratedTitleMap[] = INCBIN_U16("graphics/helix_generated_title/night.bin");
const u16 gHelixGeneratedTitlePalette[] = INCBIN_U16("graphics/helix_generated_title/night.gbapal");
#define sCoastTiles gHelixGeneratedTitleTiles
#define sCoastMap gHelixGeneratedTitleMap
#define sCoastPalette gHelixGeneratedTitlePalette

enum { AURORA_REVEAL = 1, AURORA_TITLE, AURORA_CREDITS, AURORA_LEAVING };
EWRAM_DATA u16 gAuroraTitlePhase = 0;
EWRAM_DATA u16 gAuroraTitleFrame = 0;
static EWRAM_DATA u16 sTextMap[32 * 32] = {0};
static EWRAM_DATA MainCallback sNextCallback = NULL;
static EWRAM_DATA u8 sTitleLightColors[4] = {0};
static EWRAM_DATA u8 sTitleLoopBlend = 0;
static void AnimateCoastLights(void);
static void InitializeTitleMotion(void);
static void PrepareTitleMotion(void);
static void CopyTitleMotionToVram(void);

// Model-generated sprite phases are composited and quantized before compilation.
// Playback selects one immutable ROM slice; no image processing runs per frame.
#include "data/helix_title_sprite_frames.h"
const u32 gHelixTitleSpriteFrames[] = INCBIN_U32("graphics/helix_title_sprite_frames/frames.8bpp");
const u32 gHelixTitleSpriteDescriptor[] =
{
    1, HELIX_TITLE_SPRITE_FRAME_COUNT, HELIX_TITLE_SPRITE_FRAME_TICKS,
    HELIX_TITLE_SPRITE_FRAME_BYTES, HELIX_TITLE_SPRITE_REGION_COUNT,
};
STATIC_ASSERT(sizeof(gHelixTitleSpriteFrames) == HELIX_TITLE_SPRITE_FRAME_COUNT * HELIX_TITLE_SPRITE_FRAME_BYTES, HelixTitleSpriteFrameSize);
STATIC_ASSERT(HELIX_TITLE_SPRITE_FRAME_COUNT > 0 && HELIX_TITLE_SPRITE_FRAME_TICKS > 0, HelixTitleSpriteTiming);
const struct
{
    u8 tileX, tileY, width, height;
} gHelixTitleSpriteRegions[] = HELIX_TITLE_SPRITE_REGIONS;
#define sTitleMotionRegions gHelixTitleSpriteRegions
STATIC_ASSERT(sizeof(gHelixTitleSpriteRegions[0]) == 4, HelixTitleSpriteRegionSize);
STATIC_ASSERT(ARRAY_COUNT(sTitleMotionRegions) == HELIX_TITLE_SPRITE_REGION_COUNT, HelixTitleSpriteRegionCount);
static EWRAM_DATA u16 sTitleMotionTicks = 0;
static EWRAM_DATA u16 sTitleMotionFrame = 0;
static EWRAM_DATA volatile bool8 sTitleMotionPending = FALSE;

static const struct BgTemplate sBgs[] =
{
    {.bg = 0, .charBaseIndex = 3, .mapBaseIndex = 22, .priority = 0},
    {.bg = 2, .charBaseIndex = 0, .mapBaseIndex = 23, .paletteMode = 1, .priority = 2},
};
static const struct WindowTemplate sWindows[] =
{
    {.bg = 0, .tilemapLeft = 2, .tilemapTop = 1, .width = 26, .height = 19,
     .paletteNum = 15, .baseBlock = 1},
    DUMMY_WIN_TEMPLATE,
};
static const u16 sTextPalette[] =
{
    RGB_BLACK, RGB(30, 30, 27), RGB(1, 3, 6), RGB(15, 28, 26),
};
static const u8 sTextColors[] = {0, 1, 2};
static const u8 sAccentColors[] = {0, 3, 2};
static const u8 sTitle[] = _("POKéMON HELIX");
static const u8 sControls[] = _("START: PLAY   SELECT: INFO");
static const u8 sAuroraCredit[] = _("Noite Aurora: AI-generated art");
static const u8 sFanProject[] = _("Independent fan project");
static const u8 sOriginalGame[] = _("ORIGINAL: POKéMON EMERALD");
static const u8 sGameFreak[] = _("GAME FREAK");
static const u8 sPokemonCredit[] = _("Pokémon: Nintendo / Creatures /");
static const u8 sRhhCredit[] = _("Engine: RHH pokeemerald-expansion");
static const u8 sPretCredit[] = _("Decompilation: pret/pokeemerald");
static const u8 sCreditsReturn[] = _("A / B / SELECT: BACK");

static void VBlank_AuroraTitle(void)
{
    LoadOam();
    ProcessSpriteCopyRequests();
    CopyTitleMotionToVram();
    TransferPlttBuffer();
}

static void PrintCentered(const u8 *text, u32 top, bool32 accent)
{
    u32 width = GetStringWidth(FONT_SMALL, text, 0);
    AddTextPrinterParameterized3(0, FONT_SMALL, (208 - width) / 2, top,
                                 accent ? sAccentColors : sTextColors, TEXT_SKIP_DRAW, text);
}

static void ShowTitleText(void)
{
    FillWindowPixelBuffer(0, PIXEL_FILL(0));
    // This transparent last-row hint stays below the generated characters.
    PrintCentered(sControls, 137, TRUE);
    CopyWindowToVram(0, COPYWIN_FULL);
}

static void ShowCredits(void)
{
    gAuroraTitlePhase = AURORA_CREDITS;
    sTitleMotionPending = FALSE;
    HideBg(2);
    FillWindowPixelBuffer(0, PIXEL_FILL(0));
    PrintCentered(sTitle, 0, TRUE);
    PrintCentered(sAuroraCredit, 16, FALSE);
    PrintCentered(sFanProject, 28, FALSE);
    PrintCentered(sOriginalGame, 48, TRUE);
    PrintCentered(sGameFreak, 60, FALSE);
    PrintCentered(sPokemonCredit, 72, FALSE);
    PrintCentered(sGameFreak, 84, FALSE);
    PrintCentered(sRhhCredit, 104, FALSE);
    PrintCentered(sPretCredit, 116, FALSE);
    PrintCentered(sCreditsReturn, 130, TRUE);
    CopyWindowToVram(0, COPYWIN_FULL);
}

static void FinishReveal(void)
{
    LoadPalette(sCoastPalette, 0, 224 * sizeof(u16));
    sTitleLoopBlend = 0;
    AnimateCoastLights();
    InitializeTitleMotion();
    gAuroraTitlePhase = AURORA_TITLE;
    SetGpuReg(REG_OFFSET_DISPCNT, DISPCNT_MODE_0 | DISPCNT_BG0_ON | DISPCNT_BG2_ON);
    ShowTitleText();
}

static void LeaveTitle(MainCallback next)
{
    gAuroraTitlePhase = AURORA_LEAVING;
    sTitleMotionPending = FALSE;
    sNextCallback = next;
    FadeOutBGM(4);
    BeginNormalPaletteFade(PALETTES_ALL, 0, 0, 16, RGB_BLACK);
}

static u32 TitleLightBand(u32 x, u32 y)
{
    // Only existing luminous pixels inside the hologram, screens, incubator
    // and two aurora strips can animate. Keep the wordmark/characters still.
    if (x >= 105 && x <= 135 && y >= 55 && y <= 94)
        return (y - 55) / 15;
    if ((x >= 48 && x <= 65 && y >= 60 && y <= 70)
     || (x >= 179 && x <= 195 && y >= 60 && y <= 70)
     || (x >= 10 && x <= 31 && y >= 78 && y <= 104)
     || (x >= 31 && x <= 67 && y >= 1 && y <= 22)
     || (x >= 175 && x <= 205 && y >= 1 && y <= 22))
        return 3;
    return 4;
}

static void PrepareTitleLightTiles(void)
{
    const u8 *original = (const u8 *)sCoastTiles;
    u16 counts[224] = {0};
    u32 x, y, i, j;

    for (y = 0; y < 160; y++)
    for (x = 0; x < 240; x++)
    {
        u32 index = original[(1 + y / 8 * 30 + x / 8) * 64 + y % 8 * 8 + x % 8];
        u32 color = sCoastPalette[index];
        u32 r = color & 31;
        u32 g = (color >> 5) & 31;
        u32 b = (color >> 10) & 31;
        if (TitleLightBand(x, y) < 4 && index < 224
            && g >= 14 && b >= 14 && min(g, b) > r + 3)
            counts[index]++;
    }
    for (i = 0; i < 4; i++)
    {
        u32 best = sAuroraLightIndices[i % ARRAY_COUNT(sAuroraLightIndices)];
        for (j = 1; j < 224; j++)
            if (counts[j] > counts[best])
                best = j;
        sTitleLightColors[i] = best;
        counts[best] = 0;
    }
    for (y = 0; y < 20; y++)
    for (x = 0; x < 30; x++)
    {
        u32 tile = 1 + y * 30 + x;
        u16 words[32];
        u8 *pixels = (u8 *)words;
        bool32 changed = FALSE;
        CpuCopy16(original + tile * 64, words, sizeof(words));
        for (i = 0; i < 64; i++)
        {
            u32 band = TitleLightBand(x * 8 + i % 8, y * 8 + i / 8);
            if (band >= 4)
                continue;
            for (j = 0; j < 4; j++)
                if (pixels[i] == sTitleLightColors[j])
                {
                    pixels[i] = 224 + band * 4 + j;
                    changed = TRUE;
                    break;
                }
        }
        // GBA VRAM requires halfword writes, even for 8bpp tile pixels.
        if (changed)
            CpuCopy16(words, (u8 *)BG_CHAR_ADDR(0) + tile * 64, sizeof(words));
    }
}

static u16 TitleLoopColor(u16 color, u8 phase)
{
    u32 strength = 112 + (Sin(phase, 128) + 128) * 144 / 256;
    // Blend at full precision before RGB555 rounding, so the stronger pulse
    // still changes each channel by at most one level during its entry blend.
    strength = 256 * 64 - (256 - strength) * sTitleLoopBlend;
    return RGB((color & 31) * strength / (256 * 64),
               ((color >> 5) & 31) * strength / (256 * 64),
               ((color >> 10) & 31) * strength / (256 * 64));
}

static void AnimateCoastLights(void)
{
    u16 colors[16];
    u32 band, i;
    for (band = 0; band < 4; band++)
    for (i = 0; i < 4; i++)
    {
        // Ambient monitors, incubator and aurora visibly breathe every 256
        // native frames. Slots 224..239 isolate this from art/text colors.
        u8 phase = band == 3 ? gAuroraTitleFrame + 80 : gAuroraTitleFrame - band * 40;
        u32 source = sCoastPalette[sTitleLightColors[i]];
        colors[band * 4 + i] = TitleLoopColor(source, phase);
    }
    LoadPalette(colors, 224, sizeof(colors));
    // Start at the exact reveal color, then ease into the moving light over
    // 64 frames. A saturating counter avoids restarting at frame wraparound.
    if (sTitleLoopBlend < 64)
        sTitleLoopBlend++;
}

static u16 TitleRevealColor(u16 color, u32 frame)
{
    u32 r = color & 31;
    u32 g = (color >> 5) & 31;
    u32 b = (color >> 10) & 31;
    u32 delay = 0;
    u32 progress;

    // Illuminate existing pixels only: room first, then amber lamps/lettering,
    // then the cyan hologram and monitors. No color exceeds its source value.
    if (r >= 16 && r >= g && g > b + 4)
        delay = 24;
    else if (g >= 14 && b >= 14 && min(g, b) > r + 3)
        delay = 60;
    progress = frame > delay ? min(frame - delay, 72) : 0;
    return RGB(r * progress / 72, g * progress / 72, b * progress / 72);
}

static void AnimateTitleReveal(void)
{
    u16 colors[240];
    u32 i;
    for (i = 0; i < 224; i++)
        colors[i] = TitleRevealColor(sCoastPalette[i], gAuroraTitleFrame);
    for (i = 224; i < ARRAY_COUNT(colors); i++)
        colors[i] = TitleRevealColor(sCoastPalette[sTitleLightColors[i % 4]], gAuroraTitleFrame);
    LoadPalette(colors, 0, sizeof(colors));
}

static void InitializeTitleMotion(void)
{
    sTitleMotionPending = FALSE;
    __asm__ volatile("" ::: "memory");
    sTitleMotionTicks = 0;
    sTitleMotionFrame = 0;
    __asm__ volatile("" ::: "memory");
    sTitleMotionPending = TRUE;
}

static void PrepareTitleMotion(void)
{
    // One bounded counter update per native frame. A ROM frame is uploaded only
    // when its hold ends; the independent counter wraps at the sequence length.
    if (++sTitleMotionTicks < HELIX_TITLE_SPRITE_FRAME_TICKS)
        return;
    sTitleMotionPending = FALSE;
    __asm__ volatile("" ::: "memory");
    sTitleMotionTicks = 0;
    if (++sTitleMotionFrame == HELIX_TITLE_SPRITE_FRAME_COUNT)
        sTitleMotionFrame = 0;
    __asm__ volatile("" ::: "memory");
    sTitleMotionPending = TRUE;
}

static void CopyTitleMotionToVram(void)
{
    u32 region, row;
    const u8 *source;
    if (!sTitleMotionPending)
        return;
    source = (const u8 *)gHelixTitleSpriteFrames + sTitleMotionFrame * HELIX_TITLE_SPRITE_FRAME_BYTES;
    for (region = 0; region < ARRAY_COUNT(sTitleMotionRegions); region++)
    for (row = 0; row < sTitleMotionRegions[region].height; row++)
    {
        u32 destination = 1 + (sTitleMotionRegions[region].tileY + row) * 30
            + sTitleMotionRegions[region].tileX;
        u32 bytes = sTitleMotionRegions[region].width * 64;
        CpuCopy16(source, (u8 *)BG_CHAR_ADDR(0) + destination * 64, bytes);
        source += bytes;
    }
    sTitleMotionPending = FALSE;
}

static void MainCB2_AuroraTitle(void)
{
    if (gAuroraTitlePhase == AURORA_LEAVING)
    {
        if (!UpdatePaletteFade())
        {
            SetVBlankCallback(NULL);
            FreeAllWindowBuffers();
            if (sNextCallback == CB2_InitBerryFixProgram)
                m4aMPlayAllStop();
            SetMainCallback2(sNextCallback);
        }
        return;
    }
    gAuroraTitleFrame++;
    if (gAuroraTitlePhase == AURORA_CREDITS)
    {
        if (JOY_NEW(A_BUTTON | B_BUTTON | SELECT_BUTTON))
        {
            ShowBg(2);
            FinishReveal();
        }
        else if (JOY_NEW(START_BUTTON))
            LeaveTitle(CB2_InitMainMenu);
        return;
    }

    // Preserve Emerald's maintenance shortcuts as well as normal Continue/New
    // Game. No title state is written into a save or a companion mailbox.
    if (JOY_HELD(B_BUTTON | SELECT_BUTTON | DPAD_UP) == (B_BUTTON | SELECT_BUTTON | DPAD_UP))
        LeaveTitle(CB2_InitClearSaveDataScreen);
    else if (JOY_HELD(B_BUTTON | SELECT_BUTTON | DPAD_LEFT) == (B_BUTTON | SELECT_BUTTON | DPAD_LEFT)
          && CanResetRTC())
        LeaveTitle(CB2_InitResetRtcScreen);
    else if (JOY_HELD(B_BUTTON | SELECT_BUTTON) == (B_BUTTON | SELECT_BUTTON))
        LeaveTitle(CB2_InitBerryFixProgram);
    else if (JOY_NEW(A_BUTTON | START_BUTTON))
        LeaveTitle(CB2_InitMainMenu);
    else if (gAuroraTitlePhase == AURORA_REVEAL)
    {
        AnimateTitleReveal();
        if (gAuroraTitleFrame >= 156 || JOY_NEW(B_BUTTON | SELECT_BUTTON))
            FinishReveal();
    }
    else if (JOY_NEW(SELECT_BUTTON))
        ShowCredits();
    else
    {
        AnimateCoastLights();
        PrepareTitleMotion();
    }
}

void CB2_InitAuroraTitleScreen(void)
{
    SetVBlankCallback(NULL);
    sTitleMotionPending = FALSE;
    SetHBlankCallback(NULL);
    SetGpuReg(REG_OFFSET_DISPCNT, 0);
    SetGpuReg(REG_OFFSET_BLDCNT, 0);
    SetGpuReg(REG_OFFSET_BLDALPHA, 0);
    SetGpuReg(REG_OFFSET_BLDY, 0);
    CpuFill32(0, (void *)VRAM, VRAM_SIZE);
    CpuFill32(0, (void *)OAM, OAM_SIZE);
    ScanlineEffect_Stop();
    ResetTasks();
    ResetSpriteData();
    FreeAllSpritePalettes();
    ResetPaletteFade();
    ResetBgsAndClearDma3BusyFlags(0);
    InitBgsFromTemplates(0, sBgs, ARRAY_COUNT(sBgs));
    ChangeBgX(0, 0, BG_COORD_SET);
    ChangeBgY(0, 0, BG_COORD_SET);
    ChangeBgX(2, 0, BG_COORD_SET);
    ChangeBgY(2, 0, BG_COORD_SET);
    CpuCopy32(sCoastTiles, (void *)BG_CHAR_ADDR(0), sizeof(sCoastTiles));
    PrepareTitleLightTiles();
    CpuCopy16(sCoastMap, (void *)BG_SCREEN_ADDR(23), sizeof(sCoastMap));
    LoadPalette(sCoastPalette, 0, sizeof(sCoastPalette));
    LoadPalette(sTextPalette, BG_PLTT_ID(15), sizeof(sTextPalette));
    gAuroraTitleFrame = 0;
    AnimateTitleReveal();
    CpuFill16(0, sTextMap, sizeof(sTextMap));
    SetBgTilemapBuffer(0, sTextMap);
    InitWindows(sWindows);
    DeactivateAllTextPrinters();
    FillWindowPixelBuffer(0, PIXEL_FILL(0));
    PutWindowTilemap(0);
    CopyWindowToVram(0, COPYWIN_FULL);
    ShowBg(0);
    ShowBg(2);
    SetGpuReg(REG_OFFSET_DISPCNT, DISPCNT_MODE_0 | DISPCNT_BG0_ON | DISPCNT_BG2_ON);
    gAuroraTitlePhase = AURORA_REVEAL;
    gAuroraTitleFrame = 0;
    BuildOamBuffer();
    SetVBlankCallback(VBlank_AuroraTitle);
    PlayBGM(MUS_LITTLEROOT);
    SetMainCallback2(MainCB2_AuroraTitle);
}
