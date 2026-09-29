# Nexi Project Context

This file is the local project memory for Nexi. It records the FYP proposal scope, the team ownership split, and the current implementation state so future work stays aligned and does not accidentally drift into a teammate's area.

Current IDE owner/context: **Faseeh**, working primarily on the system/Rust layer in `nexi-daemon`.

## Project Summary

Nexi is a locally run, privacy-respecting AI desktop companion. The intended system observes desktop activity, learns recurring workflows from local interaction logs, accepts voice commands, and safely executes learned or direct actions on the user's computer.

The FYP proposal title is:

**NEXI: A Locally-Run, Personality-Driven AI Desktop Companion with Passive Workflow Learning**

The main project idea is not just a chatbot or a macro recorder. Nexi should combine:

- Local voice transcription and intent understanding.
- Passive desktop interaction logging.
- Workflow pattern extraction from recorded behavior.
- Voice-triggered workflow lookup and playback.
- A visible companion interface.
- Local text-to-speech feedback.
- Safety gates, confirmation prompts, and an emergency kill switch.
- Later-stage webcam/vision features for hand gestures and fatigue/mood signals.

## Proposal Scope

The proposal describes these major modules:

- **Edge-optimized capture daemon:** a low-level background service, currently Rust, that captures global input events and active window/process metadata.
- **Offline voice core:** local speech-to-text using Whisper or similar offline models.
- **Intent classification:** fast local command routing for easy commands, with local LLM fallback for harder requests.
- **Workflow learning engine:** extraction of recurring multi-step behavior from logs into named workflow templates.
- **Voice-triggered playback:** matching voice commands to saved workflow templates and executing them.
- **Companion overlay:** a small always-on-top visual assistant UI.
- **Desktop control layer:** local mouse, keyboard, app, and file control.
- **Offline TTS:** local speech output through Piper or similar.
- **Safety system:** confirmation gates, confidence checks, and kill switch.
- **Vision and gesture modules:** OpenCV/MediaPipe hand tracking and facial fatigue/mood analysis.
- **Cursor friction analysis:** cursor path anomaly detection to identify user confusion or stalls.

## Team Division

### Azmeer - Voice and Thinking Side

Azmeer owns the voice and cognition pipeline: letting the user talk to Nexi and having Nexi understand the request.

Responsibilities:

- Set up local voice listening and speech-to-text with Whisper.
- Sort commands into easy vs hard commands.
- Handle easy commands through simple fast rules.
- Send harder commands to a local AI model such as Phi-3 Mini.
- Connect voice commands to learned workflows once those workflows exist.
- Look up commands like "run my morning startup" against stored workflow names and hand the selected workflow to the execution layer.

Primary repo area:

- `nexi-core`

Current related files:

- `nexi-core/voice/*`
- `nexi-core/intent/*`
- `nexi-core/ipc/*`
- `nexi-core/schema/*`
- `nexi-core/intent_demo.py`
- `nexi-core/voice_demo.py`

### Malaika - Face, Hands, and Safety Side

Malaika owns the visible companion, execution layer, speech output, and safety controls.

Responsibilities:

- Build the always-on-top PyQt5 companion window/character.
- Use PyAutoGUI or related tools to control mouse, keyboard, app launch, typing, and other desktop actions.
- Set up local text-to-speech through Piper.
- Build the safety layer:
  - kill switch;
  - confirmation before risky actions;
  - confidence check before uncertain execution.
- Replay named workflows step by step once workflow templates exist.

Primary repo area:

- `nexi-ui`

Current related files:

- `nexi-ui/Companion/companion.py`
- `nexi-ui/action_server.py`
- `nexi-ui/safety/kill_switch.py`
- `nexi-ui/voice/tts.py`
- `nexi-ui/schema/*`

### Faseeh - System, Daemon, and Workflow Learning Side

Faseeh owns the system layer, Rust daemon, passive workflow-learning base, and the daemon-side contract that later lets voice commands trigger learned workflows.

