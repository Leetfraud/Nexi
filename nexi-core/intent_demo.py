"""Speak a command (or pass --text) and print the Action it routes to.

With --send the Action also goes to nexi-ui on port 9001. Run stub_ui.py in
another terminal to see the whole path end to end without nexi-ui existing.
"""
import argparse
import json
import sys

from voice_demo import SECONDS, drain_stdin


def deliver(action):
    """Send one Action to nexi-ui and report what came back."""
    from ipc.client import PORT, send_action
    result = send_action(action)
    if result is None:
        print(f"→ nexi-ui not reachable on port {PORT} — nothing executed")
    else:
        detail = f" — {result.detail}" if result.detail else ""
        print(f"→ nexi-ui says {result.status.value}{detail}")


def show(routed, send=False):
    """Print the routed Action and what nexi-ui would do with it."""
    action = routed.action
    print(action.model_dump_json(exclude_defaults=True))
    where = f"tier {routed.tier}" if routed.tier else "no command heard"
    if action.is_executable():
        print(f"→ would execute ({where}, confidence {action.confidence:.2f})")
    else:
        why = "unclassified" if action.type.value == "unknown" else "needs confirmation"
        print(f"→ would ask first — {why} ({where}, confidence {action.confidence:.2f})")

    # An unclassified action is not worth a round trip; nexi-ui can do nothing
    # with it and the user has already been told it was not understood.
    if send and action.type.value != "unknown":
        deliver(action)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", help="Route this text instead of recording")
    parser.add_argument("--no-tier2", action="store_true", help="Skip the LLM fallback")
    parser.add_argument("--send", action="store_true",
                        help="Send the Action to nexi-ui on port 9001")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--device", type=int, help="Microphone device index")
    args = parser.parse_args()
    use_tier2 = not args.no_tier2

    try:
        from intent.router import route_detailed
        if args.text:
            show(route_detailed(args.text, use_tier2=use_tier2), send=args.send)
            return 0

        import sounddevice as sd
        from voice.pipeline import listen_once
        from voice.transcriber import SILENCE_RMS, Transcriber, rms
        if args.list_devices:
            print(sd.query_devices())
            return 0

        print("Loading local Whisper base…")
        transcriber = Transcriber()
        while True:
            drain_stdin()
            if input(f"Enter to record {SECONDS:.0f} seconds, or q to quit: ").strip().lower() == "q":
                return 0
            print(f"Recording {SECONDS:.0f} seconds — speak now…", flush=True)
            result, audio = listen_once(transcriber, seconds=SECONDS,
                                        device=args.device, with_audio=True)
            print("Transcribing…", flush=True)
            print(json.dumps(result, ensure_ascii=False))
            if not result["text"]:
                level = rms(audio)
                if level < SILENCE_RMS:
                    print(f"Silence (level {level:.5f}) — the microphone captured nothing.")
                else:
                    print(f"Audio captured (level {level:.5f}) but no speech recognized.")
                continue
            show(route_detailed(result["text"], use_tier2=use_tier2), send=args.send)
    except (KeyboardInterrupt, EOFError):
        print("Stopped.")
        return 0
    except ImportError as exc:
        print(f"Missing dependency: {exc}. Install requirements-intent.txt.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Intent demo failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
