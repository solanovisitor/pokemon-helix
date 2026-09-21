# Working agreements

- Read README.md and the relevant public docs before editing.
- Use uv and the locked Python environment. Default to deterministic fixtures.
- Keep C/event code in rom-source, emulator glue in Lua, host work in Python.
- Preserve the pinned RHH/pret upstream history and notices.
- Treat host/model output as bounded data, never executable authority.
- Keep networking and computation off the emulator frame loop.
- Never commit ROMs, saves, credentials, personal data or private authoring stores.
- Native changes need an exact build identity, inspected mGBA screenshots,
  state assertions and isolated ordinary Save/Continue tests before play claims.
- Do not reuse local accepted identities or saves for public fixtures.
- V14 is the accepted local default; V15c/V16b/V17c are candidates. CORAL stays blocked.
- Keep docs short and distinguish implemented behavior, proposals and unknowns.
