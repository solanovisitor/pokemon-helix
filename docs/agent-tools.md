# Bounded agent tools

The public host now includes a local LangGraph dialogue runtime, durable draft
producers, a versioned world planner and a visual asset tool. These produce
validated dialogue or candidates. They do not install quests, create accepted
individuals, mint currency or turn a draft into playable native content.

## Run deterministic fixtures

```sh
uv sync --locked --python 3.12 --extra generation
uv run --offline --frozen python scripts/smoke-agent-tools.py
uv run --offline --frozen python scripts/npc-quest-generator.py \
  --seed 27 --queue .local/examples/quest.sqlite3 --output .local/examples/quest.json
uv run --offline --frozen python scripts/world-planner.py tick \
  --state .local/examples/world.sqlite3
```

The smoke denies socket connections, uses temporary synthetic state, and checks
dialogue restart/replay, a candidate quest and visual conversion/cache reuse.
The NPC generator uses a fixed reviewed garden template with bounded EN/PT text;
its result is a draft, with no native action. Repeating an identical completed
request reuses its result. A changed producer contract cannot silently resume an
old pending job. Pokémon proposals similarly remain candidates; use
`scripts/pokemon-generator.py --help` for the explicit plan/run stages.

The world planner's `tick` command performs one bounded local update. Nothing
schedules it automatically. Public examples contain no player profiles or private
world canon. Font/character metrics and reference data are explicit, versioned
inputs under `examples/`, so host checks do not require a native checkout.

## Visual assets

`game_agents.visual_asset_tool.build_visual_asset_tool(runtime)` exposes
`generate_visual_asset(asset_type, prompts)` to an explicitly configured agent.
Types are `sprite` (64×64) and `item_icon` (24×24), with one to four short public
descriptions. The tool accepts no model-selected paths, URLs, credentials or
player identifiers. For direct fixture use:

```python
from game_agents.visual_asset_tool import VisualAssetRuntime

runtime = VisualAssetRuntime(".local/examples/assets")
result = runtime.generate("item_icon", ["A blue watering pot with a wide handle."])
```

The pipeline bounds input and response sizes, converts PNG to RGB555/4bpp,
checks dimensions and palette, hashes the full production contract and verifies
cached files by reconversion. Interrupted external attempts stay pending with an
unknown outcome; they do not automatically call the provider again. File reads
reject symlinks and special files without blocking on a FIFO.

`ready` means **validated asset only**. It explicitly records no native admission
and no visual review. Fixture pixels are placeholders. Installing art still
requires composition review, native constraints, compilation and exact-ROM
mGBA evidence. Arbitrary maps, trainers and tilesets are not supported asset types.

## Explicit live integrations

Fixture is always the default. Optional Deep Agents integration limits model and
tool calls; live use requires an explicit model and external credentials. The
OpenRouter adapters prefer latency, require supported parameters and disable
fallbacks. Low reasoning is selected for the exact supported GLM 5.3/Flash IDs;
that policy is part of producer identity. Provider availability and latency must
be checked before use; no latency guarantee follows from one local measurement.

The image adapter pins `gpt-image-2.5-sunburst-2026-09-08`, one high-quality
1024×1024 transparent PNG per attempt, no retries and a bounded socket timeout
(not a total wall-clock deadline). The host must explicitly supply
`OpenAIImageProvider` and a matching `VisualAssetConfig`. Image calls have a
separate budget; an existing agent queue does not acquire that capability
implicitly. Public CI never calls either paid provider.

For local graph development, `langgraph.json` intentionally contains no dotenv
path. Run **from the repository root** with tracing disabled and isolated data;
the CLI entrypoint is fixture-only. Its `.langgraph_api/` state is ignored:

```sh
LANGGRAPH_ANALYTICS_ENABLED=false LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false \
  GAME_AGENT_MEMORY_PATH=.local/examples/cli-memory.sqlite3 \
  uv run --offline --frozen langgraph dev --no-browser
```

The public text guard uses deliberately invented restricted terms to exercise
the boundary. It is a fixture policy, not the private game's canon. Editing that
versioned policy changes the bound producer hashes. Do not inject private
authoring material into NPC prompts; lexical checks alone cannot detect every
semantic or visual disclosure. See the [quest contract](quest-agents.md) and
[continuation prompt](continue-development.md) for the next playable slice.
