import threading
from pynput import keyboard


class KillSwitch:
    """
    Listens globally for Escape. This is deliberately independent of the
    socket to nexi-core - the root README requires stopping to work even
    if the connection to nexi-core is down or misbehaving.
    """

    def __init__(self):
        self._killed = threading.Event()
        self._start_listener()

    def _start_listener(self):
        def on_press(key):
            if key == keyboard.Key.esc:
                self._killed.set()
                print("[KILL SWITCH] Escape pressed — halting all Nexi actions.")

        self._listener = keyboard.Listener(on_press=on_press)
        self._listener.daemon = True
        self._listener.start()

    def is_killed(self) -> bool:
        return self._killed.is_set()

    def reset(self):
        self._killed.clear()
