# Quest agents and player choices

Helix's direction is a continuous journey: NPC motives, field observations and
earlier choices should support quests that remain coherent across conversations.
A generic **director** plans a bounded quest thread; a **curator** reviews reusable
definitions and their provenance. These are authoring responsibilities, not
player-facing characters or permission to change a save.

## Current boundary

The native source contains prepared quest and laboratory logic. Host authoring
tools can produce candidates under explicit contracts; see
[agent tools](agent-tools.md). A generated candidate is not a dynamically loaded
quest. Persistent agent-directed quest threads and an in-game
`ask_user_question` capability still need their own implementation and exact-ROM
proof. The public export does not yet provide a complete playable Helix package.

## Intended interaction

A quest thread should carry one understandable purpose through a small sequence
of conversations and actions. NPCs should respond to the player's actual stage,
previous decisions and relevant observations. Repeated contact should continue
the thread or revisit its result without duplicating rewards.

Use an `ask_user_question`-style tool for a question and a small fixed menu of
choices. Each visible choice should contain **two or three words**. The GBA flow
uses buttons, not free-text entry. Stable choice IDs carry meaning; labels are
localized presentation. Cancellation, returning later and stale questions need
explicit behavior. A timeout or rejected proposal must not select for the player.

The director receives a bounded public dossier and proposes the next permitted
step. It does not execute scripts, select filesystem paths, assign ownership or
grant arbitrary effects. The native game rechecks stage, revision, eligibility
and any cost before committing an admitted choice. Nonpublic authoring material
must stay out of provider context and player-facing output.

## Tool results and reuse

| Result | Meaning |
| --- | --- |
| `pending` | No usable result yet. An uncertain provider outcome is retained without automatic duplicate spending. |
| `rejected` | The request or result failed its contract. Return a bounded reason, preserve player state and do not reflect rejected content. |
| `ready` | The declared candidate checks passed. The result must state its scope; this does not imply visual approval, native admission or successful gameplay. |

Cache identity should bind the complete request, producer, validation policy and
relevant source versions. Replay verifies retained bytes and avoids regeneration.
Identical-request replay is not semantic matching of different descriptions.

Reusable public definitions and content-addressed art can serve multiple players.
A player's quest instance, choices, save lineage, ownership and individual IDs
remain separate. Reusing art does not duplicate an individual's identity or
transfer ownership. A shared semantic catalog and curator admission workflow
remain future work; retain original provenance when adding new producers.

## Required end-to-end proof

An increment needs one complete path: approved context → validated proposal →
native question → button choice → admitted effect → ordinary Save/Continue →
coherent follow-up. Also exercise cancellation, malformed output, stale state,
duplicate delivery, provider absence and replay without another effect.

Run the exact compiled public candidate with synthetic identities in mGBA.
Inspect screenshots together with state assertions and isolated ordinary saves.
Source checks, mocked agents and successful compilation answer narrower
questions. Linux ARM64 Docker does not prove RG34XX controls, saving, suspend or
power-loss behavior; physical-device evidence remains separate.
