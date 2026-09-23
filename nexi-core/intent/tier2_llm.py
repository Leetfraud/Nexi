"""Tier 2: local LLM fallback via Ollama.

Used when Tier 1 is not confident. Asks the model for a single JSON Action and
validates it against the schema — a malformed or unexecutable answer is
downgraded to UNKNOWN rather than trusted.
"""
import json
import os

from schema.action import Action, ActionType

OLLAMA_URL = os.environ.get("NEXI_OLLAMA_URL", "http://localhost:11434")
# Context.txt specifies Phi-3 Mini; override with NEXI_OLLAMA_MODEL to match
# whatever is actually pulled on the machine.
MODEL = os.environ.get("NEXI_OLLAMA_MODEL", "gemma3:4b")
TIMEOUT = float(os.environ.get("NEXI_OLLAMA_TIMEOUT", "30"))

SYSTEM_PROMPT = """You convert a spoken desktop command into one JSON action.

Reply with ONLY a JSON object, no prose. Use exactly these fields:
  "type"     one of: app_launch, file_open, text_input, window_control, workflow_replay, unknown
  "app"      required when type is app_launch      (e.g. "chrome")
  "file"     required when type is file_open       (e.g. "The Batman.mp4")
  "text"     required when type is text_input      (the literal text to type)
  "target"   required when type is window_control  (which window)
  "workflow" required when type is workflow_replay (the saved workflow name)
  "path"     optional directory hint
  "steps"    optional list of short human-readable steps
  "confidence" your confidence from 0.0 to 1.0

Use "unknown" when the command is chit-chat, a question, or too vague to act on.
Never invent a file or app that was not mentioned.

Examples:
  "open chrome" -> {"type":"app_launch","app":"chrome","confidence":0.95}
  "play the batman" -> {"type":"file_open","file":"The Batman","confidence":0.8}
  "start my session" -> {"type":"workflow_replay","workflow":"session","confidence":0.9}
  "what time is it" -> {"type":"unknown","confidence":0.9}
"""

FIELDS = {"type", "app", "file", "path", "text", "target", "workflow", "steps", "confidence"}


def available():
    """True when an Ollama server is reachable."""
    import requests
    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).raise_for_status()
        return True
    except Exception:
        return False


def classify_action(text, model=None):
    """Ask the LLM for an Action. Returns None when Ollama is unreachable."""
    import requests

    payload = {
        "model": model or MODEL,
        "prompt": f"{SYSTEM_PROMPT}\nCommand: {text!r}\nJSON:",
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
    }
    try:
        response = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=TIMEOUT)
        response.raise_for_status()
        raw = response.json().get("response", "")
    except Exception:
        return None

    return _to_action(raw, text)


def _to_action(raw, utterance):
    """Validate the model's JSON. Anything unusable becomes UNKNOWN."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return Action(type=ActionType.UNKNOWN, confidence=0.0, utterance=utterance)

    if not isinstance(data, dict):
        return Action(type=ActionType.UNKNOWN, confidence=0.0, utterance=utterance)

    fields = {k: v for k, v in data.items() if k in FIELDS and v is not None}
    fields["utterance"] = utterance
    if isinstance(fields.get("steps"), str):
        fields["steps"] = [fields["steps"]]
    try:
        return Action(**fields)
    except Exception:
        # Wrong shape, missing required slot, or a type outside the enum.
        return Action(type=ActionType.UNKNOWN, confidence=0.0, utterance=utterance)
