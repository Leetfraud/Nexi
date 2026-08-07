# Nexi

A locally-run, personality-driven AI desktop companion with passive workflow learning.

Nexi watches how you use your computer — mouse, keyboard, and window
context — and learns to reproduce your workflows without being explicitly
programmed to. Final Year Project, University of Lahore, Department of
Software Engineering.

## Repo layout

This is a monorepo with one folder per layer. Each team member works inside
their own folder; cross-layer communication happens over a local TCP socket
on port 9000, passing newline-delimited JSON.

Nexi/
nexi-daemon/ Rust - input capture, storage, IPC (Faseeh)
nexi-core/ Python - voice, intent classification, LLM (Azmeer)
nexi-ui/ Python - desktop control, overlay, TTS (Malaika)

See nexi-daemon/README.md for daemon-specific setup and requirements.

## Getting started

1. Start the daemon first - it owns the TCP socket the other layers connect to.
2. Start nexi-core listener (or eventually its full pipeline) second.
3. nexi-ui will connect the same way once it exists.

## Design notes

Open design decisions and rationale live in docs/. Check there before
re-deciding something that was already thought through - e.g.
docs/DESIGN_NOTES_click_coordinates.md covers why click tokens do not
currently carry exact pixel position.

## Safety requirements (non-negotiable)

- Kill switch: holding Escape immediately halts all automation
- Confirmation gate before delete, send, or submit actions
- Low-confidence workflow matches ask before executing

