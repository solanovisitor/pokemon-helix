#include "global.h"
#include "helix_universal.h"
#include "helix_settings.h"
#include "pokemon.h"
#include "pokemon_storage_system.h"
#include "random.h"
#include "event_data.h"
#include "string_util.h"
#include "constants/characters.h"

STATIC_ASSERT(sizeof(struct HelixUniversalRecord) == 36, HelixUniversalRecordBytes);
STATIC_ASSERT(sizeof(struct HelixUniversalStore) == 1472, HelixUniversalStoreBytes);
STATIC_ASSERT(sizeof(struct BoxPokemon) == 80, HelixUniversalBoxUnchanged);
STATIC_ASSERT(sizeof(struct Pokemon) == 100, HelixUniversalPartyUnchanged);

EWRAM_DATA struct HelixUniversalView gHelixUniversalView = {0};
EWRAM_DATA struct HelixUniversalView gHelixUniversalEncounter = {0};
EWRAM_DATA u32 gHelixUniversalMigrationStatus = 0;
EWRAM_DATA u32 gHelixUniversalMigrated = 0;

const u32 gHelixUniversalDescriptor[8] = {
    HELIX_UNIVERSAL_VERSION, HELIX_UNIVERSAL_SCHEMA, HELIX_UNIVERSAL_ALGORITHM,
    HELIX_UNIVERSAL_GENOME_BYTES, 96, 2, 16, HELIX_UNIVERSAL_CAPACITY,
};
const u32 gHelixUniversalSaveLayout[16] = {
    offsetof(struct SaveBlock3, helixUniversal), sizeof(struct HelixUniversalStore),
    sizeof(struct HelixUniversalRecord), offsetof(struct HelixUniversalStore, records),
    offsetof(struct HelixUniversalStore, crc), sizeof(struct SaveBlock3),
    sizeof(struct BoxPokemon), sizeof(struct Pokemon),
    TOTAL_BOXES_COUNT, IN_BOX_COUNT, PARTY_SIZE, sizeof(struct HelixUniversalView),
    SPECIES_WINGULL, SPECIES_PELIPPER, HELIX_UNIVERSAL_MAGIC, 116,
};

static bool32 IsSupported(u16 species)
{
    return species == SPECIES_WINGULL || species == SPECIES_PELIPPER;
}

static struct HelixUniversalStore *Store(void)
{
    return &gSaveBlock3Ptr->helixUniversal;
}

static void SealStore(void)
{
    Store()->crc = HelixUniversalStoreCrc(Store());
}

static void InitializeStore(void)
{
    u32 i;
    struct HelixUniversalStore *store = Store();
    memset(store, 0, sizeof(*store));
    store->magic = HELIX_UNIVERSAL_MAGIC;
    store->version = HELIX_UNIVERSAL_VERSION;
    store->schema = HELIX_UNIVERSAL_SCHEMA;
    store->algorithm = HELIX_UNIVERSAL_ALGORITHM;
    store->nextSerial = 1;
    // Sampling happens once at explicit New Game/Continue migration, never in
    // rendering. Emerald's RNG is not a global uniqueness or entropy authority.
    for (i = 0; i < 3; i++) store->namespace[i] = Random32();
    if (!(store->namespace[0] | store->namespace[1] | store->namespace[2])) store->namespace[2] = 1;
    SealStore();
}

void HelixUniversalNewGame(void)
{
    // ClearSav3 has already cleared this new game's data, never an older save.
    InitializeStore();
    memset(&gHelixUniversalView, 0, sizeof(gHelixUniversalView));
    memset(&gHelixUniversalEncounter, 0, sizeof(gHelixUniversalEncounter));
    gHelixUniversalMigrationStatus = HELIX_UNIVERSAL_OK;
    gHelixUniversalMigrated = 0;
}

static s32 FindRecord(const struct BoxPokemon *mon, u8 tag)
{
    u32 i;
    for (i = 0; i < Store()->count; i++)
        if (Store()->records[i].personality == mon->personality
            && Store()->records[i].otId == mon->otId && Store()->records[i].tag == tag)
            return i;
    return -1;
}

static u8 AvailableTag(const struct BoxPokemon *mon)
{
    u32 i, used = 1;
    for (i = 0; i < Store()->count; i++)
        if (Store()->records[i].personality == mon->personality && Store()->records[i].otId == mon->otId)
            used |= 1 << Store()->records[i].tag;
    for (i = 1; i < 8; i++) if ((0x96 & (1 << i)) && !(used & (1 << i))) return i;
    return 0;
}

