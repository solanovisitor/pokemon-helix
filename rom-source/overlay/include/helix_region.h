#ifndef GUARD_HELIX_REGION_H
#define GUARD_HELIX_REGION_H

struct HelixRegionView
{
    u16 raw, state, phase, inspection, recipe, utility, care;
};
extern struct HelixRegionView gHelixRegionView;
void GetHelixRegionState(void);
void CheckHelixRegionCompanion(void);
void CommitHelixRegionAction(void);
void BufferHelixRegionText(void);
void GetHelixUtilityState(void);
void GetHelixCareState(void);

#endif
