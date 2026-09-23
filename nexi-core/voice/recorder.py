"""Record in-memory mono audio for Whisper."""
import math
SAMPLE_RATE = 16000


def record(seconds=5.0, device=None):
    if not math.isfinite(seconds) or not 0 < seconds <= 30:
        raise ValueError("Duration must be greater than zero and at most 30 seconds.")
    import sounddevice as sd
    sd.check_input_settings(device=device, channels=1, dtype="float32", samplerate=SAMPLE_RATE)
    try:
        audio = sd.rec(round(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                       channels=1, dtype="float32", device=device)
        status = sd.wait()
        if status:
            raise RuntimeError(f"Audio capture failed: {status}")
        return audio[:, 0].copy()
    finally:
        sd.stop()
