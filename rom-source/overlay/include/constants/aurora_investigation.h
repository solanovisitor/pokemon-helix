#ifndef GUARD_CONSTANTS_AURORA_INVESTIGATION_H
#define GUARD_CONSTANTS_AURORA_INVESTIGATION_H

#include "constants/aurora_adventure_content.h"

// Authored progress only. Generated dialogue/art cannot change these states.
#define AURORA_QUEST_UNMET 0
#define AURORA_QUEST_RELAY 1
#define AURORA_QUEST_RELAY_READ 2
#define AURORA_QUEST_NORTH_SIGNAL 3
#define AURORA_QUEST_NORTH_DECODED 4
#define AURORA_QUEST_HOME_ANSWERED 5
#define AURORA_QUEST_COMPLETE 6

// Separate chapter: never reinterpret completed original investigation (6)
// or the lab's successfully awarded clue (VAR_AURORA_LAB_CLUE == 1).
#define AURORA_NORTH_UNMET 0
#define AURORA_NORTH_ACCEPTED 1
#define AURORA_NORTH_BATTLE_WON 2
#define AURORA_NORTH_COMPLETE 3
#define AURORA_NORTH_REED 1
#define AURORA_NORTH_STONE 2
#define AURORA_NORTH_ALL_CLUES 3

#endif
