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
| Rust | 1.96.0 (verified); any recent stable with the MSVC toolchain works |
| Python | 3.14 (only needed for the listener; a venv already exists at `../.venv`) |

---

## Known issue: the current source does not compile

`src/main.rs` has five duplicate `use` statements on **lines 17–21** that shadow
the imports already made on lines 11–16. `cargo build` fails with five `E0252`
errors before anything else happens:

```
error[E0252]: the name `GetForegroundWindow` is defined multiple times
error[E0252]: the name `GetWindowTextW` is defined multiple times
error[E0252]: the name `OpenProcess` is defined multiple times
error[E0252]: the name `GetWindowThreadProcessId` is defined multiple times
error[E0252]: the name `DWORD` is defined multiple times
```

**Fix:** delete lines 17–21 of `src/main.rs`. They are pure duplicates — nothing
else references them.

```rust
// delete these five lines:
use winapi::um::winuser::{GetForegroundWindow, GetWindowTextW};
use winapi::um::processthreadsapi::OpenProcess;
use winapi::um::psapi::GetModuleFileNameExW;   // keep this one — line 19 is NOT a duplicate
use winapi::um::winuser::GetWindowThreadProcessId;
use winapi::shared::minwindef::DWORD;
```

Careful: `GetModuleFileNameExW` (line 19) is the one import in that block that is
*not* duplicated and *is* used by `get_active_window()`. Keep it.

After that the crate builds with warnings only (a handful of genuinely unused
imports on lines 9–15 — `OsString`, `OsStringExt`, `MAX_PATH`, `CloseHandle`,
`GetModuleBaseNameW`, `PROCESS_QUERY_LIMITED_INFORMATION`).

The prebuilt `target/debug/nexi-daemon.exe` in this tree is from an earlier,
working revision, so it runs even while the source is broken. Don't mistake that
for a successful build.

---

## Build

```powershell
cd "D:\Project 5\Nexi\nexi-daemon"
cargo build              # debug
cargo build --release    # optimized
```

This produces two binaries:

- `nexi-daemon` — the capture daemon (`src/main.rs`)
- `read_db` — a one-shot dump of everything in the database (`src/bin/read_db.rs`)

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

There is none — everything is hardcoded in `src/main.rs`. To change it, edit and
rebuild:

| what | value | where |
|---|---|---|
| Bind address | `127.0.0.1:9000` | `src/main.rs:131` |
| Database path | `D:/Project 5/Nexi/nexi-daemon/nexi_events.db` | `src/main.rs:127` |

The absolute database path means the daemon must run on a machine where
`D:\Project 5\Nexi\nexi-daemon\` exists; it does not resolve relative to the
working directory. `src/bin/read_db.rs:4` hardcodes the same path.

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

## Relationship to `nexi-core`

`../nexi-core` is an earlier variant of this same daemon: its `Cargo.toml`
declares the **same package name** (`nexi-daemon`), and its `src/main.rs` is the
same program without the window/process tagging. Both crates hardcode the same
port (`9000`) and the same database path
(`D:/Project 5/Nexi/nexi-daemon/nexi_events.db`), so **they cannot run at the
same time** — whichever starts second panics on the sled lock or the port bind.

Use this crate for the daemon. Use `nexi-core` only for `listener.py`.

There is no workspace root; each directory is a separate crate with its own git
repository, and `cargo` commands must be run from inside one of them.
