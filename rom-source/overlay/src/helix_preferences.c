#include "global.h"
#include <stddef.h>
#include "helix_preferences.h"

STATIC_ASSERT(sizeof(gSaveBlock3Ptr->helixLanguage) == 4, HelixLanguageRecordSize);
STATIC_ASSERT(sizeof(struct SaveBlock3) <= 1624, HelixLanguageSaveBudget);

const volatile u16 gHelixPreferencesSaveLayout[4] = {
    1, offsetof(struct SaveBlock3, helixLanguage), 4, sizeof(struct SaveBlock3)
};

static bool32 EmptyRecord(void)
{
    return gSaveBlock3Ptr->helixLanguage.signature == 0
        && gSaveBlock3Ptr->helixLanguage.language == 0
        && gSaveBlock3Ptr->helixLanguage.complement == 0;
}

static bool32 ValidRecord(void)
{
    return gSaveBlock3Ptr->helixLanguage.signature == HELIX_LANGUAGE_SIGNATURE
        && gSaveBlock3Ptr->helixLanguage.language <= 1
        && gSaveBlock3Ptr->helixLanguage.complement == (gSaveBlock3Ptr->helixLanguage.language ^ 0xFF);
}

u16 HelixPreferences_LoadLanguage(void)
{
    // Legacy zero tails and unknown/corrupt records are read-only defaults.
    return gHelixPreferencesSaveLayout[0] == 1 && ValidRecord() ? gSaveBlock3Ptr->helixLanguage.language : 0;
}

bool32 HelixPreferences_SetLanguage(u16 language)
{
    if (language > 1 || (!EmptyRecord() && !ValidRecord()))
        return FALSE;
    gSaveBlock3Ptr->helixLanguage.signature = HELIX_LANGUAGE_SIGNATURE;
    gSaveBlock3Ptr->helixLanguage.language = language;
    gSaveBlock3Ptr->helixLanguage.complement = language ^ 0xFF;
    return TRUE;
}
