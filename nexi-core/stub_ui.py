"""A stand-in for nexi-ui's action_server.py, so the sender can be tested alone.

This is a test double, not an implementation. It speaks the wire format and
answers correctly, but it never touches the desktop — executing actions is
nexi-ui's job, and this file deliberately stops at the layer boundary.

It doubles as the reference for the wire format: one Action arrives as a line
of JSON, one ActionResult goes back as a line of JSON, then the connection
closes.

    python stub_ui.py              # ask at the terminal when confirmation is needed
    python stub_ui.py --auto       # confirm everything, for scripted runs
    python stub_ui.py --decline    # refuse everything, to exercise the no path
"""
import argparse
import socket
import sys

from schema.action import Action
from schema.result import ActionResult, ResultStatus

HOST = "127.0.0.1"
PORT = 9001
MAX_REQUEST = 64 * 1024


def read_line(conn):
    """Read one newline-delimited Action, or None if the peer sends none."""
    buffer = b""
    while b"\n" not in buffer:
        chunk = conn.recv(4096)
        if not chunk:
            return None
        buffer += chunk
        if len(buffer) > MAX_REQUEST:
            return None
    return buffer.split(b"\n", 1)[0].decode("utf-8", errors="replace")


def decide(action, mode):
    """Answer one Action the way nexi-ui would, minus the desktop control."""
    if action.requires_confirmation:
        if mode == "auto":
            answer = True
        elif mode == "decline":
            answer = False
        else:
            quoted = action.utterance or action.type.value
            try:
                answer = input(f'  Confirm "{quoted}"? [y/N] ').strip().lower() == "y"
            except EOFError:
                answer = False
        if not answer:
            return ActionResult(status=ResultStatus.DECLINED,
                                detail="user refused at the confirmation prompt")
    elif mode == "decline":
        return ActionResult(status=ResultStatus.DECLINED, detail="stub refuses everything")

    # A real nexi-ui would act here. The stub only reports what it would do.
    return ActionResult(status=ResultStatus.EXECUTED,
                        detail=f"stub would run {action.type.value}")


def serve(port, mode):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, port))
        server.listen(5)
        print(f"Stub nexi-ui listening on {HOST}:{port} (mode: {mode})")
        print("Nothing is executed. Ctrl-C to stop.\n")

        while True:
            conn, _ = server.accept()
            with conn:
                line = read_line(conn)
                if line is None:
                    continue
                try:
                    action = Action.model_validate_json(line)
                except ValueError as exc:
                    # Pydantic errors run to several lines; the reply is one
                    # line of JSON, so keep the detail short enough to read.
                    why = " ".join(str(exc).split())[:200]
                    print(f"← rejected: {why}")
                    reply = ActionResult(status=ResultStatus.UNSUPPORTED,
                                         detail=f"not a valid Action: {why}")
                else:
                    gate = " (needs confirmation)" if action.requires_confirmation else ""
                    print(f"← {action.type.value}{gate}: {line}")
                    reply = decide(action, mode)
                conn.sendall((reply.model_dump_json() + "\n").encode("utf-8"))
                print(f"→ {reply.status.value}: {reply.detail}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=PORT)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--auto", action="store_true", help="Confirm without asking")
    group.add_argument("--decline", action="store_true", help="Refuse everything")
    args = parser.parse_args()
    mode = "auto" if args.auto else "decline" if args.decline else "ask"

    try:
        serve(args.port, mode)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except OSError as exc:
        print(f"Cannot listen on port {args.port}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
