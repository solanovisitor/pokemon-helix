#ifndef GUARD_HELIX_SIGNAL_H
#define GUARD_HELIX_SIGNAL_H

struct BoxPokemon;
enum {
    HELIX_SIGNAL_INVALID,
    HELIX_SIGNAL_READY,
    HELIX_SIGNAL_BOXED,
    HELIX_SIGNAL_FAINTED,
    HELIX_SIGNAL_MISSING,
    HELIX_SIGNAL_PENDING,
};
u16 HelixSignalInspect(struct BoxPokemon *out);
void GetHelixSignalRoute(void);
void GetHelixSignalReady(void);
void BufferHelixSignalPage(void);

#endif
