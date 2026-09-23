"""Tier 1: fast local intent classification.

A TF-IDF + logistic-regression model over a seed corpus, plus regex slot
extraction. Covers the common phrasings without touching the LLM; anything it
is not confident about is handed to Tier 2 by the router.
"""
import re

from schema.action import Action, ActionType

# Seed corpus. Small on purpose — the router's threshold sends anything
# ambiguous to Tier 2 rather than letting a thin model guess.
INTENT_EXAMPLES = {
    ActionType.APP_LAUNCH: [
        "open chrome", "open google chrome", "launch vs code", "start spotify",
        "run notepad", "open the browser", "launch terminal", "open vlc",
        "fire up discord", "open my editor", "start the music player",
        "open settings", "launch file explorer", "open calculator",
    ],
    ActionType.FILE_OPEN: [
        "open the batman dot mp4", "play the batman", "open my report file",
        "open budget spreadsheet", "play that movie", "open notes dot txt",
        "open the pdf", "open my thesis document", "play the song",
        "open readme dot md", "open the presentation",
    ],
    ActionType.TEXT_INPUT: [
        "type hello world", "write an email to john", "enter my password",
        "type out the address", "write down these notes", "type this message",
        "enter the search query", "write hello there", "type my name",
    ],
    ActionType.WINDOW_CONTROL: [
        "close this window", "minimize chrome", "maximize the window",
        "switch to vs code", "focus the browser", "close that tab",
        "minimize everything", "bring up spotify", "switch windows",
    ],
    ActionType.WORKFLOW_REPLAY: [
        "start my session", "run my morning routine", "do my usual setup",
        "start my workflow", "run my coding setup", "do the usual",
        "start my work session", "replay my routine", "run my evening setup",
    ],
    ActionType.UNKNOWN: [
        "hello", "hey there", "how are you", "what is the weather",
        "tell me a joke", "what time is it", "thanks", "never mind",
        "who are you", "what can you do", "goodbye", "nothing",
    ],
}

KNOWN_APPS = {
    "chrome", "firefox", "safari", "edge", "brave", "vlc", "spotify",
    "discord", "slack", "notepad", "terminal", "vscode", "code", "word",
    "excel", "powerpoint", "calculator", "settings", "explorer", "finder",
}

# Words that carry no slot meaning once the verb is stripped.
FILLER = {"the", "my", "a", "an", "up", "please", "that", "this", "some", "to"}

_APP_VERB = re.compile(r"\b(?:open|launch|start|run|fire up|bring up)\b", re.I)
_FILE_VERB = re.compile(r"\b(?:open|play)\b", re.I)
_TEXT_VERB = re.compile(r"\b(?:type|write|enter)\b(?:\s+(?:out|down))?", re.I)
_WINDOW_VERB = re.compile(r"\b(?:close|minimize|maximize|focus|switch to)\b", re.I)
_WORKFLOW_VERB = re.compile(r"\b(?:start|run|do|replay)\s+(?:my|the)\b", re.I)

_pipeline = None


def _model():
    """Build and fit the classifier once, on first use."""
    global _pipeline
    if _pipeline is None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline

        texts, labels = [], []
        for intent, examples in INTENT_EXAMPLES.items():
            texts.extend(examples)
            labels.extend([intent.value] * len(examples))
        _pipeline = make_pipeline(
            TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True),
            LogisticRegression(max_iter=1000, C=4.0),
        )
        _pipeline.fit(texts, labels)
    return _pipeline


def classify(text):
    """Return (ActionType, confidence) for a transcript."""
    if not text or not text.strip():
        return ActionType.UNKNOWN, 0.0
    model = _model()
    probabilities = model.predict_proba([text])[0]
    best = probabilities.argmax()
    return ActionType(model.classes_[best]), float(probabilities[best])


def _tail(pattern, text):
    """Everything after the matched verb, with filler words removed."""
    match = pattern.search(text)
    if not match:
        return None
    words = [w for w in text[match.end():].split() if w.lower().strip(".,!?") not in FILLER]
    return " ".join(words).strip(".,!? ") or None


def extract_slots(text, action_type):
    """Pull the one field this action type needs out of the transcript."""
    if action_type is ActionType.APP_LAUNCH:
        tail = _tail(_APP_VERB, text)
        if tail:
            for word in tail.lower().split():
                if word in KNOWN_APPS:
                    return {"app": word}
            return {"app": tail.split()[0]}
    elif action_type is ActionType.FILE_OPEN:
        tail = _tail(_FILE_VERB, text)
        if tail:
            return {"file": tail}
    elif action_type is ActionType.TEXT_INPUT:
        tail = _tail(_TEXT_VERB, text)
        if tail:
            return {"text": tail}
    elif action_type is ActionType.WINDOW_CONTROL:
        tail = _tail(_WINDOW_VERB, text)
        if tail:
            return {"target": tail}
    elif action_type is ActionType.WORKFLOW_REPLAY:
        tail = _tail(_WORKFLOW_VERB, text)
        if tail:
            return {"workflow": tail}
    return {}


def classify_action(text):
    """Classify and fill slots. Returns an Action, UNKNOWN if slots are missing."""
    action_type, confidence = classify(text)
    slots = extract_slots(text, action_type)
    if action_type is not ActionType.UNKNOWN and not slots:
        # Right intent, nothing to act on — let Tier 2 try instead.
        return Action(type=ActionType.UNKNOWN, confidence=0.0, utterance=text)
    return Action(type=action_type, confidence=confidence, utterance=text, **slots)
