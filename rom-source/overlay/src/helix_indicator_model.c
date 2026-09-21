#include "helix_indicator_model.h"

// The guard precedes multiplication. For admitted s <= 1000:
// s*s <= 1,000,000; denominator <= 1,250,000;
// 80*s*s + denominator/2 <= 80,625,000, strictly below UINT32_MAX.
// Unsigned integer division implements the frozen half-up rounding exactly.
bool8 HelixIndicatorSignal(u32 stimulus, u16 *signal)
{
    u32 square, denominator, numerator;
    if (signal == NULL || stimulus > HELIX_INDICATOR_MAX_STIMULUS)
        return FALSE;
    square = stimulus * stimulus;
    denominator = 250000u + square;
    numerator = 80u * square + denominator / 2u;
    *signal = 10u + numerator / denominator;
    return TRUE;
}

bool8 HelixIndicatorAssay(u16 condition, u16 prediction,
                         struct HelixIndicatorAssayResult *result)
{
    struct HelixIndicatorAssayResult calculated;
    u32 baseline, i;
    if (result == NULL
        || (condition != HELIX_INDICATOR_SHELTERED && condition != HELIX_INDICATOR_EXPOSED)
        || (prediction != HELIX_INDICATOR_STABLE && prediction != HELIX_INDICATOR_SENSITIVE))
        return FALSE;

    baseline = condition == HELIX_INDICATOR_SHELTERED ? 50u : 500u;
    calculated.result = condition;
    for (i = 0; i < 3; i++)
    {
        calculated.stimuli[i] = baseline - 50u + 50u * i;
        if (!HelixIndicatorSignal(calculated.stimuli[i], &calculated.values[i]))
            return FALSE;
    }
    if (!HelixIndicatorSignal(0, &calculated.control))
        return FALSE;
    calculated.signal = calculated.values[1];
    calculated.span = calculated.values[2] - calculated.values[0];
    calculated.predictionMatch = prediction == condition;
    *result = calculated;
    return TRUE;
}
