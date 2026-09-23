# Action schema

The contract between nexi-core and nexi-ui. nexi-core emits Actions; nexi-ui
executes them over the socket on port 9001.

`action.py` is the pydantic model. **Mirrored in `nexi-ui/schema` — the two
copies must stay identical.**

## Not to be confused with `Act`

`Nexi_Act_Architecture.md` describes Faseeh's Rust **`Act`** struct — the
identity of a single click during workflow mining (`process_name`, `label`,
`bucket`, `icon_hash`). That is a different thing from the **`Action`** here,
and it does not define these fields. The agreed Action shape comes from
`Context.txt`.

## Fields

| Field | Type | Notes |
|---|---|---|
| `type` | enum | `app_launch`, `file_open`, `text_input`, `window_control`, `workflow_replay`, `unknown` |
| `app` | str | required for `app_launch` |
| `file` | str | required for `file_open` |
| `text` | str | required for `text_input` |
| `target` | str | required for `window_control` |
| `workflow` | str | required for `workflow_replay` |
| `path` | str | optional directory hint |
| `steps` | list[str] | optional human-readable breakdown |
| `confidence` | float | 0.0–1.0, from whichever tier answered |
| `requires_confirmation` | bool | nexi-ui must ask before executing |
| `utterance` | str | the original transcript, so the confirm prompt can quote it |

A missing required field raises at construction, so an unexecutable Action
cannot reach nexi-ui.

## The safety fields are not advisory

The root README makes confirmation before delete/send/submit non-negotiable,
and requires low-confidence matches to ask first. Those rules travel with the
Action rather than being re-derived by the executor:

- `requires_confirmation` is only ever raised by the validator, never lowered,
  so a confident-but-wrong Tier-2 answer cannot opt out of the gate.
- `type: unknown` always sets it, so an unclassified command is never run
  unattended.
- Destructive wording in the utterance sets it regardless of what the
  classifier returned — including two-word forms like "shut everything down".

`action.is_executable()` is the single check nexi-ui should use.

## The reply: `ActionResult`

`result.py` is the other half of the contract — what nexi-ui sends back. **Also
mirrored in `nexi-ui/schema`.**

| Field | Type | Notes |
|---|---|---|
| `status` | enum | `executed`, `declined`, `failed`, `unsupported` |
| `detail` | str | free text for the human: the error, or what was asked |

`declined` exists because `requires_confirmation` means the user can say no.
Without a reply path nexi-core would never learn that happened, so the
confirmation gate would have no closed loop and no success rate could be
measured. See `ipc/README.md` for the wire format.
