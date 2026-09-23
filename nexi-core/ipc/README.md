# Outbound IPC — nexi-core to nexi-ui

`client.py` sends Actions to nexi-ui's `action_server.py` on **port 9001**.

## Wire format

One Action goes out as a single line of JSON. One ActionResult comes back as a
single line of JSON. Then the connection closes.

    nexi-core ──▶  {"type":"app_launch","app":"chrome", …}\n   ──▶ nexi-ui
    nexi-core ◀──  {"status":"executed","detail":"…"}\n       ◀── nexi-ui

Same framing the daemon uses on port 9000: newline-delimited JSON, UTF-8.
Multi-line content inside a field is safe, because JSON escapes newlines.

## Why there is a reply at all

Nothing in the original spec said nexi-ui answers. It has to. An Action can
carry `requires_confirmation`, which means the user is shown a prompt and may
refuse — and without a reply nexi-core would never learn the outcome. The root
README calls the confirmation gate non-negotiable, and a gate whose result is
never reported is not a gate. It is also the only way to get a success rate
for the benchmark.

`status` is one of `executed`, `declined`, `failed`, `unsupported`.
See `schema/result.py`.

## Design decisions

**One connection per action.** Actions are seconds apart at best, so pooling
buys nothing, and a fresh connection each time means restarting nexi-ui cannot
wedge the voice pipeline.

**Unreachable is not fatal.** `send_action` returns `None` instead of raising,
the same fail-soft contract tier 2 uses when Ollama is down. A missing UI
degrades the pipeline rather than stopping it.

**Two timeouts.** A plain action is answered at machine speed (5 s). One that
needs confirmation waits on a human reading a prompt, so it gets 120 s. A
single short timeout would break exactly the actions that matter most.

**Unknown actions are not sent.** nexi-ui can do nothing with them and the
user has already been told the command was not understood.

## Testing without nexi-ui

`stub_ui.py` in the project root is a test double that speaks this protocol
and never touches the desktop. In one terminal:

    python stub_ui.py            # ask at the terminal when confirmation is needed
    python stub_ui.py --auto     # confirm everything, for scripted runs
    python stub_ui.py --decline  # refuse everything, to exercise the no path

In another:

    python intent_demo.py --text "open chrome" --send

It is also the reference implementation of the wire format for nexi-ui.
