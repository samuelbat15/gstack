Before creating a PR (both must pass, per CLAUDE.md's "Testing" section):
1. `bun test` — free tier, must be green.
2. `bun run test:evals` — paid tier, diff-based; run `bun run eval:select` first to see what it will trigger and confirm the cost is expected.

Before touching CHANGELOG.md/VERSION: re-read CLAUDE.md's "CHANGELOG + VERSION style" section in full — the rules around branch-scoped versioning and collapsing branch-internal bumps are easy to get wrong and are explicitly, extensively documented there; don't rely on this memory's summary for that task.