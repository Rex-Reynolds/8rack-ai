"""Core Resolver class: mixin composition and dispatch."""

from __future__ import annotations

from ..actions import Action, ActionResult, ActionType
from ..state import GameState
from .helpers import FETCH_TARGETS
from .legal_actions import LegalActionsMixin
from .stack import StackMixin
from .templates_eight_rack import EightRackTemplatesMixin
from .templates_opponents import OpponentTemplatesMixin
from .templates_removal import RemovalTemplatesMixin
from .tier1 import Tier1Mixin


class Resolver(
    Tier1Mixin,
    StackMixin,
    EightRackTemplatesMixin,
    RemovalTemplatesMixin,
    OpponentTemplatesMixin,
    LegalActionsMixin,
):
    """Resolves game actions through Tier 1 (deterministic) and Tier 2 (templates)."""

    def __init__(self, trigger_registry=None) -> None:
        self._templates: dict[str, callable] = {}
        self._trigger_registry = trigger_registry
        self._register_templates()

    def _register_templates(self) -> None:
        """Register all Tier 2 card-specific resolution templates."""
        self._register_eight_rack_templates()
        self._register_removal_templates()
        self._register_opponent_templates()

    def can_resolve(self, action: Action) -> bool:
        """Check if this resolver can handle the action (Tier 1 or 2)."""
        if action.type in (
            ActionType.PLAY_LAND,
            ActionType.PASS_PRIORITY,
            ActionType.DISCARD,
            ActionType.ATTACK,
            ActionType.BLOCK,
        ):
            return True  # Tier 1
        if action.type == ActionType.CAST_SPELL and action.card_name in self._templates:
            return True  # Tier 2
        if action.type == ActionType.ACTIVATE_ABILITY:
            if action.card_name in self._templates:
                return True
            if action.card_name in FETCH_TARGETS:
                return True
        return False

    def resolve(self, state: GameState, action: Action, agents: dict | None = None) -> ActionResult:
        """Resolve an action. Returns result with state mutations applied."""
        match action.type:
            case ActionType.PLAY_LAND:
                return self._resolve_play_land(state, action)
            case ActionType.PASS_PRIORITY:
                return ActionResult(success=True, message="Priority passed", tier_used=1)
            case ActionType.DISCARD:
                return self._resolve_discard(state, action)
            case ActionType.ATTACK:
                return self._resolve_attack(state, action)
            case ActionType.CAST_SPELL:
                return self.put_spell_on_stack(state, action)
            case ActionType.ACTIVATE_ABILITY:
                return self._resolve_activate_ability(state, action, agents=agents)
            case ActionType.BLOCK:
                return self._resolve_block(state, action)
            case _:
                return ActionResult(success=False, message=f"Cannot resolve {action.type}")
