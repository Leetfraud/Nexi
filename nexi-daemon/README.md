# nexi-daemon

A Windows input-capture daemon. It hooks global mouse and keyboard events with
`rdev`, tags each one with the active window title and process name, persists it
to an embedded `sled` database, and streams it as newline-delimited JSON to any
TCP client connected on `127.0.0.1:9000`.

The intended consumer is the Python listener in `../nexi-core/listener.py`.

---

## Requirements

| | |
|---|---|
| OS | Windows only — the daemon calls Win32 (`GetForegroundWindow`, `GetModuleFileNameExW`) directly |
| Rust | Stable Windows GNU toolchain (`stable-x86_64-pc-windows-gnu`) |
| Python | 3.14 (only needed for the listener; a venv already exists at `../.venv`) |

---

## Build status

`cargo check --bins` passes. The existing unused `WindowRect` type alias produces
a warning. The old duplicate-import compile errors are resolved.

---

## Build

```powershell
cd "D:\Project 5\Nexi\nexi-daemon"
cargo build              # debug
cargo build --release    # optimized
```

This produces three binaries:

- `nexi-daemon` — the capture daemon (`src/main.rs`)
- `read_db` — a one-shot dump of everything in the database (`src/bin/read_db.rs`)
- `extract_patterns` — mines recurring patterns and saves `patterns.json`.

---

## Run the daemon

```powershell
cd "D:\Project 5\Nexi\nexi-daemon"
cargo run --bin nexi-daemon
```

or directly:

```powershell
.\target\debug\nexi-daemon.exe
```

Expected output:

```
Nexi daemon listening on 127.0.0.1:9000
Capturing input events with window context...
Python client connected          <- printed when a client attaches
```

The daemon runs in the foreground and captures until you stop it. **Stop with
`Ctrl+C`** in its console window.

Note that it starts capturing immediately — every keystroke you make anywhere on
the machine, including in other applications, is written to disk in plaintext.

### Elevation

`rdev` installs a low-level Windows hook, which works unelevated for ordinary
applications. It will **not** see input directed at processes running as
administrator (Task Manager, an elevated terminal, UAC prompts). If you need
those, start the daemon from an elevated PowerShell.

---

## Consume the events

### Option A — the Python listener (live stream)

Start the daemon first, then in a second terminal:

```powershell
cd "D:\Project 5\Nexi"
.\.venv\Scripts\Activate.ps1
python nexi-core\listener.py
```

It connects to `127.0.0.1:9000` and pretty-prints events as they arrive:

```
Nexi Core — Python Listener
────────────────────────────
Connected to Nexi daemon on 127.0.0.1:9000
Listening for events...

[2026-06-05T21:43:38.138968900+00:00] KEY — KeyA | Code.exe | main.rs - Nexi
[2026-06-05T21:43:39.221004100+00:00] CLICK — Left | chrome.exe | New Tab
```

Only the standard library is used, so no `pip install` step is required.
`Ctrl+C` to stop.

Mouse-move events are throttled in the printer (`int(x) % 50 == 0`) — the daemon
still stores and streams every one of them.

### Option B — dump the database (offline)

```powershell
cargo run --bin read_db
```

Prints every stored event as JSON, then a total:

```
Events stored in database:
──────────────────────────
{"event_type":"mouse_move","x":1540.0,"y":1252.0,...}
...
──────────────────────────
Total: 44984 events
```

Because `sled` takes an exclusive file lock, **`read_db` cannot run while the
daemon is running.** Stop the daemon first, or you'll get a lock error.

### Option C — any TCP client

Nothing about the protocol is Python-specific. Connect to `127.0.0.1:9000` and
read newline-delimited JSON:

```powershell
# quick smoke test
$c = New-Object System.Net.Sockets.TcpClient("127.0.0.1", 9000)
$r = New-Object System.IO.StreamReader($c.GetStream())
while ($true) { $r.ReadLine() }
```

Clients are broadcast-only — the daemon never reads from the socket. A client
that disconnects is dropped from the list on the next failed write.

---

## Event format

One JSON object per line. `event_type` is one of `mouse_move`, `mouse_click`,
`key_press`; every other `rdev` event (key release, button release, wheel) is
discarded.

