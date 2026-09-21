#ifndef GUARD_HELIX_LAB_BRIDGE_H
#define GUARD_HELIX_LAB_BRIDGE_H
// Only this bounded mailbox is writable by the optional lab transport.
struct HelixLabMailbox {
    u32 magic;
    u16 version, status;
    u32 epoch, request;
    u16 model, raw, condition, prediction, recipe, reserved;
    u8 saveKey[16], individual[32];
    u32 bindingCrc, contextCrc;
    u16 result, signal, span, control;
};
extern volatile struct HelixLabMailbox gHelixLabMailbox;
extern u16 gHelixLabBridgeLastResult;
void StartHelixLabSimulation(void);
#endif
