"""Tier 3 LLM rules adjudicator for complex card interactions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ..llm.client import LLMClient
from .actions import Action, ActionResult
from .state import GameState, VisibleGameState

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_PATH = Path(__file__).parent.parent.parent.parent / "config" / "prompts" / "rules_adjudicator.md"


class StateChange(BaseModel):
    """A single game state change from adjudication."""

    target_type: str = ""  # "player", "card", "zone"
    target_id: str = ""
    change: str = ""  # human-readable description
    field: str = ""  # e.g., "life", "zone", "counters"
    value: str = ""  # new value or delta


class AdjudicationResult(BaseModel):
    """Structured response from the LLM adjudicator."""

    legal: bool = True
    resolution: str = ""
    state_changes: list[StateChange] = Field(default_factory=list)
    reasoning: str = ""
    triggered_abilities: list[str] = Field(default_factory=list)


class LLMAdjudicator:
    """Uses an LLM to resolve complex card interactions not covered by Tier 1/2.

    Called when the deterministic resolver can't handle the action -
    typically novel opponent cards or complex multi-card interactions.
    """

    def __init__(self, llm_client: LLMClient, model: str = "sonnet"):
        self.llm = llm_client
        self.model = model
        self._system_prompt: str | None = None

    @property
    def system_prompt(self) -> str:
        if self._system_prompt is None:
            if SYSTEM_PROMPT_PATH.exists():
                self._system_prompt = SYSTEM_PROMPT_PATH.read_text()
            else:
                self._system_prompt = (
                    "You are an expert MTG rules judge. Resolve the given card "
                    "interaction precisely according to the Comprehensive Rules."
                )
        return self._system_prompt

    def adjudicate(self, state: GameState, action: Action) -> ActionResult:
        """Resolve an action using LLM adjudication.

        Converts the game state to a text representation, sends it to the LLM
        with the action details, and parses the structured response into
        state changes.
        """
        game_description = self._describe_game_state(state)
        action_description = self._describe_action(state, action)

        prompt = (
            f"## Current Game State\n{game_description}\n\n"
            f"## Action to Resolve\n{action_description}\n\n"
            f"Determine if this action is legal and how it resolves. "
            f"List all state changes that result from this action resolving."
        )

        logger.info(f"Tier 3 adjudication: {action.card_name} ({action.type.value})")

        result = self.llm.query(
            response_model=AdjudicationResult,
            system=self.system_prompt,
            messages=[{"role": "user", "content": prompt}],
            model=self.model,
            max_tokens=1500,
            temperature=0.0,
        )

        # Apply state changes from adjudication
        changes_applied = self._apply_state_changes(state, action, result)

        return ActionResult(
            success=result.legal,
            message=result.resolution,
            state_changes=changes_applied,
            tier_used=3,
        )

    def _describe_game_state(self, state: GameState) -> str:
        """Convert game state to a text description for the LLM."""
        lines = []
        lines.append(f"Turn {state.turn_number}, Phase: {state.phase.value}")
        lines.append(f"Active player: {state.active_player.name}")

        for player in state.players:
            lines.append(f"\n### {player.name}")
            lines.append(f"Life: {player.life}")
            lines.append(f"Hand ({player.hand_size} cards): {', '.join(c.name for c in player.hand)}")

            bf = player.battlefield
            if bf:
                bf_strs = []
                for c in bf:
                    parts = [c.name]
                    if c.tapped:
                        parts.append("(tapped)")
                    if c.counters:
                        parts.append(f"counters={c.counters}")
                    if c.definition.is_creature:
                        parts.append(f"{c.definition.power}/{c.definition.toughness}")
                    bf_strs.append(" ".join(parts))
                lines.append(f"Battlefield: {'; '.join(bf_strs)}")
            else:
                lines.append("Battlefield: empty")

            gy = player.graveyard
            if gy:
                lines.append(f"Graveyard: {', '.join(c.name for c in gy)}")

            lines.append(f"Library: {len(player.library)} cards")

        if state.stack:
            lines.append(f"\nStack: {', '.join(s.description for s in state.stack)}")

        return "\n".join(lines)

    def _describe_action(self, state: GameState, action: Action) -> str:
        """Convert an action to a text description for the LLM."""
        player = state.get_player(action.player_id)
        lines = [
            f"Player: {player.name}",
            f"Action: {action.type.value}",
        ]

        if action.card_id:
            card = player.find_card(action.card_id)
            if card:
                lines.append(f"Card: {card.name}")
                lines.append(f"Type: {card.definition.type_line}")
                lines.append(f"Cost: {card.definition.mana_cost}")
                if card.definition.oracle_text:
                    lines.append(f"Text: {card.definition.oracle_text}")

        if action.targets:
            target_names = []
            for tid in action.targets:
                if tid.startswith("player:"):
                    pid = tid.split(":")[1]
                    target_names.append(state.get_player(pid).name)
                else:
                    for p in state.players:
                        c = p.find_card(tid)
                        if c:
                            target_names.append(f"{c.name} ({c.zone.value})")
                            break
            lines.append(f"Targets: {', '.join(target_names)}")

        if action.choices:
            lines.append(f"Choices: {action.choices}")

        return "\n".join(lines)

    def _apply_state_changes(
        self, state: GameState, action: Action, result: AdjudicationResult
    ) -> list[str]:
        """Apply LLM-determined state changes to the actual game state.

        This is conservative - it handles common change types and logs
        anything it can't automatically apply.
        """
        applied = []
        player = state.get_player(action.player_id)

        for change in result.state_changes:
            try:
                if change.target_type == "player" and change.field == "life":
                    target_player = state.get_player(change.target_id) if change.target_id else player
                    delta = int(change.value)
                    target_player.life += delta
                    applied.append(f"{target_player.name} life {'+' if delta > 0 else ''}{delta} -> {target_player.life}")

                elif change.target_type == "card" and change.field == "zone":
                    for p in state.players:
                        card = p.find_card(change.target_id)
                        if card:
                            from .state import Zone
                            new_zone = Zone(change.value)
                            card.zone = new_zone
                            applied.append(f"{card.name} -> {new_zone.value}")
                            break

                elif change.target_type == "card" and change.field == "counters":
                    for p in state.players:
                        card = p.find_card(change.target_id)
                        if card:
                            # value format: "loyalty:3" or "+1/+1:2"
                            parts = change.value.split(":")
                            if len(parts) == 2:
                                counter_type, count = parts[0], int(parts[1])
                                card.counters[counter_type] = card.counters.get(counter_type, 0) + count
                                applied.append(f"{card.name} gets {count} {counter_type} counters")
                            break

                elif change.target_type == "card" and change.field == "damage":
                    for p in state.players:
                        card = p.find_card(change.target_id)
                        if card:
                            dmg = int(change.value)
                            card.damage_marked += dmg
                            applied.append(f"{card.name} takes {dmg} damage")
                            break

                else:
                    # Log unhandled changes for review
                    applied.append(f"[LLM] {change.change}")

            except (ValueError, KeyError) as e:
                logger.warning(f"Failed to apply state change: {change} - {e}")
                applied.append(f"[LLM unresolved] {change.change}")

        # If the action was casting a spell, move the card appropriately
        if action.card_id and action.type.value == "cast_spell":
            card = player.find_card(action.card_id)
            if card and card.zone.value == "hand":
                if card.definition.is_instant or card.definition.is_sorcery:
                    from .state import Zone as Z
                    card.zone = Z.GRAVEYARD
                    applied.append(f"{card.name} -> graveyard (after resolution)")
                else:
                    from .state import Zone
                    card.zone = Zone.BATTLEFIELD
                    card.controller = player.id
                    if card.definition.is_creature:
                        card.sick = True
                    applied.append(f"{card.name} -> battlefield")

        return applied
