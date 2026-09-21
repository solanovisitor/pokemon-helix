#ifndef GUARD_HELIX_SETTINGS_H
#define GUARD_HELIX_SETTINGS_H

#include "constants/helix_settings.h"

struct HelixSettingsMailbox
{
    u32 magic;
    u16 version;
    u16 status;
    u32 request;
    u16 operation;
    u16 argument;
    u32 revision;
    u16 connectivity;
    u16 account;
    u16 microphone;
    u16 timezoneMode;
    s16 utcOffset;
    u16 localMinute;
    u16 result;
    u16 capabilities;
    u16 language;
    u16 reserved;
    u16 voiceEnabled;
    u16 timezoneIndex;
    u16 openrouterKey;
    u16 elevenlabsKey;
};

// Sanitized display state, separate from the untrusted transport mailbox.
struct HelixSettingsView
{
    u32 revision;
    u16 connectivity;
    u16 account;
    u16 microphone;
    u16 timezoneMode;
    s16 utcOffset;
    u16 localMinute;
    u16 result;
    u16 capabilities;
    u16 available;
    u16 pending;
    u16 language;
    u16 reserved;
    u16 voiceEnabled;
    u16 timezoneIndex;
    u16 openrouterKey;
    u16 elevenlabsKey;
};

extern const volatile u16 gHelixSettingsAbi[2];
extern volatile struct HelixSettingsMailbox gHelixSettingsMailbox;
extern struct HelixSettingsView gHelixSettingsView;
extern u16 gHelixSettingsPage;
extern u16 gHelixSettingsSelection;
extern u16 gHelixSettingsSubmenu;
extern u16 gHelixSettingsSubselection;

void HelixSettings_Open(void);
void HelixSettings_Close(void);
bool32 HelixSettings_Update(void);
bool32 HelixSettings_Request(u16 operation, u16 argument);

#endif
