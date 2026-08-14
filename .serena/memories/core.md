## Authoritative source

`CLAUDE.md` at repo root is the canonical, actively-maintained project doc (commands, full directory structure, SKILL.md generation workflow, versioning/CHANGELOG rules, security architecture, slop-scan policy, community-PR guardrails). It is large and detailed — read it directly for anything not covered by the terse pointers below; do not duplicate its content into memory.

## Non-obvious invariants (supplement to CLAUDE.md, not a replacement)

- gstack is a monorepo of Claude Code *skills* (each top-level dir like `ship/`, `review/`, `qa/`) plus two compiled CLI binaries (`browse/`, `design/`) and a build pipeline (`scripts/gen-skill-docs.ts`) that generates every `SKILL.md` from a `SKILL.md.tmpl` — never hand-edit a generated `SKILL.md`, always edit the `.tmpl` and rerun `bun run gen:skill-docs`.
- `browse/dist/` and `design/dist/` are committed compiled binaries (macOS arm64 only, historical mistake per CLAUDE.md) — never stage them; they show as modified in `git status` due to being tracked despite `.gitignore`.
- Test tiers are cost-differentiated: `bun test` is free/fast (skill validation + snapshot), `bun run test:evals`/`test:e2e` are paid (LLM judge, real `claude -p` runs) and diff-based by default (`test/helpers/touchfiles.ts` maps files to tests) — don't run the paid tiers reflexively; use `bun run eval:select` to preview what a diff would trigger.
- VERSION/CHANGELOG are branch-scoped, not repo-scoped: every shipping branch gets its own bump + entry describing only what that branch adds, written at `/ship` time, never mid-branch. See CLAUDE.md's "Commit style" and "CHANGELOG + VERSION style" sections for the full (long, opinionated) rules before touching either file.
- `.claude/skills/gstack` may be a live symlink to this working directory during dev — check with `ls -la .claude/skills/gstack` before large template refactors (breaking changes propagate immediately to any concurrent gstack session).

## Serena scope note

This `serena-gstack` instance is pinned to the gstack repo root and configured `language: typescript` — it cannot parse Python subprojects nested inside gstack (e.g. `.github/jarvis-starter/`). Those have their own dedicated Serena MCP instances (`serena-jarvis`) with `language: python` — use the dedicated instance when working in a nested non-TS subproject rather than assuming this one covers it.

See `mem:suggested_commands` for the day-to-day command set, `mem:conventions` for commit/PR discipline, `mem:task_completion` for pre-PR gates.