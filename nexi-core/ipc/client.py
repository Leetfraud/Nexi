"""Send Actions to nexi-ui over the socket on port 9001.

One connection per action. Actions are seconds apart at best, so pooling buys
nothing, and a fresh connection each time means restarting nexi-ui cannot
wedge this side of the pipeline.

Unreachable is not fatal: send_action returns None rather than raising, the
same fail-soft contract tier 2 uses when Ollama is down. A missing UI degrades
the pipeline instead of stopping it.
"""
import socket

from schema.action import Action
from schema.result import ActionResult, ResultStatus

HOST = "127.0.0.1"
PORT = 9001

# A plain action is answered at machine speed. One that needs confirmation
# waits on a human reading a prompt, so it gets a far longer budget.
TIMEOUT = 5.0
CONFIRM_TIMEOUT = 120.0

# A peer that never sends a newline must not grow the buffer without bound.
MAX_REPLY = 64 * 1024


def _read_line(sock):
    """Read one newline-delimited reply, or None if the peer never sends one."""
    buffer = b""
    while b"\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            return None
        buffer += chunk
        if len(buffer) > MAX_REPLY:
            return None
    return buffer.split(b"\n", 1)[0].decode("utf-8", errors="replace")


def send_action(action: Action, host=HOST, port=PORT, timeout=None):
    """Send one Action and wait for nexi-ui's result.

    Returns an ActionResult, or None when nexi-ui cannot be reached or answers
    with nothing. Callers should treat None as "the UI is not running".
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT if action.requires_confirmation else TIMEOUT

    payload = (action.model_dump_json() + "\n").encode("utf-8")
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(payload)
            line = _read_line(sock)
    except OSError:
        return None

    if line is None:
        return None
    try:
        return ActionResult.model_validate_json(line)
    except ValueError:
        # nexi-ui answered with something that is not an ActionResult. That is
        # a failure to report, not a reason to crash the voice pipeline.
        return ActionResult(status=ResultStatus.FAILED,
                            detail=f"unparseable reply: {line[:120]}")
