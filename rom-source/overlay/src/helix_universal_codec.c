#include "global.h"
#include "helix_universal.h"

// helix-native-founder-v1: xorshift128, unsigned 32-bit wrap, 24 LE words.
// 192 consecutive nibbles: first homolog's 96 loci, then the second homolog.
// Eight linkage groups of twelve loci. This is fictional DNA, never IVs.
void HelixUniversalExpandGenome(const u32 seed[4], u8 genome[HELIX_UNIVERSAL_GENOME_BYTES])
{
    u32 x = seed[0], y = seed[1], z = seed[2], w = seed[3], t, i;
    for (i = 0; i < HELIX_UNIVERSAL_GENOME_BYTES; i += 4)
    {
        t = x ^ (x << 11);
        x = y;
        y = z;
        z = w;
        w = w ^ (w >> 19) ^ t ^ (t >> 8);
        genome[i] = w;
        genome[i + 1] = w >> 8;
        genome[i + 2] = w >> 16;
        genome[i + 3] = w >> 24;
    }
}

static u32 CrcByte(u32 crc, u8 byte)
{
    u32 bit;
    crc ^= byte;
    for (bit = 0; bit < 8; bit++)
        crc = (crc >> 1) ^ ((crc & 1) ? 0xEDB88320 : 0);
    return crc;
}

u32 HelixUniversalCrc32(const u8 *data, u32 size)
{
    u32 crc = 0xFFFFFFFF, i;
    for (i = 0; i < size; i++) crc = CrcByte(crc, data[i]);
    return ~crc;
}

u32 HelixUniversalStoreCrc(const struct HelixUniversalStore *store)
{
    const u8 *data = (const u8 *)store;
    u32 i, crc = 0xFFFFFFFF;
    for (i = 0; i < sizeof(*store); i++)
        crc = CrcByte(crc, (i >= 24 && i < 28) ? 0 : data[i]);
    return ~crc;
}

u32 HelixUniversalValidateStore(const struct HelixUniversalStore *store)
{
    const u8 *bytes = (const u8 *)store;
    u32 i, j, nonzero = 0;
    const struct HelixUniversalRecord *r;
    for (i = 0; i < sizeof(*store); i++) nonzero |= bytes[i];
    if (!nonzero) return HELIX_UNIVERSAL_EMPTY;
    if (store->magic != HELIX_UNIVERSAL_MAGIC || store->version != HELIX_UNIVERSAL_VERSION
        || store->schema != HELIX_UNIVERSAL_SCHEMA || store->algorithm != HELIX_UNIVERSAL_ALGORITHM)
        return HELIX_UNIVERSAL_UNKNOWN;
    if (store->count > HELIX_UNIVERSAL_CAPACITY || !store->nextSerial || store->reserved
        || !(store->namespace[0] | store->namespace[1] | store->namespace[2])
        || store->crc != HelixUniversalStoreCrc(store)) return HELIX_UNIVERSAL_CORRUPT;
    for (i = 0; i < store->count; i++)
    {
        r = &store->records[i];
        if (!r->serial || r->serial >= store->nextSerial
            || (r->tag != 1 && r->tag != 2 && r->tag != 4 && r->tag != 7)
            || !(r->seed[0] | r->seed[1] | r->seed[2] | r->seed[3])
            || (r->origin != HELIX_UNIVERSAL_ENCOUNTER && r->origin != HELIX_UNIVERSAL_LEGACY)
            || (r->sourceSpecies != SPECIES_WINGULL && r->sourceSpecies != SPECIES_PELIPPER)
            || r->crc != HelixUniversalCrc32((const u8 *)r, 32)) return HELIX_UNIVERSAL_CORRUPT;
        for (j = 0; j < i; j++)
            if (r->serial == store->records[j].serial
                || (r->personality == store->records[j].personality
                    && r->otId == store->records[j].otId && r->tag == store->records[j].tag))
                return HELIX_UNIVERSAL_DUPLICATE;
    }
    bytes = (const u8 *)&store->records[store->count];
    for (i = 0; i < (HELIX_UNIVERSAL_CAPACITY - store->count) * sizeof(*r); i++)
        if (bytes[i]) return HELIX_UNIVERSAL_CORRUPT;
    return HELIX_UNIVERSAL_OK;
}
