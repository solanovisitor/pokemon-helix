#include "global.h"
#include <stddef.h>
#include "helix_settings.h"

STATIC_ASSERT(sizeof(struct HelixSettingsMailbox) == 48, HelixSettingsMailboxSize);
STATIC_ASSERT(offsetof(struct HelixSettingsMailbox, status) == 6, HelixSettingsStatusOffset);
STATIC_ASSERT(offsetof(struct HelixSettingsMailbox, revision) == 16, HelixSettingsRevisionOffset);
STATIC_ASSERT(offsetof(struct HelixSettingsMailbox, capabilities) == 34, HelixSettingsCapabilitiesOffset);
STATIC_ASSERT(offsetof(struct HelixSettingsMailbox, language) == 36, HelixSettingsLanguageOffset);
STATIC_ASSERT(sizeof(struct HelixSettingsView) == 36, HelixSettingsViewSize);
STATIC_ASSERT(offsetof(struct HelixSettingsView, available) == 20, HelixSettingsAvailableOffset);
STATIC_ASSERT(offsetof(struct HelixSettingsView, language) == 24, HelixSettingsViewLanguageOffset);

const volatile u16 gHelixSettingsAbi[2] = {HELIX_SETTINGS_VERSION, sizeof(struct HelixSettingsMailbox)};

EWRAM_DATA volatile struct HelixSettingsMailbox gHelixSettingsMailbox = {0};
EWRAM_DATA struct HelixSettingsView gHelixSettingsView = {0};
EWRAM_DATA u16 gHelixSettingsPage = 0;
EWRAM_DATA u16 gHelixSettingsSelection = 0;
EWRAM_DATA u16 gHelixSettingsSubmenu = 0;
EWRAM_DATA u16 gHelixSettingsSubselection = 0;
STATIC_ASSERT(offsetof(struct HelixSettingsMailbox, voiceEnabled) == 40, HelixSettingsVoiceOffset);
STATIC_ASSERT(offsetof(struct HelixSettingsMailbox, elevenlabsKey) == 46, HelixSettingsKeyOffset);
STATIC_ASSERT(offsetof(struct HelixSettingsView, voiceEnabled) == 28, HelixSettingsViewVoiceOffset);
static EWRAM_DATA u32 sRequest = 0;
static EWRAM_DATA u32 sRevision = 0;
static EWRAM_DATA u16 sOperation = 0;
static EWRAM_DATA u16 sArgument = 0;
static EWRAM_DATA u16 sWaiting = 0;
static EWRAM_DATA u16 sAge = 0;
static EWRAM_DATA u16 sRefresh = 0;
static EWRAM_DATA bool8 sOpen = FALSE;

static void SafeView(u16 result)
{
    // No host acknowledgement means no known local clock or permission grant.
    gHelixSettingsView.revision = 0;
    gHelixSettingsView.connectivity = 0;
    gHelixSettingsView.account = 0;
    gHelixSettingsView.microphone = 0;
    gHelixSettingsView.timezoneMode = 0;
    gHelixSettingsView.utcOffset = 0;
    gHelixSettingsView.localMinute = HELIX_SETTINGS_UNKNOWN_MINUTE;
    gHelixSettingsView.result = result;
    gHelixSettingsView.capabilities = 0;
    gHelixSettingsView.available = FALSE;
    // Retain only the last acknowledged display language in this RAM session.
    // It is not connectivity or permission; fresh boots still default to EN.
    if (gHelixSettingsView.language > 1)
        gHelixSettingsView.language = 0;
    gHelixSettingsView.reserved = 0;
    gHelixSettingsView.voiceEnabled = 0;
    gHelixSettingsView.timezoneIndex = 0;
    gHelixSettingsView.openrouterKey = 0;
    gHelixSettingsView.elevenlabsKey = 0;
}

static void FinishUnavailable(u16 result)
{
    SafeView(result);
    gHelixSettingsView.pending = FALSE;
    gHelixSettingsMailbox.status = HELIX_SETTINGS_IDLE;
    sRefresh = 0;
}

bool32 HelixSettings_Request(u16 operation, u16 argument)
{
    if (gHelixSettingsAbi[1] != 48 || !sOpen || gHelixSettingsView.pending || sRequest == 0xFFFFFFFF)
        return FALSE;
    if (operation < HELIX_SETTINGS_QUERY || operation > HELIX_SETTINGS_REMOVE_KEY
        || argument > (operation == HELIX_SETTINGS_SET_TIMEZONE ? HELIX_SETTINGS_TIMEZONE_COUNT - 1
            : operation == HELIX_SETTINGS_SET_INTERNET || operation == HELIX_SETTINGS_SET_MICROPHONE
            || operation == HELIX_SETTINGS_SET_LANGUAGE || operation == HELIX_SETTINGS_SET_VOICE
            || operation == HELIX_SETTINGS_IMPORT_COPIED_KEY || operation == HELIX_SETTINGS_REMOVE_KEY ? 1 : 0)
        || (operation != HELIX_SETTINGS_QUERY && !gHelixSettingsView.available))
        return FALSE;
    sRequest++;
    sOperation = operation;
    sArgument = argument;
    sRevision = gHelixSettingsView.revision;
    sWaiting = 0;
    gHelixSettingsView.pending = TRUE;
    gHelixSettingsMailbox.status = HELIX_SETTINGS_IDLE;
    gHelixSettingsMailbox.magic = HELIX_SETTINGS_MAGIC;
    gHelixSettingsMailbox.version = HELIX_SETTINGS_VERSION;
    gHelixSettingsMailbox.request = sRequest;
    gHelixSettingsMailbox.operation = operation;
    gHelixSettingsMailbox.argument = argument;
    gHelixSettingsMailbox.revision = sRevision;
    gHelixSettingsMailbox.reserved = 0;
    // Publishing last prevents the adapter from seeing a partial request.
    gHelixSettingsMailbox.status = HELIX_SETTINGS_REQUEST;
    return TRUE;
}

