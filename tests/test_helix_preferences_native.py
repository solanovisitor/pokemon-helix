"""Public C preference checks with a synthetic save layout and host compiler.

No ROM, accepted save, private audit, launcher or emulator is loaded. The C
sources are compiled directly from the reviewed public overlay, unchanged.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "rom-source/overlay"

GLOBAL = r'''
#ifndef INDEPENDENT_GLOBAL_H
#define INDEPENDENT_GLOBAL_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32;
typedef int16_t s16; typedef int32_t s32;
typedef uint8_t bool8; typedef uint32_t bool32;
#define EWRAM_DATA
#define TRUE 1
#define FALSE 0
#define STATIC_ASSERT(a,b) _Static_assert(a,#b)
struct SaveBlock3 {
    u8 previous[1476];
    struct {u16 signature;u8 language,complement;} helixLanguage;
};
extern struct SaveBlock3 *gSaveBlock3Ptr;
#endif
'''

HARNESS = r'''
#include "global.h"
#include "helix_preferences.h"
#include "helix_settings.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
static struct SaveBlock3 save;
struct SaveBlock3 *gSaveBlock3Ptr=&save;

static void Initialize(void) {
    memset(&save,0,sizeof(save));
    for(u32 i=0;i<1476;i++)save.previous[i]=(i*17u+13u)&255;
}
static void PrefixIntact(void) {
    for(u32 i=0;i<1476;i++)assert(save.previous[i]==((i*17u+13u)&255));
}
static void RefusesUnknown(void) {
    struct SaveBlock3 before=save;
    assert(HelixPreferences_LoadLanguage()==0);
    assert(!memcmp(&before,&save,sizeof(save)));
    assert(!HelixPreferences_SetLanguage(0));
    assert(!HelixPreferences_SetLanguage(1));
    assert(!memcmp(&before,&save,sizeof(save)));
}
static void Preferences(void) {
    Initialize();struct SaveBlock3 before=save;
    assert(HelixPreferences_LoadLanguage()==0&&!memcmp(&save,&before,sizeof(save)));
    assert(gHelixPreferencesSaveLayout[0]==1&&gHelixPreferencesSaveLayout[1]==1476);
    assert(gHelixPreferencesSaveLayout[2]==4&&gHelixPreferencesSaveLayout[3]==1480);
    for(u16 language=0;language<2;language++) {
        Initialize();assert(HelixPreferences_SetLanguage(language));
        assert(save.helixLanguage.signature==0x4c01);
        assert(save.helixLanguage.language==language&&save.helixLanguage.complement==(language^255));
        assert(HelixPreferences_LoadLanguage()==language);PrefixIntact();
        before=save;
        for(u32 at=0;at<4;at++)for(u32 byte=0;byte<256;byte++) {
            save=before;u8 *record=(u8*)&save.helixLanguage;
            if(record[at]==byte)continue;
            record[at]=byte;RefusesUnknown();PrefixIntact();
        }
        save=before;
        for(u32 input=2;input<=65535;input++) {
            assert(!HelixPreferences_SetLanguage(input));assert(!memcmp(&before,&save,sizeof(save)));
        }
        assert(HelixPreferences_SetLanguage(1-language));
        assert(HelixPreferences_LoadLanguage()==1-language);PrefixIntact();
    }
    for(u32 signature=0;signature<=65535;signature++) {
        if(signature==0x4c01)continue;
        Initialize();save.helixLanguage.signature=signature;
        save.helixLanguage.language=1;save.helixLanguage.complement=254;
        RefusesUnknown();
    }
    for(u32 language=2;language<=255;language++) {
        Initialize();save.helixLanguage.signature=0x4c01;
        save.helixLanguage.language=language;save.helixLanguage.complement=language^255;
        RefusesUnknown();
    }
    Initialize();memset(&save.helixLanguage,255,4);RefusesUnknown();
}
static void Reply(u16 language) {
    gHelixSettingsMailbox.revision=41;gHelixSettingsMailbox.connectivity=1;
    gHelixSettingsMailbox.account=0;gHelixSettingsMailbox.microphone=4;
    gHelixSettingsMailbox.timezoneMode=0;gHelixSettingsMailbox.utcOffset=0;
    gHelixSettingsMailbox.localMinute=444;gHelixSettingsMailbox.result=0;
    gHelixSettingsMailbox.capabilities=0;gHelixSettingsMailbox.language=language;
    gHelixSettingsMailbox.voiceEnabled=0;gHelixSettingsMailbox.timezoneIndex=0;
    gHelixSettingsMailbox.openrouterKey=1;gHelixSettingsMailbox.elevenlabsKey=1;
    gHelixSettingsMailbox.status=2;
}
static void Mailbox(void) {
    Initialize();HelixSettings_Close();
    assert(!HelixSettings_Request(8,1)&&save.helixLanguage.signature==0);
    HelixSettings_Open();assert(gHelixSettingsView.pending);
    struct HelixSettingsMailbox request=gHelixSettingsMailbox;
    assert(HelixSettings_Request(8,1));
    assert(gHelixSettingsView.language==1&&gHelixSettingsView.pending);
    assert(!memcmp(&request,(const void*)&gHelixSettingsMailbox,sizeof(request)));
    Reply(0);assert(HelixSettings_Update());
    assert(gHelixSettingsView.language==1&&HelixPreferences_LoadLanguage()==1);
    assert(gHelixSettingsView.available&&!gHelixSettingsView.pending);
    assert(HelixSettings_Request(1,0));
    assert(HelixSettings_Request(8,0));Reply(1);HelixSettings_Update();
    assert(gHelixSettingsView.language==0&&HelixPreferences_LoadLanguage()==0);
    assert(HelixSettings_Request(1,0));assert(HelixSettings_Request(8,1));
    for(u32 frame=0;frame<300;frame++)HelixSettings_Update();
    assert(gHelixSettingsView.language==1&&!gHelixSettingsView.available);
    assert(HelixSettings_Request(8,0));assert(!HelixSettings_Request(8,2));
    assert(HelixPreferences_LoadLanguage()==0&&gHelixSettingsView.language==0);
    HelixSettings_Close();assert(!HelixSettings_Request(8,1));
    assert(HelixPreferences_LoadLanguage()==0);PrefixIntact();
    // A late old response after page close cannot become native authority.
    Reply(1);assert(!HelixSettings_Update());assert(HelixPreferences_LoadLanguage()==0);
    // Unknown versions remain intact even through the public Settings action.
    save.helixLanguage.signature=0x4c02;
    struct SaveBlock3 before=save;HelixSettings_Open();
    assert(!HelixSettings_Request(8,1)&&!memcmp(&before,&save,sizeof(save)));
    HelixSettings_Close();
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"preferences"))Preferences();
    else if(!strcmp(argv[1],"mailbox"))Mailbox();
    else assert(0);
    return 0;
}
'''

class HelixPreferencesNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang") or shutil.which("cc")
        if compiler is None:
            raise RuntimeError("a C compiler is required for native preference checks")
        cls.temporary = tempfile.TemporaryDirectory(prefix="helix-public-preferences-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        (directory / "global.h").write_text(GLOBAL)
        (directory / "case.c").write_text(HARNESS)
        cls.binary = directory / "case"
        result = subprocess.run(
            [compiler, "-std=c17", "-Wall", "-Wextra", "-Werror",
             "-fsanitize=undefined", "-fno-sanitize-recover=all", "-O1",
             "-I" + str(directory), "-I" + str(NATIVE / "include"),
             str(directory / "case.c"),
             str(NATIVE / "src/helix_preferences.c"),
             str(NATIVE / "src/helix_settings.c"), "-o", str(cls.binary)],
            capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_single_byte_corruptions_unknown_versions_and_invalid_choices_preserve_save(self):
        self.run_case("preferences")

    def test_pending_host_timeout_conflicting_query_and_closed_menu_cannot_own_language(self):
        self.run_case("mailbox")


if __name__ == "__main__":
    unittest.main()
