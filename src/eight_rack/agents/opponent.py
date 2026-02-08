"""LLM-driven opponent agent with archetype-specific strategy."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field

from ..game.actions import Action, ActionType
from ..game.state import CardInstance, GameState, VisibleGameState

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent.parent.parent / "config" / "prompts" / "opponents"


class OpponentActionChoice(BaseModel):
    """Structured LLM response for opponent action selection."""

    action_index: int = Field(description="Index of the chosen action (0-based)")
    reasoning: str = Field(description="Brief strategic reasoning")


class LLMOpponent:
    """LLM-piloted opponent with archetype-specific strategy.

    Uses cheaper models (Haiku) with archetype strategy prompts
    to play representatively (not optimally).
    """

    def __init__(
        self,
        archetype: str,
        llm_client=None,
        model: str = "haiku",
    ):
        self.archetype = archetype
        self._llm = llm_client
        self._model = model
        self._system_prompt: str | None = None
        self.llm_calls = 0

    @property
    def name(self) -> str:
        return f"{self.archetype} (LLM)"

    @property
    def system_prompt(self) -> str:
        if self._system_prompt is None:
            prompt_path = PROMPTS_DIR / f"{self.archetype}.md"
            if prompt_path.exists():
                self._system_prompt = prompt_path.read_text()
            else:
                self._system_prompt = (
                    f"You are piloting a {self.archetype} deck in Modern MTG. "
                    f"Play your cards effectively to win the game."
                )
        return self._system_prompt

    def choose_mulligan(self, hand: list, mulligans: int) -> bool:
        """Simple mulligan: keep if we have 2-5 lands and some spells."""
        if mulligans >= 2:
            return False
        names = [c.name if hasattr(c, 'name') else c for c in hand]
        lands = sum(1 for c in names if _looks_like_land(c))
        if lands < 1 or lands > 5:
            return True
        spells = len(names) - lands
        if spells == 0:
            return True
        return False

    def choose_cards_to_bottom(
        self, hand: list[CardInstance], count: int
    ) -> list[str]:
        """Bottom highest-CMC cards."""
        sorted_hand = sorted(hand, key=lambda c: c.definition.cmc, reverse=True)
        return [c.id for c in sorted_hand[:count]]

    def choose_action(self, state: GameState, legal_actions: list[Action]) -> Action:
        """Use LLM for action selection if available, otherwise play heuristically."""
        if not legal_actions:
            return Action(type=ActionType.PASS_PRIORITY, player_id="")

        if len(legal_actions) == 1:
            return legal_actions[0]

        # If no LLM client, use simple heuristics
        if self._llm is None:
            return self._heuristic_action(state, legal_actions)

        return self._llm_action(state, legal_actions)

    def choose_discard_target(
        self, state: GameState, opponent_hand: list[CardInstance]
    ) -> str | None:
        return None

    def choose_discard_from_hand(
        self, state: GameState, hand: list[CardInstance]
    ) -> str | None:
        return _heuristic_discard_from_hand(hand)

    def choose_sacrifice(
        self, state: GameState, candidates: list[CardInstance]
    ) -> str | None:
        return _heuristic_sacrifice(candidates)

    def choose_search_target(
        self, state: GameState, candidates: list[CardInstance]
    ) -> str | None:
        return candidates[0].id if candidates else None

    def _heuristic_action(self, state: GameState, legal_actions: list[Action]) -> Action:
        """Simple heuristic: play lands, cast cheapest spells, attack, block."""
        # Play land first
        for a in legal_actions:
            if a.type == ActionType.PLAY_LAND:
                return a

        # Attack
        for a in legal_actions:
            if a.type == ActionType.ATTACK:
                return a

        # Block with smallest creature that survives combat
        blocks = [a for a in legal_actions if a.type == ActionType.BLOCK]
        if blocks:
            return blocks[0]

        # Cast spells (prefer creatures)
        casts = [a for a in legal_actions if a.type == ActionType.CAST_SPELL]
        if casts:
            return casts[0]

        # Pass
        return next(
            (a for a in legal_actions if a.type == ActionType.PASS_PRIORITY),
            legal_actions[0],
        )

    def _llm_action(self, state: GameState, legal_actions: list[Action]) -> Action:
        """Use LLM to choose an action."""
        self.llm_calls += 1
        player_id = legal_actions[0].player_id
        visible = VisibleGameState.from_game_state(state, player_id)

        action_list = "\n".join(
            f"  [{i}] {a.description or str(a)}" for i, a in enumerate(legal_actions)
        )

        prompt = (
            f"Turn {visible.turn_number}, Phase: {visible.phase.value}\n"
            f"Your life: {visible.viewer_life} | Opponent life: {visible.opponent_life}\n"
            f"Your hand: {', '.join(visible.viewer_hand)}\n"
            f"Your board: {_format_board(visible.viewer_battlefield)}\n"
            f"Opponent board: {_format_board(visible.opponent_battlefield)}\n"
            f"Opponent hand size: {visible.opponent_hand_size}\n\n"
            f"Legal actions:\n{action_list}\n\n"
            f"Choose the best action by index."
        )

        try:
            result = self._llm.query(
                response_model=OpponentActionChoice,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
                model=self._model,
                max_tokens=300,
            )
            idx = max(0, min(result.action_index, len(legal_actions) - 1))
            return legal_actions[idx]
        except Exception as e:
            logger.warning(f"LLM opponent action failed: {e}")
            return self._heuristic_action(state, legal_actions)


class ScriptedOpponent:
    """Heuristic-only opponent for testing without LLM.

    Plays lands, casts creatures on curve, attacks when able.
    """

    def __init__(self, archetype: str = "generic"):
        self.archetype = archetype

    @property
    def name(self) -> str:
        return f"{self.archetype} (Scripted)"

    def choose_mulligan(self, hand: list, mulligans: int) -> bool:
        if mulligans >= 2:
            return False
        names = [c.name if hasattr(c, 'name') else c for c in hand]
        lands = sum(1 for c in names if _looks_like_land(c))
        return lands < 1 or lands > 5

    def choose_cards_to_bottom(
        self, hand: list[CardInstance], count: int
    ) -> list[str]:
        sorted_hand = sorted(hand, key=lambda c: c.definition.cmc, reverse=True)
        return [c.id for c in sorted_hand[:count]]

    def choose_action(self, state: GameState, legal_actions: list[Action]) -> Action:
        if not legal_actions:
            return Action(type=ActionType.PASS_PRIORITY, player_id="")

        # Play land
        for a in legal_actions:
            if a.type == ActionType.PLAY_LAND:
                return a

        # Attack with everything
        for a in legal_actions:
            if a.type == ActionType.ATTACK:
                return a

        # Block
        for a in legal_actions:
            if a.type == ActionType.BLOCK:
                return a

        # Cast cheapest spell first (play on curve)
        casts = [a for a in legal_actions if a.type == ActionType.CAST_SPELL]
        if casts:
            return casts[0]

        # Activate abilities
        for a in legal_actions:
            if a.type == ActionType.ACTIVATE_ABILITY:
                return a

        return next(
            (a for a in legal_actions if a.type == ActionType.PASS_PRIORITY),
            legal_actions[0],
        )

    def choose_discard_target(
        self, state: GameState, opponent_hand: list[CardInstance]
    ) -> str | None:
        return None

    def choose_discard_from_hand(
        self, state: GameState, hand: list[CardInstance]
    ) -> str | None:
        return _heuristic_discard_from_hand(hand)

    def choose_sacrifice(
        self, state: GameState, candidates: list[CardInstance]
    ) -> str | None:
        return _heuristic_sacrifice(candidates)

    def choose_search_target(
        self, state: GameState, candidates: list[CardInstance]
    ) -> str | None:
        return candidates[0].id if candidates else None


def _looks_like_land(name: str) -> bool:
    """Heuristic check if a card name is likely a land."""
    land_keywords = [
        "Plains", "Island", "Swamp", "Mountain", "Forest",
        "Mesa", "Foundry", "Strand", "Flats", "Heath",
        "Parlor", "Encampment", "Arena", "Factory", "Castle",
        "Saga", "Urborg", "Tomb", "Cavern",
    ]
    return any(kw in name for kw in land_keywords)


def _heuristic_discard_from_hand(hand: list[CardInstance]) -> str | None:
    """Discard highest CMC non-land, or a land if hand is all lands."""
    if not hand:
        return None
    non_lands = [c for c in hand if not c.definition.is_land]
    if non_lands:
        best = max(non_lands, key=lambda c: c.definition.cmc)
        return best.id
    return hand[0].id


def _heuristic_sacrifice(candidates: list[CardInstance]) -> str | None:
    """Sacrifice least valuable permanent (lowest CMC)."""
    if not candidates:
        return None
    worst = min(candidates, key=lambda c: c.definition.cmc)
    return worst.id


def _format_board(cards: list[dict]) -> str:
    if not cards:
        return "empty"
    parts = []
    for c in cards:
        s = c["name"]
        if c.get("tapped"):
            s += " (tapped)"
        if c.get("power"):
            s += f" {c['power']}/{c['toughness']}"
        parts.append(s)
    return ", ".join(parts)
