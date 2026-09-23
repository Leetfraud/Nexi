"""Explicit one-time model setup; requires internet."""
from voice.transcriber import MODEL_DIR
import os

if __name__ == "__main__":
    import certifi
    import whisper
    # Python.org macOS installs may not have their default CA bundle configured.
    # Keep certificate verification enabled and respect a custom CA configuration.
    if not os.environ.get("SSL_CERT_FILE") and not os.environ.get("SSL_CERT_DIR"):
        os.environ["SSL_CERT_FILE"] = certifi.where()
    print(f"Downloading/checking Whisper base in {MODEL_DIR}")
    whisper.load_model("base", device="cpu", download_root=str(MODEL_DIR))
    print("Ready. Run python voice_demo.py")
