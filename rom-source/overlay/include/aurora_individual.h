#ifndef GUARD_AURORA_INDIVIDUAL_H
#define GUARD_AURORA_INDIVIDUAL_H

#include "constants/aurora_individual.h"
#include "aurora_roster.h"

// Separate from dialogue. All fields little endian; status publishes last.
struct AuroraIndividualMailbox
{
    u32 magic;
    u16 version;
    u16 status;
    u32 epoch;
    u32 request;
    u16 operation;
    u16 payloadLength;
    u8 individualId[12];
    u8 genome[16];
    u8 artHash[32];
    u32 payloadCrc;
    u8 payload[AURORA_INDIVIDUAL_PAYLOAD_SIZE];
};

// Occupies 76 of the existing 104 unused SaveBlock2 Pokedex filler bytes.
// Never alter SaveBlock layouts or overwrite unknown nonzero filler content.
struct AuroraIndividualRecord
{
    u32 magic;
    u16 version;
    u16 flags;
    u8 individualId[12];
    u8 genome[16];
    u8 artHash[32];
    u32 payloadCrc;
    u32 recordCrc;
};

extern volatile struct AuroraIndividualMailbox gAuroraIndividualMailbox;
extern u16 gAuroraIndividualLastResult;
extern u16 gAuroraIndividualViewerOpen;
extern const u32 gAuroraIndividualSaveLayout[3];
extern const u32 gAuroraCompanionLayout[20];
extern u16 gAuroraIndividualPartyState;

u32 AuroraIndividualCrc32(const u8 *data, u32 size);
bool32 AuroraIndividualValidatePayload(const u8 *data, u16 size, u32 crc);
bool32 AuroraIndividualValidateRecord(const struct AuroraIndividualRecord *record);
u16 AuroraIndividualReadState(const u8 *bytes, u32 size);
void GetAuroraIndividualState(void);
void HatchAuroraIndividual(void);
void ShowAuroraIndividual(void);
void GetAuroraIndividualPartyState(void);
void JoinAuroraIndividualParty(void);
void GetAuroraIndividualBattleReady(void);
void GetAuroraIndividualBattleWon(void);

#endif
