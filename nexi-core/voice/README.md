# Task 1: voice to text

Enter → five-second recording → local Whisper base → JSON transcript.
This initial version transcribes English. Audio stays in memory, is not saved,
and is not uploaded. It displays text without executing commands or needing the daemon.

## Files

- `recorder.py`: captures 16 kHz mono float32 microphone samples.
- `transcriber.py`: loads the downloaded model once and recognizes speech on CPU.
- `pipeline.py`: connects recording and transcription; `with_audio=True`
  also returns the samples so a caller can tell a dead microphone apart
  from unrecognized speech.
- `../voice_demo.py`: terminal interaction and structured output.
- `../download_model.py`: explicit one-time model download.

## Setup (from nexi-core)

Use Python 3.11 for this starter.

macOS/Linux:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-voice.txt
.venv/bin/python download_model.py
.venv/bin/python voice_demo.py
```

Windows:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-voice.txt
.venv\Scripts\python download_model.py
.venv\Scripts\python voice_demo.py
```

Allow terminal microphone access when prompted. Use `voice_demo.py --list-devices`
and `voice_demo.py --device INDEX` to choose a microphone supporting 16 kHz mono.
Linux may require the system PortAudio library. Whisper's general setup includes
FFmpeg; this demo supplies an audio array directly instead of decoding audio files.

## Manual check

Press Enter, say “Open Chrome” within five seconds, and check the JSON text.
Repeat with “Start my session”, silence, and Ctrl+C.
The output fields are `event_type: voice_transcript`, `text`, and `language: en`.
This is a voice event, separate from the desktop Action schema.

Keys pressed while a take is recording are discarded, so mashing Enter during
the five seconds no longer starts an immediate second take that records silence
before you are ready to speak.

When the text comes back empty the demo reports the measured input level and
says which case it was: silence (below the `SILENCE_RMS` gate in
`transcriber.py`, so nothing reached Whisper) or audio that Whisper heard but
could not resolve into speech.

The energy threshold skips near-silence, but noise can still produce incorrect
transcripts, and short takes can repeat a phrase ("Open chrome. Open chrome.").
Microphone quality and actual inference latency need real-device validation
before connecting this module to automation.

## Troubleshooting

`download_model.py` failing with `CERTIFICATE_VERIFY_FAILED: self-signed
certificate in certificate chain` means the network is intercepting TLS, not
that a CA bundle is missing — the script already points OpenSSL at `certifi`.
Run it again on a network that does not intercept, or export `SSL_CERT_FILE`
to a bundle containing the interceptor's root. The script is safe to re-run: it
verifies the checkpoint already in `models/whisper` and skips the download.

References: https://github.com/openai/whisper and
https://python-sounddevice.readthedocs.io/en/latest/usage.html