static void AppendRecord(struct BoxPokemon *mon, u16 species, u8 tag, u8 origin)
{
    struct HelixUniversalRecord *record = &Store()->records[Store()->count];
    u32 i;
    memset(record, 0, sizeof(*record));
    record->serial = Store()->nextSerial++;
    record->personality = mon->personality;
    record->otId = mon->otId;
    for (i = 0; i < 4; i++) record->seed[i] = Random32();
    if (!(record->seed[0] | record->seed[1] | record->seed[2] | record->seed[3])) record->seed[3] = 1;
    record->sourceSpecies = species;
    record->origin = origin;
    record->tag = tag;
    record->crc = HelixUniversalCrc32((const u8 *)record, 32);
    HelixUniversalWriteTag(mon, tag); // Preflight guarantees a valid untagged mon.
    Store()->count++;
}

static struct BoxPokemon *OwnedMon(u32 slot)
{
    if (slot < PARTY_SIZE) return &gParties[B_TRAINER_PLAYER][slot].box;
    slot -= PARTY_SIZE;
    return GetBoxedMonPtr(slot / IN_BOX_COUNT, slot % IN_BOX_COUNT);
}

void HelixUniversalContinue(void)
{
    struct { struct BoxPokemon *mon; u16 species; u8 tag; } plan[HELIX_UNIVERSAL_CAPACITY];
    u8 seen[HELIX_UNIVERSAL_CAPACITY] = {0};
    u32 status = HelixUniversalValidateStore(Store()), i, j, count = 0, used;
    u16 species;
    u8 tag;
    s32 record;
    struct BoxPokemon *mon;
    bool32 empty = status == HELIX_UNIVERSAL_EMPTY;
    gHelixUniversalMigrated = 0;
    memset(&gHelixUniversalEncounter, 0, sizeof(gHelixUniversalEncounter));
    if (!empty && status != HELIX_UNIVERSAL_OK) goto done;
    // Complete preflight before allocating a namespace, touching any Pokémon or
    // migrating any entry. No partial migration on full/corrupt/ambiguous data.
    for (i = 0; i < PARTY_SIZE + TOTAL_BOXES_COUNT * IN_BOX_COUNT; i++)
    {
        mon = OwnedMon(i);
        if (!mon->hasSpecies || mon->isEgg) continue;
        if (!HelixUniversalReadBox(mon, &species, &tag))
        {
            status = HELIX_UNIVERSAL_CORRUPT;
            goto done;
        }
        if (!IsSupported(species)) continue;
        if (tag)
        {
            record = empty ? -1 : FindRecord(mon, tag);
            if (record < 0) { status = HELIX_UNIVERSAL_UNREGISTERED; goto done; }
            if (seen[record]++) { status = HELIX_UNIVERSAL_DUPLICATE; goto done; }
            continue;
        }
        if (count + (empty ? 0 : Store()->count) >= HELIX_UNIVERSAL_CAPACITY)
        { status = HELIX_UNIVERSAL_FULL; goto done; }
        used = 1;
        if (!empty)
            for (j = 0; j < Store()->count; j++)
                if (Store()->records[j].personality == mon->personality && Store()->records[j].otId == mon->otId)
                {
                    // A previously registered locator losing its tag is not a
                    // newly discovered legacy mon. Do not silently reidentify.
                    status = HELIX_UNIVERSAL_UNREGISTERED;
                    goto done;
                }
        for (j = 0; j < count; j++)
            if (plan[j].mon->personality == mon->personality && plan[j].mon->otId == mon->otId)
                used |= 1 << plan[j].tag;
        for (tag = 1; tag < 8; tag++) if ((0x96 & (1 << tag)) && !(used & (1 << tag))) break;
        if (tag == 8) { status = HELIX_UNIVERSAL_COLLISION; goto done; }
        plan[count].mon = mon;
        plan[count].species = species;
        plan[count++].tag = tag;
    }
    if (!empty && (Store()->nextSerial == 0xFFFFFFFF || count > 0xFFFFFFFF - Store()->nextSerial))
    { status = HELIX_UNIVERSAL_FULL; goto done; }
    if (empty) InitializeStore();
    for (i = 0; i < count; i++) AppendRecord(plan[i].mon, plan[i].species, plan[i].tag, HELIX_UNIVERSAL_LEGACY);
    if (count) SealStore();
    gHelixUniversalMigrated = count;
    status = HELIX_UNIVERSAL_OK;
done:
    gHelixUniversalMigrationStatus = status;
}

static u32 CountOwnedLocator(const struct BoxPokemon *mon, u8 tag)
{
    u32 i, count = 0;
    u16 species;
    u8 otherTag;
    struct BoxPokemon *other;
    for (i = 0; i < PARTY_SIZE + TOTAL_BOXES_COUNT * IN_BOX_COUNT; i++)
    {
        other = OwnedMon(i);
        if (other->hasSpecies && other->personality == mon->personality && other->otId == mon->otId
            && HelixUniversalReadBox(other, &species, &otherTag) && otherTag == tag) count++;
    }
    return count;
}

