"""Offline text-to-speech with Piper.

Why this file is built the way it is: the first version launched a brand-new
`python -m piper` process for every sentence, which reloaded the ~63 MB voice
model from disk each time (seconds of delay before any sound). Now the model
is loaded ONCE and kept in memory; each sentence is synthesised in-process
straight into an in-memory WAV and played from memory. Sentences Nexi has
already said are cached, so repeats are instant.

If the fast path ever fails, speak() falls back to the old slow-but-simple
command-line route rather than staying silent.
"""
import io
import os
import subprocess
import sys
import tempfile
import threading
import wave

import winsound

DEFAULT_MODEL = os.path.join(
    os.path.dirname(__file__), "models", "en_US-lessac-medium.onnx"
)

_voice = None
_voice_path = None
_lock = threading.Lock()      # one synthesis at a time (model isn't thread-safe)
_cache = {}                   # (model_path, text) -> wav bytes
_CACHE_MAX = 32


def _load_voice(model_path: str):
    global _voice, _voice_path
    if _voice is None or _voice_path != model_path:
        from piper import PiperVoice
        _voice = PiperVoice.load(model_path)
        _voice_path = model_path
    return _voice


def _synthesize(text: str, model_path: str) -> bytes:
    """Text -> WAV bytes. Caller must hold _lock."""
    key = (model_path, text)
    if key in _cache:
        return _cache[key]

    voice = _load_voice(model_path)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        voice.synthesize_wav(text, wav)
    data = buf.getvalue()

    if len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))   # drop the oldest entry
    _cache[key] = data
    return data


def warm_up(model_path: str = DEFAULT_MODEL):
    """Load the voice and run one throwaway sentence so the FIRST real
    speak() is as fast as the rest. Call this in a background thread at
    startup so it doesn't hold anything up."""
    if not os.path.exists(model_path):
        print(f"[TTS] Voice model not found at {model_path}")
        return
    try:
        with _lock:
            _synthesize("ready", model_path)
        print("[TTS] voice ready")
    except Exception as exc:  # noqa: BLE001
        print(f"[TTS] warm-up failed (will use slow fallback): {exc}")


def speak(text: str, model_path: str = DEFAULT_MODEL):
    """Speak `text` and block until it finishes playing. action_server.py
    calls this AFTER the ActionResult has been sent back, so it never eats
    into nexi-core's reply timeout."""
    if not text or not text.strip():
        return
    if not os.path.exists(model_path):
        print(f"[TTS] Voice model not found at {model_path}")
        return

    try:
        with _lock:
            wav_bytes = _synthesize(text, model_path)
        # Played outside the lock so a warm-up/next sentence isn't blocked.
        winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)
    except Exception as exc:  # noqa: BLE001
        print(f"[TTS] fast path failed ({exc}); using slow fallback")
        _speak_via_cli(text, model_path)


def _speak_via_cli(text: str, model_path: str):
    """The original approach: spawn piper, write a temp .wav, play it."""
    wav_path = None
    try:
        fd, wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        subprocess.run(
            [sys.executable, "-m", "piper", "--model", model_path,
             "--output_file", wav_path],
            input=text.encode("utf-8"), check=True, capture_output=True,
        )
        winsound.PlaySound(wav_path, winsound.SND_FILENAME)
    except subprocess.CalledProcessError as exc:
        print(f"[TTS] Piper failed: {exc.stderr.decode(errors='ignore')}")
    finally:
        if wav_path and os.path.exists(wav_path):
            os.remove(wav_path)


if __name__ == "__main__":
    # Standalone check: the first line pays the one-time load, the second
    # (and anything repeated) should start almost instantly.
    import time
    t = time.time(); warm_up(); print(f"warm-up: {time.time() - t:.2f}s")
    t = time.time(); speak("Hello, this is Nexi. Voice is working.")
    print(f"first sentence (synth + play): {time.time() - t:.2f}s")
    t = time.time(); speak("Hello, this is Nexi. Voice is working.")
    print(f"same sentence again (cached): {time.time() - t:.2f}s")
