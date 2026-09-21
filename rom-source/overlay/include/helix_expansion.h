#ifndef GUARD_HELIX_EXPANSION_H
#define GUARD_HELIX_EXPANSION_H
#define HELIX_EXPANSION_FIRST_FLAG 0x30
#define HELIX_EXPANSION_MAGIC 0x6000
#define HELIX_EXPANSION_INVALID 0xFFFF
// u16 fields, stable observer ABI; coordinates are authored map-local targets.
struct HelixExpansionView { u16 raw, stage, clues, method, resolution, prepared, phase, menu, inspection, recipe; };
extern struct HelixExpansionView gHelixExpansionView;
extern const u32 gHelixExpansionSaveLayout[4];
extern const u16 gHelixExpansionDescriptor[6];
void GetHelixExpansionState(void);
void GetHelixExpansionLayout(void);
void CommitHelixExpansionAction(void);
void BufferHelixExpansionText(void);
void ShowHelixExpansionMenu(void);
void ClearHelixExpansionPreview(void);
#endif
