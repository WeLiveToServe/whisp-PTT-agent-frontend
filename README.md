# Whisp PTT Agent Frontend

## Project Snapshot
This started as a simple push-to-talk transcription client and has grown into a little stack of its own. The goal is for users (aka me) to be able to work with agents via voice, but with pitstop through transcription. Typing out appropriate prompts is a PITA on the go and interactive voice leads to distracted run on prompts and frustrating back and forths. A waste of time and tokens. 
Right now it includes:

- A recorder / transcriber loop
- A FastAPI server
- A browser frontend (HTML/CSS)
- A legacy CLI UI
- An early “agent” microservice

The loop is: record audio → transcribe with OpenAI → show in UI → (soon) pass into agents for responses.

*(Recording is now toggled by clicking the mic icon, not the spacebar. Still not cleaned up in the code for naming/commenting... sorry!)*

---

## How It’s Put Together

### Recorder (`recorder_redline.py`)
Captures audio to WAV files when you hit record. Originally keypress-based, but now controlled from the browser UI. Keeps sessions under `/sessions/`.

### Transcriber (`transcripter_redline.py`)
Sends audio to OpenAI. Prefers `gpt-4o-transcribe` (or `-mini`), falls back to `whisper-1`. Can log transcripts, handle prompts, and has some stubbed “live” streaming helpers.

### Server (`device_server.py`)
FastAPI service that coordinates recording and transcription. Exposes routes like:
- `/api/record/start`
- `/api/record/stop`
- `/api/status`
- `/api/session/export`

Stores transcripts and lightweight session memory in SQLite.

### UI
- **CLI (`ui.py`)**: old-school Rich console widgets (spinners, banners).  
- **Web (`html_*.html` + `theme.css`)**: recorder page, transcript editor, agent factory, profile/export, Android-style chat window. Theme lives in CSS with a “matrix green” look.

### Agents
- **`agent_factory.py`**: registry + config loader for agent personas.  
- **`agent-psmith.py`**: FastAPI microservice. Can run one-off, interactive REPL, or serve at `/run`.

---

## Config & Setup

- Set `OPENAI_API_KEY` in your env.  
- Optional env vars:  
  - `WHISP_TRANSCRIBE_APP_ID` and `WHISP_TRANSCRIBE_APP_INSTRUCTIONS` if using OpenAI Apps.  
  - `WHISP_TRANSCRIBE_APP_REQUIRED=true` to force App usage (disable Whisper fallback).  
  - `WHISP_REALTIME_MODEL` (ex: `gpt-4o-mini-realtime-preview`), plus sample rate + instructions. Needs `websockets` installed for live mode.  

Dependencies: `fastapi`, `sounddevice`, `soundfile`, `rich`, `openai`, `uvicorn`.

---

## What Works Today

- Record via browser UI, transcribe via OpenAI.  
- Local sessions with transcripts, logs, and WAVs in `/sessions/`.  
- Browser frontend: recorder, transcript editor, agent factory, profile/export, Android-style chat.  
- CLI utilities for quick testing.  
- Agent microservice with YAML registry + SQLite memory.  
- Automated workflow test that drives the server and logs outputs.

---

## What’s Still Rough

- Real-time streaming transcription: unstable, repeats/dupes.  
- Guardrails: placeholders exist, but no enforcement yet.  
- Persistence: only logs and SQLite session memory, no long-term storage.  
- Code comments: recorder still talks about “keypress” when it’s actually icon click.

---

## Roadmap

1. Wire the browser frontend to the agent service (`/api/agents/run`). Let the “Agents” button send transcripts through an agent and show the result in the log/export.  
2. Add guardrails (input length checks, output sanitization).  
3. Expand workflow tests to cover agents.  
4. Refactor recorder/transcriber into importable packages.  
5. Polish gesture/UX once backend is sturdier.  
6. Revisit real-time transcription once core loop is solid.

---

## Repo Layout (highlights)

- `recorder_redline.py`, `transcripter_redline.py`, `device_server.py`, `ui.py` — main Python code.  
- `html_*.html`, `theme.css`, `assets/` — web UI.  
- `agent_factory.py`, `agent-psmith.py` — agent stuff.  
- `sessions/` — transcripts, logs, audio.  
- `tests/` — workflow tests.  
- `project-notes-errata/`, `front-end-designs/` — scratch / archived designs.  

---

## Status
It’s functional but in flux. The goal is an end-to-end loop: speak → see transcript → push into agent → get response. Right now, the first two parts are working reliably, the rest are coming together.
