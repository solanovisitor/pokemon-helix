#ifndef GUARD_AURORA_ROSTER_H
#define GUARD_AURORA_ROSTER_H

#include "constants/aurora_roster.h"

#define AURORA_ROSTER_MAGIC 0x31525541
#define AURORA_ROSTER_VERSION 1
#define AURORA_ROSTER_CHILD_ISSUED 1
#define AURORA_ROSTER_ORIGINAL 0
#define AURORA_ROSTER_CHILD 1
#define AURORA_ROSTER_EDIT_SOMATIC 1
#define AURORA_ROSTER_EDIT_GERMLINE 2
#define AURORA_ROSTER_HATCHLING 0
#define AURORA_ROSTER_JUVENILE 1
#define AURORA_ROSTER_MATURE 2
#define AURORA_ROSTER_RESULT_INVALID 5
#define AURORA_ROSTER_RESULT_UPDATED 8
#define AURORA_ROSTER_RESULT_PREVIEW 9
#define AURORA_ROSTER_RESULT_EDITED 10
#define AURORA_ROSTER_RESULT_UNAVAILABLE 11
#define AURORA_ROSTER_RESULT_TOO_YOUNG 12
#define AURORA_ROSTER_SIGNAL_THRESHOLD 8

// Append-only companion to the unchanged 76-byte v1 Lumifin record. Explicit
// rest advances simulated days; neither XP nor time outside the game ages it.
struct AuroraRosterExtension
{
    u32 magic;
    u8 version;
    u8 flags;
    u8 phenotypeRevision;
    u8 genotypeRevision;
    u16 originalDays;
    u16 childDays;
    u32 manifestCrc;
    u8 reserved[8];
    u32 crc;
};

bool32 AuroraRosterValidateExtension(const struct AuroraRosterExtension *record);
u16 AuroraRosterLifeStage(u16 days);
extern const u32 gAuroraRosterSaveLayout[8];
extern const u32 gAuroraRosterDescriptor[8];
extern u16 gAuroraRosterLastResult;
extern u16 gAuroraRosterLastState;
void GetAuroraRosterState(void);
void AdoptAuroraRosterChild(void);
void GetAuroraRosterAge(void);
void BufferAuroraRosterInfo(void);
void RestAuroraRoster(void);
void PreviewAuroraRosterEdit(void);
void CancelAuroraRosterEdit(void);
void CommitAuroraRosterEdit(void);
void GetAuroraRosterSignal(void);

#endif
