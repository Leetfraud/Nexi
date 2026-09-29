"""The Action contract: nexi-core emits these, nexi-ui executes them.

Mirrored in nexi-ui/schema — the two copies must stay identical. Field names
follow the agreed shape in Context.txt; `confidence`, `requires_confirmation`
and `utterance` are added so the safety rules in the root README can actually
travel with the action instead of being re-derived by the executor.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "1.0"


class ActionType(str, Enum):
    APP_LAUNCH = "app_launch"
    FILE_OPEN = "file_open"
    TEXT_INPUT = "text_input"
    WINDOW_CONTROL = "window_control"
    WORKFLOW_REPLAY = "workflow_replay"
    UNKNOWN = "unknown"


# Verbs that force the confirmation gate. The root README makes delete, send
# and submit non-negotiable; the rest are the same class of irreversible act.
DESTRUCTIVE_KEYWORDS = frozenset({
    "delete", "remove", "erase", "trash", "wipe", "drop", "overwrite",
    "send", "submit", "post", "publish", "reply",
    "uninstall", "format", "shutdown", "restart", "kill",
})

# Destructive intents that only read as destructive across two words, so the
# single-token check above misses them ("shut everything down", "log off").
DESTRUCTIVE_PHRASES = (
    "shut down", "shutting down", "power off", "turn off", "log off",
    "log out", "sign out", "close all", "close everything",
    "delete all", "empty trash", "factory reset",
)


def _reads_destructive(haystack):
    """True when the words describe an irreversible act."""
    if any(word in haystack.split() for word in DESTRUCTIVE_KEYWORDS):
        return True
    if any(phrase in haystack for phrase in DESTRUCTIVE_PHRASES):
        return True
    # "shut everything down", "shut it all down" — split verb and particle.
    words = haystack.split()
    if "shut" in words and "down" in words:
        return True
    return False

# Field that must be populated for each type to be executable.
REQUIRED_FIELD = {
    ActionType.APP_LAUNCH: "app",
    ActionType.FILE_OPEN: "file",
    ActionType.TEXT_INPUT: "text",
    ActionType.WINDOW_CONTROL: "target",
    ActionType.WORKFLOW_REPLAY: "workflow",
}


class Action(BaseModel):
    """One executable desktop action."""

    type: ActionType
    app: Optional[str] = None
    file: Optional[str] = None
    path: Optional[str] = None
    text: Optional[str] = None
    target: Optional[str] = None
    workflow: Optional[str] = None
    steps: list[str] = Field(default_factory=list)

    confidence: float = Field(0.0, ge=0.0, le=1.0)
    requires_confirmation: bool = False
    # The transcript this came from. Kept so nexi-ui can show the user what it
    # heard when it asks to confirm, and so the gate below can read the
    # original words rather than trusting the classifier's summary.
    utterance: str = ""

    @model_validator(mode="after")
    def _enforce_contract(self):
        required = REQUIRED_FIELD.get(self.type)
        if required and not getattr(self, required):
            raise ValueError(f"{self.type.value} requires a non-empty '{required}'")

        # An action nobody could classify is never executed unattended.
        if self.type is ActionType.UNKNOWN:
            self.requires_confirmation = True

        # Backstop: the gate can be raised here but never lowered, so a
        # confident-but-wrong Tier-2 answer cannot opt out of confirmation.
        haystack = " ".join(
            part.lower() for part in
            (self.utterance, self.text, self.file, self.target, self.workflow, *self.steps)
            if part
        )
        if _reads_destructive(haystack):
            self.requires_confirmation = True
        return self

    def is_executable(self) -> bool:
        """True when nexi-ui may run this without asking first."""
        return self.type is not ActionType.UNKNOWN and not self.requires_confirmation
