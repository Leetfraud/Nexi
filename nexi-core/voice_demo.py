"""Press Enter to record five seconds and print a local transcript."""
import argparse
import json
import sys

SECONDS = 5.0


def drain_stdin():
    """Discard keystrokes typed while recording.

    Enter presses during a take stay buffered, so the next input() returns
    immediately and records silence before the user is ready to speak.
    """
    try:
        if sys.platform == "win32":
            import msvcrt
            while msvcrt.kbhit():
                msvcrt.getwch()
        else:
            import termios
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass  # Not a terminal (piped input); nothing to drain.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--device", type=int, help="Microphone device index")
    args = parser.parse_args()
    try:
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
                    print(f"Silence (level {level:.5f}) — the microphone captured nothing. "
                          "Check the input device and that the terminal has microphone access.")
                else:
                    print(f"Audio captured (level {level:.5f}) but no speech recognized. "
                          "Speak up, closer to the microphone.")
    except (KeyboardInterrupt, EOFError):
        print("Stopped.")
        return 0
    except ImportError as exc:
        print(f"Missing dependency: {exc}. Install requirements-voice.txt.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Voice demo failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
