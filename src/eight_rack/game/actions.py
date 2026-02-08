"""Game action type definitions."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class ActionType(str, Enum):
    PLAY_LAND = "play_land"
    CAST_SPELL = "cast_spell"
    ACTIVATE_ABILITY = "activate_ability"
    ATTACK = "attack"
    BLOCK = "block"
    PASS_PRIORITY = "pass_priority"
    DISCARD = "discard"  # for hand size / spell effects
    CHOOSE_TARGET = "choose_target"  # sub-action for targeting
    MULLIGAN = "mulligan"
    KEEP_HAND = "keep_hand"
    CONCEDE = "concede"


class Action(BaseModel):
    """A game action taken by a player."""

    type: ActionType
    player_id: str
    card_id: Optional[str] = None  # the card being played/activated
    card_name: str = ""  # for display
    targets: list[str] = []  # card_ids or "player:<id>"
    choices: dict[str, str] = {}  # named choices (e.g., mode selection)
    description: str = ""

    def __str__(self) -> str:
        if self.description:
            return self.description
        match self.type:
            case ActionType.PLAY_LAND:
                return f"Play {self.card_name}"
            case ActionType.CAST_SPELL:
                return f"Cast {self.card_name}"
            case ActionType.ACTIVATE_ABILITY:
                return f"Activate {self.card_name}"
            case ActionType.ATTACK:
                return f"Attack with {self.card_name}"
            case ActionType.BLOCK:
                return f"Block with {self.card_name}"
            case ActionType.PASS_PRIORITY:
                return "Pass priority"
            case ActionType.DISCARD:
                return f"Discard {self.card_name}"
            case _:
                return f"{self.type.value}: {self.card_name}"


class ActionResult(BaseModel):
    """Result of resolving an action."""

    success: bool = True
    message: str = ""
    state_changes: list[str] = []  # human-readable log of what changed
    tier_used: int = 1  # which adjudication tier handled this (1, 2, or 3)