Responsibilities:

- Rust OS hooks and passive event capture.
- IPC/JSON streaming from the daemon.
- Embedded local event database.
- Pattern extraction from recorded behavior.
- Workflow template storage and stable workflow IDs.
- Replay contract design for executable workflow steps.
- Workflow matching/confidence output for replay requests.
- Cursor path friction logic.
- Low-level automation shell or any daemon-side automation support.

Primary repo area:

- `nexi-daemon`

Current related files:

- `nexi-daemon/src/main.rs`
- `nexi-daemon/src/lib.rs`
- `nexi-daemon/src/bin/read_db.rs`
- `nexi-daemon/src/bin/extract_patterns.rs`
- `nexi-daemon/README.md`

## Collaboration Rule

Avoid changing a teammate's area unless one of these is true:

- The user's task explicitly asks for it.
- A blocking interface is missing and your own module cannot move forward without a small contract change.
- The change is documentation or a clearly shared schema/interface.
- The change is a tiny compatibility fix needed to run or test your own module.

When a teammate-owned area must be touched, keep the change narrow and document why it was needed.

## Current Implementation State

Updated 2026-09-30. Baseline: `origin/Main` at `a65889a`; this checkpoint targets `dev` and includes the daemon changes described below. No teammate-owned code was changed for this checkpoint.

### `nexi-daemon`

Implemented:

- Captures global mouse and keyboard events with `rdev`.
- Reads active window title, process name, window rectangle, and relative click coordinates.
- Stores events in a local `sled` database.
- Streams events as newline-delimited JSON on `127.0.0.1:9000`.
- Has a `read_db` binary.
- All three daemon binaries use `events_db_path()` from `src/lib.rs`; the machine-specific database path now has one shared definition. Verified with `cargo check --bins` (passes with the existing unused `WindowRect` warning).
- Has an `extract_patterns` binary that filters noise, segments sessions, abstracts sessions into tokens, mines repeated token sequences, and prints recurring patterns.

Not finished / known gaps:

- Database path remains machine-specific, but is centralized in `src/lib.rs`.
- `extract_patterns` now saves `patterns.json` beside the configured database, with generated names, stable token-derived IDs, and per-occurrence raw events plus exact sled keys. Edited names survive reruns for patterns still detected; the export is a snapshot, not an archive.
- Source ranges are zero-based and end-exclusive in filtered sessions. JSON schema version is 1; IDs use a lossless hexadecimal encoding of token JSON. See the daemon README for the implemented contract (the example below remains conceptual).
- Named patterns are learning evidence; executable workflow templates and replay safety still need a separate contract.
- Daemon README now reflects the passing build, shared config, and pattern export. Two extractor tests and `cargo check --bins` pass; the unused `WindowRect` warning remains.
- No cursor friction/anomaly engine is wired yet.

### `nexi-core`

Implemented:

- Local voice module scaffolding.
- Recorder/transcriber pipeline.
- Intent routing entry point.
- Tier 1 classifier with simple command handling.
- Tier 2 local LLM routing scaffold.
- Action schema and result schema.
- IPC client for sending actions to `nexi-ui` on `127.0.0.1:9001`.
- Demo scripts for voice and intent.

Not finished / known gaps:

- No workflow registry/loader exists yet.
- Voice command `"run my workflow"` can classify as `workflow_replay`, but there is no stored workflow lookup layer.
- No integration yet from daemon-generated learned workflows into `nexi-core`.
- Local LLM details should be checked against the agreed Phi-3 Mini direction.

### `nexi-ui`

Implemented:

- PyQt5 companion window.
- Socket action server on `127.0.0.1:9001`.
- PyAutoGUI-based app launch/file open/text input support.
- Confirmation prompt for actions that need approval.
- Kill switch module.
- Piper TTS support and warm-up.
- Mirrored action/result schemas.

Not finished / known gaps:

