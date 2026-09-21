# Desktop lab bridge source

`lab.lua` is the existing bounded LAB1 transport for desktop mGBA. It expects
an explicitly prepared `BRIDGE_CONFIG` with `session`, `lab_mailbox`, `port`
and the **exact** compiled ROM's `rom_crc32`. There is deliberately no public
loader containing the historical ROM's memory addresses or checksum.

A future isolated public gameplay package must derive mailbox addresses from
its matching ELF, pin its own ROM, initialize the other native host protocols,
and verify real mGBA behavior before this transport can be described as usable
gameplay. Do not load it against an arbitrary ROM or a retained player save.

The service listens on loopback. Connect is outside the frame callback;
callbacks perform bounded nonblocking transport and mailbox work. The native
side revalidates result/context before consuming inventory. This source does
not add a scripting frontend to libretro mGBA or prove an RG34XX adapter.
