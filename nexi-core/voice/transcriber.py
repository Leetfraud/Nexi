"""Reuse a downloaded Whisper model; no runtime model download."""
from pathlib import Path
MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "whisper"
# Below this level the take is treated as silence and never reaches Whisper,
# which otherwise invents text for near-empty audio.
SILENCE_RMS = 0.001


def rms(audio):
    """Root-mean-square level of a take, for the silence gate and for feedback."""
    import numpy as np
    return float(np.sqrt(np.mean(audio ** 2)))


class Transcriber:
    def __init__(self):
        import whisper
        checkpoint = MODEL_DIR / "base.pt"
        if not checkpoint.is_file():
            raise FileNotFoundError("Run python download_model.py first.")
        self.model = whisper.load_model(str(checkpoint), device="cpu")

    def transcribe(self, audio):
        import numpy as np
        if audio.ndim != 1 or not audio.size or not np.isfinite(audio).all():
            raise ValueError("Expected finite, nonempty mono 16 kHz audio.")
        # Energy check only, not a speech detector.
        if rms(audio) < SILENCE_RMS:
            return {"event_type": "voice_transcript", "text": "", "language": "en"}
        result = self.model.transcribe(audio, language="en", fp16=False,
                                      condition_on_previous_text=False)
        return {"event_type": "voice_transcript", "text": result["text"].strip(),
                "language": result["language"]}
