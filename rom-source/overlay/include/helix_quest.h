#ifndef GUARD_HELIX_QUEST_H
#define GUARD_HELIX_QUEST_H

// Emerald-only permanent unused flags 020..02F; not temp/daily flags.
// Reserve two existing bytes without changing SaveBlock1 geometry.
#define HELIX_QUEST_FIRST_FLAG 0x20
#define HELIX_QUEST_MAGIC 0x5000
#define HELIX_QUEST_MAGIC_MASK 0xFE00
#define HELIX_QUEST_INVALID 0xFFFF

// Actions in VAR_0x8006. Effects are authored, never external-model commands.
#define HELIX_QUEST_ACCEPT 1
#define HELIX_QUEST_SCRATCHES 2
#define HELIX_QUEST_REFERENCE 3
#define HELIX_QUEST_GUIDE_REPORT 4
#define HELIX_QUEST_HYPOTHESIS_JOINT 5
#define HELIX_QUEST_HYPOTHESIS_MOVED 6
#define HELIX_QUEST_PREPARE 7
#define HELIX_QUEST_OBSERVE 8
#define HELIX_QUEST_LOCK 9
#define HELIX_QUEST_SPLIT 10

// Menu ID in VAR_0x8007; option results are zero-based, B returns 127.
#define HELIX_QUEST_MENU_GUIDE 1
#define HELIX_QUEST_MENU_POST 2
#define HELIX_QUEST_MENU_SIGN 3
#define HELIX_QUEST_MENU_TEST 4
#define HELIX_QUEST_MENU_HYPOTHESIS 5
#define HELIX_QUEST_MENU_SOLUTION 6

// Text page in VAR_0x8005. Pages 0..22 retain fixture insertion order.
#define HELIX_QUEST_PAGE_OFFER 0
#define HELIX_QUEST_PAGE_DECLINED 1
#define HELIX_QUEST_PAGE_ACCEPTED 2
#define HELIX_QUEST_PAGE_SCRATCHES 3
#define HELIX_QUEST_PAGE_GUIDE 4
#define HELIX_QUEST_PAGE_REFERENCE 5
#define HELIX_QUEST_PAGE_JOINT 6
#define HELIX_QUEST_PAGE_MOVED 7
#define HELIX_QUEST_PAGE_NAUTIL_PREPARE 8
#define HELIX_QUEST_PAGE_NAUTIL_TEST 9
#define HELIX_QUEST_PAGE_FERRO_PREPARE 10
#define HELIX_QUEST_PAGE_FERRO_TEST 11
#define HELIX_QUEST_PAGE_UNAVAILABLE 12
#define HELIX_QUEST_PAGE_NEED_CLUES 13
#define HELIX_QUEST_PAGE_CANCELLED 14
#define HELIX_QUEST_PAGE_RESUME 15
#define HELIX_QUEST_PAGE_CHOOSE 16
#define HELIX_QUEST_PAGE_LOCK_PLAN 17
#define HELIX_QUEST_PAGE_SPLIT_PLAN 18
#define HELIX_QUEST_PAGE_LOCK_RESULT 19
#define HELIX_QUEST_PAGE_SPLIT_RESULT 20
#define HELIX_QUEST_PAGE_LOCK_HOOK 21
#define HELIX_QUEST_PAGE_SPLIT_HOOK 22
#define HELIX_QUEST_PAGE_INVALID 23
#define HELIX_QUEST_PAGE_NOTES 24
#define HELIX_QUEST_PAGE_NOT_STARTED 25
#define HELIX_QUEST_PAGE_NEED_TEST 26
#define HELIX_QUEST_PAGE_PREPARE 27
#define HELIX_QUEST_PAGE_TEST 28
#define HELIX_QUEST_PAGE_RESULT 29

struct HelixQuestView
{
    u16 raw, stage, clues, hypothesis, method, resolution;
    u16 prepared, phase, menu, inspection, recipe;
};
extern struct HelixQuestView gHelixQuestView;
extern const u32 gHelixQuestSaveLayout[4];
extern const u16 gHelixQuestDescriptor[6];
void GetHelixQuestState(void);
void GetHelixQuestLocation(void);
void CommitHelixQuestAction(void);
void BufferHelixQuestText(void);
void ShowHelixQuestMenu(void);
void ClearHelixQuestPreview(void);

#endif
