"""nexi-ui's action_server.py — the real counterpart to nexi-core/stub_ui.py.

Listens on 127.0.0.1:9001. One connection carries one Action in as a line
of JSON, one ActionResult goes back as a line of JSON, then the connection
closes — same framing stub_ui.py uses, so nexi-core cannot tell the
difference between talking to the stub and talking to this.

Threading note: PyQt5 widgets may only be touched from the main thread.
The socket server runs on a background thread so it can block on accept()
without freezing the UI event loop. UIBridge marshals calls back onto the
main thread - state changes are fire-and-forget, but confirmation needs a
genuine answer before the socket thread can reply to nexi-core, so that
one is a *blocking* queued connection: emitting it blocks the socket
thread until the main thread's popup actually returns.
"""
import os
import sys
import time
import socket
import threading
# ORDER MATTERS on Windows: onnxruntime (used by Piper) must load BEFORE
# PyQt5, or it fails with "DLL load failed ... initialization routine failed".
try:
    import onnxruntime  # noqa: F401
except Exception as exc:
    print(f"[TTS] onnxruntime could not be preloaded: {exc}")
import pyautogui
from PyQt5.QtCore import Qt, QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMessageBox

from schema.action import Action, ActionType
from schema.result import ActionResult, ResultStatus
from Companion.companion import NexiCompanion
from safety.kill_switch import KillSwitch
from voice.tts import speak, warm_up

pyautogui.FAILSAFE = True

HOST = "127.0.0.1"
PORT = 9001
MAX_REQUEST = 64 * 1024
# How long to let a freshly launched app/file appear before we report back.
# Lower = Nexi answers sooner; raise it if a following action (like typing)
# starts before the window has opened.
LAUNCH_SETTLE_SECONDS = 0.6


class UIBridge(QObject):
    state_changed = pyqtSignal(str)
    confirm_requested = pyqtSignal(str)

    def __init__(self, companion: NexiCompanion):
        super().__init__()
        self.companion = companion
        self._last_confirm_result = False

        self.state_changed.connect(self._on_state_changed)
        self.confirm_requested.connect(
            self._on_confirm_requested, Qt.BlockingQueuedConnection
        )

    def _on_state_changed(self, state: str):
        self.companion.set_state(state)

    def _on_confirm_requested(self, description: str):
        box = QMessageBox()
        box.setWindowFlags(box.windowFlags() | Qt.WindowStaysOnTopHint)
        box.setWindowTitle("Nexi needs confirmation")
        box.setText(f'Confirm: "{description}"?')
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        result = box.exec_()
        self._last_confirm_result = result == QMessageBox.Yes

    def set_state(self, state: str):
        self.state_changed.emit(state)

    def ask_confirmation(self, description: str) -> bool:
        """Blocks the calling (socket) thread until the popup is answered."""
        self.confirm_requested.emit(description)
        return self._last_confirm_result


def read_line(conn) -> str | None:
    buffer = b""
    while b"\n" not in buffer:
        chunk = conn.recv(4096)
        if not chunk:
            return None
        buffer += chunk
        if len(buffer) > MAX_REQUEST:
            return None
    return buffer.split(b"\n", 1)[0].decode("utf-8", errors="replace")


def execute(action: Action, bridge: UIBridge) -> ActionResult:
    """
    Runs one already-confirmed Action on the real desktop. Confirmation
    and the kill switch are handled by handle_connection() before this is
    reached - this function only does the PyAutoGUI/OS work.
    """
    bridge.set_state("Acting")
    try:
        if action.type == ActionType.APP_LAUNCH:
            os.system(f"start {action.app}")  # Windows-specific
            time.sleep(LAUNCH_SETTLE_SECONDS)
            return ActionResult(status=ResultStatus.EXECUTED, detail=f"opened {action.app}")

        elif action.type == ActionType.FILE_OPEN:
            target = os.path.join(action.path, action.file) if action.path else action.file
            if not os.path.exists(target):
                return ActionResult(status=ResultStatus.FAILED, detail=f"file not found: {target}")
            os.system(f'start "" "{target}"')
            time.sleep(LAUNCH_SETTLE_SECONDS)
            return ActionResult(status=ResultStatus.EXECUTED, detail=f"opened {target}")

        elif action.type == ActionType.TEXT_INPUT:
            pyautogui.typewrite(action.text, interval=0.03)
            return ActionResult(status=ResultStatus.EXECUTED, detail="typed text")

        elif action.type == ActionType.WINDOW_CONTROL:
            # No window-focus/minimize library wired in yet. Reporting
            # unsupported honestly rather than faking success.
            return ActionResult(
                status=ResultStatus.UNSUPPORTED,
                detail=f"window_control not implemented yet (target={action.target})",
            )

        elif action.type == ActionType.WORKFLOW_REPLAY:
            # Blocked on the open decision in docs/Design-notes.md: `steps`
            # here is a human-readable list[str], not executable
            # coordinates. Nothing safe to run until that's resolved with
            # Faseeh/Azmeer.
            return ActionResult(
                status=ResultStatus.UNSUPPORTED,
                detail=f"workflow_replay not wired yet (workflow={action.workflow})",
            )

        else:
            return ActionResult(
                status=ResultStatus.UNSUPPORTED,
                detail=f"unhandled type: {action.type.value}",
            )
    finally:
        bridge.set_state("Idle")


