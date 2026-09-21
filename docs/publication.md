# Public checkout and updates

This repository is an intentional export from the Helix development workspace.
Its history begins with the reviewed public kickstart; local operator history,
private stores, generated packages and retained game evidence are not copied.
The engine's complete upstream Git history is fetched separately by
`scripts/bootstrap-game.py`, at the exact revision in `rom-source/manifest.json`.

The runnable boundary is the deterministic synthetic host demo, its tests and
the local lab service. Native source is provided as a reviewed text patch plus
an explicit overlay. The local accepted packages are absent and the public
fixture identities cannot be used with accepted/local saves. See
[native reproduction limits](../rom-source/README.md).

## Maintainer update workflow

1. Create a branch in this public repository. Select source changes by explicit
   path; never copy a development tree, asset collection or artifacts directory.
2. Review origin, license and privacy before copying. Keep examples synthetic
   and all user data outside Git. Keep new native fixtures in the public namespace.
3. For native updates, regenerate the text patch against the pinned upstream,
   update overlay/result hashes and the bootstrap digest in the native manifest.
   Preserve upstream notices. Never install retained local packages into this export.
4. Update `public-files.txt` deliberately when paths change. Run `make test`,
   `make smoke`, the container smoke and `uv run python scripts/check-public.py`.
   Inspect `git diff --cached` and the full history of anything being pushed.
5. Verify the documented quickstart in a new clone with a new environment.
   Native behavior claims additionally need a new compiled-ROM mGBA run with
   screenshots, state assertions and isolated Save/Continue checks.
6. Submit a PR with scope and evidence. Keep local acceptance and public CI
   results distinct; update [verification](verification.md) only with actual results.

CI uses read-only repository permission and pinned actions. It runs no emulator,
inference, publishing, deployments or ROM uploads. The filename/secret/link
checks are bounded safeguards, not a guarantee that every future contribution
is safe. Human review remains necessary.
