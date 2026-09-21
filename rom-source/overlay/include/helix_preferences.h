#ifndef GUARD_HELIX_PREFERENCES_H
#define GUARD_HELIX_PREFERENCES_H

// Append-only save record. Signature includes codec version 1.
#define HELIX_LANGUAGE_SIGNATURE 0x4C01
u16 HelixPreferences_LoadLanguage(void);
bool32 HelixPreferences_SetLanguage(u16 language);
extern const volatile u16 gHelixPreferencesSaveLayout[4];

#endif
