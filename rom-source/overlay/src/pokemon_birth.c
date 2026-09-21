#include "global.h"
#include "pokemon.h"
#include "pokemon_birth.h"
#include "rtc.h"

const u32 gPokemonBirthDateDescriptor[6] = {1, 19, 5, 2000, 2099, 36525};
static const u8 sMonthDays[12] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};

static u32 MonthDays(u16 year, u8 month)
{
    // All callers validate month first. The supported century includes 2000.
    return sMonthDays[month - 1] + (month == 2 && year % 4 == 0);
}

u16 PokemonBirthDateFromCalendar(u16 year, u8 month, u8 day)
{
    u32 y, m, result = day;
    if (year < 2000 || year > 2099 || month < 1 || month > 12
        || day < 1 || day > MonthDays(year, month)) return 0;
    for (y = 2000; y < year; y++) result += 365 + (y % 4 == 0);
    for (m = 1; m < month; m++) result += MonthDays(year, m);
    return result;
}

bool32 PokemonBirthDateToCalendar(u16 date, struct PokemonBirthDate *out)
{
    u16 year = 2000;
    u8 month = 1;
    if (!date || date > POKEMON_BIRTH_DATE_MAX || out == NULL) return FALSE;
    while (date > 365 + (year % 4 == 0))
    {
        date -= 365 + (year % 4 == 0);
        year++;
    }
    while (date > MonthDays(year, month)) date -= MonthDays(year, month++);
    out->year = year;
    out->month = month;
    out->day = date;
    return TRUE;
}

u32 PokemonBirthDatePack(u32 date)
{
    return date && date <= POKEMON_BIRTH_DATE_MAX ? (5 << 16) | date : 0;
}

u16 PokemonBirthDateUnpack(u32 packed)
{
    u32 date = packed & 0xFFFF;
    return (packed >> 16) == 5 && date && date <= POKEMON_BIRTH_DATE_MAX ? date : 0;
}

u32 PokemonBirthDateRaw(const struct PokemonSubstruct0 *growth, const struct PokemonSubstruct1 *moves)
{
    return growth->unused_02 | (growth->unused_04 << 6) | (growth->unused_0A << 9)
        | (moves->unused_04 << 11) | (moves->unused_06 << 16);
}

bool32 PokemonBirthDateWrite(struct PokemonSubstruct0 *growth, struct PokemonSubstruct1 *moves, u32 date)
{
    u32 packed = PokemonBirthDatePack(date);
    u32 existing = PokemonBirthDateRaw(growth, moves);
    if (!packed) return FALSE;
    // Even malformed occupied bits belong to an earlier save, never free space.
    if (existing) return existing == packed;
    growth->unused_02 = packed & 63;
    growth->unused_04 = (packed >> 6) & 7;
    growth->unused_0A = (packed >> 9) & 3;
    moves->unused_04 = (packed >> 11) & 31;
    moves->unused_06 = (packed >> 16) & 7;
    return TRUE;
}

static u32 ReadBcd(u8 value)
{
    if ((value & 15) > 9 || (value >> 4) > 9) return 255;
    return (value >> 4) * 10 + (value & 15);
}

u16 PokemonBirthDateFromRtc(const struct SiiRtcInfo *rtc)
{
    u32 year = ReadBcd(rtc->year);
    if (rtc->status & SIIRTCINFO_POWER || !(rtc->status & SIIRTCINFO_24HOUR)
        || year > 99 || ReadBcd(rtc->hour) > 23 || ReadBcd(rtc->minute) > 59
        || ReadBcd(rtc->second) > 59 || rtc->dayOfWeek > 6) return 0;
    // Do not use RtcCheckInfo: upstream indexes month before validating it.
    return PokemonBirthDateFromCalendar(2000 + year, ReadBcd(rtc->month), ReadBcd(rtc->day));
}

u16 PokemonBirthDateToday(void)
{
    struct SiiRtcInfo rtc = {0};
    bool32 valid;
    // RtcGetInfo substitutes 2000-01-01 on failure. Only a successful raw read
    // with no initialization errors can establish a new calendar date.
    if (OW_USE_FAKE_RTC || RtcGetErrorStatus() != 0) return 0;
    RtcDisableInterrupts();
    valid = SiiRtcGetStatus(&rtc) && SiiRtcGetDateTime(&rtc);
    RtcRestoreInterrupts();
    return valid ? PokemonBirthDateFromRtc(&rtc) : 0;
}

void RecordMonBirthDate(struct Pokemon *mon)
{
    u32 date = PokemonBirthDateToday();
    if (date) SetMonData(mon, MON_DATA_DATE_OF_BIRTH, &date);
}
