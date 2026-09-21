"""Independent read-only decoder for the first Helix native DNA representation.

No save mutation, native issuance or inference. Unsupported codecs fail closed.
"""
from __future__ import annotations

import struct
import zlib
import hashlib

from genetics.universal import GENOME_SCHEMA, Genome

FOUNDER_ALGORITHM = "helix-native-founder-v1"
STORE_BYTES = 1472
RECORD_BYTES = 36
CAPACITY = 40
SAVE_BLOCK_3_OFFSET = 4


def decode_native_mon(raw: bytes, order: bytes) -> dict:
    """Read one exact boxed/party record, retaining every field for migration audit.

    Only the three audited tag bits and the recalculated Pokémon checksum may
    differ during registration. No birth-date bit, battle field or header is
    hidden. Party tail remains part of the invariant when supplied.
    """
    if (not isinstance(raw, bytes) or len(raw) not in (80, 100)
            or not isinstance(order, bytes) or len(order) != 96
            or any(sorted(order[k * 24 + p] for k in range(4)) != [0, 1, 2, 3] for p in range(24))):
        raise ValueError("unsupported native Pokémon/order layout")
    pid, ot = struct.unpack_from("<II", raw)
    key = pid ^ ot
    plain = bytearray(b"".join(struct.pack("<I", word ^ key) for word in struct.unpack("<12I", raw[32:80])))
    if sum(struct.unpack("<24H", plain)) & 0xffff != struct.unpack_from("<H", raw, 28)[0]:
        raise ValueError("native Pokémon checksum mismatch")
    growth = order[pid % 24] * 12
    misc = order[3 * 24 + pid % 24] * 12
    species = struct.unpack_from("<H", plain, growth)[0] & 0x7ff
    if (species == 0 or raw[19] & 5 or struct.unpack_from("<I", plain, misc + 4)[0] & (1 << 30)):
        raise ValueError("empty/egg/bad-egg cannot establish native identity")
    tag = (raw[19] >> 7) | ((raw[31] >> 7) << 1) | (((plain[misc + 11] >> 4) & 1) << 2)
    if tag not in (0, 1, 2, 4, 7):
        raise ValueError("invalid native identity tag parity")
    invariant = bytearray(raw)
    if species in (278, 279):
        invariant[19] &= 0x7f
        invariant[31] &= 0x7f
        invariant[28:30] = bytes(2)
        plain[misc + 11] &= 0xef
        invariant[32:80] = plain
    return {"species": species, "personality": pid, "ot_id": ot, "tag": tag,
            "registration_invariant_hex": invariant.hex(),
            "registration_invariant_sha256": hashlib.sha256(invariant).hexdigest()}


def expand_founder(seed_hex: str, *, algorithm: str = FOUNDER_ALGORITHM,
                   genome_schema: str = GENOME_SCHEMA) -> Genome:
    """Expand LE x/y/z/w words through 24 fixed Marsaglia xorshift128 draws.

    Every draw emits the updated w as four little-endian bytes. Nibbles are
    first homolog then second, low nibble first. No global RNG is touched.
    All-zero seed is decodable (the zero genome); issuance policy is separate.
    """
    if algorithm != FOUNDER_ALGORITHM or genome_schema != GENOME_SCHEMA:
        raise ValueError("unsupported founder reconstruction version")
    if (not isinstance(seed_hex, str) or len(seed_hex) != 32
            or any(c not in "0123456789abcdef" for c in seed_hex)):
        raise ValueError("seed must contain exactly 128 recorded bits")
    x, y, z, w = struct.unpack("<4I", bytes.fromhex(seed_hex))
    output = bytearray()
    for _ in range(24):
        temporary = (x ^ (x << 11)) & 0xffffffff
        x, y, z, w = y, z, w, (w ^ (w >> 19) ^ temporary ^ (temporary >> 8)) & 0xffffffff
        output.extend(w.to_bytes(4, "little"))
    return Genome.from_dict({"schema": GENOME_SCHEMA, "loci": 96, "ploidy": 2,
                             "alleles": 16, "packed_hex": output.hex()})


