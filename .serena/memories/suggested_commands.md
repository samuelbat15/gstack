Full command list lives in CLAUDE.md's "Commands" section (`mem:core`) — this is only the Windows-specific / easy-to-forget subset.

- `bun install` / `bun test` — standard, same on Windows as elsewhere.
- `bun run gen:skill-docs` — regenerate all `SKILL.md` from `.tmpl` sources; run after any template edit, before committing.
- `bun run eval:select` — preview which paid evals a diff would trigger, before running `test:evals`/`test:e2e` for real (they cost money).
- Paid evals need `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` sourced into the process env first (see CLAUDE.md's exact `bash -c` snippet under "Where the keys live on this machine") — do not pass `env: {...}` to `runAgentSdkTest`, mutate `process.env` ambiently instead (documented failure mode otherwise).
- `serena memories check` (prefix `PYTHONIOENCODING=utf-8` on Windows or it crashes on the ✓ character) — verify memory referential integrity after editing/renaming memories in any project.