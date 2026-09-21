#ifndef GUARD_HELIX_LAB_ITEMS_H
#define GUARD_HELIX_LAB_ITEMS_H

#define HELIX_LAB_ITEMS_FIRST_FLAG 0x40
#define HELIX_LAB_ITEMS_MAGIC 0x7000
// Stable observer ABI, all fields are u16. Preparation is RAM-only.
struct HelixLabItemsView
{
    u16 raw, stage, condition, prediction, recipe, prepared;
    u16 phase, menu, inspection, medium, reader, resident;
};
extern struct HelixLabItemsView gHelixLabItemsView;
extern const u32 gHelixLabItemsSaveLayout[4];
extern const u16 gHelixLabItemsDescriptor[8];
void GetHelixLabItemsState(void);
void CommitHelixLabItemsAction(void);
void BufferHelixLabItemsText(void);
void ShowHelixLabItemsMenu(void);
void ClearHelixLabItemsPreview(void);
bool32 HelixLabItemsValidateRequest(u16 raw, u16 condition, u16 prediction);
bool32 HelixLabItemsApplyResult(u16 raw, u16 condition, u16 prediction, u16 result);
const u8 *HelixLabItemsItemName(u16 item);
const u8 *HelixLabItemsItemDescription(u16 item);

#endif
