#ifndef GUARD_HELIX_INDICATOR_MODEL_H
#define GUARD_HELIX_INDICATOR_MODEL_H

#include "global.h"

// Exact native evaluation of helix-indicator-hill-v1. No save, IO, RNG or DNA.
#define HELIX_INDICATOR_MODEL_VERSION 1
#define HELIX_INDICATOR_MAX_STIMULUS 1000
#define HELIX_INDICATOR_SHELTERED 1
#define HELIX_INDICATOR_EXPOSED 2
#define HELIX_INDICATOR_STABLE 1
#define HELIX_INDICATOR_SENSITIVE 2

struct HelixIndicatorAssayResult
{
    u16 result;
    u16 stimuli[3];
    u16 values[3];
    u16 signal;
    u16 span;
    u16 control;
    u16 predictionMatch;
};

// FALSE for a null output, out-of-range stimulus or unsupported protocol.
// On failure the caller's output remains untouched.
bool8 HelixIndicatorSignal(u32 stimulus, u16 *signal);
bool8 HelixIndicatorAssay(u16 condition, u16 prediction,
                         struct HelixIndicatorAssayResult *result);

#endif
