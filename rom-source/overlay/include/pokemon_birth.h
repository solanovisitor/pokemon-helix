#ifndef GUARD_POKEMON_BIRTH_H
#define GUARD_POKEMON_BIRTH_H

#include "global.h"

struct Pokemon;
struct PokemonSubstruct0;
struct PokemonSubstruct1;
struct SiiRtcInfo;

struct PokemonBirthDate
{
    u16 year;
    u8 month;
    u8 day;
};

// One-based day since 2000-01-01; zero means unknown. Calendar, never UTC.
#define POKEMON_BIRTH_DATE_MAX 36525
extern const u32 gPokemonBirthDateDescriptor[6];
u16 PokemonBirthDateFromCalendar(u16 year, u8 month, u8 day);
bool32 PokemonBirthDateToCalendar(u16 date, struct PokemonBirthDate *out);
u32 PokemonBirthDatePack(u32 date);
u16 PokemonBirthDateUnpack(u32 packed);
u32 PokemonBirthDateRaw(const struct PokemonSubstruct0 *growth, const struct PokemonSubstruct1 *moves);
bool32 PokemonBirthDateWrite(struct PokemonSubstruct0 *growth, struct PokemonSubstruct1 *moves, u32 date);
u16 PokemonBirthDateFromRtc(const struct SiiRtcInfo *rtc);
u16 PokemonBirthDateToday(void);
void RecordMonBirthDate(struct Pokemon *mon);

#endif
