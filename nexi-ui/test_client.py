"""Sends a few sample Actions to action_server.py, so you can test your
whole nexi-ui layer without needing Azmeer's real nexi-core running yet.

Run action_server.py first (in another terminal), then run this:
    python test_client.py
"""
import socket

from schema.action import Action, ActionType

HOST = "127.0.0.1"
PORT = 9001


def send(action: Action, timeout: float = 30.0):
    payload = (action.model_dump_json() + "\n").encode("utf-8")
    with socket.create_connection((HOST, PORT), timeout=timeout) as sock:
        sock.sendall(payload)
        sock.settimeout(timeout)
        buffer = b""
        while b"\n" not in buffer:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
        print("  reply:", buffer.split(b"\n", 1)[0].decode("utf-8", errors="replace"))


if __name__ == "__main__":
    print("1) Plain action - should just run, no popup")
    send(Action(type=ActionType.APP_LAUNCH, app="notepad",
                confidence=0.95, utterance="open notepad"))

    input("\nPress Enter to send the next one...")

    print("2) Destructive wording - should trigger the confirmation popup")
    send(Action(type=ActionType.FILE_OPEN, file="test.txt",
                confidence=0.9, utterance="delete test.txt"),
         timeout=125.0)  # matches CONFIRM_TIMEOUT in the real client

    input("\nPress Enter to send the next one...")

    print("3) Unknown action - should be declined with no popup at all")
    send(Action(type=ActionType.UNKNOWN, utterance="do the thing"))

    print("\nDone. Check action_server.py's terminal for the <- / -> log lines too.")