u32 HelixUniversalInspect(const struct BoxPokemon *mon, struct HelixUniversalView *view)
{
    u16 species;
    u8 tag;
    s32 index;
    const struct HelixUniversalRecord *record;
    memset(view, 0, sizeof(*view));
    view->status = HelixUniversalValidateStore(Store());
    if (view->status != HELIX_UNIVERSAL_OK) return view->status;
    view->count = Store()->count;
    if (!HelixUniversalReadBox(mon, &species, &tag)) return view->status = HELIX_UNIVERSAL_CORRUPT;
    view->species = species;
    if (!IsSupported(species)) return view->status = HELIX_UNIVERSAL_UNSUPPORTED;
    index = FindRecord(mon, tag);
    if (!tag || index < 0) return view->status = HELIX_UNIVERSAL_UNREGISTERED;
    if (CountOwnedLocator(mon, tag) > 1) return view->status = HELIX_UNIVERSAL_DUPLICATE;
    record = &Store()->records[index];
    view->origin = record->origin;
    memcpy(view->namespace, Store()->namespace, sizeof(view->namespace));
    view->serial = record->serial;
    memcpy(view->seed, record->seed, sizeof(view->seed));
    HelixUniversalExpandGenome(record->seed, view->genome);
    view->genomeCrc = HelixUniversalCrc32(view->genome, sizeof(view->genome));
    return view->status;
}

void HelixUniversalRegisterEncounter(struct BoxPokemon *mon)
{
    u32 status;
    u16 species;
    u8 tag;
    memset(&gHelixUniversalEncounter, 0, sizeof(gHelixUniversalEncounter));
    if (!HelixUniversalReadBox(mon, &species, &tag)) status = HELIX_UNIVERSAL_CORRUPT;
    else if (!IsSupported(species)) status = HELIX_UNIVERSAL_UNSUPPORTED;
    else if ((status = HelixUniversalValidateStore(Store())) != HELIX_UNIVERSAL_OK) { }
    else if (tag) { HelixUniversalInspect(mon, &gHelixUniversalEncounter); return; }
    else if (Store()->count >= HELIX_UNIVERSAL_CAPACITY || Store()->nextSerial == 0xFFFFFFFF)
        status = HELIX_UNIVERSAL_FULL;
    else if (!(tag = AvailableTag(mon))) status = HELIX_UNIVERSAL_COLLISION;
    else
    {
        AppendRecord(mon, species, tag, HELIX_UNIVERSAL_ENCOUNTER);
        SealStore();
        HelixUniversalInspect(mon, &gHelixUniversalEncounter);
        gHelixUniversalEncounter.location = 2; // Observed wild encounter, before capture.
        return;
    }
    // Registration failure never blocks/replaces an ordinary encounter or capture.
    // No ID/DNA is claimed for that unsupported encounter.
    gHelixUniversalEncounter.status = status;
}

static void Hex8(u8 *out, u32 value)
{
    static const u8 digits[] = _("0123456789ABCDEF");
    u32 i;
    for (i = 0; i < 8; i++) out[i] = digits[(value >> (28 - i * 4)) & 15];
    out[8] = EOS;
}

void HelixUniversalInspectFirst(void)
{
    u32 i;
    u16 species;
    u8 tag;
    struct BoxPokemon *mon;
    struct BoxPokemon copy;
    memset(&gHelixUniversalView, 0, sizeof(gHelixUniversalView));
    gSpecialVar_Result = HELIX_UNIVERSAL_NONE;
    gSpecialVar_0x8004 = gHelixSettingsView.language == 1;
    gSpecialVar_0x8005 = 0;
    for (i = 0; i < PARTY_SIZE + TOTAL_BOXES_COUNT * IN_BOX_COUNT; i++)
    {
        mon = OwnedMon(i);
        if (!HelixUniversalReadBox(mon, &species, &tag) || !IsSupported(species)) continue;
        gSpecialVar_Result = HelixUniversalInspect(mon, &gHelixUniversalView);
        gSpecialVar_0x8005 = gHelixUniversalView.origin;
        gHelixUniversalView.location = i < PARTY_SIZE ? 0 : 1;
        gHelixUniversalView.slot = i < PARTY_SIZE ? i : i - PARTY_SIZE;
        copy = *mon;
        GetBoxMonData(&copy, MON_DATA_NICKNAME, gStringVar1);
        Hex8(gStringVar2, gHelixUniversalView.serial);
        Hex8(gStringVar3, gHelixUniversalView.genomeCrc);
        return;
    }
}