def handle_connection(conn, bridge: UIBridge, kill_switch: KillSwitch):
    line = read_line(conn)
    if line is None:
        return

    def reply(result: ActionResult):
        conn.sendall((result.model_dump_json() + "\n").encode("utf-8"))
        print(f"-> {result.status.value}: {result.detail}\n")

    try:
        action = Action.model_validate_json(line)
    except ValueError as exc:
        why = " ".join(str(exc).split())[:200]
        reply(ActionResult(status=ResultStatus.UNSUPPORTED, detail=f"not a valid Action: {why}"))
        return

    gate = " (needs confirmation)" if action.requires_confirmation else ""
    print(f"<- {action.type.value}{gate}: {line}")

    # The kill switch is nexi-ui's own responsibility (root README) and
    # applies regardless of what the schema says about this action.
    if kill_switch.is_killed():
        reply(ActionResult(status=ResultStatus.FAILED, detail="blocked: kill switch is active"))
        return

    # action.is_executable() is the single check this layer should use -
    # the schema already folded in the destructive-keyword and
    # low-confidence rules (see schema/action.py), so we don't re-derive
    # them here.
    if not action.is_executable():
        if action.type == ActionType.UNKNOWN:
            # Nothing to confirm running, since there's no action here at all.
            reply(ActionResult(status=ResultStatus.UNSUPPORTED, detail="command not understood"))
            return

        bridge.set_state("Thinking")
        quoted = action.utterance or action.type.value
        approved = bridge.ask_confirmation(quoted)
        bridge.set_state("Idle")

        if not approved:
            reply(ActionResult(
                status=ResultStatus.DECLINED,
                detail="user refused at the confirmation prompt",
            ))
            return
        # approved - fall through to execution below

    result = execute(action, bridge)
    reply(result)

    # Voice feedback happens AFTER the reply is sent, so it never delays
    # nexi-core's 5s (plain) / 120s (confirmed) reply budget.
    if result.status == ResultStatus.EXECUTED:
        bridge.set_state("Speaking")
        speak(result.detail)
        bridge.set_state("Idle")


def serve(bridge: UIBridge, kill_switch: KillSwitch, port: int = PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, port))
        server.listen(5)
        print(f"nexi-ui action_server listening on {HOST}:{port}")
        print("Nothing executes until a real Action arrives. Ctrl-C to stop.\n")

        while True:
            conn, _ = server.accept()
            with conn:
                try:
                    handle_connection(conn, bridge, kill_switch)
                except Exception as exc:  # noqa: BLE001 - keep the server alive
                    print(f"[action_server] error handling connection: {exc}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Without this, Qt auto-quits the whole app once it thinks the last
    # "real" window closed - and the companion's Qt.Tool flag means Qt
    # doesn't count it as one, so closing the confirmation popup alone
    # would otherwise kill the companion too.
    app.setQuitOnLastWindowClosed(False)

    companion = NexiCompanion()
    companion.show()

    bridge = UIBridge(companion)
    kill_switch = KillSwitch()

    server_thread = threading.Thread(
        target=serve, args=(bridge, kill_switch), daemon=True
    )
    server_thread.start()

    # Load the voice model now, in the background, so the first spoken
    # reply isn't slow.
    threading.Thread(target=warm_up, daemon=True).start()

    sys.exit(app.exec_())