void HelixSettings_Open(void)
{
    HelixSettings_Close();
    sOpen = TRUE;
    sAge = sRefresh = 0;
    HelixSettings_Request(HELIX_SETTINGS_QUERY, 0);
}

void HelixSettings_Close(void)
{
    sOpen = FALSE;
    FinishUnavailable(HELIX_SETTINGS_UNAVAILABLE);
}

static bool32 ValidResponse(const struct HelixSettingsMailbox *response)
{
    return response->magic == HELIX_SETTINGS_MAGIC
        && response->version == HELIX_SETTINGS_VERSION
        && response->status == HELIX_SETTINGS_RESPONSE
        && response->request == sRequest
        && response->operation == sOperation
        && response->argument == sArgument
        && (sOperation == HELIX_SETTINGS_QUERY || response->revision >= sRevision
            || response->result == HELIX_SETTINGS_CONFLICT)
        && response->connectivity <= 1 && response->account <= 1
        && response->microphone <= 4 && response->timezoneMode <= 2
        && response->utcOffset >= -840 && response->utcOffset <= 840
        && (response->localMinute <= 1439 || response->localMinute == HELIX_SETTINGS_UNKNOWN_MINUTE)
        && response->result <= HELIX_SETTINGS_INVALID
        && response->capabilities <= 7
        && response->language <= 1 && response->reserved == 0
        && response->voiceEnabled <= 1
        && (response->timezoneIndex < HELIX_SETTINGS_TIMEZONE_COUNT || response->timezoneIndex == HELIX_SETTINGS_CUSTOM_TIMEZONE)
        && response->openrouterKey <= 3 && response->elevenlabsKey <= 3
        && (!response->account || (response->capabilities & HELIX_SETTINGS_CAP_ACCOUNT));
}

bool32 HelixSettings_Update(void)
{
    bool32 changed = FALSE;
    if (!sOpen)
        return FALSE;
    if (sAge < HELIX_SETTINGS_TIMEOUT)
        sAge++;
    if (gHelixSettingsView.available && sAge >= HELIX_SETTINGS_TIMEOUT)
    {
        SafeView(HELIX_SETTINGS_UNAVAILABLE);
        changed = TRUE;
    }
    if (gHelixSettingsView.pending)
    {
        if (gHelixSettingsMailbox.status == HELIX_SETTINGS_RESPONSE)
        {
            struct HelixSettingsMailbox response = gHelixSettingsMailbox;
            if (!ValidResponse(&response))
            {
                FinishUnavailable(HELIX_SETTINGS_INVALID);
                return TRUE;
            }
            gHelixSettingsView.revision = response.revision;
            gHelixSettingsView.connectivity = response.connectivity;
            gHelixSettingsView.account = response.account;
            gHelixSettingsView.microphone = response.microphone;
            gHelixSettingsView.timezoneMode = response.timezoneMode;
            gHelixSettingsView.utcOffset = response.utcOffset;
            gHelixSettingsView.localMinute = response.localMinute;
            gHelixSettingsView.result = response.result;
            gHelixSettingsView.capabilities = response.capabilities;
            gHelixSettingsView.language = response.language;
            gHelixSettingsView.voiceEnabled = response.voiceEnabled;
            gHelixSettingsView.timezoneIndex = response.timezoneIndex;
            gHelixSettingsView.openrouterKey = response.openrouterKey;
            gHelixSettingsView.elevenlabsKey = response.elevenlabsKey;
            gHelixSettingsView.reserved = 0;
            gHelixSettingsView.available = TRUE;
            gHelixSettingsView.pending = FALSE;
            sAge = sRefresh = 0;
            gHelixSettingsMailbox.status = HELIX_SETTINGS_IDLE;
            return TRUE;
        }
        if (gHelixSettingsMailbox.status != HELIX_SETTINGS_REQUEST || ++sWaiting >= HELIX_SETTINGS_TIMEOUT)
        {
            FinishUnavailable(HELIX_SETTINGS_UNAVAILABLE);
            return TRUE;
        }
    }
    else if (++sRefresh >= HELIX_SETTINGS_REFRESH)
    {
        sRefresh = 0;
        changed |= HelixSettings_Request(HELIX_SETTINGS_QUERY, 0);
    }
    return changed;
}