```json
{
  "event_type": "key_press",
  "x": null,
  "y": null,
  "button": null,
  "key": "KeyA",
  "timestamp": "2026-06-05T21:43:38.138968900+00:00",
  "window_title": "main.rs - Nexi - Visual Studio Code",
  "process_name": "Code.exe"
}
```

| field | populated for | notes |
|---|---|---|
| `x`, `y` | `mouse_move` | screen coordinates, `null` otherwise |
| `button` | `mouse_click` | `rdev` debug form, e.g. `Left`, `Right` |
| `key` | `key_press` | `rdev` debug form, e.g. `KeyA`, `ShiftLeft` |
| `timestamp` | all | UTC RFC 3339, also used as the database key |
| `window_title`, `process_name` | all | `"unknown"` if the foreground window can't be queried |

---

## Configuration

The shared `EVENTS_DB_PATH` constant in `src/lib.rs` configures the database for
all three binaries. Edit it and rebuild when moving to another machine.
`patterns.json` is written beside that database, independent of the working directory.
The TCP bind address remains `127.0.0.1:9000` in `src/main.rs`.

The database directory is in `.gitignore` (though `nexi_events.db/db` was
committed before the ignore rule was added). It grows without bound — mouse
moves dominate. Delete the whole `nexi_events.db/` directory to reset, with the
daemon stopped.

---

## Troubleshooting

**`Address already in use` / panic on startup at the `TcpListener::bind`**
Another copy of the daemon is already running. `Get-Process nexi-daemon` to find
it, or `Get-NetTCPConnection -LocalPort 9000` to see what holds the port.

**Panic at `sled::open`**
Another process holds the database lock — usually a second daemon instance or a
`read_db` run. Only one process may open `nexi_events.db` at a time.

**Listener prints `ConnectionRefusedError`**
The daemon isn't running, or it crashed on startup. Start it first; it must
print the "listening" line before the listener can attach.

**Daemon starts but no events appear**
The `rdev` hook is per-session — the daemon must run in the same interactive
desktop session as the input. Also check elevation (above) if the input is going
to an admin process.

**`window_title` / `process_name` are `"unknown"`**
Expected when the foreground window belongs to a protected or elevated process
that `OpenProcess` can't be opened against, or when no window has focus (e.g.
the lock screen).

---

## Relationship to the other modules

Faseeh owns this daemon and workflow learning. Azmeer's `nexi-core` owns voice
and intent routing; Malaika's `nexi-ui` owns desktop execution and safety.
The pattern export is a handoff artifact; workflow lookup and replay integration
remain to be implemented.

## Extract and name patterns

Stop the daemon first: sled allows only one process to open the database.

```powershell
cargo run --bin extract_patterns
```

The extractor drops mouse movement, splits sessions after 30 seconds idle, and
mines sequences of 3–8 tokens occurring at least three times across two sessions.
It removes fragments contained in longer qualifying patterns, then writes
`patterns.json` beside the configured database. An empty result writes an empty
`patterns` array.

The version 1 JSON contains:

- `schema_version`, `generated_at`, and `source_db`.
- Each pattern's `id`, editable `name`, `tokens`, `occurrences`, `session_count`,
  and `matches`.
- Each match's `session_index`, `token_start/end`, `event_start/end`, and
  `source_events`. Indices are zero-based, with exclusive end indices.
  Event indices refer to the filtered session, not database positions.
- Each source event's `db_key` (the exact sled key as a JSON byte array) and
  `event` (the original decoded InputEvent). Mouse movement is excluded.
  A typing token retains every contributing keypress; a Switch token references
  the event where the process change was observed.

IDs use `pattern_v1_` plus the hexadecimal encoding of the token JSON. They
are deliberately verbose but collision-free and stable for an unchanged token
sequence under this schema, regardless of extraction order.

Edit a pattern's `name` in the JSON, for example to `Morning startup`. Reruns
preserve names for token sequences still detected. This file is a snapshot:
patterns no longer detected are removed, and their names are not archived.
Malformed existing JSON, an unsupported schema, or a different source database
causes an error rather than overwriting the previous export. The writer syncs
a sibling temporary file before replacing the export.

Patterns are evidence for workflow learning, not executable replay scripts.
Token buckets alone cannot reliably locate a replay target, and key releases
are not recorded. Replay steps and safety checks need a separate contract.
Exports contain recorded input and are excluded from Git.

Validation:

```powershell
cargo test --bin extract_patterns
cargo check --bins
```
