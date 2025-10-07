# Whisp PTT Agent Frontend Snapshot

## Project Snapshot
The application has grown from a prototype push-to-talk transcription client into a coordinated stack that now includes a recorder/transcriber loop, a web front end, a test harness, and an emerging agent microservice. Audio capture is handled locally, converted to text through the existing transcription wrappers, and rendered in the single-page HTML UI. A FastAPI-based agent runner (`agent-psmith.py`) sits beside the core web workflow so that transcript strings can soon be routed through OpenAI's Agents SDK for summarisation and follow-on actions. Continuous verification is provided by an automated workflow test that drives the HTTP server, mocks the hardware layers, and leaves a reproducible artefact in the `sessions/` directory.

## Directory Structure
- `.vscode/` - editor tasks and launch settings for local development.
- `assets/` - static web assets including the matrix theme, icons, and the refreshed tinted logo.
- `bug-log-noncritical/` - scratchpad for low priority issues discovered during exploratory testing.
- `front-end-designs/` - archived HTML/CSS iterations and design references.
- `project-notes-errata/` - research notes and historical experiments retained for context.
- `sessions/` - runtime exports (transcripts, logs, audio placeholders) plus the agent SQLite memory store.
- `tests/` - automated workflow verification scripts driven by Python's `unittest` runner.
- root files - operational source (`recorder_redline.py`, `transcripter_redline.py`, `ui.py`, `whisp_server_redline.py`), agent tooling, configs, and project documentation.

## Key Modules
- `recorder_redline.py` / `recorder_latest.py` - sounddevice-based push-to-talk loop that streams microphone frames into WAV snippets while mirroring status back to the CLI indicator.
- `transcripter_redline.py` / `transcripter_latest.py` - synchronous wrapper that now prefers the OpenAI App SDK for transcription (falling back to Whisper), writes session logs, and exposes stubbed live-transcription helpers.
- `ui.py` - legacy terminal UI utilities (spinner, timers, prompts) that remain in use by the recorder threads and tests.
- `whisp_server_redline.py` - threading HTTP bridge exposing `/api/record/start`, `/api/record/stop`, `/api/status`, and `/api/session/export`, with SQLite-backed memory, OpenAI-friendly timestamps, and a transcript store.
- `agent_factory.py` - YAML-driven agent registry that normalises verbosity/temperature settings into `ModelSettings`, materialises `Agent` instances, and provisions `SQLiteSession` handles for multi-turn memory.
- `agent-psmith.py` - CLI + FastAPI microservice for running agents; supports single-run mode, interactive REPL (`chat`), and a `/run` HTTP endpoint.

## Configuration Notes
- Set `OPENAI_API_KEY` to authenticate all OpenAI SDK calls.
- Optionally provide `WHISP_TRANSCRIBE_APP_ID` (and, if desired, `WHISP_TRANSCRIBE_APP_INSTRUCTIONS`) to route transcription through an OpenAI App. When the variable is absent the code falls back to Whisper-1.
- Use `WHISP_TRANSCRIBE_APP_REQUIRED=true` to disable the Whisper fallback so that misconfiguration fails fast during deployment.
- Set `WHISP_REALTIME_MODEL` (for example `gpt-4o-mini-realtime-preview`) to stream audio over a single Realtime session. You can override `WHISP_REALTIME_SAMPLE_RATE` (default 24000) and `WHISP_REALTIME_INSTRUCTIONS` for advanced tuning. Install the optional `websockets` dependency so the realtime client can connect.

## Progress Since `codex-handoff.md`
- Achieved: HTML theme extracted into dedicated CSS, button duplication bug eliminated, recorder MP3 conversion removed to reduce latency, backend logging standardised, and the new agent microservice with configuration registry and automated workflow test are in place. The UI now uses bundled SVG assets and provides visible export artefacts for testing.
- Discarded: Real-time streaming transcription and CLI flow wiring for finish options remain on ice; guardrail placeholders are not enforced yet, and no persistence outside transient logs is attempted.
- Unfinished: Wiring the web UI to the agent service, enabling true streaming Whisper output, strengthening guardrail integration, and finalising keyboard gesture polish are still outstanding.

## Suggested Next Steps
The immediate priority should be end-to-end integration between the browser front end and `agent-psmith.py`. By adding a `/api/agents/run` bridge in `whisp_server_redline.py` (or proxying directly to the FastAPI service) the "Agents" button can deliver transcripts to the configured agent, play back the response in the log, and optionally capture the result in the export history. This would validate the agent stack under realistic load and surface any requirements for result formatting, error handling, or session management before we scale beyond the P. Smith persona.

Once that loop is functional, I recommend focusing on resilience and developer ergonomics. Introducing structured guardrails (input length validation, output sanitisation) will make the agent responses safe to surface automatically. Expanding the workflow test suite to cover the new agent endpoint, refactoring recorder/transcriber modules into importable packages, and trimming legacy globals will keep the codebase healthy as we add more agents. With those foundations in place, we can revisit real-time transcription and polished gesture controls with confidence that the backend architecture will sustain them.

