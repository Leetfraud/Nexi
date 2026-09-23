"""Single entry point: transcript in, Action out.

Tier 1 answers when it is confident; otherwise Tier 2 (the local LLM) gets a
turn. Whatever comes back is put behind the confirmation gate if its
confidence is low, per the safety rules in the root README.
"""
from dataclasses import dataclass
from difflib import SequenceMatcher

from schema.action import Action, ActionType
from . import tier1_classifier, tier2_llm

WAKE_WORD = "nexi"
# Whisper renders the name inconsistently ("Nexzy", "Nexy", "next"), so the
# wake word is matched by similarity rather than equality.
WAKE_SIMILARITY = 0.6
GREETINGS = {"hey", "hi", "hello", "ok", "okay", "yo"}

# Below this, Tier 1's answer is not trusted and Tier 2 is asked.
TIER1_THRESHOLD = 0.55
# Below this, the action is never executed without confirming first.
CONFIDENCE_FLOOR = 0.5


def _similar(word, target=WAKE_WORD):
    return SequenceMatcher(None, word, target).ratio() >= WAKE_SIMILARITY


def strip_wake_word(text):
    """Drop a leading greeting and wake word. Returns (text, wake_word_heard)."""
    words = text.split()
    heard = False
    index = 0
    while index < len(words) and index < 3:
        bare = words[index].lower().strip(".,!?;:")
        if not bare:
            index += 1
        elif bare in GREETINGS:
            index += 1
        elif _similar(bare):
            heard = True
            index += 1
            break
        else:
            break
    return " ".join(words[index:]).strip(), heard


@dataclass
class Routed:
    """An Action plus how it was reached. The diagnostics stay out of Action
    itself so the contract mirrored in nexi-ui carries only what it executes."""
    action: Action
    tier: int
    wake_word: bool


def route_detailed(text, use_tier2=True):
    """Classify one transcript, reporting which tier answered."""
    command, heard_wake_word = strip_wake_word(text or "")
    if not command:
        empty = Action(type=ActionType.UNKNOWN, confidence=0.0, utterance=text or "")
        return Routed(empty, 0, heard_wake_word)

    action = tier1_classifier.classify_action(command)
    tier = 1

    if action.type is ActionType.UNKNOWN or action.confidence < TIER1_THRESHOLD:
        if use_tier2:
            escalated = tier2_llm.classify_action(command)
            if escalated is not None:
                action, tier = escalated, 2

    # Preserve what the user actually said, wake word and all, so nexi-ui can
    # quote it back when it asks for confirmation.
    action.utterance = text
    if action.confidence < CONFIDENCE_FLOOR:
        action.requires_confirmation = True
    return Routed(action, tier, heard_wake_word)


def route(text, use_tier2=True):
    """Classify one transcript into an Action."""
    return route_detailed(text, use_tier2).action
