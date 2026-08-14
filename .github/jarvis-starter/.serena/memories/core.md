## Source map

- `jarvis.py` — orchestrator. `Config`/`load_config` (config.json), 4 AI clients (`NoAIClient`/`OpenAIResponsesClient`/`OllamaClient`/`OpenRouterClient`, selected by `build_ai_client()` from env), `Speaker` (ElevenLabs-first, pyttsx3 fallback — see `mem:tech_stack`), `Listener` (mic capture, delegates transcription to `voice.py`), `Memory` (flat notes.md), `BufferWatcher` (periodic analysis of a running buffer, ~30-60s interval — never continuous inference, too slow on CPU), `Jarvis` (main class: `handle()` routes text commands, `run_agentic()` drives the 6-turn tool-calling loop).
- `voice.py` — local STT (faster-whisper) + `AudioBuffer` (rolling mic capture, explicit start/stop, never auto-started).
- `vision.py` — webcam capture + Ollama vision description (moondream) + `VisionBuffer` (rolling frame capture, same explicit-lifecycle contract as AudioBuffer).
- `tts.py` — ElevenLabs synthesis, called by `Speaker`; always has a working fallback path (pyttsx3), synthesis failure never blocks a response.
- `gmail_client.py` — Gmail API, read-only scope only, OAuth (`credentials.json`+`token.json`, both gitignored, never commit).
- `server.py` — HTTP backend (stdlib `http.server`), 2-step confirmation flow for risky actions, token-based auth for non-localhost access.
- `graphity_runtime.py` / `vault_memory.py` — long-term memory via Obsidian vault + graphify.
- `reminders.py`, `notifications.py` — scheduled reminders, Windows toast notifications.
- `gui.py` — Tkinter desktop UI.

## Invariants

- Every external capability (voice, vision, Gmail, ElevenLabs) degrades gracefully — network/model/credential failure returns an error string or falls back, never crashes the caller. Preserve this contract in any new integration.
- Continuous sensors (mic, webcam) are opt-in only: explicit start, explicit stop, never triggered by app startup or by the agentic loop itself.
- `BufferWatcher`-style periodic inference intervals are 30-60s minimum — this machine's CPU-only Ollama/Whisper inference cannot sustain faster cadences (single vision description: ~6-78s cold-start dependent).

See `mem:tech_stack` for dependency/version pins that matter, `mem:conventions` for code-level patterns, `mem:suggested_commands` and `mem:task_completion` for the dev loop.