"""What nexi-ui reports back after receiving an Action.

Mirrored in nexi-ui/schema alongside action.py — the two copies must stay
identical.

An Action can carry `requires_confirmation`, which means the user gets a
prompt and may refuse. Without a reply path nexi-core would never learn that
happened, so the confirmation gate the root README calls non-negotiable would
have no closed loop, and nothing could be measured for the FYP benchmark.
"""
from enum import Enum

from pydantic import BaseModel


class ResultStatus(str, Enum):
    EXECUTED = "executed"      # nexi-ui ran it
    DECLINED = "declined"      # the user said no at the confirmation prompt
    FAILED = "failed"          # nexi-ui tried and could not
    UNSUPPORTED = "unsupported"  # nexi-ui does not implement this action type


class ActionResult(BaseModel):
    """One reply to one Action."""

    status: ResultStatus
    # Free text for the human: the error, or what the user was asked.
    detail: str = ""

    def ok(self) -> bool:
        return self.status is ResultStatus.EXECUTED
