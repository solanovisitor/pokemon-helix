#ifndef GUARD_AI_BRIDGE_H
#define GUARD_AI_BRIDGE_H

#include "constants/ai_bridge.h"

// The emulator resolves this symbol in the matching ELF. All fields are
// little-endian. Publish status last; responseLength excludes the EOS byte.
struct AiBridgeMailbox
{
    u32 magic;
    u16 version;
    u16 status;
    u32 epoch;
    u32 request;
    u16 npc;
    u16 motivation;
    u16 quest;
    u16 responseLength;
    u8 response[AI_BRIDGE_RESPONSE_CAPACITY];
};

extern volatile struct AiBridgeMailbox gAiBridgeMailbox;
extern u16 gAiBridgeLastResult;
extern u16 gAiBridgeConversationActive;
extern const u32 gAiBridgeSaveOffsets[2];

void RequestIvoDialogue(void);
void RequestLabDialogue(void);
void EndAiDialogue(void);

#endif
