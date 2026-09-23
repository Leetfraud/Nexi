"""Connect microphone input to transcription."""
from .recorder import record


def listen_once(transcriber, seconds=5.0, device=None, with_audio=False):
    """Record one take and transcribe it.

    with_audio also returns the samples, so a caller can tell a dead microphone
    apart from speech Whisper failed to recognize.
    """
    audio = record(seconds, device)
    result = transcriber.transcribe(audio)
    return (result, audio) if with_audio else result