- `workflow_replay` is explicitly unsupported in `action_server.py`.
- Window control is explicitly unsupported.
- Real step-by-step replay of learned workflows is not wired.
- Safety exists at the action level, but workflow-level safety still needs design before replay.

## Immediate Project Priority

The next useful milestone is the passive workflow learning bridge:

1. Completed: centralize the database path in `src/lib.rs` and use it in all three daemon binaries.
2. Completed: save named mined patterns as JSON; executable workflow template design remains pending.
3. Completed: include exact source database keys and decoded events for each occurrence.
4. Next daemon priority: include process identity in Click tokens so click-only patterns cannot combine unrelated apps. Define an ID/schema migration because tokens determine IDs and preserved names.
5. Define and test a non-overlapping occurrence-counting policy before trusting counts as workflow evidence.
6. Define a draft executable workflow schema, validator, and preview command. These have only been discussed, not implemented. Current capture lacks key-release events; do not infer faithful text/hotkey replay from key presses alone.
7. Coordinate the agreed workflow contract with Azmeer (lookup/voice routing in `nexi-core`) and Malaika (execution, target checks, confirmations, kill switch in `nexi-ui`). Neither lookup nor workflow replay is wired yet.

This order keeps the work aligned with the FYP proposal while respecting team boundaries. The daemon export is Faseeh's responsibility, but it is also a cross-team contract because Azmeer's `nexi-core` work and Malaika's replay work depend on it.

## Implemented Pattern JSON Contract

`nexi-daemon/patterns.json` is a version 1 evidence snapshot, not an executable workflow registry.

- Top level: `schema_version`, `generated_at`, `source_db`, `patterns`.
- Pattern: `id`, editable `name`, `tokens`, `occurrences`, `session_count`, `matches`.
- Match: `session_index`, `token_start`, `token_end`, `event_start`, `event_end`, `source_events`.
- Source entry: `db_key` (exact sled key as a byte array), `event` (decoded InputEvent).
- Indices are zero-based and ends exclusive; event indices address the filtered session.
- IDs are `pattern_v1_` plus the hex encoding of token JSON. Names survive reruns for unchanged token sequences still detected. Disappearing patterns and their names are not archived.
- Invalid existing exports are rejected; output is synced to a sibling temporary file before replacement.
- Export files are ignored by Git because they contain recorded input. No event data belongs in this checkpoint.
- Stop the daemon before extraction because sled holds an exclusive database lock.

## Verification and Working Style

- `cargo test --bin extract_patterns`: two tests passed, covering event provenance/typing bursts and name preservation/corrupt-file protection.
- `cargo check --bins`: passed with the existing unused `WindowRect` warning.
- Faseeh initially requested guided code placement to learn the implementation, then explicitly delegated the shared-path wiring and pattern export. Match future implementation depth to his current request.
- The next requested activity after this checkpoint is an idea discussion; do not automatically begin replay or mining fixes.

## Notes From Proposal vs Current Repo

### Manual pattern-export test

- Inspected `patterns.json` generated at `2026-09-29T20:49:07Z`: four patterns, with occurrence counts and session counts matching their exported matches; event/token ranges were internally consistent and source keys were present. Keys were not independently checked against sled during this inspection.
- The Notepad click/type/click/click pattern appeared three times across three sessions, retaining 12, 13, and 13 source events.
- Found a mining limitation: Click tokens omit process identity, so one click-only pattern combined Chrome and Notepad occurrences. Overlapping windows also inflated its occurrence count. Address these before treating mined patterns as reliable replay candidates.
- Manual rename persistence was not checked in this inspection (covered by the automated export test).

- The repo already has a reasonable start on daemon logging, voice, intent, IPC, UI execution, TTS, and safety.
- Pattern persistence is implemented; reliable mining, executable workflow definitions, lookup, and replay remain.
- Gesture tracking, fatigue detection, and proactive help overlay are still proposal-level or future modules.
- The project should first prove the loop from observed behavior to saved workflow to voice lookup before expanding into webcam and mood features.
