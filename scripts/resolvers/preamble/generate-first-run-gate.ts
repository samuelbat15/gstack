export function generateFirstRunGate(): string {
  return `**First-run gate:** \`FIRST_RUN_COMPLETE\` is captured at session start and is **immutable for the entire session** — it does NOT change when the lake intro fires during this session. If \`FIRST_RUN_COMPLETE\` is \`no\`: show the lake intro only, then skip all remaining onboarding prompts (telemetry, proactive, routing injection) for this session. They will surface in session 2+. The user can configure them early via \`/plan-tune\`.`;
}
