# OpenAI App SDK Integration Opportunities

This document captures how the current codebase is wired today and outlines places where the OpenAI App SDK (Agents + Realtime) can replace or supercharge the existing logic. The emphasis is on reducing streaming latency, reusing the App runtime for post-processing, and paving the way for new product surfaces.

## 1. Current Pipeline Recap
- **Recorder pipeline** (`device/recorder_service.py`): microphone frames are buffered, chunked into ~2 s windows, written to disk, and sent to `transcribe_live_chunk()` which calls `transcribe_whisper_file()` (Whisper-1). Each chunk is saved in SQLite as a `LiveSegment` and polled by the browser every second.
- **Final transcript**: when `/api/record/stop` fires, the full WAV is transcribed again via Whisper-1 in `transcribe_and_enhance()`; the enhanced pass is currently a no-op (returns raw text).
- **Frontend** (`html_redline.html`): polls `/api/live`, renders segments, and copies the final transcript into the editor view. Navigation to the editor caches the transcript in `sessionStorage` and replays it in `html_editor.html`.
- **Agent lane** (`agent-psmith.py`, `agent_factory.py`): already imports `openai-agents` and spins up FastAPI endpoints but nothing in the UI hits them yet.

The key latency driver is the disk+HTTP loop for every chunk; each request has to upload a WAV, wait for Whisper to finish, then poll for results.

## 2. Realtime Transcription via App SDK
The App SDK’s Realtime API can run the complete speech pipeline inside an App, streaming partial text events back over a single WebSocket. A staged migration strategy:

1. **Create an App spec** (e.g. `apps/whisptt-realtime.yaml`):
   ```yaml
   name: whisptt-realtime
   instructions: |
     You convert live meeting audio into structured transcript messages.
   tools:
     - type: response.create
       response:
         modalities: [text]
         model: gpt-4o-mini-transcribe
   ```
2. **Server-side session proxy** (`device_server.py`):
   - Add an endpoint `/api/realtime/session` that creates an App session using `openai.realtime.sessions.create(app_id=...)` and returns the `client_secret` plus the App’s `ws_url` to the browser.
   - Spin up an async bridge that accepts PCM frames from the recorder and writes them to the App session using `session.stream_input_audio()` instead of writing WAV slices. The `_stream_worker` loop can push frames directly (no temp files, no second transcribe call).
   - Forward partial transcripts emitted by the App (events of type `response.output_text.delta`) straight into the existing `LiveSegment` table so the UI keeps working. The bridge can also emit “completed” events when the App finalises an utterance.
3. **Browser WebSocket client**:
   - When recording starts, call the new session endpoint, open the Realtime WebSocket from the browser (or via the device server if we need to hide credentials), and send raw PCM frames (WebRTC `MediaRecorder` or existing `recorder_redline` loop via WebSocket).
   - Replace the `/api/live` poller with a streaming handler that listens for App SDK events and immediately renders them.
4. **Fallback path**: Keep the current chunked transcription lit for environments where a WebSocket session is not available; gate the new path behind a feature flag in `recorder_service` so we can roll it out gradually.

Benefits: one network round-trip per session, lower latency, no temp WAV churn, and App-side intelligence (timestamps, speaker labels) if we swap to `gpt-4o-realtime-preview` models.

## 3. Post-Recording Enhancements with the App
Even before the full realtime migration, the App SDK can own the “enhance transcript” step:

- Define another App with instructions for cleanup + summarisation. Instead of calling Whisper twice, send the raw transcript to `ResponsesClient` with a prompt like “Clean punctuation and return action items”.
- Swap the stubbed `transcribe_and_enhance()` body for:
  ```python
  from openai import OpenAI
  client = OpenAI()
  response = client.responses.create(
      model="gpt-4o-mini",
      input=[{"role": "system", "content": instructions},
             {"role": "user", "content": raw_text}],
  )
  enhanced_text = response.output_text
  ```
- Store both raw and enhanced outputs in `sessions/transcripts.log` (already supported) and bubble the enhanced text to the UI.

## 4. Agent + App SDK Convergence
The agent microservice already depends on `openai-agents`. Suggested next steps:

1. **Replace Runner shim with App Sessions**: Use `openai.agents.AsyncSession` to create a persistent App session. That lets us reuse the same App for both CLI and web requests, bringing memory/state without custom SQLite tables.
2. **UI bridge**: Add `/api/agents/run` in `device_server.py` that forwards the latest transcript (or the session export) to the App via `session.respond()`. Display the reply in the log or open the editor with the agent output appended.
3. **Tooling**: The App spec can declare tools that talk to local endpoints (e.g. saving summaries, launching desktop flows). The existing `agent_factory` YAML can map 1:1 onto App manifests, so migrating won’t break configuration.

## 5. Other App-Friendly Touchpoints
- **Guardrails & QA**: Wrap each live chunk (or completed transcript) in an App call that classifies for PII, toxicity, or meeting-specific cues. Responses can return flags that the UI uses to highlight risky sections.
- **Topic routing**: A lightweight App can tag transcripts with categories (Support, Sales, Standup) that determine which agent or downstream workflow to trigger.
- **Auto summaries for the editor**: When the editor page opens, call an App endpoint that returns bullet summaries, action items, and email drafts alongside the editable transcript.
- **Voice shortcuts**: Use the Realtime App to listen for spoken commands (“bookmark”, “flag that”, “send to agent”) and emit tool calls back to the device server instead of requiring keyboard/mouse.

## 6. Implementation Checklist
- [ ] Draft App manifest(s) for realtime transcription and post-processing.
- [ ] Prototype `openai.realtime` bridge inside `RecorderService._stream_worker` (keep chunked Whisper as a fallback flag).
- [ ] Swap final enhancement step to `client.responses.create()` and persist enhanced text.
- [ ] Add `/api/agents/run` -> App session bridge and surface results in UI.
- [ ] Update frontend to open a WebSocket session when recording and render streaming events.
- [ ] Extend test harness to mock App SDK responses so CI covers the new flow.

By leaning on the App SDK we can collapse multiple bespoke loops (chunk files, polling, manual enhancement) into a single programmable surface. The short-term win is lower latency; the longer-term payoff is a unified place to run summarisation, guardrails, and agent responses with far less glue code.