def decode_store(raw: bytes) -> dict:
    """Decode exact store bytes; preserve unknown/corrupt input by refusing it."""
    if not isinstance(raw, bytes) or len(raw) != STORE_BYTES:
        raise ValueError("native store must contain exactly 1472 bytes")
    if raw == bytes(STORE_BYTES):
        return {"status": "empty", "records": []}
    magic, version, schema, algorithm, count, next_serial = struct.unpack_from("<IBBBBI", raw)
    if (magic, version, schema, algorithm) != (0x31445548, 1, 3, 1):
        raise ValueError("unknown native identity/genome version")
    if (count > CAPACITY or next_serial == 0 or raw[28:32] != bytes(4)
            or raw[12:24] == bytes(12)):
        raise ValueError("corrupt native registry header")
    expected_crc = zlib.crc32(raw[:24] + bytes(4) + raw[28:])
    if struct.unpack_from("<I", raw, 24)[0] != expected_crc:
        raise ValueError("native registry CRC mismatch")
    namespace = raw[12:24].hex()
    records, seen_serials, seen_locators = [], set(), set()
    for index in range(count):
        record = raw[32 + index * RECORD_BYTES:32 + (index + 1) * RECORD_BYTES]
        serial, personality, ot_id, seed, species, origin, tag, crc = struct.unpack("<III16sHBBI", record)
        if (not 0 < serial < next_serial or tag not in (1, 2, 4, 7) or seed == bytes(16)
                or species not in (278, 279) or origin not in (1, 2)
                or zlib.crc32(record[:32]) != crc):
            raise ValueError("corrupt native individual record")
        locator = (personality, ot_id, tag)
        if serial in seen_serials or locator in seen_locators:
            raise ValueError("duplicate native identity or compatibility locator")
        seen_serials.add(serial)
        seen_locators.add(locator)
        genome = expand_founder(seed.hex())
        records.append({"id_codec": "helix-native-id128-v1",
                        "id_hex": namespace + serial.to_bytes(4, "little").hex(),
                        "namespace_hex": namespace, "serial": serial, "personality": personality,
                        "ot_id": ot_id, "tag": tag, "seed_hex": seed.hex(), "source_species": species,
                        "origin": "wild_encounter" if origin == 1 else "legacy_registration",
                        "parents": None, "birth_date": None, "birth_date_note": "read from Pokémon separately",
                        "genome": genome.to_dict(), "genome_sha256": genome.sha256,
                        "genome_crc32": zlib.crc32(genome.pack())})
    if any(raw[32 + count * RECORD_BYTES:]):
        raise ValueError("occupied unused registry tail")
    return {"status": "ok", "namespace_hex": namespace, "next_serial": next_serial,
            "capacity": CAPACITY, "count": count, "records": records, "crc32": expected_crc}


def decode_save_slot(save: bytes, slot: int, sector_sizes: tuple[int, ...], *,
                     store_offset: int = SAVE_BLOCK_3_OFFSET) -> dict:
    """Strict independently selected slot; never guesses newest or repairs input.

    Callers supply 14 main-data lengths from the exact ELF/save layout. Sector
    CRC excludes SB3 upstream, so both outer integrity and registry CRC matter.
    Uniform counters are required even though upstream does not require them.
    """
    if (not isinstance(save, bytes) or len(save) not in (0x20000, 0x20010)
            or type(slot) is not int or slot not in (0, 1)
            or len(sector_sizes) != 14
            or any(type(size) is not int or not 0 <= size <= 3968 or size % 4 for size in sector_sizes)
            or type(store_offset) is not int or not 0 <= store_offset <= 1624 - STORE_BYTES):
        raise ValueError("invalid exact save/slot/layout")
    sectors, counters = {}, set()
    for physical in range(14):
        offset = (slot * 14 + physical) * 4096
        sector = save[offset:offset + 4096]
        logical, checksum, signature, counter = struct.unpack_from("<HHII", sector, 4084)
        if logical >= 14 or logical in sectors or signature != 0x08012025:
            raise ValueError("missing, duplicate or invalid save sector")
        data = sector[:sector_sizes[logical]]
        total = sum(int.from_bytes(data[i:i + 4], "little") for i in range(0, len(data), 4)) & 0xffffffff
        if ((total >> 16) + (total & 0xffff)) & 0xffff != checksum:
            raise ValueError("main save sector checksum mismatch")
        sectors[logical] = sector[3968:4084]
        counters.add(counter)
    if len(counters) != 1:
        raise ValueError("interrupted/mixed save counters; preserve original and select a complete copy")
    counter = counters.pop()
    if counter % 2 != slot:
        raise ValueError("slot/counter binding mismatch")
    block = b"".join(sectors[index] for index in range(14))
    store = decode_store(block[store_offset:store_offset + STORE_BYTES])
    return {"slot": slot, "counter": counter, "store_offset": store_offset, "store": store,
            "save_block_3_hex": block.hex()}
