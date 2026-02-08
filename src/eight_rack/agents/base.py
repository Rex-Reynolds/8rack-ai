"""Base agent protocol and utilities."""

from __future__ import annotations

from typing import Protocol

from ..game.actions import Action
from ..game.state import CardInstance, GameState


class Agent(Protocol):
    """Protocol for game agents."""

    @property
    def name(self) -> str: ...

    def choose_action(self, state: GameState, legal_actions: list[Action]) -> Action:
        """Choose an action from the legal options."""
        ...

    def choose_mulligan(self, hand: list[str], mulligans: int) -> bool:
        """Return True to mulligan, False to keep."""
        ...

    def choose_cards_to_bottom(
        self, hand: list[CardInstance], count: int
    ) -> list[str]:
        """Choose `count` cards to put on bottom for London mulligan. Returns card_ids."""
        ...

    def choose_discard_target(
        self, state: GameState, opponent_hand: list[CardInstance]
    ) -> str | None:
        """Choose a card from the opponent's revealed hand to make them discard.
        Returns card_id or None."""
        ...

    def choose_discard_from_hand(
        self, state: GameState, hand: list[CardInstance]
    ) -> str | None:
        """Choose a card from own hand to discard. Returns card_id or None."""
        ...

    def choose_sacrifice(
        self, state: GameState, candidates: list[CardInstance]
    ) -> str | None:
        """Choose a permanent to sacrifice from candidates. Returns card_id or None."""
        ...
