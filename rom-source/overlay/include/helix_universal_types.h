#ifndef GUARD_HELIX_UNIVERSAL_TYPES_H
#define GUARD_HELIX_UNIVERSAL_TYPES_H

// Native slice only. These layouts are an append-only save ABI, not species slots.
#define HELIX_UNIVERSAL_CAPACITY 40
#define HELIX_UNIVERSAL_GENOME_BYTES 96
#define HELIX_UNIVERSAL_MAGIC 0x31445548 // HUD1, little endian
#define HELIX_UNIVERSAL_VERSION 1
#define HELIX_UNIVERSAL_SCHEMA 3
#define HELIX_UNIVERSAL_ALGORITHM 1

struct HelixUniversalRecord
{
    u32 serial;
    u32 personality; // Compatibility locator, NEVER the individual's identity.
    u32 otId;        // Compatibility locator; tag distinguishes equal PID/OT.
    u32 seed[4];     // Complete pinned founder reconstruction input, not an ID.
    u16 sourceSpecies;
    u8 origin;      // 1 encountered, 2 legacy; parents explicitly unknown.
    u8 tag;         // Odd-parity codes 1,2,4,7; zero is unregistered.
    u32 crc;        // IEEE CRC32 over bytes 0..31.
};

struct HelixUniversalStore
{
    u32 magic;
    u8 version, schema, algorithm, count;
    u32 nextSerial;
    u32 namespace[3]; // Save-local namespace; copies preserve it. Not global IDs.
    u32 crc;          // IEEE CRC32 over all 1472 bytes with this field zero.
    u32 reserved;     // Must remain zero.
    struct HelixUniversalRecord records[HELIX_UNIVERSAL_CAPACITY];
};

#endif
