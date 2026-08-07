# Design note: click coordinates in the pattern-matching layer

**Status:** Open decision — not yet implemented. Documented here so it isn't
a surprise later, and so anyone picking up `extract_patterns.rs` knows this
was considered, not overlooked.

## Context

`main.rs` now captures real `(x, y)` coordinates on `mouse_click` events
(tracked from the last `MouseMove` position). Raw events in `nexi_events.db`
correctly carry exact pixel coordinates.

The `Token::Click` variant used in `extract_patterns.rs`, however, currently
only stores the button (`Click("Left")`), not position. This was intentional,
not an oversight — but it needs a real decision before pattern mining (stage
4) gets built on top of it.

## The problem

A learned workflow that says "click here" with no "here" isn't replayable —
so position clearly needs to factor into pattern matching somewhere.

But raw pixel coordinates won't repeat exactly between sessions: the window
may be a different size, moved, or the user clicks a few pixels off from
last time. If `Token::Click` carries exact `(x, y)`, two functionally
identical clicks will almost never match as "the same pattern" — pattern
mining (stage 4) would find nothing, since it works by matching identical
token sequences.

## Two layers, two different needs

- **Raw event layer (sled, `InputEvent`)** — needs exact coordinates. This is
  what Malaika's PyAutoGUI replay layer will eventually need to actually
  move the mouse and click. This part is already correct as of the current
  `main.rs` fix.
- **Abstraction/token layer (`Token`, stage 3–4)** — needs something that
  repeats across sessions so pattern mining can actually find matches.
  Exact coordinates are the wrong granularity here.

## Likely direction (not yet implemented)

Bucket click position into coarse zones (e.g. a grid over the window, or
named regions like "top-left toolbar", "center") rather than using exact
`(x, y)`, so semantically-the-same click still matches across minor pixel
drift. Exact coordinates stay on the raw event for eventual replay use.

This is deliberately left undecided until there's real multi-session
capture data to look at — the right bucket size/granularity should be
chosen based on what actual click clustering looks like, not guessed in
advance.

## To revisit

Once several real capture sessions exist and stage 4 (sequence mining) is
being built, decide:
1. Bucket granularity (grid size vs. named UI regions)
2. Whether bucketing happens per-window (relative to window bounds) or
   per-screen (absolute) — per-window is probably more robust to window
   resizing/repositioning between sessions
